"""Thin tool-facing facade over focused Person 3 services."""

from datetime import date
from typing import Any

from app.schemas.kyc_entity import ObservedTransactionFeatures, OwnershipGraphResult

from .contradiction_detection import ContradictionService
from .document_intelligence import DocumentIntelligenceService
from .entity_resolution import EntityResolutionService
from .kyc_service import KycSnapshotService
from .ownership_ubo import OwnershipUboService
from .profile_deviation import ProfileDeviationService


class KycEntityFacade:
    def __init__(self) -> None:
        self.snapshot_service = KycSnapshotService()
        self.document_service = DocumentIntelligenceService()
        self.resolution_service = EntityResolutionService()
        self.ownership_service = OwnershipUboService()
        self.profile_service = ProfileDeviationService(self.snapshot_service)
        self.contradiction_service = ContradictionService()

    def resolve_account_owner(self, account_id: str, as_of_date: date):
        return self.snapshot_service.resolve_account_owner(account_id, as_of_date)

    def get_customer_kyc_snapshot(self, customer_id: str, as_of_date: date):
        return self.snapshot_service.get_customer_kyc_snapshot(customer_id, as_of_date)

    def get_company_profile(self, company_id: str, as_of_date: date):
        return self.snapshot_service.get_company_profile(company_id, as_of_date)

    def get_kyc_documents(self, entity_id: str):
        return self.document_service.get_kyc_documents(entity_id)

    def extract_document_fields(self, document_id: str):
        return self.document_service.extract_document_fields(document_id)

    def check_document_validity(self, document_ids: list[str], as_of_date: date):
        return self.document_service.check_document_validity(document_ids, as_of_date)

    def compare_kyc_fields(self, entity_id: str, as_of_date: date):
        return self.document_service.compare_kyc_fields(entity_id, as_of_date)

    def compare_profile_with_observed_behavior(
        self,
        entity_id: str,
        observed: ObservedTransactionFeatures,
        as_of_date: date,
    ):
        return self.profile_service.compare_profile_with_observed_behavior(
            entity_id, observed, as_of_date
        )

    def normalize_identity(self, raw_identity: dict[str, Any]):
        return self.resolution_service.normalize_identity(raw_identity)

    def resolve_entity(
        self,
        input_entity: dict[str, Any],
        candidate_entities: list[dict[str, Any]],
    ):
        return self.resolution_service.resolve_entity(input_entity, candidate_entities)

    def build_ownership_graph(
        self, company_id: str, as_of_date: date, max_depth: int = 3
    ):
        return self.ownership_service.build_ownership_graph(
            company_id, as_of_date, max_depth
        )

    def calculate_ubo(
        self,
        ownership_graph: OwnershipGraphResult,
        ownership_threshold: float = 0.25,
    ):
        return self.ownership_service.calculate_ubo(
            ownership_graph, ownership_threshold
        )

    def find_ownership_gaps(self, ownership_graph: OwnershipGraphResult):
        return self.ownership_service.find_ownership_gaps(ownership_graph)

    def detect_kyc_contradictions(self, entity_id: str, as_of_date: date):
        return self.contradiction_service.detect_kyc_contradictions(
            entity_id, as_of_date
        )

    def flag_unverified_ubo(
        self, company_id: str, as_of_date: date, max_depth: int = 3
    ):
        return self.ownership_service.flag_unverified_ubo(
            company_id, as_of_date, max_depth
        )
