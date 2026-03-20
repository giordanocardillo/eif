resource "google_compute_security_policy" "this" {
  name = var.policy_name

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    description = "default allow rule"
  }

  dynamic "rule" {
    for_each = var.blocked_ip_ranges
    content {
      action   = "deny(403)"
      priority = rule.key + 1
      match {
        versioned_expr = "SRC_IPS_V1"
        config { src_ip_ranges = [rule.value] }
      }
    }
  }
}
