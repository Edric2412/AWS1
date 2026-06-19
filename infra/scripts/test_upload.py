import os
import sys
import boto3

def main():
    s3_endpoint = os.getenv("AWS_S3_ENDPOINT_URL", "http://localhost:4566")
    bucket_name = os.getenv("TICKETS_BUCKET", "syncops-tickets")
    
    is_local = any(x in s3_endpoint for x in ["localhost", "127.0.0.1", "localstack"])
    
    if is_local:
        print(f"Connecting to LocalStack S3 at {s3_endpoint}...")
        try:
            s3_client = boto3.client(
                "s3",
                endpoint_url=s3_endpoint,
                region_name="us-east-1",
                aws_access_key_id="mock",
                aws_secret_access_key="mock"
            )
            s3_client.list_buckets()
        except Exception as e:
            print(f"Error connecting to local S3 endpoint: {e}", file=sys.stderr)
            print("Please make sure LocalStack is running and accessible.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Connecting to AWS S3 (region: us-east-1)...")
        try:
            s3_client = boto3.client("s3")
            s3_client.list_buckets()
        except Exception as e:
            print(f"Error connecting to AWS S3: {e}", file=sys.stderr)
            print("Please verify your AWS credentials.", file=sys.stderr)
            sys.exit(1)

    tickets = {
        "address_change.txt": "Please update my address to 123 Main St, Paris, zipcode EC1A2 for order ORD-12345.",
        "inventory_check.txt": "Please check if there is inventory for Smart Sensors in warehouse WH-BER-03.",
        "process_return.txt": "I want to process a return of 2 items for order ORD-99999.",
        "account_upgrade.txt": "Please upgrade customer account CUST-001 to Enterprise tier."
    }
    
    print("\nUploading test tickets to s3://syncops-tickets/...\n")
    for filename, content in tickets.items():
        try:
            print(f"Uploading {filename}...")
            s3_client.put_object(
                Bucket=bucket_name,
                Key=filename,
                Body=content.encode("utf-8")
            )
            print(f"Successfully uploaded {filename}!")
        except Exception as e:
            print(f"Error uploading {filename}: {e}", file=sys.stderr)
            
    print("\nAll test uploads completed.")

if __name__ == "__main__":
    main()
