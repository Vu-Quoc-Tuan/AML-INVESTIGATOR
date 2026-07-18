"""Backend-owned Person 3 tool registry with atomic case append."""

from typing import Any

from pydantic import BaseModel, ValidationError

from app.data.exceptions import DataRepositoryError, DataRepositoryNotInitializedError
from app.kyc_entity.evidence import content_record_id, source_evidence
from app.kyc_entity.exceptions import EvidenceContractError, KycEntityError
from app.kyc_entity.facade import KycEntityFacade
from app.kyc_entity.normalization import normalize_name
from app.schemas.kyc_entity import (
    AccountOwnerSnapshot,
    CompanyProfileSnapshot,
    ContradictionResult,
    CustomerKycSnapshot,
    DocumentAnalysisResult,
    EntityResolutionResult,
    KycCaseContribution,
    NormalizedEntity,
    NormalizedIdentity,
    OwnershipGap,
    OwnershipGraphResult,
    ProfileDeviationResult,
    UboCalculationResult,
    VisibilitySummary,
)
from app.schemas.tools import (
    AccountOwnerInput,
    CalculateUboInput,
    CompanyInput,
    CustomerInput,
    DocumentInput,
    DocumentsValidityInput,
    EntityInput,
    FlagUnverifiedUboInput,
    KycToolContext,
    NormalizeIdentityInput,
    OwnershipGraphInput,
    OwnershipGraphPayloadInput,
    ProfileComparisonInput,
    ResolveEntityInput,
)

from .case_store import (
    CaseRevisionConflictError,
    CaseStateStore,
    InMemoryCaseStateStore,
)
from .state import append_kyc_contribution


class KycToolRegistry:
    def __init__(
        self,
        facade: KycEntityFacade | None = None,
        case_store: CaseStateStore | None = None,
    ) -> None:
        self.facade = facade or KycEntityFacade()
        self.case_store = case_store or InMemoryCaseStateStore()
        self._input_models: dict[str, type[BaseModel]] = {
            "resolve_account_owner": AccountOwnerInput,
            "get_customer_kyc_snapshot": CustomerInput,
            "get_company_profile": CompanyInput,
            "get_kyc_documents": EntityInput,
            "extract_document_fields": DocumentInput,
            "check_document_validity": DocumentsValidityInput,
            "compare_kyc_fields": EntityInput,
            "compare_profile_with_observed_behavior": ProfileComparisonInput,
            "normalize_identity": NormalizeIdentityInput,
            "resolve_entity": ResolveEntityInput,
            "build_ownership_graph": OwnershipGraphInput,
            "calculate_ubo": CalculateUboInput,
            "find_ownership_gaps": OwnershipGraphPayloadInput,
            "detect_kyc_contradictions": EntityInput,
            "flag_unverified_ubo": FlagUnverifiedUboInput,
        }

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(self._input_models)

    def invoke(
        self, name: str, payload: dict[str, Any], context: KycToolContext
    ) -> dict[str, Any]:
        if name not in self._input_models:
            return {"status": "error", "error": {"code": "UNKNOWN_TOOL", "message": name}}
        try:
            parsed = self._input_models[name].model_validate(payload)
            result = self._dispatch(name, parsed, context)
            contribution = self._to_contribution(name, parsed, result, context)
            current = self.case_store.get(context.case_id)
            updated = append_kyc_contribution(current, contribution)
            self.case_store.replace(context.case_id, current.revision, updated)
            return {
                "status": "ok",
                "case_id": context.case_id,
                "case_revision": updated.revision,
                "result": self._serialize(result),
            }
        except ValidationError as exc:
            return {
                "status": "error",
                "error": {"code": "INPUT_VALIDATION_ERROR", "message": str(exc)},
            }
        except KycEntityError as exc:
            return {
                "status": "error",
                "error": {"code": exc.code, "message": str(exc)},
            }
        except DataRepositoryNotInitializedError as exc:
            return {
                "status": "error",
                "error": {
                    "code": "DATA_REPOSITORY_NOT_INITIALIZED",
                    "message": str(exc),
                },
            }
        except DataRepositoryError as exc:
            return {
                "status": "error",
                "error": {"code": "DATA_REPOSITORY_ERROR", "message": str(exc)},
            }
        except CaseRevisionConflictError as exc:
            return {
                "status": "error",
                "error": {"code": "CASE_REVISION_CONFLICT", "message": str(exc)},
            }
        except RuntimeError as exc:
            return {
                "status": "error",
                "error": {"code": "INTERNAL_ERROR", "message": str(exc)},
            }

    def _dispatch(self, name: str, parsed: BaseModel, context: KycToolContext):
        data = parsed.model_dump()
        if name == "resolve_account_owner":
            return self.facade.resolve_account_owner(data["account_id"], context.as_of_date)
        if name == "get_customer_kyc_snapshot":
            return self.facade.get_customer_kyc_snapshot(data["customer_id"], context.as_of_date)
        if name == "get_company_profile":
            return self.facade.get_company_profile(data["company_id"], context.as_of_date)
        if name == "get_kyc_documents":
            return self.facade.get_kyc_documents(data["entity_id"])
        if name == "extract_document_fields":
            return self.facade.extract_document_fields(data["document_id"])
        if name == "check_document_validity":
            return self.facade.check_document_validity(data["document_ids"], data["as_of_date"])
        if name == "compare_kyc_fields":
            return self.facade.compare_kyc_fields(data["entity_id"], context.as_of_date)
        if name == "compare_profile_with_observed_behavior":
            return self.facade.compare_profile_with_observed_behavior(
                data["entity_id"], parsed.observed_transaction_features, context.as_of_date
            )
        if name == "normalize_identity":
            return self.facade.normalize_identity(data["raw_identity"])
        if name == "resolve_entity":
            return self.facade.resolve_entity(data["input_entity"], data["candidate_entities"])
        if name == "build_ownership_graph":
            return self.facade.build_ownership_graph(
                data["company_id"], context.as_of_date, data["max_depth"]
            )
        if name == "calculate_ubo":
            graph = self._stored_ownership_graph(parsed.ownership_graph, context)
            return self.facade.calculate_ubo(
                graph, data["ownership_threshold"]
            )
        if name == "find_ownership_gaps":
            graph = self._stored_ownership_graph(parsed.ownership_graph, context)
            return self.facade.find_ownership_gaps(graph)
        if name == "detect_kyc_contradictions":
            return self.facade.detect_kyc_contradictions(data["entity_id"], context.as_of_date)
        if name == "flag_unverified_ubo":
            return self.facade.flag_unverified_ubo(
                data["company_id"], context.as_of_date, data["max_depth"]
            )
        raise AssertionError(f"unhandled tool {name}")

    def _stored_ownership_graph(
        self,
        graph: OwnershipGraphResult,
        context: KycToolContext,
    ) -> OwnershipGraphResult:
        case = self.case_store.get(context.case_id)
        stored = next(
            (
                item
                for item in case.ownership_graphs
                if item.graph_id == graph.graph_id
            ),
            None,
        )
        if stored is None:
            raise EvidenceContractError(
                f"ownership graph {graph.graph_id} is not stored in case "
                f"{context.case_id}"
            )
        if stored != graph:
            raise EvidenceContractError(
                f"ownership graph {graph.graph_id} differs from the stored case graph"
            )
        return stored

    def _to_contribution(
        self,
        name: str,
        parsed: BaseModel,
        result: Any,
        context: KycToolContext,
    ) -> KycCaseContribution:
        if isinstance(result, AccountOwnerSnapshot):
            snapshot = result.snapshot
            display_name = snapshot.entity.get("full_name") or snapshot.entity.get("legal_name") or ""
            return KycCaseContribution(
                normalized_entities=[NormalizedEntity(
                    resolution_id=f"ACCOUNT-OWNER-{result.account_id}",
                    entity_id=result.owner_entity_id,
                    entity_type=result.owner_entity_type,
                    standardized_name=normalize_name(display_name) or "",
                    confidence=1.0,
                    decision="CORE_BANKING_OWNER",
                    identity_scope="FULL_INTERNAL",
                    ubo_eligible=result.owner_entity_type == "CUSTOMER",
                    matched_fields=["account_id", "owner_entity_id"],
                )],
                missing_documents=snapshot.missing_documents,
                evidence=result.evidence,
                visibility_summary=VisibilitySummary(internal_entities=[result.owner_entity_id]),
            )
        if isinstance(result, (CustomerKycSnapshot, CompanyProfileSnapshot)):
            entity_id = str(result.entity.get("customer_id") or result.entity.get("company_id"))
            return KycCaseContribution(
                missing_documents=result.missing_documents,
                evidence=result.evidence,
                visibility_summary=VisibilitySummary(internal_entities=[entity_id]),
            )
        if isinstance(result, DocumentAnalysisResult):
            internal = sorted({str(item.get("entity_id")) for item in result.documents if item.get("entity_id")})
            return KycCaseContribution(
                kyc_findings=result.findings,
                missing_documents=result.missing_documents,
                contradictions=result.contradictions,
                evidence=result.evidence,
                visibility_summary=VisibilitySummary(internal_entities=internal),
            )
        if isinstance(result, EntityResolutionResult):
            return KycCaseContribution(
                normalized_entities=result.candidates,
                contradictions=result.contradictions,
                evidence=result.evidence,
                visibility_summary=VisibilitySummary(
                    internal_entities=sorted({item.entity_id for item in result.candidates if item.entity_id and item.identity_scope == "FULL_INTERNAL"}),
                    external_entities=sorted({item.entity_id for item in result.candidates if item.entity_id and item.identity_scope == "LIMITED_EXTERNAL_IDENTITY"}),
                ),
            )
        if isinstance(result, NormalizedIdentity):
            raw = parsed.raw_identity
            record_id = content_record_id("NORMALIZED", raw)
            entity_id = str(raw.get("entity_id") or raw.get("external_account_id") or record_id)
            evidence = source_evidence(
                "IDENTITY", record_id, "IDENTITY_INPUT", "Normalized identity input",
                raw, result.identity_scope,
            )
            normalized = NormalizedEntity(
                resolution_id=record_id,
                entity_id=None if entity_id == record_id else entity_id,
                entity_type=str(raw.get("entity_type") or raw.get("counterparty_type") or "UNKNOWN"),
                standardized_name=result.standardized_name or "",
                confidence=1.0,
                decision="NORMALIZED",
                identity_scope=result.identity_scope,
                ubo_eligible=False,
            )
            return KycCaseContribution(
                normalized_entities=[normalized], evidence=[evidence]
            )
        if isinstance(result, OwnershipGraphResult):
            return KycCaseContribution(
                ownership_graphs=[result],
                evidence=result.evidence,
                visibility_summary=VisibilitySummary(internal_entities=[result.root_company_id]),
            )
        if isinstance(result, UboCalculationResult):
            return KycCaseContribution(
                kyc_findings=result.findings,
                identified_ubos=result.identified_ubos,
                ownership_gaps=result.ownership_gaps,
                evidence=result.evidence,
            )
        if isinstance(result, ProfileDeviationResult):
            return KycCaseContribution(
                profile_mismatches=result.profile_mismatches,
                evidence=result.evidence,
                visibility_summary=result.visibility_summary,
            )
        if isinstance(result, ContradictionResult):
            return KycCaseContribution(
                contradictions=result.contradictions,
                missing_documents=result.missing_documents,
                evidence=result.evidence,
            )
        if isinstance(result, list) and all(isinstance(item, OwnershipGap) for item in result):
            graph = parsed.ownership_graph
            return KycCaseContribution(
                ownership_gaps=result,
                evidence=graph.evidence,
            )
        raise RuntimeError(
            f"tool {name} returned unmapped result type "
            f"{type(result).__name__}"
        )

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in value
            ]
        return value
