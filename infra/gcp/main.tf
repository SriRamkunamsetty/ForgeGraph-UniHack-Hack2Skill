terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  service_name = "forgegraph-api"
  labels = {
    app         = "forgegraph"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "google_project_service" "required" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudtasks.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "forgegraph"
  description   = "ForgeGraph production containers"
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.required]
}

resource "google_sql_database_instance" "postgres" {
  name                = "forgegraph-${var.environment}"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.environment == "production"

  settings {
    tier              = var.cloud_sql_tier
    availability_type = var.environment == "production" ? "REGIONAL" : "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = var.cloud_sql_disk_gb
    disk_autoresize   = true
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = var.environment == "production"
      transaction_log_retention_days = var.environment == "production" ? 7 : 1
    }
    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
      record_client_address   = false
    }
    user_labels = local.labels
  }
  depends_on = [google_project_service.required]
}

resource "google_sql_database" "forgegraph" {
  name     = "forgegraph"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "forgegraph" {
  name     = "forgegraph"
  instance = google_sql_database_instance.postgres.name
  password = var.database_password
}

resource "google_storage_bucket" "artifacts" {
  name                        = var.artifact_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.environment != "production"
  labels                      = local.labels
  versioning { enabled = true }
  lifecycle_rule {
    condition { age = var.artifact_retention_days }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "database_password" {
  secret_id = "forgegraph-database-password-${var.environment}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "database_password" {
  secret      = google_secret_manager_secret.database_password.id
  secret_data = var.database_password
}

resource "google_secret_manager_secret" "worker_token" {
  secret_id = "forgegraph-worker-token-${var.environment}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "worker_token" {
  secret      = google_secret_manager_secret.worker_token.id
  secret_data = var.worker_token
}

resource "google_cloud_tasks_queue" "catalog" {
  name     = "forgegraph-jobs"
  location = var.region
  rate_limits {
    max_concurrent_dispatches = var.max_concurrent_tasks
    max_dispatches_per_second = var.max_tasks_per_second
  }
  retry_config {
    max_attempts       = 5
    max_retry_duration = "3600s"
    max_backoff        = "300s"
    max_doublings      = 5
  }
  depends_on = [google_project_service.required]
}

resource "google_service_account" "runtime" {
  account_id   = "forgegraph-runtime-${var.environment}"
  display_name = "ForgeGraph Cloud Run runtime"
}

resource "google_service_account" "tasks" {
  account_id   = "forgegraph-tasks-${var.environment}"
  display_name = "ForgeGraph Cloud Tasks dispatcher"
}

resource "google_storage_bucket_iam_member" "runtime_artifacts" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "api" {
  name     = local.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.labels

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "900s"
    max_instance_request_concurrency = 20
    scaling {
      min_instance_count = var.environment == "production" ? 1 : 0
      max_instance_count = var.cloud_run_max_instances
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
    containers {
      image = var.api_image
      ports { container_port = 8080 }
      resources {
        limits = {
          cpu    = var.cloud_run_cpu
          memory = var.cloud_run_memory
        }
        startup_cpu_boost = true
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "STORAGE_BACKEND"
        value = "postgres"
      }
      env {
        name  = "AUTO_CREATE_SCHEMA"
        value = "false"
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
        value = var.enable_cloud_tasks ? "cloud_tasks" : "inline"
      }
      env {
        name  = "CLOUD_TASKS_QUEUE"
        value = google_cloud_tasks_queue.catalog.name
      }
      env {
        name  = "CLOUD_TASKS_LOCATION"
        value = var.region
      }
      env {
        name  = "CLOUD_TASKS_DISPATCH_URL"
        value = var.cloud_tasks_dispatch_url
      }
      env {
        name  = "CLOUD_TASKS_SERVICE_ACCOUNT"
        value = google_service_account.tasks.email
      }
      env {
        name  = "CORS_ORIGINS"
        value = var.cors_origins
      }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+psycopg://forgegraph@/forgegraph?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
      }
      env {
        name = "DATABASE_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "INTERNAL_WORKER_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.worker_token.secret_id
            version = "latest"
          }
        }
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }
  depends_on = [google_project_service.required, google_project_iam_member.runtime_cloudsql]
}

resource "google_cloud_run_v2_service_iam_member" "public_api" {
  location = google_cloud_run_v2_service.api.location
  project  = var.project_id
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_tasks_queue_iam_member" "runtime_enqueue" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_tasks_queue.catalog.name
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_service_account_iam_member" "tasks_token_creator" {
  service_account_id = google_service_account.tasks.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime.email}"
}
