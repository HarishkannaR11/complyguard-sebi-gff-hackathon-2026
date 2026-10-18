output "public_ip" {
  description = "Elastic IP of the host. Point your domain's A record here."
  value       = aws_eip.app.public_ip
}

output "app_url" {
  description = "Where the app is served once the first boot has finished building (~10-15 min)."
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "http://${aws_eip.app.public_ip}"
}

output "instance_id" {
  value = aws_instance.app.id
}

output "ssm_session_command" {
  description = "Shell on the host without SSH."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.app.id}"
}

output "bootstrap_log_command" {
  description = "Run on the host to follow the first-boot build."
  value       = "sudo tail -f /var/log/regops-bootstrap.log"
}

output "redeploy_command" {
  description = "Run on the host to pull the latest code and rebuild."
  value       = "sudo /opt/regops/redeploy.sh"
}
