from __future__ import annotations

import json
from typing import Any

from forgegraph.ai.gateway import AIError, StructuredAIGateway
from forgegraph.catalog.models import Claim, ClaimStatus, EvidenceSource, ProductRecord

CLAIM_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "attribute": {"type": "string"},
                    "normalized_value": {},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "reason_codes": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "attribute",
                    "normalized_value",
                    "confidence",
                    "evidence_ids",
                    "reason_codes",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}


class ClaimExtractor:
    def __init__(self, gateway: StructuredAIGateway) -> None:
        self.gateway = gateway

    def extract(
        self,
        product: ProductRecord,
        category: str,
        allowed_attributes: list[str],
        evidence: list[EvidenceSource],
    ) -> list[Claim]:
        evidence_payload = [
            {
                "id": str(item.id),
                "url": item.url,
                "title": item.title,
                "page": item.page,
                "text": item.evidence_text,
            }
            for item in evidence
        ]
        system_prompt = (
            "You are ForgeGraph's industrial attribute extraction worker. "
            "Return only the supplied JSON schema. Use only the product row and evidence. "
            "Never infer a technical specification. Return no claim when evidence is absent."
        )
        user_prompt = json.dumps(
            {
                "category": category,
                "allowed_attributes": allowed_attributes,
                "product": product.model_dump(mode="json"),
                "evidence": evidence_payload,
            },
            ensure_ascii=False,
        )
        try:
            output = self.gateway.generate_json(system_prompt, user_prompt, CLAIM_RESPONSE_SCHEMA)
        except AIError:
            return []
        claims: list[Claim] = []
        evidence_ids = {str(item.id): item.id for item in evidence}
        allowed = {attribute.casefold() for attribute in allowed_attributes}
        for item in output.get("claims", []):
            attribute = str(item.get("attribute", "")).strip()
            if not attribute or attribute.casefold() not in allowed:
                continue
            linked_ids = [
                evidence_ids[value]
                for value in item.get("evidence_ids", [])
                if value in evidence_ids
            ]
            confidence = float(item.get("confidence", 0.0))
            status = (
                ClaimStatus.ACCEPTED
                if linked_ids and confidence >= 0.8
                else ClaimStatus.REVIEW_REQUIRED
            )
            claims.append(
                Claim(
                    product_id=product.product_id,
                    attribute=attribute,
                    normalized_value=item.get("normalized_value"),
                    status=status,
                    confidence=confidence,
                    evidence_ids=linked_ids,
                    source_type="manufacturer_evidence" if linked_ids else "ai_candidate",
                    reason_codes=[str(code) for code in item.get("reason_codes", [])],
                )
            )
        return claims
