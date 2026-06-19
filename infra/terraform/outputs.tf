output "ec2_public_ip" {
  value       = module.ec2.public_ip
  description = "Public IP of the EC2 K3s host"
}

output "ec2_private_ip" {
  value       = module.ec2.private_ip
  description = "Private IP of the EC2 K3s host"
}

output "ecr_repository_url" {
  value       = module.ecr.repository_url
  description = "URL of the created ECR repository"
}

output "ticket_bucket_name" {
  value       = module.s3.ticket_bucket_name
  description = "Name of the ticket ingest S3 bucket"
}

output "data_lake_bucket_name" {
  value       = module.s3.data_lake_bucket_name
  description = "Name of the data lake S3 bucket"
}

output "benchmarks_bucket_name" {
  value       = module.s3.benchmarks_bucket_name
  description = "Name of the benchmarks S3 bucket"
}

output "reports_bucket_name" {
  value       = module.s3.reports_bucket_name
  description = "Name of the reports S3 bucket"
}

output "lambda_arn" {
  value       = module.lambda.lambda_arn
  description = "ARN of the ticket ingest Lambda function"
}
