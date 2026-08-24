terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
  backend "gcs" {
    bucket = "YOUR_TERRAFORM_STATE_BUCKET"
    prefix = "forgegraph/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# ── Variables ─────────────────────────────────────────────────────────────────
variable "project_id" {
  description = "GCP Project ID"
  type        = string
  default     = "YOUR_GCP_PROJECT_ID"
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "asia-south1"
}

variable "app_name" {
  description = "Application name used for resource naming"
  type        = string
  default     = "forgegraph"
}

variable "environment" {
  description = "Deployment environment (production, staging)"
  type        = string
  default     = "production"
}

variable "db_password" {
  description = "PostgreSQL database password"
  type        = string
  sensitive   = true
}

variable "internal_worker_token" {
  description = "Shared secret for Cloud Tasks worker authentication"
  type        = string
  sensitive   = true
}

variable "ai_api_key" {
  description = "AI provider API key (if using OpenAI-compatible provider)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "manufacturer_domains" {
  description = "Comma-separated approved manufacturer domains for evidence retrieval"
  type        = string
  default     = ""
}

variable "cors_origins" {
  description = "Comma-separated allowed CORS origins"
  type        = string
  default     = "https://forgegraph-unihack-hack2skill.vercel.app"
}

# ── APIs ──────────────────────────────────────────────────────────────────────
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
    "cloudtasks.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# ── Service Account ───────────────────────────────────────────────────────────
resource "google_service_account" "api" {
  account_id   = "${var.app_name}-api"
  display_name = "ForgeGraph API Service Account"
  project      = var.project_id
}

resource "google_project_iam_member" "api_roles" {
  for_each = toset([
    "roles/cloudsql.client",
    "roles/storage.objectAdmin",
    "roles/cloudtasks.enqueuer",
    "roles/secretmanager.secretAccessor",
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.api.email}"
}

# ── VPC Network ───────────────────────────────────────────────────────────────
resource "google_compute_network" "main" {
  name                    = "${var.app_name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  name          = "${var.app_name}-subnet"
  ip_cidr_range = "10.10.0.0/24"
  region        = var.region
  network       = google_compute_network.main.id
}

resource "google_compute_global_address" "private_ip" {
  name          = "${var.app_name}-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}

resource "google_service_networking_connection" "private_vpc" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip.name]
  depends_on              = [google_project_service.apis]
}

resource "google_vpc_access_connector" "connector" {
  name          = "${var.app_name}-connector"
  region        = var.region
  network       = google_compute_network.main.name
  ip_cidr_range = "10.8.0.0/28"
  min_instances = 2
  max_instances = 10
}

# ── Cloud SQL (PostgreSQL 15) ─────────────────────────────────────────────────
resource "google_sql_database_instance" "postgres" {
  name             = "${var.app_name}-db-${var.environment}"
  database_version = "POSTGRES_15"
  region           = var.region
  deletion_protection = true

  settings {
    tier              = "db-custom-2-4096"
    availability_type = "REGIONAL"

    disk_type       = "PD_SSD"
    disk_size       = 50
    disk_autoresize = true

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 30
        retention_unit   = "COUNT"
      }
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
    }

    maintenance_window {
      day  = 7
      hour = 4
    }

    database_flags {
      name  = "max_connections"
      value = "200"
    }
    database_flags {
      name  = "pg_stat_statements.track"
      value = "all"
    }
  }

  depends_on = [google_service_networking_connection.private_vpc]
}

resource "google_sql_database" "forgegraph" {
  name     = var.app_name
  instance = google_sql_database_instance.postgres.name
  charset  = "UTF8"
}

resource "google_sql_user" "api_user" {
  name     = "${var.app_name}_api"
  instance = google_sql_database_instance.postgres.name
  password = var.db_password
}

# ── GCS Bucket ────────────────────────────────────────────────────────────────
resource "google_storage_bucket" "artifacts" {
  name          = "${var.project_id}-${var.app_name}-artifacts"
  location      = var.region
  storage_class = "STANDARD"
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  cors {
    origin          = ["*"]
    method          = ["GET", "HEAD"]
    response_header = ["Content-Type"]
    max_age_seconds = 3600
  }
}

resource "google_storage_bucket_iam_member" "api_storage" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}

# ── Secret Manager ────────────────────────────────────────────────────────────
locals {
  secrets = {
    db_password           = var.db_password
    internal_worker_token = var.internal_worker_token
    ai_api_key            = var.ai_api_key
  }
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secrets
  secret_id = "${var.app_name}-${replace(each.key, "_", "-")}"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "secret_versions" {
  for_each    = local.secrets
  secret      = google_secret_manager_secret.secrets[each.key].id
  secret_data = each.value
}

# ── Cloud Tasks Queue ─────────────────────────────────────────────────────────
resource "google_cloud_tasks_queue" "jobs" {
  name     = "${var.app_name}-jobs"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 10
    max_concurrent_dispatches = 5
  }

  retry_config {
    max_attempts       = 5
    max_retry_duration = "3600s"
    min_backoff        = "10s"
    max_backoff        = "300s"
    max_doublings      = 4
  }
}

# ── Cloud Run ─────────────────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "api" {
  name     = "${var.app_name}-api"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api.email

    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    scaling {
      min_instance_count = 1
      max_instance_count = 20
    }

    containers {
      image = "gcr.io/${var.project_id}/${var.app_name}-api:latest"
      name  = "api"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      ports {
        container_port = 8080
      }

      # Runtime environment
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "CORS_ORIGINS"
        value = var.cors_origins
      }
      env {
        name  = "STORAGE_BACKEND"
        value = "postgres"
      }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+psycopg://${var.app_name}_api@/${var.app_name}?host=/cloudsql/${var.project_id}:${var.region}:${google_sql_database_instance.postgres.name}"
      }
      env {
        name = "DATABASE_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["db_password"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "OBJECT_STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "OBJECT_STORAGE_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "JOB_EXECUTION_MODE"
        value = "cloud_tasks"
      }
      env {
        name  = "CLOUD_TASKS_QUEUE"
        value = google_cloud_tasks_queue.jobs.name
      }
      env {
        name  = "CLOUD_TASKS_LOCATION"
        value = var.region
      }
      env {
        name  = "CLOUD_TASKS_SERVICE_ACCOUNT"
        value = google_service_account.api.email
      }
      env {
        name = "INTERNAL_WORKER_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["internal_worker_token"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "AI_PROVIDER"
        value = "vertex_ai"
      }
      env {
        name  = "AI_MODEL"
        value = "gemini-2.5-flash"
      }
      env {
        name  = "MANUFACTURER_DOMAINS"
        value = var.manufacturer_domains
      }

      startup_probe {
        http_get {
          path = "/health/live"
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get {
          path = "/health/live"
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    # Cloud SQL connection
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = ["${var.project_id}:${var.region}:${google_sql_database_instance.postgres.name}"]
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}

# Allow unauthenticated requests (public API)
resource "google_cloud_run_v2_service_iam_member" "public" {
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "api_url" {
  description = "Cloud Run API service URL"
  value       = google_cloud_run_v2_service.api.uri
}

output "database_instance_name" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.postgres.name
}

output "storage_bucket" {
  description = "GCS artifact storage bucket name"
  value       = google_storage_bucket.artifacts.name
}

output "cloud_tasks_queue" {
  description = "Cloud Tasks queue name"
  value       = google_cloud_tasks_queue.jobs.name
}

output "service_account_email" {
  description = "API service account email"
  value       = google_service_account.api.email
}
