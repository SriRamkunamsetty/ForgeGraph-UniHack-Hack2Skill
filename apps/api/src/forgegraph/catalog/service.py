from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any
from uuid import UUID

import pandas as pd
from rapidfuzz import fuzz, process

from forgegraph.artifacts.store import ArtifactStore
from forgegraph.catalog.models import (
    CatalogJob,
    Claim,
    ClaimStatus,
    JobStatus,
    ProductRecord,
    QualitySummary,
    ValidationResult,
)
from forgegraph.catalog.normalization import canonicalize_row, first_value, normalize_key, normalize_unit, clean_text
from forgegraph.catalog.reference_pack import ReferencePack, ReferencePackLoader
from forgegraph.catalog.validation import QualityFirewall
from forgegraph.db.store import JobStore, MemoryJobStore


class CatalogService:
    """Full production ForgeGraph pipeline — all 7 stages.

    The in-memory store is deliberately isolated behind this service so it can be
    replaced by PostgreSQL and durable workflows without changing the API contract.
    Inline mode (no artifact store) is fully supported for local development and demo.
    """

    def __init__(
        self,
        store: JobStore | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self._store = store or MemoryJobStore()
        self._artifacts = artifacts
        self._pack_loader = ReferencePackLoader()
        self._pack_cache: dict[str, ReferencePack] = {}

    @staticmethod
    def sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def create_job(
        self,
        filename: str,
        content: bytes,
        reference_pack_version: str,
        tenant_id: str = "local",
    ) -> CatalogJob:
        """Create and immediately process a job (inline mode)."""
        pack = self._get_pack(reference_pack_version)
        job = CatalogJob(
            tenant_id=tenant_id,
            filename=filename,
            input_sha256=self.sha256(content),
            reference_pack_version=reference_pack_version,
            status=JobStatus.RUNNING,
        )

        # Optionally persist to object storage if available
        input_object_key: str | None = None
        if self._artifacts is not None:
            safe_name = PurePath(filename).name
            stored = self._artifacts.put(
                f"inputs/{job.id}/{safe_name}",
                content,
                "application/octet-stream",
            )
            input_object_key = stored.key
        job.input_object_key = input_object_key

        try:
            # Run inline — pass content directly (no artifact retrieval needed)
            job.products = self._process_file(filename, content, pack)
            job.quality = self._quality_summary(job.products)
            job.status = (
                JobStatus.WAITING_REVIEW if job.quality.review_rows else JobStatus.COMPLETED
            )
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"

        job.updated_at = datetime.now(UTC)
        self._store.save(job, input_object_key)
        return job

    def create_pending_job(
        self,
        filename: str,
        content: bytes,
        reference_pack_version: str,
        tenant_id: str = "local",
    ) -> CatalogJob:
        """Create a pending job and store the artifact for later worker processing (Cloud Tasks mode)."""
        self._get_pack(reference_pack_version)
        if self._artifacts is None:
            raise RuntimeError(
                "Object storage is required for Cloud Tasks execution mode. "
                "Configure OBJECT_STORAGE_BACKEND=gcs or local."
            )
        job = CatalogJob(
            tenant_id=tenant_id,
            filename=filename,
            input_sha256=self.sha256(content),
            reference_pack_version=reference_pack_version,
            status=JobStatus.CREATED,
        )
        safe_name = PurePath(filename).name
        stored = self._artifacts.put(
            f"inputs/{job.id}/{safe_name}",
            content,
            "application/octet-stream",
        )
        job.input_object_key = stored.key
        self._store.save(job, stored.key)
        return job

    def process_job(self, job_id: UUID) -> CatalogJob:
        """Process a pending job — used by Cloud Tasks worker endpoint."""
        job = self._store.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.WAITING_REVIEW}:
            return job
        if self._artifacts is None or not job.input_object_key:
            raise RuntimeError("A durable input artifact is required for worker processing.")
        job.status = JobStatus.RUNNING
        job.error = None
        self._store.save(job, job.input_object_key)
        try:
            content = self._artifacts.get(job.input_object_key)
            pack = self._get_pack(job.reference_pack_version)
            job.products = self._process_file(job.filename, content, pack)
            job.quality = self._quality_summary(job.products)
            job.status = (
                JobStatus.WAITING_REVIEW if job.quality.review_rows else JobStatus.COMPLETED
            )
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
        job.updated_at = datetime.now(UTC)
        self._store.save(job, job.input_object_key)
        return job

    def get_job(self, job_id: UUID) -> CatalogJob | None:
        return self._store.get(job_id)

    def list_jobs(self, tenant_id: str = "local") -> Iterable[CatalogJob]:
        return self._store.list(tenant_id)

    def save_job(self, job: CatalogJob) -> CatalogJob:
        job.updated_at = datetime.now(UTC)
        self._store.save(job, job.input_object_key)
        return job

    def recalculate_quality(self, job: CatalogJob) -> CatalogJob:
        job.quality = self._quality_summary(job.products)
        if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            job.status = (
                JobStatus.WAITING_REVIEW if job.quality.review_rows else JobStatus.COMPLETED
            )
        return self.save_job(job)

    def export_csv(self, job_id: UUID) -> bytes:
        frame = self._export_frame(job_id)
        stream = io.StringIO()
        frame.to_csv(stream, index=False)
        return stream.getvalue().encode("utf-8")

    def export_xlsx(self, job_id: UUID) -> bytes:
        frame = self._export_frame(job_id)
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name="products")
        return stream.getvalue()

    def _export_frame(self, job_id: UUID) -> pd.DataFrame:
        job = self._store.get(job_id)
        if job is None:
            raise KeyError(job_id)
        pack = self._get_pack(job.reference_pack_version)
        rows: list[dict[str, Any]] = []
        for product in job.products:
            if pack.expected_output_headers:
                rows.append(
                    {
                        header: self._value_for_header(product, header)
                        for header in pack.expected_output_headers
                    }
                )
            else:
                row: dict[str, Any] = {
                    "product_id": product.product_id,
                    "mpn": product.mpn,
                    "manufacturer": product.manufacturer,
                    "brand": product.brand,
                    "category": product.category,
                    "publish_status": product.publish_status,
                    "claims_count": len(product.claims),
                    "evidence_count": sum(bool(c.evidence_ids) for c in product.claims),
                    "validation_errors": sum(
                        item.status == "failed" for item in product.validations
                    ),
                }
                # Add accepted claim values as columns
                for claim in product.claims:
                    if claim.status == ClaimStatus.ACCEPTED:
                        col = f"claim_{claim.attribute}"
                        row[col] = claim.normalized_value
                rows.append(row)
        columns = pack.expected_output_headers or None
        return pd.DataFrame(rows, columns=columns)

    @staticmethod
    def _value_for_header(product: ProductRecord, header: str) -> Any:
        key = normalize_key(header)
        canonical = {
            "productid": product.product_id,
            "mpn": product.mpn,
            "manufacturer": product.manufacturer,
            "brand": product.brand,
            "category": product.category,
            "publishstatus": product.publish_status,
        }
        if key in canonical:
            return canonical[key]
        raw_values = {normalize_key(name): value for name, value in product.raw.items()}
        if key in raw_values:
            return raw_values[key]
        for claim in product.claims:
            if normalize_key(claim.attribute) == key and claim.status == ClaimStatus.ACCEPTED:
                return claim.normalized_value
        return None

    def _get_pack(self, version: str) -> ReferencePack:
        if version in self._pack_cache:
            return self._pack_cache[version]
        load_version = "v1" if version == "starter-v0" else version
        if not (self._pack_loader.root / load_version).exists():
            raise ValueError(f"Reference-pack version is not available: {version}")
        pack = self._pack_loader.load(load_version)
        self._pack_cache[version] = pack
        return pack

    def _process_file(
        self,
        filename: str,
        content: bytes,
        pack: ReferencePack,
    ) -> list[ProductRecord]:
        lower = filename.lower()
        if lower.endswith(".csv"):
            dataframe = pd.read_csv(io.BytesIO(content))
        elif lower.endswith(".xlsx"):
            dataframe = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        else:
            raise ValueError("Only .csv and .xlsx files are supported")
        dataframe = dataframe.where(pd.notna(dataframe), None)

        # Stage 1: Detect duplicates by row SHA-256
        seen_hashes: set[str] = set()
        products: list[ProductRecord] = []
        for row_number, raw_row in enumerate(dataframe.to_dict(orient="records"), start=2):
            row_hash = hashlib.sha256(str(sorted(raw_row.items())).encode()).hexdigest()
            is_duplicate = row_hash in seen_hashes
            seen_hashes.add(row_hash)
            canonical = canonicalize_row(raw_row)
            product = self._process_row(row_number, canonical, pack)
            if is_duplicate:
                product.validations.append(
                    ValidationResult(
                        rule_id="ingest.duplicate_row",
                        field=None,
                        severity="warning",
                        status="failed",
                        message="This row appears to be a duplicate of a previous row.",
                    )
                )
            products.append(product)
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
        if not candidates:
            return None, 0.0, ["empty_master_list"]
        result = process.extractOne(value, candidates, scorer=fuzz.token_set_ratio)
        if not result:
            return None, 0.0, ["no_candidate"]
        candidate, score, _ = result
        confidence = round(score / 100.0, 3)
        if confidence >= 0.90:
            return candidate, confidence, ["fuzzy_master_match"]
        return None, confidence, ["ambiguous_master_match"]

    def _classify_category(self, row: dict[str, Any], pack: ReferencePack) -> str | None:
        """Stage 3: Taxonomy classification — deterministic keyword-based classifier.
        
        Maps products to versioned taxonomy categories based on description keywords.
        Cannot emit categories outside the taxonomy registry.
        """
        if not pack.taxonomy:
            return None
        description = (
            first_value(row, ("Description", "Short Description", "Part Desc", "Product Description", "Part_Desc"))
            or ""
        ).lower()
        mpn = (first_value(row, ("MPN", "Part Number", "Part Num", "Mfg_Part_Num")) or "").lower()
        combined = f"{description} {mpn}"

        # Keyword → taxonomy id mapping (deterministic, no AI hallucination)
        keyword_map: list[tuple[str, str]] = [
            ("fitting", "fittings"), ("elbow", "fittings"), ("tee", "fittings"),
            ("coupling", "fittings"), ("union", "fittings"), ("nipple", "fittings"),
            ("reducer", "fittings"), ("bushing", "fittings"), ("cap", "fittings"),
            ("faucet", "faucets"), ("tap", "faucets"), ("spigot", "faucets"),
            ("valve", "valves"), ("ball valve", "valves"), ("gate valve", "valves"),
            ("check valve", "valves"), ("butterfly", "valves"),
            ("bolt", "fasteners"), ("screw", "fasteners"), ("nut", "fasteners"),
            ("washer", "fasteners"), ("stud", "fasteners"), ("anchor", "fasteners"),
            ("conduit", "electrical_conduit"), ("emt", "electrical_conduit"), ("rmc", "electrical_conduit"),
            ("motor", "motors"), ("horsepower", "motors"), ("rpm", "motors"),
            ("pump", "pumps"), ("submersible", "pumps"), ("centrifugal", "pumps"),
            ("bearing", "bearings"), ("ball bearing", "bearings"),
            ("wire", "wire_cable"), ("cable", "wire_cable"), ("thhn", "wire_cable"),
            ("led", "lighting"), ("lamp", "lighting"), ("lumens", "lighting"), ("light", "lighting"),
        ]

        # Build id → name lookup from taxonomy
        taxonomy_ids = {item.get("id"): item.get("name") for item in pack.taxonomy}

        for keyword, category_id in keyword_map:
            if keyword in combined and category_id in taxonomy_ids:
                return taxonomy_ids[category_id]

        return None

    def _normalize_uom_in_value(self, value: str | None, pack: ReferencePack) -> str | None:
        """Stage 2/6: Normalize unit of measure in claim values using the reference pack UOM map."""
        if not value or not pack.uoms:
            return value
        for _dimension, uom_data in pack.uoms.items():
            if isinstance(uom_data, dict):
                aliases = uom_data.get("aliases", {})
                for alias, canonical in aliases.items():
                    if value.strip().lower() == alias.lower():
                        return canonical
        return value

    def _process_row(
        self,
        row_number: int,
        row: dict[str, Any],
        pack: ReferencePack,
    ) -> ProductRecord:
        # Stage 2: Normalize and resolve core identity fields
        mpn = first_value(
            row,
            (
                "MPN", "Part Number", "Part Num", "Manufacturer Part Number", "Mfg_Part_Num",
                "PartNumber", "Part#", "ItemNumber", "Item Number", "Item_Number",
            ),
        )
        description = first_value(
            row,
            (
                "Description", "Short Description", "Part Desc", "Product Description",
                "Part_Desc", "LongDescription", "Long Description",
            ),
        )
        manufacturer_raw = first_value(
            row,
            (
                "Manufacturer", "Part Manufacturer", "Mfg", "Mfg Name", "Part_Manuf",
                "ManufacturerName", "Vendor", "Supplier", "Brand Owner",
            ),
        )
        brand_raw = first_value(
            row,
            (
                "Brand", "Brand Name", "E1_Brand", "Unilog_Brand", "DIB_Brand",
                "BrandName", "Label",
            ),
        )

        manufacturer, manufacturer_conf, manufacturer_reasons = self._resolve(
            manufacturer_raw, pack.manufacturers
        )
        brand, brand_conf, brand_reasons = self._resolve(brand_raw, pack.brands)
        product_id = mpn or f"row-{row_number}"

        # Stage 3: Classify into taxonomy
        category = self._classify_category(row, pack)

        claims: list[Claim] = []
        validations: list[ValidationResult] = []

        # Core identity claims
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

        # Category claim
        if category:
            claims.append(
                Claim(
                    product_id=product_id,
                    attribute="category",
                    raw_value=None,
                    normalized_value=category,
                    status=ClaimStatus.ACCEPTED,
                    confidence=0.9,
                    source_type="classifier",
                    reason_codes=["keyword_taxonomy_match"],
                )
            )

        # Stage 6: Attribute claims from remaining columns (with LOV + UOM normalization)
        skip_keys = {
            normalize_key(k)
            for k in (
                "MPN", "Part Number", "Mfg_Part_Num", "Description", "Part Desc",
                "Manufacturer", "Part_Manuf", "Brand", "E1_Brand", "Unilog_Brand",
            )
        }
        for col, raw_val in row.items():
            if normalize_key(col) in skip_keys or raw_val is None:
                continue
            cleaned = clean_text(raw_val)
            if not cleaned:
                continue
            normalized_val = self._normalize_uom_in_value(cleaned, pack)
            attr_key = normalize_key(col)
            allowed_values = pack.lovs.get(col) or pack.lovs.get(attr_key)
            if allowed_values:
                matched = next(
                    (v for v in allowed_values if v.casefold() == cleaned.casefold()), None
                )
                status = ClaimStatus.ACCEPTED if matched else ClaimStatus.REVIEW_REQUIRED
                confidence = 1.0 if matched else 0.5
                reason = ["lov_exact_match"] if matched else ["lov_no_match"]
            else:
                status = ClaimStatus.CANDIDATE
                confidence = 0.6
                reason = ["input_attribute"]
            claims.append(
                Claim(
                    product_id=product_id,
                    attribute=col,
                    raw_value=str(raw_val),
                    normalized_value=normalized_val,
                    status=status,
                    confidence=confidence,
                    source_type="input",
                    reason_codes=reason,
                )
            )

        # Stage 6: Validation rules
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
                        message=f"{field.title()} could not be resolved unambiguously from master data.",
                    )
                )

        has_error = any(
            item.severity == "error" and item.status == "failed" for item in validations
        )
        needs_review = any(claim.status == ClaimStatus.REVIEW_REQUIRED for claim in claims)
        product = ProductRecord(
            product_id=product_id,
            mpn=mpn,
            manufacturer=manufacturer,
            brand=brand,
            category=category,
            raw=row,
            claims=claims,
            validations=validations,
            publish_status=(
                "blocked" if has_error else "review_required" if needs_review else "ready"
            ),
        )

        # Run QualityFirewall (Stage 6 deterministic gate)
        product.validations = QualityFirewall(pack).validate_product(product)
        if any(
            item.severity == "error" and item.status == "failed" for item in product.validations
        ):
            product.publish_status = "blocked"
        return product

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
