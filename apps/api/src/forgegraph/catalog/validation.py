from __future__ import annotations

from dataclasses import dataclass

from forgegraph.catalog.models import Claim, ProductRecord, ValidationResult
from forgegraph.catalog.reference_pack import ReferencePack


@dataclass(frozen=True)
class ValidationPolicy:
    require_manufacturer_evidence_for_technical: bool = True
    min_publish_confidence: float = 0.8


class QualityFirewall:
    def __init__(self, pack: ReferencePack, policy: ValidationPolicy | None = None) -> None:
        self.pack = pack
        self.policy = policy or ValidationPolicy()

    def validate_product(self, product: ProductRecord) -> list[ValidationResult]:
        results = list(product.validations)
        if not product.mpn:
            results.append(self._failed("required.mpn", "mpn", "MPN is required."))
        if not product.manufacturer:
            results.append(
                self._failed(
                    "identity.manufacturer",
                    "manufacturer",
                    "Manufacturer could not be resolved from approved master data.",
                    severity="warning",
                )
            )
        for claim in product.claims:
            results.extend(self.validate_claim(claim))
        return self._deduplicate(results)

    def validate_claim(self, claim: Claim) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        allowed_values = self.pack.lovs.get(claim.attribute)
        if allowed_values and claim.normalized_value is not None:
            normalized_allowed = {str(value).casefold() for value in allowed_values}
            if str(claim.normalized_value).casefold() not in normalized_allowed:
                results.append(
                    self._failed(
                        "lov.membership",
                        claim.attribute,
                        "Claim value is not in the versioned allowed-value list.",
                    )
                )
        if self.policy.require_manufacturer_evidence_for_technical and self._is_technical(claim):
            if claim.status.value == "accepted" and not claim.evidence_ids:
                results.append(
                    self._failed(
                        "evidence.required",
                        claim.attribute,
                        "Technical claims require manufacturer evidence before publication.",
                    )
                )
        if (
            claim.status.value == "accepted"
            and claim.confidence < self.policy.min_publish_confidence
        ):
            results.append(
                self._failed(
                    "confidence.minimum",
                    claim.attribute,
                    "Accepted claim confidence is below the publication threshold.",
                    severity="warning",
                )
            )
        return results

    def validate_output_headers(self, headers: list[str]) -> list[ValidationResult]:
        if not self.pack.expected_output_headers:
            return []
        if headers != self.pack.expected_output_headers:
            return [
                self._failed(
                    "output.headers.exact",
                    None,
                    (
                        "Output headers must match the active reference-pack schema "
                        "exactly and in order."
                    ),
                )
            ]
        return []

    @staticmethod
    def _is_technical(claim: Claim) -> bool:
        return claim.attribute.casefold() not in {
            "description",
            "title",
            "keywords",
            "manufacturer",
            "brand",
            "mpn",
            "category",
        }

    @staticmethod
    def _failed(
        rule_id: str,
        field: str | None,
        message: str,
        severity: str = "error",
    ) -> ValidationResult:
        return ValidationResult(
            rule_id=rule_id,
            field=field,
            severity=severity,
            status="failed",
            message=message,
        )

    @staticmethod
    def _deduplicate(results: list[ValidationResult]) -> list[ValidationResult]:
        unique: dict[tuple[str, str | None], ValidationResult] = {}
        for result in results:
            unique[(result.rule_id, result.field)] = result
        return list(unique.values())
