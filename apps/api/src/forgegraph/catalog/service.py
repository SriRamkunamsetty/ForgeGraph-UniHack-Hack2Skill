from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pandas as pd
from rapidfuzz import fuzz, process

from forgegraph.catalog.models import (
    CatalogJob,
    Claim,
    ClaimStatus,
    JobStatus,
    ProductRecord,
    QualitySummary,
    ValidationResult,
)
from forgegraph.catalog.normalization import canonicalize_row, first_value, normalize_key
from forgegraph.catalog.reference_pack import ReferencePackLoader


class CatalogService:
    """First vertical slice of ForgeGraph.

    The in-memory store is deliberately isolated behind this service so it can be
    replaced by PostgreSQL and durable workflows without changing the API contract.
    """

    def __init__(self) -> None:
        self._jobs: dict[UUID, CatalogJob] = {}
        pack = ReferencePackLoader().load("v1")
        self._manufacturers = pack.manufacturers
        self._brands = pack.brands

    @staticmethod
    def sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def create_job(self, filename: str, content: bytes, reference_pack_version: str) -> CatalogJob:
        job = CatalogJob(
            filename=filename,
            input_sha256=self.sha256(content),
            reference_pack_version=reference_pack_version,
            status=JobStatus.RUNNING,
        )
        self._jobs[job.id] = job
        try:
            job.products = self._process_file(filename, content)
            job.quality = self._quality_summary(job.products)
            job.status = (
                JobStatus.WAITING_REVIEW if job.quality.review_rows else JobStatus.COMPLETED
            )
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
        job.updated_at = datetime.now(UTC)
        self._jobs[job.id] = job
        return job

    def get_job(self, job_id: UUID) -> CatalogJob | None:
        return self._jobs.get(job_id)

    def export_csv(self, job_id: UUID) -> bytes:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        rows: list[dict[str, Any]] = []
        for product in job.products:
            rows.append(
                {
                    "product_id": product.product_id,
                    "mpn": product.mpn,
                    "manufacturer": product.manufacturer,
                    "brand": product.brand,
                    "category": product.category,
                    "publish_status": product.publish_status,
                    "claims_count": len(product.claims),
                    "validation_errors": sum(
                        item.status == "failed" for item in product.validations
                    ),
                }
            )
        frame = pd.DataFrame(rows)
        stream = io.StringIO()
        frame.to_csv(stream, index=False)
        return stream.getvalue().encode("utf-8")

    def _process_file(self, filename: str, content: bytes) -> list[ProductRecord]:
        lower = filename.lower()
        if lower.endswith(".csv"):
            dataframe = pd.read_csv(io.BytesIO(content))
        elif lower.endswith(".xlsx"):
            dataframe = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        else:
            raise ValueError("Only .csv and .xlsx files are supported")
        dataframe = dataframe.where(pd.notna(dataframe), None)
        products: list[ProductRecord] = []
        for row_number, raw_row in enumerate(dataframe.to_dict(orient="records"), start=2):
            products.append(self._process_row(row_number, canonicalize_row(raw_row)))
        return products

    def _resolve(
        self,
        value: str | None,
        candidates: list[str],
    ) -> tuple[str | None, float, list[str]]:
        if not value:
            return None, 0.0, ["missing_input"]
        normalized = normalize_key(value)
        exact = {normalize_key(candidate): candidate for candidate in candidates}
        if normalized in exact:
            return exact[normalized], 1.0, ["exact_master_match"]
        result = process.extractOne(value, candidates, scorer=fuzz.token_set_ratio)
        if not result:
            return None, 0.0, ["no_candidate"]
        candidate, score, _ = result
        confidence = round(score / 100.0, 3)
        if confidence >= 0.90:
            return candidate, confidence, ["fuzzy_master_match"]
        return None, confidence, ["ambiguous_master_match"]

    def _process_row(self, row_number: int, row: dict[str, Any]) -> ProductRecord:
        mpn = first_value(row, ("MPN", "Part Number", "Part Num", "Manufacturer Part Number"))
        description = first_value(
            row,
            ("Description", "Short Description", "Part Desc", "Product Description"),
        )
        manufacturer_raw = first_value(
            row,
            ("Manufacturer", "Part Manufacturer", "Mfg", "Mfg Name"),
        )
        brand_raw = first_value(row, ("Brand", "Brand Name"))
        manufacturer, manufacturer_conf, manufacturer_reasons = self._resolve(
            manufacturer_raw,
            self._manufacturers,
        )
        brand, brand_conf, brand_reasons = self._resolve(brand_raw, self._brands)
        product_id = mpn or f"row-{row_number}"
        claims: list[Claim] = []
        validations: list[ValidationResult] = []

        claims.append(
            Claim(
                product_id=product_id,
                attribute="manufacturer",
                raw_value=manufacturer_raw,
                normalized_value=manufacturer,
                status=ClaimStatus.ACCEPTED if manufacturer else ClaimStatus.REVIEW_REQUIRED,
                confidence=manufacturer_conf,
                source_type="master_data",
                reason_codes=manufacturer_reasons,
            )
        )
        claims.append(
            Claim(
                product_id=product_id,
                attribute="brand",
                raw_value=brand_raw,
                normalized_value=brand,
                status=ClaimStatus.ACCEPTED if brand else ClaimStatus.REVIEW_REQUIRED,
                confidence=brand_conf,
                source_type="master_data",
                reason_codes=brand_reasons,
            )
        )
        claims.append(
            Claim(
                product_id=product_id,
                attribute="description",
                raw_value=description,
                normalized_value=description,
                status=ClaimStatus.ACCEPTED if description else ClaimStatus.UNRESOLVED,
                confidence=1.0 if description else 0.0,
                source_type="input",
                reason_codes=["direct_input"] if description else ["missing_input"],
            )
        )

        if not mpn:
            validations.append(
                ValidationResult(
                    rule_id="required.mpn",
                    field="mpn",
                    severity="error",
                    status="failed",
                    message="MPN or part number is required for product identity.",
                )
            )
        if not description:
            validations.append(
                ValidationResult(
                    rule_id="required.description",
                    field="description",
                    severity="warning",
                    status="failed",
                    message="A product description is missing and requires enrichment or review.",
                )
            )
        for field, value in (("manufacturer", manufacturer), ("brand", brand)):
            if value is None:
                validations.append(
                    ValidationResult(
                        rule_id=f"master.{field}",
                        field=field,
                        severity="warning",
                        status="failed",
                        message=f"{field.title()} could not be resolved unambiguously.",
                    )
                )

        has_error = any(
            item.severity == "error" and item.status == "failed" for item in validations
        )
        needs_review = any(claim.status == ClaimStatus.REVIEW_REQUIRED for claim in claims)
        return ProductRecord(
            product_id=product_id,
            mpn=mpn,
            manufacturer=manufacturer,
            brand=brand,
            category=None,
            raw=row,
            claims=claims,
            validations=validations,
            publish_status=(
                "blocked" if has_error else "review_required" if needs_review else "ready"
            ),
        )

    @staticmethod
    def _quality_summary(products: list[ProductRecord]) -> QualitySummary:
        claims = [claim for product in products for claim in product.claims]
        validations = [validation for product in products for validation in product.validations]
        accepted = sum(product.publish_status == "ready" for product in products)
        review = sum(product.publish_status == "review_required" for product in products)
        failed = sum(product.publish_status == "blocked" for product in products)
        evidence_count = sum(bool(claim.evidence_ids) for claim in claims)
        return QualitySummary(
            total_rows=len(products),
            processed_rows=len(products),
            accepted_rows=accepted,
            review_rows=review,
            failed_rows=failed,
            claims_total=len(claims),
            claims_with_evidence=evidence_count,
            validation_errors=sum(
                item.status == "failed" and item.severity == "error" for item in validations
            ),
            evidence_coverage=round(evidence_count / len(claims), 3) if claims else 0.0,
        )
