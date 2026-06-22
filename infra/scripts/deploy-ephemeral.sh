#!/usr/bin/env bash
# deploy-ephemeral.sh: Automates the ephemeral staging pipeline for Phase 4

set -euo pipefail

# Configurations
AWS_REGION="us-east-1"
ENVIRONMENT="staging"
SSH_KEY_NAME="syncops-key"
KEY_FILE="./syncops-key"
TERRAFORM_DIR="infra/terraform"

echo "=========================================================="
echo "Starting Ephemeral Staging Deployment Pipeline (Phase 4)"
echo "=========================================================="

# Step 0: Verify AWS connection
echo "Checking AWS connectivity and identity..."
if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "WARNING: Unable to connect to AWS. Proceeding as keys may be set right before execution."
else
    echo "AWS connection verified successfully."
fi

# Step 1: Generate temporary SSH key pair
if [ ! -f "$KEY_FILE" ]; then
    echo "Generating temporary SSH key pair: $SSH_KEY_NAME..."
    ssh-keygen -t rsa -b 2048 -f "$KEY_FILE" -N "" -q
    chmod 600 "$KEY_FILE"
    echo "Key pair generated successfully."
else
    echo "Using existing temporary SSH key pair: $KEY_FILE"
fi

SSH_PUBLIC_KEY=$(cat "${KEY_FILE}.pub")

# Step 2: Initialize and apply Terraform
echo "Initializing Terraform..."
terraform -chdir="$TERRAFORM_DIR" init

echo "Applying Terraform configuration..."
# We pass environment and ssh_public_key. By default ssh_key_name is "syncops-key" in variables.tf.
terraform -chdir="$TERRAFORM_DIR" apply -auto-approve \
    -var="environment=$ENVIRONMENT" \
    -var="ssh_public_key=$SSH_PUBLIC_KEY"

# Retrieve Terraform Outputs
echo "Retrieving Terraform outputs..."
EC2_IP=$(terraform -chdir="$TERRAFORM_DIR" output -raw ec2_public_ip)
ECR_URL=$(terraform -chdir="$TERRAFORM_DIR" output -raw ecr_repository_url)
TICKETS_BUCKET=$(terraform -chdir="$TERRAFORM_DIR" output -raw ticket_bucket_name)
DATA_LAKE_BUCKET=$(terraform -chdir="$TERRAFORM_DIR" output -raw data_lake_bucket_name)

echo "EC2 Public IP: $EC2_IP"
echo "ECR Repository URL: $ECR_URL"
echo "Tickets Bucket: $TICKETS_BUCKET"
echo "Data Lake Bucket: $DATA_LAKE_BUCKET"

# Step 3: Authenticate to ECR, build and push backend image
echo "Logging in to Amazon ECR..."
REGISTRY_URL=$(echo "$ECR_URL" | cut -d'/' -f1)
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$REGISTRY_URL"

echo "Building local Docker image for syncops-app..."
docker build -t syncops-app:latest ./backend

echo "Tagging and pushing image to ECR..."
docker tag syncops-app:latest "$ECR_URL:latest"
docker push "$ECR_URL:latest"

# Helper for cleanup on exit/interruption
cleanup() {
    local exit_code=$?
    echo "=========================================================="
    echo "Teardown & Cleanup Process"
    echo "=========================================================="
    
    if [ $exit_code -ne 0 ]; then
        echo "WARNING: Deployment or tests failed with exit code $exit_code."
        read -p "Press Enter to run cleanup and destroy AWS resources... "
    else
        echo "Deployment and validation tests passed successfully!"
        echo "Destroying resources automatically..."
    fi
    
    echo "Running terraform destroy..."
    terraform -chdir="$TERRAFORM_DIR" destroy -auto-approve \
        -var="environment=$ENVIRONMENT" \
        -var="ssh_public_key=$SSH_PUBLIC_KEY"
        
    echo "Cleaning up temporary SSH keys locally..."
    rm -f "$KEY_FILE" "${KEY_FILE}.pub"
    echo "Cleanup completed. Pipeline finished."
}
trap cleanup EXIT

# Step 4: Configure EC2 host and install K3s
echo "Waiting for SSH to be ready on EC2 host ($EC2_IP)..."
until ssh -i "$KEY_FILE" -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@"$EC2_IP" "echo SSH connectivity established" 2>/dev/null; do
    sleep 5
done

echo "Setting up 2GB swap space on EC2 host to prevent OOM..."
ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@"$EC2_IP" "
    sudo fallocate -l 2G /swapfile && \
    sudo chmod 600 /swapfile && \
    sudo mkswap /swapfile && \
    sudo swapon /swapfile && \
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab && \
    echo 'Swap space configured successfully' && \
    sudo mkdir -p /mnt/data/postgres && \
    sudo chmod -R 777 /mnt/data/postgres && \
    echo 'Postgres storage directory prepared successfully'
"

echo "Installing K3s on EC2 host..."
ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@"$EC2_IP" "
    curl -sfL https://get.k3s.io | sh -s - --disable=traefik --disable=metrics-server && \
    sudo chmod 644 /etc/rancher/k3s/k3s.yaml && \
    echo 'K3s installed and configured successfully'
"

# Step 5: Replace placeholders in Kubernetes manifests and upload
echo "Processing Kubernetes manifests locally..."
TEMP_MANIFESTS_DIR=$(mktemp -d)
cp infra/k8s/manifests/*.yaml "$TEMP_MANIFESTS_DIR/"

sed -i "s|__EC2_PUBLIC_IP__|$EC2_IP|g" "$TEMP_MANIFESTS_DIR/redpanda.yaml"
sed -i "s|__APP_IMAGE__|$ECR_URL:latest|g" "$TEMP_MANIFESTS_DIR/app.yaml"
sed -i "s|__DATA_LAKE_BUCKET__|$DATA_LAKE_BUCKET|g" "$TEMP_MANIFESTS_DIR/app.yaml"
sed -i "s|__AWS_REGION__|$AWS_REGION|g" "$TEMP_MANIFESTS_DIR/app.yaml"

echo "Uploading processed manifests to EC2 host..."
ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@"$EC2_IP" "mkdir -p /home/ubuntu/manifests"
scp -i "$KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r "$TEMP_MANIFESTS_DIR"/* ubuntu@"$EC2_IP":/home/ubuntu/manifests/
rm -rf "$TEMP_MANIFESTS_DIR"

# Step 6: Deploy resources in Kubernetes (K3s)
echo "Generating ECR image pull secrets for K3s..."
ECR_PASSWORD=$(aws ecr get-login-password --region "$AWS_REGION")
ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@"$EC2_IP" "
    sudo kubectl create secret docker-registry regcred \
        --docker-server='$REGISTRY_URL' \
        --docker-username=AWS \
        --docker-password='$ECR_PASSWORD' \
        --dry-run=client -o yaml | sudo kubectl apply -f -
"

echo "Applying Kubernetes manifests on EC2 host..."
ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@"$EC2_IP" "
    sudo kubectl apply -f manifests/postgres.yaml --validate=false
    sudo kubectl apply -f manifests/redpanda.yaml --validate=false
    sudo kubectl apply -f manifests/app.yaml --validate=false
"

# Step 7: Poll resources until ready
echo "Waiting for deployments to roll out..."
ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@"$EC2_IP" "
    echo 'Waiting for PostgreSQL database rollout...'
    sudo kubectl rollout status deployment/postgres --timeout=300s
    echo 'Waiting for Redpanda broker rollout...'
    sudo kubectl rollout status deployment/redpanda --timeout=300s
    echo 'Waiting for SyncOps app rollout...'
    sudo kubectl rollout status deployment/syncops-app --timeout=300s
"

echo "Kubernetes deployment ready! Sleep 10s to ensure everything stabilizes..."
sleep 10

# Step 8: Run Integration Tests
echo "=========================================================="
echo "Running End-to-End Validation Tests"
echo "=========================================================="

echo "Uploading test tickets to s3://$TICKETS_BUCKET..."
# Set variables so test_upload.py connects to real S3 and targets the correct bucket
TICKETS_BUCKET="$TICKETS_BUCKET" AWS_S3_ENDPOINT_URL="" backend/venv/bin/python infra/scripts/test_upload.py

echo "Waiting for SyncOps consumer processing and data lake export..."
sleep 20

echo "Querying the S3 Data Lake using DuckDB..."
# Set variables so dw_query.py connects to real S3 and queries the correct bucket
OUTPUT=$(DATA_LAKE_BUCKET="$DATA_LAKE_BUCKET" AWS_S3_ENDPOINT_URL="" PYTHONPATH=backend backend/venv/bin/python backend/app/services/dw_query.py)

echo ""
echo "=== Query Output ==="
echo "$OUTPUT"
echo "===================="
echo ""

if echo "$OUTPUT" | grep -q "TCK-"; then
    echo "TEST PASSED: Audit logs found in S3 Data Lake."
else
    echo "TEST FAILED: No audit logs found in S3 Data Lake."
    exit 1
fi

echo "Staging environment verification complete."
