"""Idempotent evidence-ledger operations."""

from app.kyc_entity.exceptions import EvidenceConflictError
from app.schemas.evidence import KycEvidence


class EvidenceLedger:
    @staticmethod
    def append_many(
        existing: list[KycEvidence], incoming: list[KycEvidence]
    ) -> list[KycEvidence]:
        by_id = {item.evidence_id: item for item in existing}
        for item in incoming:
            current = by_id.get(item.evidence_id)
            if current is not None and current != item:
                raise EvidenceConflictError(
                    f"evidence ID {item.evidence_id} has conflicting content"
                )
            by_id[item.evidence_id] = item
        return list(by_id.values())
