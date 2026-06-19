variable "environment" {
  type        = string
  description = "Environment name"
}

resource "aws_ecr_repository" "app" {
  name                 = "syncops-${var.environment}-app"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "syncops-${var.environment}-app-ecr"
    Environment = var.environment
  }
}

resource "aws_ecr_lifecycle_policy" "app_policy" {
  repository = aws_ecr_repository.app.name

  policy = <<EOF
{
    "rules": [
        {
            "rulePriority": 1,
            "description": "Keep last 5 images",
            "selection": {
                "tagStatus": "any",
                "countType": "imageCountMoreThan",
                "countNumber": 5
            },
            "action": {
                "type": "expire"
            }
        }
    ]
}
EOF
}

output "repository_url" {
  value       = aws_ecr_repository.app.repository_url
  description = "URL of the created ECR repository"
}

output "repository_name" {
  value       = aws_ecr_repository.app.name
  description = "Name of the ECR repository"
}
