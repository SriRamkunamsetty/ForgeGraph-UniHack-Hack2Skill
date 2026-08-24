from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ReferencePack:
    version: str
    manifest: dict[str, Any]
    manufacturers: list[str]
    brands: list[str]
    expected_output_headers: list[str]
    lovs: dict[str, list[str]]
    uoms: dict[str, list[str]]
    taxonomy: list[dict[str, Any]]
    content_guidelines: dict[str, Any]


class ReferencePackLoader:
    def __init__(self, root: Path | None = None) -> None:
        if root is not None:
            self.root = root
            return
        candidates = [
            Path(__file__).resolve().parents[5] / "reference-pack",
            Path(__file__).resolve().parents[3] / "reference-pack",
            Path.cwd() / "reference-pack",
        ]
        self.root = next((path for path in candidates if path.exists()), candidates[0])

    def load(self, version: str = "v1") -> ReferencePack:
        pack_dir = self.root / version
        manifest = self._read_json(pack_dir / "manifest.json")
        artifacts = manifest.get("artifacts", {})
        manufacturers = self._read_required_list(pack_dir / artifacts["manufacturer_master"])
        brands = self._read_required_list(pack_dir / artifacts["brand_master"])
        expected_output = self._read_optional(pack_dir, artifacts.get("expected_output_schema"))
        lovs = self._read_optional(pack_dir, artifacts.get("lov"))
        uoms = self._read_optional(pack_dir, artifacts.get("uom"))
        taxonomy = self._read_optional(pack_dir, artifacts.get("taxonomy"))
        guidelines = self._read_optional(pack_dir, artifacts.get("content_guidelines"))
        return ReferencePack(
            version=str(manifest.get("version", version)),
            manifest=manifest,
            manufacturers=[str(item) for item in manufacturers],
            brands=[str(item) for item in brands],
            expected_output_headers=self._headers(expected_output),
            lovs=self._mapping_of_lists(lovs),
            uoms=self._mapping_of_lists(uoms),
            taxonomy=self._mapping_of_records(taxonomy),
            content_guidelines=guidelines if isinstance(guidelines, dict) else {},
        )

    @staticmethod
    def _headers(value: Any) -> list[str]:
        if isinstance(value, list):
            if all(isinstance(item, str) for item in value):
                return [str(item) for item in value]
            if value and all(isinstance(item, dict) for item in value):
                return [str(item.get("name")) for item in value if item.get("name")]
        if isinstance(value, dict):
            headers = value.get("headers") or value.get("columns")
            if isinstance(headers, list):
                return [str(item) for item in headers]
        return []

    @staticmethod
    def _mapping_of_lists(value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[str]] = {}
        for key, values in value.items():
            if isinstance(values, list):
                result[str(key)] = [str(item) for item in values]
        return result

    @staticmethod
    def _mapping_of_records(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return [dict(item) for item in value]
        return []

    @classmethod
    def _read_required_list(cls, path: Path) -> list[Any]:
        value = cls._read_artifact(path)
        if not isinstance(value, list):
            raise ValueError(f"Reference-pack artifact must be an array: {path}")
        return value

    @classmethod
    def _read_optional(cls, pack_dir: Path, relative_path: str | None) -> Any:
        if not relative_path:
            return None
        path = pack_dir / relative_path
        if not path.exists():
            raise ValueError(f"Reference-pack artifact is missing: {path}")
        return cls._read_artifact(path)

    @staticmethod
    def _read_artifact(path: Path) -> Any:
        suffix = path.suffix.lower()
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        if suffix == ".csv":
            return pd.read_csv(path).where(pd.notna, None).to_dict(orient="records")
        if suffix in {".xlsx", ".xlsm"}:
            sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
            return {
                str(sheet): frame.where(pd.notna, None).to_dict(orient="records")
                for sheet, frame in sheets.items()
            }
        raise ValueError(f"Unsupported reference-pack artifact format: {path.suffix}")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"Reference-pack manifest must be an object: {path}")
        return value
