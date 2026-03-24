resource "google_compute_backend_bucket" "this" {
  name        = "${var.cdn_name}-backend"
  bucket_name = var.bucket_name
  enable_cdn  = true
}

resource "google_compute_url_map" "this" {
  name            = "${var.cdn_name}-url-map"
  default_service = google_compute_backend_bucket.this.self_link
}

resource "google_compute_target_http_proxy" "this" {
  name    = "${var.cdn_name}-proxy"
  url_map = google_compute_url_map.this.self_link
}

resource "google_compute_global_forwarding_rule" "this" {
  name        = "${var.cdn_name}-forwarding-rule"
  target      = google_compute_target_http_proxy.this.self_link
  port_range  = "80"
  ip_protocol = "TCP"
}
