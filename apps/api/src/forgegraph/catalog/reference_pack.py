from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReferencePack:
    version: str
    manifest: dict[str, Any]
    manufacturers: list[str]
    brands: list[str]


class ReferencePackLoader:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[5] / "reference-pack"

    def load(self, version: str = "v1") -> ReferencePack:
        pack_dir = self.root / version
        manifest = self._read_json(pack_dir / "manifest.json")
        manufacturers = self._read_json(pack_dir / manifest["artifacts"]["manufacturer_master"])
        brands = self._read_json(pack_dir / manifest["artifacts"]["brand_master"])
        if not isinstance(manufacturers, list) or not isinstance(brands, list):
            raise ValueError("Reference-pack manufacturer and brand masters must be arrays.")
        return ReferencePack(
            version=str(manifest.get("version", version)),
            manifest=manifest,
            manufacturers=[str(item) for item in manufacturers],
            brands=[str(item) for item in brands],
        )

    @staticmethod
    def _read_json(path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
