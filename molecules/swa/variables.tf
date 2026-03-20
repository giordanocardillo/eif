variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "bucket_name" {
  description = "S3 bucket name for static assets."
  type        = string
}

variable "s3_versioning_enabled" {
  description = "Enable versioning on the S3 origin bucket."
  type        = bool
  default     = false
}

variable "cloudfront_price_class" {
  description = "CloudFront price class."
  type        = string
  default     = "PriceClass_100"
}

variable "waf_name" {
  description = "Name for the WAF WebACL."
  type        = string
  default     = "swa-waf"
}

variable "waf_managed_rule_group" {
  description = "AWS managed rule group name for WAF."
  type        = string
  default     = "AWSManagedRulesCommonRuleSet"
}
