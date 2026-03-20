variable "name" {
  description = "Name of the security group."
  type        = string
}

variable "description" {
  description = "Description of the security group."
  type        = string
  default     = "Managed by EIF"
}

variable "vpc_id" {
  description = "ID of the VPC in which to create the security group."
  type        = string
}

variable "ingress_rules" {
  description = "List of ingress rules."
  type = list(object({
    from_port   = number
    to_port     = number
    protocol    = string
    cidr_blocks = list(string)
    description = string
  }))
  default = []
}

variable "egress_rules" {
  description = "List of egress rules."
  type = list(object({
    from_port   = number
    to_port     = number
    protocol    = string
    cidr_blocks = list(string)
    description = string
  }))
  default = [{
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }]
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}
