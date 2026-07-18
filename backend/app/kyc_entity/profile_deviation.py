"""Declared KYC profile versus evidence-backed Person 2 observations."""

from datetime import date
from typing import Any

from app.schemas.kyc_entity import (
    ObservedTransactionFeatures,
    ProfileDeviationResult,
    ProfileMismatch,
    VisibilitySummary,
)
from app.services.entity_data_service import EntityDataService

from .config import KycEntityConfig
from .exceptions import EntityNotFoundError, EvidenceContractError
from .kyc_service import KycSnapshotService


class ProfileDeviationService:
    def __init__(
        self,
        snapshots: KycSnapshotService | None = None,
        entity_data: EntityDataService | None = None,
        config: KycEntityConfig | None = None,
    ) -> None:
        self.snapshots = snapshots or KycSnapshotService()
        self.entity_data = entity_data or EntityDataService()
        self.config = config or KycEntityConfig()

    def compare_profile_with_observed_behavior(
        self,
        entity_id: str,
        observed: ObservedTransactionFeatures,
        as_of_date: date,
    ) -> ProfileDeviationResult:
        if observed.entity_id != entity_id:
            raise EvidenceContractError(
                f"observed entity {observed.entity_id} does not match {entity_id}"
            )
        entity = self.entity_data.entity(entity_id)
        if entity is None:
            raise EntityNotFoundError(f"entity not found: {entity_id}")
        for account_id in observed.account_ids:
            account = self.entity_data.account(account_id)
            if account is None or str(account.get("owner_entity_id")) != entity_id:
                raise EvidenceContractError(
                    f"observed account {account_id} is not owned by {entity_id}"
                )
        for external_id in observed.external_counterparty_ids:
            if self.entity_data.external_account(external_id) is None:
                raise EvidenceContractError(f"unknown external counterparty {external_id}")
        snapshot = (
            self.snapshots.get_customer_kyc_snapshot(entity_id, as_of_date)
            if entity_id.startswith("CUST-")
            else self.snapshots.get_company_profile(entity_id, as_of_date)
        )
        profile = snapshot.kyc_profile
        if profile is None:
            raise EvidenceContractError(f"entity {entity_id} has no declared KYC profile")
        kyc_evidence = next(
            item for item in snapshot.evidence if item.source_type == "SHB_KYC_PROFILE"
        )
        mismatches: list[ProfileMismatch] = []
        days = max(
            (observed.window_end - observed.window_start).total_seconds() / 86400.0,
            1 / 86400.0,
        )
        metrics = observed.metrics
        numeric_rules = [
            ("total_inflow", "expected_monthly_inflow", "INFLOW_DEVIATION"),
            ("total_outflow", "expected_monthly_outflow", "OUTFLOW_DEVIATION"),
            ("transaction_count", "expected_transaction_count", "TRANSACTION_COUNT_DEVIATION"),
        ]
        if "company_id" in entity:
            numeric_rules.append(("total_inflow", "expected_monthly_turnover", "TURNOVER_DEVIATION"))
        for metric_name, declared_field, finding_type in numeric_rules:
            if metric_name not in metrics:
                continue
            declared = entity.get(declared_field) if declared_field == "expected_monthly_turnover" else profile.get(declared_field)
            if declared is None or float(declared) <= 0:
                continue
            observed_value = float(metrics[metric_name])
            normalized_observed = observed_value if days <= 31 else observed_value * 30.0 / days
            ratio = normalized_observed / float(declared)
            if ratio >= self.config.deviation_medium_ratio:
                mismatches.append(self._mismatch(
                    entity_id, finding_type, declared, observed_value,
                    [kyc_evidence.evidence_id, *observed.metric_evidence_ids[metric_name]],
                    self._severity(ratio), observed,
                ))
        if metrics.get("cross_border_observed") is True and profile.get("expected_cross_border") is False:
            metric = "cross_border_observed"
            mismatches.append(self._mismatch(
                entity_id, "CROSS_BORDER_EXPECTATION_MISMATCH", False, True,
                [kyc_evidence.evidence_id, *observed.metric_evidence_ids[metric]],
                "HIGH", observed,
            ))
        if "observed_countries" in metrics:
            expected = {str(item).upper() for item in profile.get("expected_countries") or []}
            actual = {str(item).upper() for item in metrics["observed_countries"]}
            unexpected = sorted(actual - expected)
            if unexpected:
                mismatches.append(self._mismatch(
                    entity_id, "UNEXPECTED_COUNTRY", sorted(expected), unexpected,
                    [kyc_evidence.evidence_id, *observed.metric_evidence_ids["observed_countries"]],
                    "HIGH" if any(country != "VN" for country in unexpected) else "MEDIUM",
                    observed,
                ))
        return ProfileDeviationResult(
            profile_mismatches=mismatches,
            evidence=snapshot.evidence,
            visibility_summary=VisibilitySummary(
                internal_entities=[entity_id],
                external_entities=sorted(set(observed.external_counterparty_ids)),
            ),
        )

    def _severity(self, ratio: float) -> str:
        if ratio >= self.config.deviation_critical_ratio:
            return "CRITICAL"
        if ratio >= self.config.deviation_high_ratio:
            return "HIGH"
        return "MEDIUM"

    @staticmethod
    def _mismatch(
        entity_id: str,
        mismatch_type: str,
        declared: Any,
        observed_value: Any,
        evidence_ids: list[str],
        severity: str,
        observed: ObservedTransactionFeatures,
    ) -> ProfileMismatch:
        return ProfileMismatch(
            mismatch_id=(
                f"MISMATCH-{entity_id}-{mismatch_type}-"
                f"{observed.window_start.isoformat()}-{observed.window_end.isoformat()}"
            ),
            type=mismatch_type,
            declared_value=declared,
            observed_value=observed_value,
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            severity=severity,
        )
