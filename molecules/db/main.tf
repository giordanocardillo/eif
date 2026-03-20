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

  name        = "${var.identifier}-sg"
  description = "Security group for ${var.identifier} RDS instance"
  vpc_id      = var.vpc_id
  environment = var.environment

  ingress_rules = [
    {
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = var.allowed_cidr_blocks
      description = "PostgreSQL access"
    }
  ]
}

# ── Atom: RDS ─────────────────────────────────────────────────────────────────
module "rds" {
  source = "../../atoms/storage/rds"

  identifier             = var.identifier
  engine                 = var.engine
  engine_version         = var.engine_version
  instance_class         = var.instance_class
  db_name                = var.db_name
  db_username            = var.db_username
  multi_az               = var.multi_az
  subnet_ids             = var.subnet_ids
  vpc_security_group_ids = [module.sg.security_group_id]
  environment            = var.environment
}
