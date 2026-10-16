locals {
  services = [
    "cloudfunctions.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "iam.googleapis.com",
  ]

  student_roles = [
    "roles/monitoring.editor",
    "roles/logging.viewer",
    "roles/logging.configWriter",
    "roles/cloudfunctions.viewer",
  ]

  student_grants = {
    for pair in setproduct(var.student_members, local.student_roles) :
    "${pair[0]}|${pair[1]}" => { member = pair[0], role = pair[1] }
  }
}

# APIs
resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# Log Analytics on the _Default bucket.
# The upgrade is permanent; destroying this resource does not undo it.
resource "google_logging_project_bucket_config" "default" {
  project          = var.project_id
  location         = "global"
  bucket_id        = "_Default"
  retention_days   = var.log_retention_days
  enable_analytics = true

  depends_on = [google_project_service.apis]
}

# Identities
resource "google_service_account" "runtime" {
  account_id   = "${var.function_name}-run"
  display_name = "Runtime identity for ${var.function_name}"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "build" {
  account_id   = "${var.function_name}-build"
  display_name = "Build identity for ${var.function_name}"

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset(["roles/logging.logWriter", "roles/monitoring.metricWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "build_roles" {
  for_each = toset(["roles/cloudbuild.builds.builder", "roles/logging.logWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.build.email}"
}

resource "google_project_iam_member" "students" {
  for_each = local.student_grants
  project  = var.project_id
  role     = each.value.role
  member   = each.value.member
}

# Source code
resource "google_storage_bucket" "source" {
  name                        = "${var.project_id}-${var.function_name}-src"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  depends_on = [google_project_service.apis]
}

data "archive_file" "source" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/function-source.zip"
}

# The hash in the name forces a redeploy whenever the code changes
resource "google_storage_bucket_object" "source" {
  name   = "function-source-${data.archive_file.source.output_md5}.zip"
  bucket = google_storage_bucket.source.name
  source = data.archive_file.source.output_path
}

# Function
resource "google_cloudfunctions2_function" "api" {
  name     = var.function_name
  location = var.region

  build_config {
    runtime         = var.runtime
    entry_point     = var.entry_point
    service_account = google_service_account.build.id

    source {
      storage_source {
        bucket = google_storage_bucket.source.name
        object = google_storage_bucket_object.source.name
      }
    }
  }

  service_config {
    available_memory                 = "512Mi"
    available_cpu                    = "1"
    timeout_seconds                  = 60
    min_instance_count               = 0
    max_instance_count               = var.max_instances
    max_instance_request_concurrency = var.concurrency
    service_account_email            = google_service_account.runtime.email
    ingress_settings                 = "ALLOW_ALL"

    environment_variables = merge(var.extra_env, {
      FAILURE_RATE     = tostring(var.failure_rate)
      EXTRA_LATENCY_MS = tostring(var.extra_latency_ms)
    })
  }

  depends_on = [
    google_project_iam_member.build_roles,
    google_project_iam_member.runtime_roles,
  ]
}

# Public access for the simulator
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
