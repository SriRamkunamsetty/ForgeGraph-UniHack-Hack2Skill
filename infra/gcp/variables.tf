variable "project_id" {
  description = "GCP project ID with billing enabled."
  type        = string
}

variable "region" {
  description = "Primary GCP region for regional services."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "staging"
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "Environment must be staging or production."
  }
}

variable "api_image" {
  description = "Artifact Registry image URI for the ForgeGraph API container."
  type        = string
}

variable "database_password" {
  description = "Initial Cloud SQL password; store this in a protected tfvars file or CI secret."
  type        = string
  sensitive   = true
}

variable "worker_token" {
  description = "Secret token used as a defense-in-depth check for the Cloud Tasks worker endpoint."
  type        = string
  sensitive   = true
}

variable "artifact_bucket_name" {
  description = "Globally unique GCS bucket name for immutable ForgeGraph artifacts."
  type        = string
}

variable "cors_origins" {
  description = "Comma-separated browser origins allowed to call the API."
  type        = string
  default     = "https://forgegraph-unihack-hack2skill.vercel.app"
}

variable "cloud_sql_tier" {
  description = "Cloud SQL machine tier."
  type        = string
  default     = "db-custom-2-7680"
}

variable "cloud_sql_disk_gb" {
  description = "Initial Cloud SQL SSD disk size."
  type        = number
  default     = 50
}

variable "artifact_retention_days" {
  description = "Retention period for non-production artifact objects."
  type        = number
  default     = 90
}

variable "cloud_run_cpu" {
  description = "Cloud Run CPU limit."
  type        = string
  default     = "2"
}

variable "cloud_run_memory" {
  description = "Cloud Run memory limit."
  type        = string
  default     = "2Gi"
}

variable "cloud_run_max_instances" {
  description = "Cloud Run autoscaling ceiling."
  type        = number
  default     = 20
}

variable "max_concurrent_tasks" {
  description = "Cloud Tasks concurrency ceiling."
  type        = number
  default     = 10
}

variable "max_tasks_per_second" {
  description = "Cloud Tasks dispatch rate."
  type        = number
  default     = 5
}

variable "enable_cloud_tasks" {
  description = "Enable asynchronous Cloud Tasks processing after the initial API revision is verified."
  type        = bool
  default     = false
}

variable "cloud_tasks_dispatch_url" {
  description = "Verified Cloud Run URL used as the Cloud Tasks callback base."
  type        = string
  default     = ""
}
