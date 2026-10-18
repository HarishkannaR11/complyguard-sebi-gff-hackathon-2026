output "app_url" {
  description = "Open this. Frontend at /, API at /api (e.g. /api/livez)."
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "web_bucket" {
  description = "Upload the built frontend (frontend/dist) here."
  value       = aws_s3_bucket.web.bucket
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.web.id
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service" {
  value = aws_ecs_service.api.name
}

output "alb_dns_name" {
  description = "Point origin_domain_name at this (CNAME) when using alb_certificate_arn."
  value       = aws_lb.api.dns_name
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

output "qdrant_url" {
  value = local.qdrant_url
}

output "logs_command" {
  value = "aws logs tail ${aws_cloudwatch_log_group.api.name} --follow --region ${var.region}"
}

output "shell_command" {
  description = "Shell inside the running API task (ECS Exec)."
  value       = "aws ecs execute-command --region ${var.region} --cluster ${aws_ecs_cluster.main.name} --task $(aws ecs list-tasks --region ${var.region} --cluster ${aws_ecs_cluster.main.name} --service-name ${aws_ecs_service.api.name} --query 'taskArns[0]' --output text) --container api --interactive --command /bin/bash"
}

output "region" {
  value = var.region
}
