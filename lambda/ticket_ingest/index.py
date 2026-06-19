import os
import json
import uuid
import urllib.request
import urllib.error
import boto3

def handler(event, context):
    print("Received event:", json.dumps(event))
    
    # Initialize S3 client. In LocalStack, AWS_ENDPOINT_URL is automatically set.
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    s3 = boto3.client('s3', endpoint_url=endpoint_url)
    
    redpanda_url = os.environ.get("REDPANDA_PROXY_URL", "http://redpanda:8082")
    topic = os.environ.get("TICKET_TOPIC", "tickets")
    post_url = f"{redpanda_url}/topics/{topic}"
    
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        print(f"Processing S3 object: s3://{bucket}/{key}")
        
        try:
            # Download file from S3
            response = s3.get_object(Bucket=bucket, Key=key)
            ticket_text = response['Body'].read().decode('utf-8')
            print(f"Ticket content: {ticket_text}")
            
            # Determine ticket ID. Use the filename prefix or generate a new UUID
            ticket_id = key.split('.')[0] if '.' in key else key
            if not ticket_id:
                ticket_id = str(uuid.uuid4())
                
            # Prepare payload for Redpanda REST proxy
            payload = {
                "records": [
                    {
                        "value": {
                            "event_type": "ticket_received",
                            "data": {
                                "ticket_id": ticket_id,
                                "ticket_text": ticket_text
                            }
                        }
                    }
                ]
            }
            
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                post_url,
                data=req_data,
                headers={
                    "Content-Type": "application/vnd.kafka.json.v2+json",
                    "Accept": "application/vnd.kafka.v2+json"
                },
                method="POST"
            )
            
            print(f"Posting to Redpanda REST proxy: {post_url}")
            with urllib.request.urlopen(req) as res:
                response_body = res.read().decode('utf-8')
                print(f"Redpanda response: {response_body}")
                
        except urllib.error.HTTPError as e:
            print(f"HTTP Error posting to Redpanda: {e.code} - {e.reason}")
            try:
                error_body = e.read().decode('utf-8')
                print(f"Response: {error_body}")
            except Exception:
                pass
            raise e
        except Exception as e:
            print(f"Error processing record: {str(e)}")
            raise e
            
    return {"status": "success"}
