"""Deterministic, non-mutating entity resolution."""

from typing import Any

from app.schemas.kyc_entity import (
    Contradiction,
    EntityResolutionResult,
    NormalizedEntity,
    NormalizedIdentity,
)

from .config import KycEntityConfig
from .evidence import content_record_id, source_evidence
from .normalization import normalize_identity


class EntityResolutionService:
    def __init__(self, config: KycEntityConfig | None = None) -> None:
        self.config = config or KycEntityConfig()

    def normalize_identity(self, raw_identity: dict[str, Any]) -> NormalizedIdentity:
        return normalize_identity(raw_identity)

    def resolve_entity(
        self,
        input_entity: dict[str, Any],
        candidate_entities: list[dict[str, Any]],
    ) -> EntityResolutionResult:
        normalized_input = normalize_identity(input_entity)
        input_record_id = content_record_id("INPUT", input_entity)
        input_evidence = source_evidence(
            "IDENTITY", input_record_id, "IDENTITY_INPUT", "Normalized identity resolution input",
            input_entity,
            normalized_input.identity_scope,
        )
        results: list[NormalizedEntity] = []
        contradictions: list[Contradiction] = []
        evidence = [input_evidence]
        for position, candidate in enumerate(candidate_entities):
            normalized = normalize_identity(candidate)
            entity_id = str(
                candidate.get("entity_id")
                or candidate.get("customer_id")
                or candidate.get("company_id")
                or candidate.get("external_account_id")
                or f"CANDIDATE-{position}"
            )
            candidate_record_id = content_record_id(entity_id, candidate)
            candidate_evidence = source_evidence(
                "IDENTITY-CANDIDATE", candidate_record_id, "IDENTITY_CANDIDATE",
                f"Candidate identity {entity_id}", candidate,
                normalized.identity_scope,
            )
            evidence.append(candidate_evidence)
            strong_conflicts = self._strong_conflicts(normalized_input, normalized)
            if strong_conflicts:
                contradictions.append(Contradiction(
                    contradiction_id=f"CONTRA-IDENTITY-{entity_id}",
                    type="IDENTITY_CONTRADICTION",
                    field=strong_conflicts[0],
                    declared=getattr(normalized_input, strong_conflicts[0]),
                    observed=getattr(normalized, strong_conflicts[0]),
                    evidence_a=input_evidence.evidence_id,
                    evidence_b=candidate_evidence.evidence_id,
                ))
                score, decision = 0.0, "CONTRADICTION"
                matched: list[str] = []
            elif self._external_record_match(normalized_input, normalized):
                score, decision, matched = 1.0, "EXTERNAL_ACCOUNT_RECORD_MATCH", ["external_account"]
            else:
                score, matched = self._score(normalized_input, normalized)
                if matched == ["name"]:
                    score = min(score, self.config.identity_possible_threshold - 0.01)
                decision = (
                    "MATCH" if score >= self.config.identity_match_threshold
                    else "POSSIBLE_MATCH" if score >= self.config.identity_possible_threshold
                    else "NO_MATCH"
                )
            scope = normalized.identity_scope
            results.append(NormalizedEntity(
                resolution_id=f"RES-{input_record_id}-{candidate_record_id}",
                entity_id=entity_id,
                entity_type=str(candidate.get("entity_type") or candidate.get("counterparty_type") or "UNKNOWN"),
                standardized_name=normalized.standardized_name or "",
                confidence=round(score, 4),
                decision=decision,
                identity_scope=scope,
                ubo_eligible=(
                    scope == "FULL_INTERNAL"
                    and str(candidate.get("entity_type")) == "CUSTOMER"
                    and entity_id.startswith("CUST-")
                ),
                matched_fields=matched,
                conflicting_fields=strong_conflicts,
            ))
        results.sort(key=lambda item: (-item.confidence, item.entity_id or ""))
        return EntityResolutionResult(
            normalized_input=normalized_input,
            candidates=results,
            contradictions=contradictions,
            evidence=evidence,
        )

    @staticmethod
    def _strong_conflicts(left: NormalizedIdentity, right: NormalizedIdentity) -> list[str]:
        result = []
        for field in ("national_id", "passport", "registration_number"):
            a, b = getattr(left, field), getattr(right, field)
            if a and b and a != b:
                result.append(field)
        return result

    @staticmethod
    def _external_record_match(left: NormalizedIdentity, right: NormalizedIdentity) -> bool:
        if left.external_account_id and right.external_account_id:
            return left.external_account_id == right.external_account_id
        return bool(
            left.masked_account_number
            and left.bank_id
            and left.masked_account_number == right.masked_account_number
            and left.bank_id == right.bank_id
        )

    def _score(
        self, left: NormalizedIdentity, right: NormalizedIdentity
    ) -> tuple[float, list[str]]:
        weights = self.config.identity_weights
        matched: list[str] = []
        score = 0.0
        strong_match = any(
            getattr(left, field) and getattr(left, field) == getattr(right, field)
            for field in ("national_id", "passport", "registration_number")
        )
        if strong_match:
            score += weights["strong_identifier"]
            matched.append("strong_identifier")
        left_names = {value for value in [left.standardized_name, *left.aliases] if value}
        right_names = {value for value in [right.standardized_name, *right.aliases] if value}
        if left_names & right_names:
            score += weights["name"]
            matched.append("name")
        for field in ("date_of_birth", "phone", "email"):
            a, b = getattr(left, field), getattr(right, field)
            if a and a == b:
                score += weights[field]
                matched.append(field)
        if left.address_tokens and right.address_tokens and set(left.address_tokens) == set(right.address_tokens):
            score += weights["address"]
            matched.append("address")
        return min(score, 1.0), matched
