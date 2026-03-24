terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
  required_version = ">= 1.5"
}

# depends on: cdn ← gcs.bucket_name

module "gcs" {
  source = "../../../../atoms/gcp/storage/gcs/v1"

  environment = var.environment
  bucket_name = var.bucket_name
  location    = var.location
}

module "armor" {
  source = "../../../../atoms/gcp/security/armor/v1"

  environment       = var.environment
  policy_name       = var.armor_policy_name
  blocked_ip_ranges = var.blocked_ip_ranges
}

module "cdn" {
  source = "../../../../atoms/gcp/networking/cdn/v1"

  environment = var.environment
  cdn_name    = var.cdn_name
  bucket_name = module.gcs.bucket_name
}
