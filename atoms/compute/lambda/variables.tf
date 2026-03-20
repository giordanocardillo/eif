variable "function_name" {
  description = "Name of the Lambda function."
  type        = string
}

variable "runtime" {
  description = "Lambda runtime identifier."
  type        = string
  default     = "python3.12"
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

variable "subnet_ids" {
  description = "VPC subnet IDs for the function. Leave empty for no VPC."
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "VPC security group IDs for the function."
  type        = list(string)
  default     = []
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}
