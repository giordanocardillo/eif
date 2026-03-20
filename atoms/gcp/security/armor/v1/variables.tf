variable "environment"       { type = string }
variable "policy_name"       { type = string }
variable "blocked_ip_ranges" { type = list(string); default = [] }
