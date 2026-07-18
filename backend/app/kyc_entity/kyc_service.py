"""Bounded customer/company KYC snapshot assembly."""

from datetime import date
from typing import Any

from app.schemas.kyc_entity import (
    AccountOwnerSnapshot,
    CompanyProfileSnapshot,
    CustomerKycSnapshot,
)
from app.services.entity_data_service import EntityDataService
from app.services.ownership_data_service import OwnershipDataService

from .config import KycEntityConfig
from .document_intelligence import DocumentIntelligenceService
from .evidence import source_evidence
from .exceptions import EntityNotFoundError, EntityScopeViolationError


class KycSnapshotService:
    def __init__(
        self,
        entity_data: EntityDataService | None = None,
        ownership_data: OwnershipDataService | None = None,
        config: KycEntityConfig | None = None,
    ) -> None:
        self.entity_data = entity_data or EntityDataService()
        self.ownership_data = ownership_data or OwnershipDataService()
        self.config = config or KycEntityConfig()
        self.documents = DocumentIntelligenceService(self.entity_data, self.config)

    def resolve_account_owner(
        self, account_id: str, as_of_date: date
    ) -> AccountOwnerSnapshot:
        account = self.entity_data.account(account_id)
        if account is None:
            if self.entity_data.external_account(account_id) is not None or account_id.startswith("EXT-"):
                raise EntityScopeViolationError(
                    f"{account_id} is external and has LIMITED_EXTERNAL_IDENTITY"
                )
            raise EntityNotFoundError(f"account not found: {account_id}")
        owner_id = str(account["owner_entity_id"])
        owner_type = str(account["owner_entity_type"])
        snapshot: CustomerKycSnapshot | CompanyProfileSnapshot
        if owner_type == "CUSTOMER":
            snapshot = self.get_customer_kyc_snapshot(owner_id, as_of_date)
        else:
            snapshot = self.get_company_profile(owner_id, as_of_date)
        account_evidence = source_evidence(
            "ACCOUNT", account_id, "SHB_ACCOUNT_MASTER",
            f"SHB account {account_id} is owned by {owner_id}", account,
        )
        return AccountOwnerSnapshot(
            account_id=account_id,
            owner_entity_id=owner_id,
            owner_entity_type=owner_type,
            snapshot=snapshot,
            evidence=self._unique_evidence([account_evidence, *snapshot.evidence]),
        )

    def get_customer_kyc_snapshot(
        self, customer_id: str, as_of_date: date
    ) -> CustomerKycSnapshot:
        self._require_internal(customer_id)
        entity = self.entity_data.entity(customer_id)
        if entity is None or "customer_id" not in entity:
            raise EntityNotFoundError(f"customer not found: {customer_id}")
        profile = self.entity_data.kyc_profile(customer_id)
        accounts = self.entity_data.accounts_for_entity(customer_id)
        document_analysis = self.documents.compare_kyc_fields(customer_id, as_of_date)
        evidence = [
            source_evidence(
                "ENTITY", customer_id, "SHB_CUSTOMER_MASTER",
                f"SHB customer master record {customer_id}", entity,
            ),
            *document_analysis.evidence,
        ]
        if profile:
            profile_id = str(profile["kyc_profile_id"])
            evidence.append(source_evidence(
                "KYC", profile_id, "SHB_KYC_PROFILE",
                f"SHB KYC profile {profile_id}", profile,
            ))
        evidence.extend(
            source_evidence(
                "ACCOUNT", str(account["account_id"]), "SHB_ACCOUNT_MASTER",
                f"SHB account {account['account_id']} owned by {customer_id}", account,
            )
            for account in accounts
        )
        return CustomerKycSnapshot(
            entity=entity,
            address=self.entity_data.address(str(entity["address_id"])),
            accounts=accounts,
            kyc_profile=profile,
            documents=document_analysis.documents,
            missing_documents=document_analysis.missing_documents,
            evidence=self._unique_evidence(evidence),
        )

    def get_company_profile(
        self, company_id: str, as_of_date: date
    ) -> CompanyProfileSnapshot:
        self._require_internal(company_id)
        entity = self.entity_data.entity(company_id)
        if entity is None or "company_id" not in entity:
            raise EntityNotFoundError(f"company not found: {company_id}")
        profile = self.entity_data.kyc_profile(company_id)
        accounts = self.entity_data.accounts_for_entity(company_id)
        representative_id = str(entity["representative_customer_id"])
        representative = self.entity_data.entity(representative_id)
        records = self._active_ownership_records(
            self.ownership_data.ownership_records(company_id), as_of_date
        )
        direct_owners: list[dict[str, Any]] = []
        for record in records:
            owner = self.entity_data.entity(str(record["owner_entity_id"]))
            direct_owners.append({**record, "owner": owner})
        coverage = sum(float(item["ownership_percentage"]) for item in records)
        status = "COMPLETE" if abs(coverage - 100.0) <= 0.01 else "INCOMPLETE"
        document_analysis = self.documents.compare_kyc_fields(company_id, as_of_date)
        evidence = [
            source_evidence(
                "ENTITY", company_id, "SHB_COMPANY_MASTER",
                f"SHB company master record {company_id}", entity,
            ),
            *document_analysis.evidence,
        ]
        if profile:
            profile_id = str(profile["kyc_profile_id"])
            evidence.append(source_evidence(
                "KYC", profile_id, "SHB_KYC_PROFILE",
                f"SHB KYC profile {profile_id}", profile,
            ))
        for record in records:
            ownership_id = str(record["ownership_id"])
            evidence.append(source_evidence(
                "OWN", ownership_id, "SHB_OWNERSHIP_RECORD",
                f"Ownership record {ownership_id}", record,
            ))
        evidence.extend(
            source_evidence(
                "ACCOUNT", str(account["account_id"]), "SHB_ACCOUNT_MASTER",
                f"SHB account {account['account_id']} owned by {company_id}", account,
            )
            for account in accounts
        )
        return CompanyProfileSnapshot(
            entity=entity,
            address=self.entity_data.address(str(entity["registered_address_id"])),
            accounts=accounts,
            kyc_profile=profile,
            documents=document_analysis.documents,
            missing_documents=document_analysis.missing_documents,
            evidence=self._unique_evidence(evidence),
            representative=representative,
            direct_owners=direct_owners,
            ownership_coverage_percentage=round(coverage, 4),
            ownership_status=status,
        )

    @staticmethod
    def _active_ownership_records(
        records: list[dict[str, Any]], as_of_date: date
    ) -> list[dict[str, Any]]:
        result = []
        for record in records:
            start = date.fromisoformat(str(record["effective_from"])[:10])
            end_raw = record.get("effective_to")
            end = (
                None
                if end_raw is None or str(end_raw) in {"", "NaT", "None"}
                else date.fromisoformat(str(end_raw)[:10])
            )
            if start <= as_of_date and (end is None or end >= as_of_date):
                result.append(record)
        return result

    @staticmethod
    def _unique_evidence(items):
        return list({item.evidence_id: item for item in items}.values())

    @staticmethod
    def _require_internal(entity_id: str) -> None:
        if entity_id.startswith("EXT-"):
            raise EntityScopeViolationError(
                f"{entity_id} has LIMITED_EXTERNAL_IDENTITY"
            )
