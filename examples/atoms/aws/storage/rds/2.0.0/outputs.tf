output "endpoint" {
  description = "Connection endpoint of the RDS instance."
  value       = aws_db_instance.this.endpoint
}

output "port" {
  description = "Port the database is listening on."
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "Name of the initial database."
  value       = aws_db_instance.this.db_name
}

output "arn" {
  description = "ARN of the RDS instance."
  value       = aws_db_instance.this.arn
}

output "resource_id" {
  description = "RDS resource ID (used for IAM authentication policies)."
  value       = aws_db_instance.this.resource_id
}
