variable "environment"        { description = "Deployment environment (e.g. dev, test, prod)." ; type = string }
variable "resource_group_name" { description = "Azure resource group name."                      ; type = string }
variable "profile_name"        { description = "Front Door profile name."                        ; type = string }
variable "endpoint_name"       { description = "Front Door endpoint name."                       ; type = string }
variable "origin_host_name"    { description = "Origin hostname (e.g. storage static website)." ; type = string }
variable "sku_name"            { description = "Front Door SKU."                                 ; type = string ; default = "Standard_AzureFrontDoor" }
