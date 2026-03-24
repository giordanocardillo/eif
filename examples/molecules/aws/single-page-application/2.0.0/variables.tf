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

variable "custom_domain" {
  description = "Custom domain name to associate with the CloudFront distribution."
  type        = string
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for the custom domain (must be in us-east-1)."
  type        = string
}
