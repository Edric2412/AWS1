#!/bin/bash
echo "=== Initializing LocalStack AWS services ==="

# Create S3 buckets
awslocal s3 mb s3://syncops-tickets
awslocal s3 mb s3://syncops-data-lake

# Create Lambda function
# We expect the ticket_ingest.zip file to be placed in the same directory, which maps to /etc/localstack/init/ready.d/
awslocal lambda create-function \
    --function-name ticket_ingest \
    --runtime python3.11 \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --handler index.handler \
    --zip-file fileb:///etc/localstack/init/ready.d/ticket_ingest.zip \
    --environment "Variables={REDPANDA_PROXY_URL=http://redpanda:8082,TICKET_TOPIC=tickets}"

# Wait for Lambda function to become active before setting up notifications
echo "Waiting for ticket_ingest Lambda to become active..."
awslocal lambda wait function-active-v2 --function-name ticket_ingest

# Configure S3 notification to trigger Lambda
# Generate notification configuration JSON
cat <<EOF > /tmp/notification.json
{
  "LambdaFunctionConfigurations": [
    {
      "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:ticket_ingest",
      "Events": ["s3:ObjectCreated:*"]
    }
  ]
}
EOF

# Grant permission to S3 to invoke the Lambda function
awslocal lambda add-permission \
    --function-name ticket_ingest \
    --statement-id s3-invoke \
    --action lambda:InvokeFunction \
    --principal s3.amazonaws.com \
    --source-arn arn:aws:s3:::syncops-tickets

# Put bucket notification configuration
awslocal s3api put-bucket-notification-configuration \
    --bucket syncops-tickets \
    --notification-configuration file:///tmp/notification.json

echo "=== LocalStack AWS services initialized successfully ==="
