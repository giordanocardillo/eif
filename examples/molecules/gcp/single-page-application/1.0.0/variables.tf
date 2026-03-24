variable "environment"       { type = string }
variable "bucket_name"       { type = string }
variable "location"          { type = string }
variable "cdn_name"          { type = string }
variable "armor_policy_name" { type = string }
variable "blocked_ip_ranges" { type = list(string); default = [] }
