terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
  required_version = ">= 1.5"
}

# ── Internal dependency: derive DB port from engine ───────────────────────────
# sg depends on this value → rds depends on sg.security_group_id
locals {
  db_port = {
    postgres = 5432
    mysql    = 3306
    mariadb  = 3306
  }[var.engine]
}

# ── Atom: Security Group ──────────────────────────────────────────────────────
module "sg" {
  source = "../../atoms/security/sg"

  name        = "${var.identifier}-sg"
  description = "Security group for ${var.identifier} ${var.engine} instance"
  vpc_id      = var.vpc_id
  environment = var.environment

  ingress_rules = [
    {
      from_port   = local.db_port
      to_port     = local.db_port
      protocol    = "tcp"
      cidr_blocks = var.allowed_cidr_blocks
      description = "${var.engine} access on port ${local.db_port}"
    }
  ]
}

# ── Atom: RDS ─────────────────────────────────────────────────────────────────
# depends on: module.sg.security_group_id
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
