"""Cross-source KYC contradictions and missing-evidence detection."""

import json
from datetime import date

from app.schemas.kyc_entity import Contradiction, ContradictionResult
from app.services.entity_data_service import EntityDataService

from .config import KycEntityConfig
from .document_intelligence import DocumentIntelligenceService
from .evidence import source_evidence
from .exceptions import EntityNotFoundError, EntityScopeViolationError


class ContradictionService:
    def __init__(
        self,
        entity_data: EntityDataService | None = None,
        config: KycEntityConfig | None = None,
    ) -> None:
        self.entity_data = entity_data or EntityDataService()
        self.config = config or KycEntityConfig()
        self.documents = DocumentIntelligenceService(self.entity_data, self.config)

    def detect_kyc_contradictions(
        self, entity_id: str, as_of_date: date
    ) -> ContradictionResult:
        if entity_id.startswith("EXT-"):
            raise EntityScopeViolationError("external counterparties have limited identity only")
        entity = self.entity_data.entity(entity_id)
        if entity is None:
            raise EntityNotFoundError(f"entity not found: {entity_id}")
        document_result = self.documents.compare_kyc_fields(entity_id, as_of_date)
        contradictions = list(document_result.contradictions)
        evidence = list(document_result.evidence)
        profile = self.entity_data.kyc_profile(entity_id)
        if profile:
            entity_evidence = next(
                item for item in evidence if item.evidence_id == f"EV-ENTITY-{entity_id}"
            )
            profile_id = str(profile["kyc_profile_id"])
            profile_evidence = source_evidence(
                "KYC", profile_id, "SHB_KYC_PROFILE",
                f"SHB KYC profile {profile_id}", profile,
            )
            evidence.append(profile_evidence)
            for field in ("expected_cross_border", "expected_countries"):
                left, right = entity.get(field), profile.get(field)
                if left is not None and right is not None and self._canonical(left) != self._canonical(right):
                    contradictions.append(Contradiction(
                        contradiction_id=f"CONTRA-{entity_id}-PROFILE-{field}",
                        type="DECLARATION_PROFILE_MISMATCH",
                        field=field,
                        declared=left,
                        observed=right,
                        evidence_a=entity_evidence.evidence_id,
                        evidence_b=profile_evidence.evidence_id,
                    ))
        identifier = entity.get("national_id") or entity.get("registration_number")
        if identifier:
            identifier_type = "NATIONAL_ID" if entity.get("national_id") else "REGISTRATION_NUMBER"
            matches = self.entity_data.entities_by_strong_identifier(identifier_type, str(identifier))
            for match in matches:
                other_id = str(match["entity_id"])
                if other_id == entity_id:
                    continue
                other_evidence = source_evidence(
                    "ENTITY", other_id, "SHB_ENTITY_MASTER",
                    f"SHB entity master record {other_id}", match,
                )
                evidence.append(other_evidence)
                contradictions.append(Contradiction(
                    contradiction_id=f"CONTRA-DUPLICATE-{identifier_type}-{entity_id}-{other_id}",
                    type="DUPLICATE_STRONG_IDENTIFIER",
                    field=identifier_type.lower(),
                    declared=entity_id,
                    observed=other_id,
                    evidence_a=f"EV-ENTITY-{entity_id}",
                    evidence_b=other_evidence.evidence_id,
                ))
        return ContradictionResult(
            contradictions=list({item.contradiction_id: item for item in contradictions}.values()),
            missing_documents=document_result.missing_documents,
            evidence=list({item.evidence_id: item for item in evidence}.values()),
        )

    @staticmethod
    def _canonical(value):
        if isinstance(value, str) and value.strip().startswith("["):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        if isinstance(value, list):
            return tuple(sorted(str(item).upper() for item in value))
        return str(value).strip().upper()
