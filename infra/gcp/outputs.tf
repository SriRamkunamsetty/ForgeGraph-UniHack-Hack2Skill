output "api_service_name" {
  value       = google_cloud_run_v2_service.api.name
  description = "Cloud Run API service name."
}

output "api_url" {
  value       = google_cloud_run_v2_service.api.uri
  description = "Public Cloud Run API URL."
}

output "cloud_sql_connection_name" {
  value       = google_sql_database_instance.postgres.connection_name
  description = "Cloud SQL connection name used by Cloud Run."
}

output "artifact_bucket" {
  value       = google_storage_bucket.artifacts.name
  description = "Private GCS artifact bucket."
}

output "artifact_registry_repository" {
  value       = google_artifact_registry_repository.containers.name
  description = "Artifact Registry repository resource name."
}

output "cloud_tasks_queue" {
  value       = google_cloud_tasks_queue.catalog.name
  description = "Cloud Tasks queue used for catalog jobs."
}
