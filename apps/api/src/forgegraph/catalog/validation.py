from __future__ import annotations

from dataclasses import dataclass, field

from forgegraph.catalog.models import Claim, ClaimStatus, ProductRecord, ValidationResult
from forgegraph.catalog.normalization import normalize_key
from forgegraph.catalog.reference_pack import ReferencePack


@dataclass(frozen=True)
class ValidationPolicy:
    """Configurable thresholds for the QualityFirewall.
    
    These should be read from the reference pack manifest in production.
    """
    require_manufacturer_evidence_for_technical: bool = True
    min_publish_confidence: float = 0.8
    # Non-critical fields do not block publication even if unresolved
    non_critical_fields: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "description", "title", "keywords", "manufacturer", "brand",
            "mpn", "category", "classifier",
        })
    )


class QualityFirewall:
    """Deterministic governance gate.

    The model proposes claims. The QualityFirewall decides what can be published.
    No AI involvement here — rules are versioned, auditable, and reproducible.
    """

    def __init__(self, pack: ReferencePack, policy: ValidationPolicy | None = None) -> None:
        self.pack = pack
        self.policy = policy or ValidationPolicy()

    def validate_product(self, product: ProductRecord) -> list[ValidationResult]:
        """Run all validation rules on a product and return the merged result list."""
        results = list(product.validations)

        # Rule: MPN required
        if not product.mpn:
            results.append(self._failed("required.mpn", "mpn", "MPN is required for product identity."))

        # Rule: Manufacturer must be resolved
        if not product.manufacturer:
            results.append(
                self._failed(
                    "identity.manufacturer",
                    "manufacturer",
                    "Manufacturer could not be resolved from the approved master data.",
                    severity="warning",
                )
            )

        # Per-claim rules
        for claim in product.claims:
            results.extend(self.validate_claim(claim))

        # Cross-claim contradiction detection (Stage 6)
        results.extend(self._detect_contradictions(product.claims))

        # Completeness check against category attributes
        if product.category and self.pack.taxonomy:
            results.extend(self._check_completeness(product))

        return self._deduplicate(results)

    def validate_claim(self, claim: Claim) -> list[ValidationResult]:
        """Per-claim validation: LOV membership, evidence policy, confidence threshold."""
        results: list[ValidationResult] = []

        # Rule: LOV membership
        allowed_values = self.pack.lovs.get(claim.attribute) or self.pack.lovs.get(
            normalize_key(claim.attribute)
        )
        if allowed_values and claim.normalized_value is not None:
            normalized_allowed = {str(value).casefold() for value in allowed_values}
            if str(claim.normalized_value).casefold() not in normalized_allowed:
                results.append(
                    self._failed(
                        "lov.membership",
                        claim.attribute,
                        f"'{claim.normalized_value}' is not in the versioned allowed-value list for '{claim.attribute}'.",
                    )
                )

        # Rule: Technical claims require evidence before auto-publication
        if (
            self.policy.require_manufacturer_evidence_for_technical
            and self._is_technical(claim)
        ):
            if claim.status == ClaimStatus.ACCEPTED and not claim.evidence_ids:
                results.append(
                    self._failed(
                        "evidence.required",
                        claim.attribute,
                        "Technical claims require manufacturer-source evidence before publication.",
                    )
                )

        # Rule: Accepted claim confidence must meet publication threshold
        if claim.status == ClaimStatus.ACCEPTED and claim.confidence < self.policy.min_publish_confidence:
            results.append(
                self._failed(
                    "confidence.minimum",
                    claim.attribute,
                    f"Accepted claim confidence {claim.confidence:.2f} is below the publication threshold of {self.policy.min_publish_confidence:.2f}.",
                    severity="warning",
                )
            )

        return results

    def validate_output_headers(self, headers: list[str]) -> list[ValidationResult]:
        """Verify that export output headers match the reference pack schema exactly."""
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

    def _detect_contradictions(self, claims: list[Claim]) -> list[ValidationResult]:
        """Stage 6: Detect contradicting claim values for the same attribute.
        
        A contradiction is when two accepted claims for the same attribute
        have different normalized values.
        """
        results: list[ValidationResult] = []
        by_attribute: dict[str, list[Claim]] = {}
        for claim in claims:
            by_attribute.setdefault(claim.attribute, []).append(claim)
        for attribute, attr_claims in by_attribute.items():
            accepted = [c for c in attr_claims if c.status == ClaimStatus.ACCEPTED]
            unique_values = {str(c.normalized_value).casefold() for c in accepted if c.normalized_value}
            if len(unique_values) > 1:
                results.append(
                    self._failed(
                        "contradiction.multi_value",
                        attribute,
                        f"Attribute '{attribute}' has {len(unique_values)} contradicting accepted values: {', '.join(sorted(unique_values))}.",
                        severity="warning",
                    )
                )
        return results

    def _check_completeness(self, product: ProductRecord) -> list[ValidationResult]:
        """Check that expected category attributes have claims.
        
        Products missing key category attributes are flagged for review.
        """
        results: list[ValidationResult] = []
        category_name_lower = (product.category or "").casefold()
        category_entry = next(
            (
                item
                for item in self.pack.taxonomy
                if str(item.get("name", "")).casefold() == category_name_lower
            ),
            None,
        )
        if not category_entry:
            return []
        expected_attributes: list[str] = category_entry.get("attributes", [])
        existing_attrs = {normalize_key(c.attribute) for c in product.claims}
        missing = [
            attr for attr in expected_attributes
            if normalize_key(attr) not in existing_attrs
        ]
        if len(missing) > 2:
            results.append(
                self._failed(
                    "completeness.category",
                    "category",
                    f"Product is missing {len(missing)} expected attributes for category '{product.category}': {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}.",
                    severity="warning",
                )
            )
        return results

    def _is_technical(self, claim: Claim) -> bool:
        return claim.attribute.casefold() not in self.policy.non_critical_fields

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
