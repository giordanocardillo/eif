output "db_endpoint" {
  description = "Connection endpoint of the RDS instance."
  value       = module.rds.endpoint
}

output "db_port" {
  description = "Port the database is listening on."
  value       = module.rds.port
}

output "db_name" {
  description = "Name of the initial database."
  value       = module.rds.db_name
}

output "security_group_id" {
  description = "ID of the database security group."
  value       = module.sg.security_group_id
}
