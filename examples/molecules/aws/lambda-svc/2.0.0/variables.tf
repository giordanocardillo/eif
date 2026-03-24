variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "function_name" {
  description = "Name of the Lambda function."
  type        = string
}

variable "runtime" {
  description = "Lambda runtime identifier."
  type        = string
  default     = "python3.13"
}

variable "handler" {
  description = "Function entrypoint in the form file.method."
  type        = string
  default     = "handler.lambda_handler"
}

variable "memory_mb" {
  description = "Amount of memory in MB allocated to the function."
  type        = number
  default     = 128
}

variable "timeout_s" {
  description = "Function timeout in seconds."
  type        = number
  default     = 30
}

variable "environment_variables" {
  description = "Environment variables to pass to the function."
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "VPC ID for the security group."
  type        = string
}

variable "subnet_ids" {
  description = "VPC subnet IDs for the Lambda function."
  type        = list(string)
}

variable "log_retention_days" {
  description = "CloudWatch log group retention in days."
  type        = number
  default     = 14
}
