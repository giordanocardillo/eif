variable "environment"              { type = string }
variable "resource_group_name"      { type = string }
variable "location"                 { type = string }
variable "storage_account_name"     { type = string }
variable "account_tier"             { type = string ; default = "Standard" }
variable "account_replication_type" { type = string ; default = "LRS" }
variable "frontdoor_profile_name"   { type = string }
variable "frontdoor_endpoint_name"  { type = string }
variable "frontdoor_sku_name"       { type = string ; default = "Standard_AzureFrontDoor" }
