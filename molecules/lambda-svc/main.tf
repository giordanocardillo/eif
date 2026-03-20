terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
  required_version = ">= 1.5"
}

# ── Atom: Security Group ──────────────────────────────────────────────────────
module "sg" {
  source = "../../atoms/security/sg"

  name        = "${var.function_name}-sg"
  description = "Security group for ${var.function_name} Lambda function"
  vpc_id      = var.vpc_id
  environment = var.environment
}

# ── Atom: Lambda ──────────────────────────────────────────────────────────────
# depends on: module.sg.security_group_id
module "lambda" {
  source = "../../atoms/compute/lambda"

  function_name          = var.function_name
  runtime                = var.runtime
  handler                = var.handler
  memory_mb              = var.memory_mb
  timeout_s              = var.timeout_s
  environment_variables  = var.environment_variables
  subnet_ids             = var.subnet_ids
  security_group_ids     = [module.sg.security_group_id]
  environment            = var.environment
}
