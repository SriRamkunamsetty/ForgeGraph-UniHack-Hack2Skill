from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from forgegraph.catalog.reference_pack import ReferencePackLoader

ARTIFACT_FLAGS = {
    "manufacturer_master": "manufacturers",
    "brand_master": "brands",
    "expected_output_schema": "expected_output",
    "lov": "lov",
    "uom": "uom",
    "taxonomy": "taxonomy",
    "content_guidelines": "content_guidelines",
}


def import_pack(args: argparse.Namespace) -> Path:
    destination = Path(args.destination) / args.version
    destination.mkdir(parents=True, exist_ok=False)
    artifacts: dict[str, str | None] = {}
    for manifest_key, argument_name in ARTIFACT_FLAGS.items():
        source_value = getattr(args, argument_name)
        if not source_value:
            artifacts[manifest_key] = None
            continue
        source = Path(source_value)
        if not source.is_file():
            raise FileNotFoundError(source)
        target = destination / source.name
        shutil.copy2(source, target)
        artifacts[manifest_key] = target.name
    if not artifacts["manufacturer_master"] or not artifacts["brand_master"]:
        raise ValueError("Manufacturers and brands are required reference-pack artifacts.")
    manifest: dict[str, Any] = {
        "version": args.version,
        "kind": "governed",
        "status": "candidate",
        "artifacts": artifacts,
        "evidence_policy": {
            "manufacturer_domains_only": True,
            "technical_claims_require_evidence": True,
        },
        "created_by": args.created_by,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    ReferencePackLoader(Path(args.destination)).load(args.version)
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a ForgeGraph versioned reference pack.")
    parser.add_argument("--version", required=True, help="Immutable pack version, e.g. unihack-v1.")
    parser.add_argument("--destination", default="reference-pack")
    parser.add_argument("--manufacturers", required=True)
    parser.add_argument("--brands", required=True)
    parser.add_argument("--expected-output")
    parser.add_argument("--lov")
    parser.add_argument("--uom")
    parser.add_argument("--taxonomy")
    parser.add_argument("--content-guidelines")
    parser.add_argument("--created-by", default="ForgeGraph operator")
    return parser


def main() -> None:
    destination = import_pack(build_parser().parse_args())
    print(f"Imported and validated reference pack: {destination}")


if __name__ == "__main__":
    main()
