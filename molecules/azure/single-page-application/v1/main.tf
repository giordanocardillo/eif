terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.0"
    }
  }
  required_version = ">= 1.5"
}

# ── Atom: Blob Storage (static website origin) ────────────────────────────────
module "blob" {
  source = "../../../../atoms/azure/storage/blob/v1"

  environment              = var.environment
  resource_group_name      = var.resource_group_name
  location                 = var.location
  storage_account_name     = var.storage_account_name
  account_tier             = var.account_tier
  account_replication_type = var.account_replication_type
}

# ── Atom: Front Door (global CDN + HTTPS redirect) ────────────────────────────
# depends on: frontdoor ← blob.primary_web_endpoint (origin)
module "frontdoor" {
  source = "../../../../atoms/azure/networking/frontdoor/v1"

  environment         = var.environment
  resource_group_name = var.resource_group_name
  profile_name        = var.frontdoor_profile_name
  endpoint_name       = var.frontdoor_endpoint_name
  sku_name            = var.frontdoor_sku_name
  origin_host_name    = replace(module.blob.primary_web_endpoint, "https://", "")
}
