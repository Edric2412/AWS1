import os
import sys
import logging
import duckdb

# Set up simple stdout logging if run directly
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("syncops.services.dw_query")

def query_data_lake():
    """Queries Parquet files stored in S3 Data Lake using DuckDB."""
    s3_endpoint = os.getenv("AWS_S3_ENDPOINT_URL", "http://localhost:4566")
    bucket_name = os.getenv("DATA_LAKE_BUCKET", "syncops-data-lake")
    
    logger.info("Connecting to DuckDB and loading httpfs extension...")
    con = duckdb.connect()
    
    try:
        con.execute("INSTALL httpfs;")
        con.execute("LOAD httpfs;")
    except Exception as e:
        logger.error("Failed to install/load httpfs extension: %s", e)
        raise
        
    is_local = any(x in s3_endpoint for x in ["localhost", "127.0.0.1", "localstack"])
    
    if is_local:
        endpoint_host = s3_endpoint.replace("http://", "").replace("https://", "")
        logger.info("Using Per-Request URL Parameter routing for local environment (%s)", endpoint_host)
        
        # Injects connection parameters directly into the path to bypass Secret Manager scoping
        s3_path = (
            f"s3://{bucket_name}/audit/**/*.parquet"
            f"?s3_endpoint={endpoint_host}"
            f"&s3_use_ssl=false"
            f"&s3_url_style=path"
            f"&s3_access_key_id=mock"
            f"&s3_secret_access_key=mock"
        )
    else:
        aws_region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        logger.info("Configuring DuckDB S3 settings using Secret API for production AWS (%s)", aws_region)
        con.execute(f"""
            CREATE OR REPLACE SECRET aws_secret (
                TYPE S3,
                REGION '{aws_region}'
            );
        """)
        s3_path = f"s3://{bucket_name}/audit/**/*.parquet"
        
    logger.info("Querying data lake path: s3://%s/audit/**/*.parquet", bucket_name)
    
    query = f"""
        SELECT 
            ticket_id, 
            event_type, 
            intent, 
            timestamp, 
            SUBSTR(params, 1, 40) AS params_preview,
            SUBSTR(api_result, 1, 40) AS api_preview,
            error 
        FROM '{s3_path}' 
        ORDER BY timestamp DESC;
    """
    
    try:
        df = con.query(query).to_df()
        return df
    except Exception as e:
        logger.error("Error executing DuckDB query: %s", e)
        try:
            import boto3
            if is_local:
                s3_client = boto3.client(
                    "s3",
                    endpoint_url=s3_endpoint,
                    region_name="us-east-1",
                    aws_access_key_id="mock",
                    aws_secret_access_key="mock"
                )
            else:
                s3_client = boto3.client("s3")
            res = s3_client.list_objects_v2(Bucket=bucket_name, Prefix="audit/")
            if "Contents" not in res:
                logger.warning("No audit logs found in bucket '%s'. Data lake is empty.", bucket_name)
                import pandas as pd
                return pd.DataFrame(columns=["ticket_id", "event_type", "intent", "timestamp", "params_preview", "api_preview", "error"])
        except Exception:
            pass
        raise

if __name__ == "__main__":
    try:
        df = query_data_lake()
        print("\n=== SyncOps AI Data Lake Audit Logs (DuckDB Query) ===")
        if df.empty:
            print("No records found in the data lake.")
        else:
            print(df.to_string(index=False))
        print("======================================================\n")
    except Exception as e:
        print(f"Error querying data lake: {e}", file=sys.stderr)
        sys.exit(1)
