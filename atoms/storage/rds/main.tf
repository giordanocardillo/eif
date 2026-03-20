terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
  required_version = ">= 1.5"
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.identifier}-subnet-group"
  subnet_ids = var.subnet_ids

  tags = {
    Environment = var.environment
    ManagedBy   = "eif"
  }
}

resource "aws_db_instance" "this" {
  identifier        = var.identifier
  engine            = var.engine
  engine_version    = var.engine_version
  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage_gb

  db_name  = var.db_name
  username = var.db_username

  # Password managed via Secrets Manager — not set here.
  manage_master_user_password = true

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.vpc_security_group_ids

  skip_final_snapshot = false
  final_snapshot_identifier = "${var.identifier}-final"

  tags = {
    Environment = var.environment
    ManagedBy   = "eif"
  }
}
