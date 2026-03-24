output "cloudfront_domain" {
  description = "Public domain of the CloudFront distribution."
  value       = module.cloudfront.distribution_domain_name
}

output "cloudfront_distribution_id" {
  description = "ID of the CloudFront distribution."
  value       = module.cloudfront.distribution_id
}

output "s3_bucket_id" {
  description = "Name of the S3 origin bucket."
  value       = module.s3.bucket_id
}
