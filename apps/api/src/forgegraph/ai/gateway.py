from __future__ import annotations

import importlib
import json
from typing import Any

import httpx
from forgegraph.core.settings import Settings


class AIError(RuntimeError):
    pass


class StructuredAIGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if self.settings.ai_provider == "disabled":
            raise AIError("AI provider is disabled; configure VERTEX_AI or OPENAI_COMPATIBLE.")
        if self.settings.ai_provider == "vertex_ai":
            return self._vertex_json(system_prompt, user_prompt, response_schema)
        return self._openai_compatible_json(system_prompt, user_prompt, response_schema)

    def _openai_compatible_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.settings.ai_base_url or not self.settings.ai_api_key:
            raise AIError(
                "AI_BASE_URL and AI_API_KEY are required for the OpenAI-compatible provider."
            )
        payload = {
            "model": self.settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "forgegraph_structured_output",
                    "strict": True,
                    "schema": response_schema,
                },
            },
        }
        with httpx.Client(timeout=self.settings.ai_timeout_seconds) as client:
            response = client.post(
                f"{self.settings.ai_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.ai_api_key}"},
                json=payload,
            )
        if response.is_error:
            raise AIError(f"Structured AI request failed with HTTP {response.status_code}.")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIError("Structured AI provider returned invalid JSON output.") from exc
        if not isinstance(result, dict):
            raise AIError("Structured AI provider returned a non-object result.")
        return result

    def _vertex_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.settings.gcp_project_id:
            raise AIError("GCP_PROJECT_ID is required for Vertex AI.")
        try:
            google_auth = importlib.import_module("google.auth")
            requests_auth = importlib.import_module("google.auth.transport.requests")
        except ImportError as exc:
            raise AIError("google-auth is required for Vertex AI.") from exc
        credentials, _ = google_auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        session = requests_auth.AuthorizedSession(credentials)
        url = (
            f"https://{self.settings.gcp_region}-aiplatform.googleapis.com/v1/"
            f"projects/{self.settings.gcp_project_id}/locations/{self.settings.gcp_region}/"
            f"publishers/google/models/{self.settings.ai_model}:generateContent"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
        }
        response = session.post(url, json=payload, timeout=self.settings.ai_timeout_seconds)
        if response.status_code >= 400:
            raise AIError(f"Vertex AI request failed with HTTP {response.status_code}.")
        try:
            content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIError("Vertex AI returned invalid structured JSON output.") from exc
        if not isinstance(result, dict):
            raise AIError("Vertex AI returned a non-object result.")
        return result
