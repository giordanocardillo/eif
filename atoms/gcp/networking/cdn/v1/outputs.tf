output "ip_address"          { value = google_compute_global_forwarding_rule.this.ip_address }
output "backend_bucket_name" { value = google_compute_backend_bucket.this.name }
