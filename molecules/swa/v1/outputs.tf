output "cloudfront_domain" {
  description = "Public domain of the CloudFront distribution."
  value       = module.cloudfront.distribution_domain_name
}

output "s3_bucket_id" {
  description = "Name of the S3 origin bucket."
  value       = module.s3.bucket_id
}

output "waf_web_acl_arn" {
  description = "ARN of the WAF WebACL."
  value       = module.waf.web_acl_arn
}
