terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
  required_version = ">= 1.5"
}

# ── Atom: S3 ──────────────────────────────────────────────────────────────────
module "s3" {
  source = "../../../../atoms/aws/storage/s3/v1"

  bucket_name        = var.bucket_name
  versioning_enabled = var.s3_versioning_enabled
  environment        = var.environment
}

# ── Atom: WAF ─────────────────────────────────────────────────────────────────
module "waf" {
  source = "../../../../atoms/aws/security/waf/v1"

  name                    = var.waf_name
  environment             = var.environment
  managed_rule_group_name = var.waf_managed_rule_group
}

# ── Atom: CloudFront ──────────────────────────────────────────────────────────
# depends on: module.s3.bucket_regional_domain_name, module.waf.web_acl_arn
module "cloudfront" {
  source = "../../../../atoms/aws/networking/cloudfront/v1"

  origin_domain_name = module.s3.bucket_regional_domain_name
  environment        = var.environment
  price_class        = var.cloudfront_price_class
  web_acl_id         = module.waf.web_acl_arn
}
