output "function_url" {
  description = "URL for the simulator"
  value       = google_cloudfunctions2_function.api.url
}

output "log_analytics_view" {
  description = "Table name for SQL queries in Log Analytics"
  value       = "`${var.project_id}.global._Default._Default`"
}

output "dashboards_console" {
  value = "https://console.cloud.google.com/monitoring/dashboards?project=${var.project_id}"
}

output "log_analytics_console" {
  value = "https://console.cloud.google.com/logs/analytics?project=${var.project_id}"
}
