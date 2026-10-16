variable "project_id" {
  description = "GCP project ID for this team"
  type        = string
}

variable "region" {
  description = "Region for the function and the source bucket"
  type        = string
  default     = "us-central1"
}

variable "function_name" {
  description = "Function name (lowercase letters, digits and hyphens)"
  type        = string
  default     = "orders-api"
}

variable "runtime" {
  description = "Cloud Run functions runtime"
  type        = string
  default     = "python313"
}

variable "entry_point" {
  description = "Name of the Python function that handles requests"
  type        = string
  default     = "handle"
}

variable "source_dir" {
  description = "Folder with main.py and requirements.txt"
  type        = string
  default     = "../backend"
}

variable "failure_rate" {
  description = "Probability of a simulated internal failure (0 to 1)"
  type        = number
  default     = 0.02
}

variable "extra_latency_ms" {
  description = "Extra latency added by the backend, in milliseconds"
  type        = number
  default     = 0
}

variable "extra_env" {
  description = "Additional environment variables for the backend"
  type        = map(string)
  default     = {}
}

variable "max_instances" {
  description = "Upper limit for autoscaling"
  type        = number
  default     = 10
}

variable "concurrency" {
  description = "Concurrent requests per instance"
  type        = number
  default     = 1
}

variable "allow_unauthenticated" {
  description = "Allow public calls so the simulator needs no token"
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "Retention for the _Default log bucket"
  type        = number
  default     = 30
}

variable "student_members" {
  description = "IAM members who need access, e.g. user:name@uvg.edu.gt"
  type        = list(string)
  default     = []
}
