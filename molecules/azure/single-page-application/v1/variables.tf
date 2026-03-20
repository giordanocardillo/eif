variable "environment"              { type = string }
variable "resource_group_name"      { type = string }
variable "location"                 { type = string }
variable "storage_account_name"     { type = string }
variable "account_tier"             { type = string; default = "Standard" }
variable "account_replication_type" { type = string; default = "LRS" }
variable "cdn_profile_name"         { type = string }
variable "cdn_endpoint_name"        { type = string }
variable "cdn_sku"                  { type = string; default = "Standard_Microsoft" }
