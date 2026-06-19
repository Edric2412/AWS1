variable "aws_region" {
  description = "Target AWS Region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "staging"
}

variable "aws_endpoint" {
  description = "Optional endpoint URL for emulating AWS services locally via LocalStack"
  type        = string
  default     = null
}

variable "instance_type" {
  description = "EC2 Instance type for the K3s host node"
  type        = string
  default     = "t3.micro"
}

variable "ssh_key_name" {
  description = "Name of the SSH Key Pair for accessing the EC2 instance"
  type        = string
  default     = "syncops-key"
}

variable "vpc_cidr" {
  description = "Classless Inter-Domain Routing block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet"
  type        = string
  default     = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  description = "CIDR block for the private subnet"
  type        = string
  default     = "10.0.2.0/24"
}

variable "ticket_bucket_name" {
  description = "Name of the S3 bucket for incoming ticket drop-off"
  type        = string
  default     = "syncops-tickets"
}

variable "data_lake_bucket_name" {
  description = "Name of the S3 bucket for the traces data lake"
  type        = string
  default     = "syncops-data-lake"
}

variable "benchmarks_bucket_name" {
  description = "Name of the S3 bucket for test benchmarks"
  type        = string
  default     = "syncops-benchmarks"
}

variable "reports_bucket_name" {
  description = "Name of the S3 bucket for evaluation reports"
  type        = string
  default     = "syncops-reports"
}

variable "ssh_public_key" {
  description = "Public key content for SSH access to EC2"
  type        = string
}

