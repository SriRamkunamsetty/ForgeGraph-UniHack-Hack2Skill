import io

import pandas as pd
from fastapi.testclient import TestClient
from forgegraph.catalog.normalization import clean_text, decimal_to_fraction, normalize_unit
from forgegraph.main import app


def test_placeholder_is_converted_to_none():
    assert clean_text(" -- No Unilog Brand -- ") is None
    assert clean_text("  stainless   steel ") == "stainless steel"


def test_fraction_conversion_is_deterministic():
    assert decimal_to_fraction(0.5) == "1/2"
    assert decimal_to_fraction(1.25) == "1 1/4"
    assert decimal_to_fraction(2) == "2"


def test_unit_aliases_are_canonicalized():
    assert normalize_unit("inches") == "in"
    assert normalize_unit("volts") == "V"


def test_catalog_job_upload_returns_quality_summary():
    dataframe = pd.DataFrame(
        [
            {
                "Part Number": "FG-001",
                "Description": "Brass coupling",
                "Manufacturer": "Acme Industrial",
                "Brand": "Acme",
            },
            {
                "Part Number": "FG-002",
                "Description": "Incomplete part",
                "Manufacturer": "Unknown supplier",
                "Brand": "Unknown brand",
            },
        ]
    )
    stream = io.BytesIO()
    dataframe.to_csv(stream, index=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/catalog/jobs",
            files={"file": ("catalog.csv", stream.getvalue(), "text/csv")},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "catalog.csv"
    assert payload["quality"]["total_rows"] == 2
    assert payload["quality"]["review_rows"] == 1
    assert len(payload["input_sha256"]) == 64


def test_catalog_job_rejects_unsupported_extension():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/catalog/jobs",
            files={"file": ("catalog.exe", b"unsafe", "application/octet-stream")},
        )
    assert response.status_code == 415


def test_review_queue_and_xlsx_export_are_available():
    dataframe = pd.DataFrame(
        [
            {
                "Part Number": "FG-REVIEW-001",
                "Description": "Review candidate",
                "Manufacturer": "Unknown supplier",
                "Brand": "Unknown brand",
            }
        ]
    )
    stream = io.BytesIO()
    dataframe.to_csv(stream, index=False)
    with TestClient(app) as client:
        job_response = client.post(
            "/api/v1/catalog/jobs",
            files={"file": ("review.csv", stream.getvalue(), "text/csv")},
        )
        assert job_response.status_code == 200
        job_id = job_response.json()["id"]
        review_response = client.get("/api/v1/reviews")
        assert review_response.status_code == 200
        tasks = [task for task in review_response.json() if task["job_id"] == job_id]
        assert tasks
        decision_response = client.post(
            f"/api/v1/reviews/{tasks[0]['id']}/decision",
            json={"decision": "approved", "comment": "Verified by operator."},
        )
        assert decision_response.status_code == 200
        xlsx_response = client.get(f"/api/v1/catalog/jobs/{job_id}/export.xlsx")
        assert xlsx_response.status_code == 200
        assert xlsx_response.content[:2] == b"PK"


def test_reference_pack_importer_preserves_external_schema(tmp_path):
    import json
    from argparse import Namespace

    from forgegraph.catalog.pack_importer import import_pack
    from forgegraph.catalog.reference_pack import ReferencePackLoader

    manufacturers = tmp_path / "manufacturers.json"
    brands = tmp_path / "brands.json"
    schema = tmp_path / "expected.json"
    manufacturers.write_text(json.dumps(["Example Manufacturer"]))
    brands.write_text(json.dumps(["Example Brand"]))
    schema.write_text(json.dumps({"headers": ["Mfg_Part_Num", "Part_Desc", "Part_Manuf"]}))
    destination = tmp_path / "packs"
    import_pack(
        Namespace(
            version="official-v1",
            destination=str(destination),
            manufacturers=str(manufacturers),
            brands=str(brands),
            expected_output=str(schema),
            lov=None,
            uom=None,
            taxonomy=None,
            content_guidelines=None,
            created_by="test",
        )
    )
    pack = ReferencePackLoader(destination).load("official-v1")
    assert pack.expected_output_headers == ["Mfg_Part_Num", "Part_Desc", "Part_Manuf"]
