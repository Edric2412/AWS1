variable "ticket_bucket_name" {
  type        = string
  description = "Base name for the ticket bucket"
}

variable "data_lake_bucket_name" {
  type        = string
  description = "Base name for the data lake bucket"
}

variable "benchmarks_bucket_name" {
  type        = string
  description = "Base name for the benchmarks bucket"
}

variable "reports_bucket_name" {
  type        = string
  description = "Base name for the reports bucket"
}

variable "environment" {
  type        = string
  description = "Environment name"
}

resource "random_id" "bucket_suffix" {
  byte_length = 2
}

locals {
  suffix             = random_id.bucket_suffix.hex
  ticket_bucket      = "${var.ticket_bucket_name}-${local.suffix}"
  data_lake_bucket   = "${var.data_lake_bucket_name}-${local.suffix}"
  benchmarks_bucket  = "${var.benchmarks_bucket_name}-${local.suffix}"
  reports_bucket     = "${var.reports_bucket_name}-${local.suffix}"
}

# 1. Ticket Ingest Bucket
resource "aws_s3_bucket" "tickets" {
  bucket        = local.ticket_bucket
  force_destroy = true

  tags = {
    Name        = local.ticket_bucket
    Environment = var.environment
  }
}

resource "aws_s3_bucket_ownership_controls" "tickets" {
  bucket = aws_s3_bucket.tickets.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_acl" "tickets" {
  depends_on = [aws_s3_bucket_ownership_controls.tickets]
  bucket     = aws_s3_bucket.tickets.id
  acl        = "private"
}

resource "aws_s3_bucket_public_access_block" "tickets" {
  bucket                  = aws_s3_bucket.tickets.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 2. Data Lake Bucket
resource "aws_s3_bucket" "data_lake" {
  bucket        = local.data_lake_bucket
  force_destroy = true

  tags = {
    Name        = local.data_lake_bucket
    Environment = var.environment
  }
}

resource "aws_s3_bucket_ownership_controls" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_acl" "data_lake" {
  depends_on = [aws_s3_bucket_ownership_controls.data_lake]
  bucket     = aws_s3_bucket.data_lake.id
  acl        = "private"
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket                  = aws_s3_bucket.data_lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    id     = "glacier-transition"
    status = "Enabled"
    filter {}

    transition {
      days          = 30
      storage_class = "GLACIER"
    }
  }
}

# 3. Benchmarks Bucket
resource "aws_s3_bucket" "benchmarks" {
  bucket        = local.benchmarks_bucket
  force_destroy = true

  tags = {
    Name        = local.benchmarks_bucket
    Environment = var.environment
  }
}

resource "aws_s3_bucket_ownership_controls" "benchmarks" {
  bucket = aws_s3_bucket.benchmarks.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_acl" "benchmarks" {
  depends_on = [aws_s3_bucket_ownership_controls.benchmarks]
  bucket     = aws_s3_bucket.benchmarks.id
  acl        = "private"
}

resource "aws_s3_bucket_public_access_block" "benchmarks" {
  bucket                  = aws_s3_bucket.benchmarks.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 4. Reports Bucket
resource "aws_s3_bucket" "reports" {
  bucket        = local.reports_bucket
  force_destroy = true

  tags = {
    Name        = local.reports_bucket
    Environment = var.environment
  }
}

resource "aws_s3_bucket_ownership_controls" "reports" {
  bucket = aws_s3_bucket.reports.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_acl" "reports" {
  depends_on = [aws_s3_bucket_ownership_controls.reports]
  bucket     = aws_s3_bucket.reports.id
  acl        = "private"
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "glacier-transition"
    status = "Enabled"
    filter {}

    transition {
      days          = 30
      storage_class = "GLACIER"
    }
  }
}

output "ticket_bucket_name" {
  value       = aws_s3_bucket.tickets.bucket
  description = "Name of the ticket ingest bucket"
}

output "ticket_bucket_arn" {
  value       = aws_s3_bucket.tickets.arn
  description = "ARN of the ticket ingest bucket"
}

output "data_lake_bucket_name" {
  value       = aws_s3_bucket.data_lake.bucket
  description = "Name of the data lake bucket"
}

output "data_lake_bucket_arn" {
  value       = aws_s3_bucket.data_lake.arn
  description = "ARN of the data lake bucket"
}

output "benchmarks_bucket_name" {
  value       = aws_s3_bucket.benchmarks.bucket
  description = "Name of the benchmarks bucket"
}

output "reports_bucket_name" {
  value       = aws_s3_bucket.reports.bucket
  description = "Name of the reports bucket"
}
