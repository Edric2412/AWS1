variable "ticket_bucket_name" {
  type        = string
  description = "Name of the ticket S3 bucket"
}

variable "ticket_bucket_arn" {
  type        = string
  description = "ARN of the ticket S3 bucket"
}

variable "redpanda_proxy_url" {
  type        = string
  description = "REDPANDA_PROXY_URL pointing to EC2 Redpanda API"
}

variable "environment" {
  type        = string
  description = "Environment name"
}

# Package the Lambda python code into a ZIP
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../../../lambda/ticket_ingest"
  output_path = "${path.module}/ticket_ingest.zip"
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "syncops-${var.environment}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for S3 read and CloudWatch logs
resource "aws_iam_role_policy" "lambda_policy" {
  name = "syncops-${var.environment}-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # CloudWatch Logs permissions
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      # S3 read permissions for the ticket bucket
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          "${var.ticket_bucket_arn}/*"
        ]
      }
    ]
  })
}

# Lambda Function
resource "aws_lambda_function" "ingest" {
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  function_name    = "syncops-${var.environment}-ticket-ingest"
  role             = aws_iam_role.lambda_role.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  timeout          = 30

  environment {
    variables = {
      REDPANDA_PROXY_URL = var.redpanda_proxy_url
      TICKET_TOPIC       = "tickets"
    }
  }

  tags = {
    Name        = "syncops-${var.environment}-ticket-ingest-lambda"
    Environment = var.environment
  }
}

# Grant S3 permission to invoke the Lambda function
resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.ticket_bucket_arn
}

# Configure S3 bucket notification trigger
resource "aws_s3_bucket_notification" "tickets_trigger" {
  bucket = var.ticket_bucket_name

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3]
}

output "lambda_arn" {
  value       = aws_lambda_function.ingest.arn
  description = "ARN of the ticket ingest Lambda function"
}
