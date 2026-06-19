terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region     = var.aws_region
  access_key = var.aws_endpoint != null ? "mock" : null
  secret_key = var.aws_endpoint != null ? "mock" : null

  # Handle local LocalStack testing when aws_endpoint is provided
  dynamic "endpoints" {
    for_each = var.aws_endpoint != null ? [var.aws_endpoint] : []
    content {
      s3     = endpoints.value
      ec2    = endpoints.value
      ecr    = endpoints.value
      lambda = endpoints.value
      iam    = endpoints.value
    }
  }
}

# 1. VPC Module (Networking)
module "vpc" {
  source              = "./modules/vpc"
  vpc_cidr            = var.vpc_cidr
  public_subnet_cidr  = var.public_subnet_cidr
  private_subnet_cidr = var.private_subnet_cidr
  environment         = var.environment
}

# 2. S3 Module (Storage)
module "s3" {
  source                 = "./modules/s3"
  ticket_bucket_name     = var.ticket_bucket_name
  data_lake_bucket_name  = var.data_lake_bucket_name
  benchmarks_bucket_name = var.benchmarks_bucket_name
  reports_bucket_name    = var.reports_bucket_name
  environment            = var.environment
}

# 3. ECR Module (Container Registry)
module "ecr" {
  source      = "./modules/ecr"
  environment = var.environment
}

# 4. EC2 Module (K3s Server Host)
module "ec2" {
  source               = "./modules/ec2"
  vpc_id               = module.vpc.vpc_id
  subnet_id            = module.vpc.public_subnet_id
  instance_type        = var.instance_type
  ssh_key_name         = var.ssh_key_name
  ssh_public_key       = var.ssh_public_key
  environment          = var.environment
  ticket_bucket_arn    = module.s3.ticket_bucket_arn
  data_lake_bucket_arn = module.s3.data_lake_bucket_arn
}

# 5. Lambda Module (Serverless Ticket Ingester)
module "lambda" {
  source             = "./modules/lambda"
  ticket_bucket_name = module.s3.ticket_bucket_name
  ticket_bucket_arn  = module.s3.ticket_bucket_arn
  redpanda_proxy_url = "http://${module.ec2.public_ip}:8082"
  environment        = var.environment
}
