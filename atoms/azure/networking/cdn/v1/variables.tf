variable "environment"        { type = string }
variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "cdn_profile_name"    { type = string }
variable "cdn_endpoint_name"   { type = string }
variable "origin_host_name"    { type = string }
variable "sku"                 { type = string; default = "Standard_Microsoft" }
