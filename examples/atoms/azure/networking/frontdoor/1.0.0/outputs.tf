output "endpoint_hostname" { value = azurerm_cdn_frontdoor_endpoint.this.host_name }
output "endpoint_id"       { value = azurerm_cdn_frontdoor_endpoint.this.id }
output "profile_id"        { value = azurerm_cdn_frontdoor_profile.this.id }
