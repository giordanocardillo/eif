variable "identifier" {
  description = "Unique identifier for the RDS instance."
  type        = string
}

variable "engine" {
  description = "Database engine (e.g. postgres, mysql)."
  type        = string
  default     = "postgres"
}

variable "engine_version" {
  description = "Database engine version."
  type        = string
  default     = "15"
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.medium"
}

variable "allocated_storage_gb" {
  description = "Allocated storage in gigabytes."
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Name of the initial database."
  type        = string
}

variable "db_username" {
  description = "Master username for the database."
  type        = string
}

variable "multi_az" {
  description = "Enable Multi-AZ deployment."
  type        = bool
  default     = false
}

variable "subnet_ids" {
  description = "List of subnet IDs for the DB subnet group."
  type        = list(string)
}

variable "vpc_security_group_ids" {
  description = "List of VPC security group IDs."
  type        = list(string)
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}
