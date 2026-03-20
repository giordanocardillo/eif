output "instance_id" {
  description = "The RDS instance identifier."
  value       = aws_db_instance.this.identifier
}

output "endpoint" {
  description = "The connection endpoint of the RDS instance."
  value       = aws_db_instance.this.endpoint
}

output "port" {
  description = "The port the database is listening on."
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "The name of the initial database."
  value       = aws_db_instance.this.db_name
}
