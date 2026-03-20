terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.0"
    }
  }
  required_version = ">= 1.5"
}

# depends on: cdn ← blob.primary_web_endpoint (origin)

module "blob" {
  source = "../../../../atoms/azure/storage/blob/v1"

  environment              = var.environment
  resource_group_name      = var.resource_group_name
  location                 = var.location
  storage_account_name     = var.storage_account_name
  account_tier             = var.account_tier
  account_replication_type = var.account_replication_type
}

module "cdn" {
  source = "../../../../atoms/azure/networking/cdn/v1"

  environment         = var.environment
  resource_group_name = var.resource_group_name
  location            = var.location
  cdn_profile_name    = var.cdn_profile_name
  cdn_endpoint_name   = var.cdn_endpoint_name
  sku                 = var.cdn_sku
  origin_host_name    = replace(module.blob.primary_web_endpoint, "https://", "")
}
