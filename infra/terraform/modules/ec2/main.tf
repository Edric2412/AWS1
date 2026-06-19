variable "vpc_id" {
  type        = string
  description = "VPC ID where the EC2 instance will be deployed"
}

variable "subnet_id" {
  type        = string
  description = "Subnet ID where the EC2 instance will be deployed"
}

variable "instance_type" {
  type        = string
  description = "EC2 instance size"
  default     = "t3.micro"
}

variable "ssh_key_name" {
  type        = string
  description = "Name for the SSH key pair in AWS"
}

variable "ssh_public_key" {
  type        = string
  description = "Content of the SSH public key"
}

variable "environment" {
  type        = string
  description = "Environment name"
}

variable "data_lake_bucket_arn" {
  type        = string
  description = "ARN of the data lake S3 bucket"
}

variable "ticket_bucket_arn" {
  type        = string
  description = "ARN of the ticket ingest S3 bucket"
}

# Look up the latest Ubuntu 22.04 LTS AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name     = "name"
    values   = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name     = "virtualization-type"
    values   = ["hvm"]
  }
}

# Register the generated public SSH key
resource "aws_key_pair" "deployer" {
  key_name   = var.ssh_key_name
  public_key = var.ssh_public_key
}

# Security Group
resource "aws_security_group" "k3s" {
  name        = "syncops-${var.environment}-sg"
  description = "Security group for ephemeral K3s host"
  vpc_id      = var.vpc_id

  # SSH Access
  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # FastAPI API Access
  ingress {
    description = "FastAPI web server"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Redpanda REST Proxy Access (for Lambda ingestion trigger)
  ingress {
    description = "Redpanda REST proxy"
    from_port   = 8082
    to_port     = 8082
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Egress (All traffic outbound)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "syncops-${var.environment}-sg"
    Environment = var.environment
  }
}

# IAM Role for EC2
resource "aws_iam_role" "ec2_role" {
  name = "syncops-${var.environment}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for S3 access and ECR authentication/pull
resource "aws_iam_role_policy" "ec2_policy" {
  name = "syncops-${var.environment}-ec2-policy"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ECR Access (ECR Pull permissions)
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      },
      # S3 Access (Read/Write to data lake and ticket buckets)
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          var.data_lake_bucket_arn,
          "${var.data_lake_bucket_arn}/*",
          var.ticket_bucket_arn,
          "${var.ticket_bucket_arn}/*"
        ]
      }
    ]
  })
}

# IAM Instance Profile
resource "aws_iam_instance_profile" "ec2_profile" {
  name = "syncops-${var.environment}-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# EC2 Instance
resource "aws_instance" "k3s_host" {
  ami                  = data.aws_ami.ubuntu.id
  instance_type        = var.instance_type
  subnet_id            = var.subnet_id
  key_name             = aws_key_pair.deployer.key_name
  security_groups      = [aws_security_group.k3s.id]
  iam_instance_profile = aws_iam_instance_profile.ec2_profile.name

  # Root disk specification
  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name        = "syncops-${var.environment}-k3s-host"
    Environment = var.environment
  }
}

output "public_ip" {
  value       = aws_instance.k3s_host.public_ip
  description = "Public IP of the EC2 instance"
}

output "private_ip" {
  value       = aws_instance.k3s_host.private_ip
  description = "Private IP of the EC2 instance"
}
