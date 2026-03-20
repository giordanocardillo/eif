variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "identifier" {
  description = "Unique identifier for the RDS instance."
  type        = string
}

variable "db_name" {
  description = "Name of the initial database."
  type        = string
}

variable "db_username" {
  description = "Master username for the database."
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

variable "multi_az" {
  description = "Enable Multi-AZ deployment."
  type        = bool
  default     = false
}

variable "subnet_ids" {
  description = "List of subnet IDs for the DB subnet group."
  type        = list(string)
}

variable "vpc_id" {
  description = "VPC ID for the security group."
  type        = string
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to connect to the database."
  type        = list(string)
  default     = []
}
