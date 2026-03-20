resource "azurerm_cdn_profile" "this" {
  name                = var.cdn_profile_name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = var.sku

  tags = { environment = var.environment }
}

resource "azurerm_cdn_endpoint" "this" {
  name                = var.cdn_endpoint_name
  profile_name        = azurerm_cdn_profile.this.name
  location            = var.location
  resource_group_name = var.resource_group_name

  origin {
    name      = "storage-origin"
    host_name = var.origin_host_name
  }

  tags = { environment = var.environment }
}
