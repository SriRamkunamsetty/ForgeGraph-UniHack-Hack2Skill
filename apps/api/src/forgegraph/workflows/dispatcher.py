from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from forgegraph.core.settings import Settings


class JobDispatcher(Protocol):
    def dispatch(self, job_id: UUID, tenant_id: str) -> str | None: ...


@dataclass(frozen=True)
class InlineDispatcher:
    def dispatch(self, job_id: UUID, tenant_id: str) -> str | None:
        return None


class CloudTasksDispatcher:
    def __init__(self, settings: Settings) -> None:
        if not settings.gcp_project_id:
            raise ValueError("GCP_PROJECT_ID is required for Cloud Tasks execution.")
        if not settings.cloud_tasks_dispatch_url:
            raise ValueError("CLOUD_TASKS_DISPATCH_URL is required for Cloud Tasks execution.")
        from google.cloud import tasks_v2  # type: ignore[import-not-found]

        self.settings = settings
        self.client = tasks_v2.CloudTasksClient()
        self.tasks_v2 = tasks_v2
        self.parent = self.client.queue_path(
            settings.gcp_project_id,
            settings.cloud_tasks_location,
            settings.cloud_tasks_queue,
        )

    def dispatch(self, job_id: UUID, tenant_id: str) -> str:
        dispatch_url = self.settings.cloud_tasks_dispatch_url
        if not dispatch_url:
            raise ValueError("CLOUD_TASKS_DISPATCH_URL is required for Cloud Tasks execution.")
        payload = f'{"job_id":"{job_id}","tenant_id":"{tenant_id}"}'.encode()
        task = {
            "http_request": {
                "http_method": self.tasks_v2.HttpMethod.POST,
                "url": (f"{dispatch_url.rstrip('/')}/internal/tasks/catalog"),
                "headers": {
                    "Content-Type": "application/json",
                    "X-ForgeGraph-Worker-Token": self.settings.internal_worker_token or "",
                },
                "body": payload,
            }
        }
        if self.settings.cloud_tasks_service_account:
            task["http_request"]["oidc_token"] = {
                "service_account_email": self.settings.cloud_tasks_service_account,
                "audience": dispatch_url,
            }
        created = self.client.create_task(parent=self.parent, task=task)
        return created.name


def build_dispatcher(settings: Settings) -> JobDispatcher:
    if settings.job_execution_mode == "cloud_tasks":
        return CloudTasksDispatcher(settings)
    return InlineDispatcher()
