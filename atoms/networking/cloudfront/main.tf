terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
  required_version = ">= 1.5"
}

locals {
  origin_id = "eif-origin-${var.environment}"
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  price_class         = var.price_class
  web_acl_id          = var.web_acl_id != "" ? var.web_acl_id : null
  default_root_object = "index.html"

  origin {
    domain_name = var.origin_domain_name
    origin_id   = local.origin_id

    s3_origin_config {
      origin_access_identity = ""
    }
  }

  default_cache_behavior {
    target_origin_id       = local.origin_id
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Environment = var.environment
    ManagedBy   = "eif"
  }
}
