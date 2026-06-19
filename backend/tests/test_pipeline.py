import os
import json
import shutil
import tempfile
import pytest
import duckdb
import pandas as pd
from unittest.mock import MagicMock

from app.services.dw_exporter import DataWarehouseExporter
from app.services.dw_query import query_data_lake

# Load lambda module dynamically because 'lambda' is a reserved keyword in Python
import importlib.util
from pathlib import Path
lambda_path = Path(__file__).resolve().parent.parent.parent / "lambda" / "ticket_ingest" / "index.py"
spec = importlib.util.spec_from_file_location("ticket_ingest", lambda_path)
assert spec is not None
assert spec.loader is not None
lambda_ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lambda_ingest)

# Helper to check if LocalStack is running
def is_localstack_running():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(("localhost", 4566))
        s.close()
        return True
    except Exception:
        return False

class DuckDBMockWrapper:
    def __init__(self, temp_dir):
        self.con = duckdb.connect()
        self.temp_dir = temp_dir
        
    def execute(self, query, *args, **kwargs):
        # Ignore S3/httpfs settings that would fail offline
        if any(x in query for x in ["INSTALL httpfs", "LOAD httpfs", "SET s3_"]):
            return self
        self.con.execute(query, *args, **kwargs)
        return self
        
    def query(self, query_str, *args, **kwargs):
        # Replace S3 path with local temp path
        local_query = query_str.replace("s3://syncops-data-lake", self.temp_dir)
        
        # Clean up any web per-request S3 URL parameters for the offline filesystem query
        if "?" in local_query:
            import re
            local_query = re.sub(r'\?[^\'\s]+', '', local_query)
            
        return self.con.query(local_query, *args, **kwargs)

@pytest.mark.asyncio
async def test_dw_exporter_and_query_all_scenarios(mocker):
    """Verifies that the Parquet exporter and DuckDB query tool process all four ticket scenarios successfully."""
    use_live = is_localstack_running()
    
    scenarios = [
        {
            "ticket_id": "address_change",
            "event_type": "ticket_resolved",
            "data": {
                "ticket_id": "address_change",
                "intent": "Update Address",
                "params": {"order_id": "ORD-12345", "street_address": "123 Main St", "city": "Paris", "zipcode": "EC1A2"},
                "api_result": {"status": "success", "message": "Address updated successfully"},
                "error": ""
            }
        },
        {
            "ticket_id": "inventory_check",
            "event_type": "ticket_resolved",
            "data": {
                "ticket_id": "inventory_check",
                "intent": "Check Inventory",
                "params": {"item": "Smart Sensors", "warehouse": "WH-BER-03"},
                "api_result": {"status": "success", "stock": 50},
                "error": ""
            }
        },
        {
            "ticket_id": "process_return",
            "event_type": "ticket_resolved",
            "data": {
                "ticket_id": "process_return",
                "intent": "Process Return",
                "params": {"order_id": "ORD-99999", "quantity": 2},
                "api_result": {"status": "success", "refund_amount": 300.00},
                "error": ""
            }
        },
        {
            "ticket_id": "account_upgrade",
            "event_type": "ticket_resolved",
            "data": {
                "ticket_id": "account_upgrade",
                "intent": "Upgrade Account",
                "params": {"customer_id": "CUST-001", "tier": "Enterprise"},
                "api_result": {"status": "success", "new_tier": "Enterprise"},
                "error": ""
            }
        }
    ]
    
    if use_live:
        # Live path: run directly against LocalStack S3
        exporter = DataWarehouseExporter()
        
        # Ensure bucket exists
        try:
            exporter.s3.create_bucket(Bucket=exporter.bucket_name)
        except exporter.s3.exceptions.BucketAlreadyExists:
            pass
        except exporter.s3.exceptions.BucketAlreadyOwnedByYou:
            pass
            
        for event in scenarios:
            exporter.export_audit_event(event)
            
        # Run DuckDB query
        df = query_data_lake()
        assert not df.empty
        assert len(df) >= 4
        assert "address_change" in df["ticket_id"].values
        assert "inventory_check" in df["ticket_id"].values
        assert "process_return" in df["ticket_id"].values
        assert "account_upgrade" in df["ticket_id"].values
    else:
        # Mocked path: verify exporter writes valid Parquet and query handles paths
        temp_s3_dir = tempfile.mkdtemp()
        mock_s3 = MagicMock()
        
        def mock_upload_file(Filename, Bucket, Key):
            dest_path = os.path.join(temp_s3_dir, Key)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy(Filename, dest_path)
            
        mock_s3.upload_file.side_effect = mock_upload_file
        mocker.patch("boto3.client", return_value=mock_s3)
        
        # Instantiate exporter (which now uses the mocked boto3 client)
        exporter = DataWarehouseExporter()
        
        for event in scenarios:
            exporter.export_audit_event(event)
            
        # Verify files were uploaded in correct layout
        uploaded_files = []
        for root, dirs, files in os.walk(temp_s3_dir):
            for file in files:
                if file.endswith(".parquet"):
                    uploaded_files.append(file)
                    # Verify content of the written parquet file
                    full_path = os.path.join(root, file)
                    df_parquet = pd.read_parquet(full_path)
                    assert len(df_parquet) == 1
                    assert "ticket_id" in df_parquet.columns
                    
        assert len(uploaded_files) == 4
        
        # Verify query_data_lake works on the local data using our DuckDB wrapper
        wrapper = DuckDBMockWrapper(temp_s3_dir)
        mocker.patch("duckdb.connect", return_value=wrapper)
        
        df = query_data_lake()
        assert not df.empty
        assert len(df) == 4
        assert "address_change" in df["ticket_id"].values
        assert "inventory_check" in df["ticket_id"].values
        assert "process_return" in df["ticket_id"].values
        assert "account_upgrade" in df["ticket_id"].values
        
        # Clean up local temp files
        shutil.rmtree(temp_s3_dir)


@pytest.mark.asyncio
async def test_lambda_ingestion_trigger_offline(mocker):
    """Verifies that the serverless ingest Lambda script executes correctly, downloading files and posting to Redpanda."""
    mock_s3 = MagicMock()
    mock_response = {
        'Body': MagicMock()
    }
    mock_response['Body'].read.return_value = b"Please update my address to 123 Main St, Paris, zipcode EC1A2 for order ORD-12345."
    mock_s3.get_object.return_value = mock_response
    
    # Mock boto3 client
    mocker.patch("boto3.client", return_value=mock_s3)
    
    # Mock urllib POST request
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.return_value.__enter__.return_value.read.return_value = b'{"status": "success"}'
    
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {
                        "name": "syncops-tickets"
                    },
                    "object": {
                        "key": "address_change.txt"
                    }
                }
            }
        ]
    }
    
    res = lambda_ingest.handler(event, None)
    assert res == {"status": "success"}
    
    # Assert s3 get_object was called to fetch the text
    mock_s3.get_object.assert_called_once_with(Bucket="syncops-tickets", Key="address_change.txt")
    
    # Assert Redpanda POST request was made
    mock_urlopen.assert_called_once()
    args = mock_urlopen.call_args[0]
    req = args[0]
    assert req.method == "POST"
    assert "topics/tickets" in req.full_url
    assert req.data is not None
    
    # Check payload format
    payload = json.loads(req.data.decode('utf-8'))
    assert "records" in payload
    assert payload["records"][0]["value"]["event_type"] == "ticket_received"
    assert payload["records"][0]["value"]["data"]["ticket_id"] == "address_change"
    assert payload["records"][0]["value"]["data"]["ticket_text"] == "Please update my address to 123 Main St, Paris, zipcode EC1A2 for order ORD-12345."
