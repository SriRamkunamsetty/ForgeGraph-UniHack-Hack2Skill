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
