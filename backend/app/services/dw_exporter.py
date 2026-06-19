import os
import json
import datetime
import tempfile
import logging
import boto3
import pandas as pd

logger = logging.getLogger("syncops.services.dw_exporter")

class DataWarehouseExporter:
    def __init__(self):
        self.bucket_name = os.getenv("DATA_LAKE_BUCKET", "syncops-data-lake")
        self.s3_endpoint = os.getenv("AWS_S3_ENDPOINT_URL", "http://localhost:4566")
        self.aws_region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        
        # Configure standard or LocalStack boto3 endpoint
        # If AWS_S3_ENDPOINT_URL points to localhost/localstack, or if we are emulating, use it
        is_local = any(x in self.s3_endpoint for x in ["localhost", "127.0.0.1", "localstack"])
        
        if is_local:
            self.s3 = boto3.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.aws_region,
                use_ssl=False,
                aws_access_key_id="mock",
                aws_secret_access_key="mock"
            )
        else:
            self.s3 = boto3.client(
                "s3",
                region_name=self.aws_region
            )

    def export_audit_event(self, event: dict):
        """Serializes a single audit event dict to Parquet format and uploads to S3."""
        try:
            logger.info("Exporting audit event to S3 Data Lake: %s", json.dumps(event))
            
            event_type = event.get("event_type", "unknown")
            data = event.get("data", {})
            
            # Extract key properties to map to columns
            ticket_id = data.get("ticket_id", "unknown")
            intent = data.get("intent", "unknown")
            params_str = json.dumps(data.get("params", {}))
            api_result_str = json.dumps(data.get("api_result", {}))
            error_str = data.get("error", "")
            
            # Get current timestamp and partition paths
            now = datetime.datetime.now(datetime.timezone.utc)
            year = now.strftime("%Y")
            month = now.strftime("%m")
            day = now.strftime("%d")
            timestamp_str = now.isoformat()

            # Create a Pandas DataFrame representing this single row
            df = pd.DataFrame([{
                "ticket_id": ticket_id,
                "event_type": event_type,
                "intent": intent,
                "params": params_str,
                "api_result": api_result_str,
                "error": error_str,
                "timestamp": timestamp_str
            }])
            
            # Construct S3 prefix/key following the partitioned layout:
            # audit/year=YYYY/month=MM/day=DD/ticket_id.parquet
            s3_key = f"audit/year={year}/month={month}/day={day}/{ticket_id}.parquet"
            
            # Write parquet to a temporary file
            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
                tmp_path = tmp.name
                
            try:
                # Use pandas/pyarrow to write parquet
                df.to_parquet(tmp_path, engine="pyarrow", index=False)
                
                # Upload to S3
                logger.info("Uploading parquet file to S3: s3://%s/%s", self.bucket_name, s3_key)
                self.s3.upload_file(tmp_path, self.bucket_name, s3_key)
                logger.info("Upload successful for ticket %s", ticket_id)
            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                    
        except Exception:
            logger.exception("Error exporting audit event to Parquet/S3")
            raise
