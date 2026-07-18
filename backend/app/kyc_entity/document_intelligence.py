"""MVP document intelligence over already-extracted JSON fields."""

from datetime import date, datetime
from typing import Any

from app.schemas.kyc_entity import (
    Contradiction,
    DocumentAnalysisResult,
    DocumentValidity,
    KycFinding,
    MissingDocument,
)
from app.services.entity_data_service import EntityDataService

from .config import KycEntityConfig
from .evidence import source_evidence
from .exceptions import EntityNotFoundError, EntityScopeViolationError
from .normalization import normalize_date, normalize_identifier, normalize_name


def _as_date(value: Any) -> date | None:
    if value is None or str(value).strip() in {"", "None", "NaT"}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class DocumentIntelligenceService:
    def __init__(
        self,
        entity_data: EntityDataService | None = None,
        config: KycEntityConfig | None = None,
    ) -> None:
        self.entity_data = entity_data or EntityDataService()
        self.config = config or KycEntityConfig()

    def get_kyc_documents(self, entity_id: str) -> DocumentAnalysisResult:
        self._require_internal(entity_id)
        if self.entity_data.entity(entity_id) is None:
            raise EntityNotFoundError(f"entity not found: {entity_id}")
        documents = self.entity_data.kyc_documents(entity_id)
        evidence = [self._document_evidence(item) for item in documents]
        return DocumentAnalysisResult(documents=documents, evidence=evidence)

    def extract_document_fields(self, document_id: str) -> DocumentAnalysisResult:
        document = self.entity_data.kyc_document(document_id)
        if document is None:
            raise EntityNotFoundError(f"document not found: {document_id}")
        self._require_internal(str(document["entity_id"]))
        extracted = {
            "document_id": document_id,
            "document_type": document.get("document_type"),
            "document_number": document.get("document_number"),
            "extracted_fields": document.get("extracted_fields") or {},
        }
        return DocumentAnalysisResult(
            documents=[extracted], evidence=[self._document_evidence(document)]
        )

    def check_document_validity(
        self, document_ids: list[str], as_of_date: date
    ) -> DocumentAnalysisResult:
        documents: list[dict[str, Any]] = []
        validity: list[DocumentValidity] = []
        findings: list[KycFinding] = []
        evidence = []
        for document_id in document_ids:
            document = self.entity_data.kyc_document(document_id)
            if document is None:
                raise EntityNotFoundError(f"document not found: {document_id}")
            self._require_internal(str(document["entity_id"]))
            item_evidence = self._document_evidence(document)
            classification = self._classify(document, as_of_date)
            documents.append(document)
            evidence.append(item_evidence)
            validity.append(DocumentValidity(
                document_id=document_id,
                classification=classification,
                as_of_date=as_of_date,
                evidence_id=item_evidence.evidence_id,
            ))
            if classification != "VALID":
                finding_type = "DOCUMENT_EXPIRED" if classification == "EXPIRED" else f"DOCUMENT_{classification}"
                findings.append(KycFinding(
                    finding_id=f"FIND-{finding_type}-{document_id}-{as_of_date.isoformat()}",
                    type=finding_type,
                    statement=f"Document {document_id} classified as {classification} on {as_of_date}",
                    evidence_ids=[item_evidence.evidence_id],
                    severity="HIGH" if classification in {"EXPIRED", "INVALID_DATES"} else "MEDIUM",
                ))
        return DocumentAnalysisResult(
            documents=documents, validity=validity, findings=findings, evidence=evidence
        )

    def compare_kyc_fields(
        self, entity_id: str, as_of_date: date
    ) -> DocumentAnalysisResult:
        self._require_internal(entity_id)
        entity = self.entity_data.entity(entity_id)
        if entity is None:
            raise EntityNotFoundError(f"entity not found: {entity_id}")
        entity_type = "CUSTOMER" if entity_id.startswith("CUST-") else "COMPANY"
        documents = self.entity_data.kyc_documents(entity_id)
        validity_result = self.check_document_validity(
            [str(item["document_id"]) for item in documents], as_of_date
        ) if documents else DocumentAnalysisResult()
        entity_evidence = source_evidence(
            "ENTITY", entity_id, "SHB_ENTITY_MASTER",
            f"SHB master record for {entity_id}", entity,
        )
        evidence = [entity_evidence, *validity_result.evidence]
        findings = list(validity_result.findings)
        contradictions: list[Contradiction] = []
        mapping = self._canonical_mapping(entity_type)
        for document in documents:
            doc_id = str(document["document_id"])
            doc_evidence_id = f"EV-DOC-{doc_id}"
            extracted = document.get("extracted_fields") or {}
            for document_field, entity_field, normalization in mapping.get(str(document["document_type"]), []):
                document_value = (
                    document.get(document_field)
                    if document_field == "document_number"
                    else extracted.get(document_field)
                )
                if document_value is None or str(document_value).strip() == "":
                    findings.append(KycFinding(
                        finding_id=f"FIND-DOCUMENT_FIELD_MISSING-{doc_id}-{document_field}",
                        type="DOCUMENT_FIELD_MISSING",
                        statement=f"{doc_id} is missing extracted field {document_field}",
                        evidence_ids=[doc_evidence_id],
                    ))
                    continue
                canonical = entity.get(entity_field)
                if canonical is not None and normalization(document_value) != normalization(canonical):
                    contradictions.append(Contradiction(
                        contradiction_id=f"CONTRA-{entity_id}-{doc_id}-{document_field}",
                        type="DOCUMENT_FIELD_MISMATCH",
                        field=document_field,
                        declared=canonical,
                        observed=document_value,
                        evidence_a=entity_evidence.evidence_id,
                        evidence_b=doc_evidence_id,
                    ))
        contradictions.extend(self._cross_document_contradictions(documents))
        missing = self.find_missing_documents(entity_id, entity_type, documents, as_of_date)
        return DocumentAnalysisResult(
            documents=documents,
            validity=validity_result.validity,
            findings=findings,
            missing_documents=missing,
            contradictions=contradictions,
            evidence=evidence,
        )

    def find_missing_documents(
        self,
        entity_id: str,
        entity_type: str,
        documents: list[dict[str, Any]],
        as_of_date: date,
    ) -> list[MissingDocument]:
        valid_types = {
            str(item["document_type"])
            for item in documents
            if self._classify(item, as_of_date) == "VALID"
        }
        missing: list[MissingDocument] = []
        for alternatives in self.config.required_documents[entity_type]:
            if not (valid_types & set(alternatives)):
                label = "_OR_".join(sorted(alternatives))
                missing.append(MissingDocument(
                    missing_document_id=f"MISSING-{entity_id}-{label}-{as_of_date.isoformat()}",
                    type=label,
                    description=f"Missing valid required document: {label}",
                ))
        return missing

    @staticmethod
    def _classify(document: dict[str, Any], as_of_date: date) -> str:
        """Classify document validity strictly against ``as_of_date``.

        Exported ``verification_status`` is a generator snapshot (often relative
        to world end). It must not force ``EXPIRED`` for historical queries when
        ``expires_at`` is still on or after ``as_of_date``.
        """
        try:
            issued = _as_date(document.get("issued_at"))
            expires = _as_date(document.get("expires_at"))
        except ValueError:
            return "INVALID_DATES"
        if issued and expires and issued > expires:
            return "INVALID_DATES"
        if issued and issued > as_of_date:
            return "NOT_YET_VALID"
        if expires and expires < as_of_date:
            return "EXPIRED"

        status = str(document.get("verification_status") or "").upper()
        if status == "VERIFIED":
            return "VALID"
        # Snapshot label EXPIRED is date-relative to export time. Once the
        # as_of date check above has passed, the document is still in force.
        if status == "EXPIRED":
            return "VALID" if expires is not None else "EXPIRED"
        return "UNVERIFIED"

    @staticmethod
    def _canonical_mapping(entity_type: str):
        if entity_type == "CUSTOMER":
            fields = [
                ("full_name", "full_name", normalize_name),
                ("date_of_birth", "date_of_birth", normalize_date),
                ("nationality", "nationality", normalize_identifier),
            ]
            return {
                "NATIONAL_ID": [*fields, ("document_number", "national_id", normalize_identifier)],
                "PASSPORT": fields,
            }
        return {
            "BUSINESS_LICENSE": [
                ("legal_name", "legal_name", normalize_name),
                ("registration_number", "registration_number", normalize_identifier),
                ("industry_code", "industry_code", normalize_identifier),
            ]
        }

    @staticmethod
    def _cross_document_contradictions(
        documents: list[dict[str, Any]],
    ) -> list[Contradiction]:
        values: dict[str, list[tuple[str, Any, Any]]] = {}
        for document in documents:
            extracted = document.get("extracted_fields") or {}
            for field in ("full_name", "date_of_birth", "national_id", "legal_name", "registration_number"):
                value = extracted.get(field)
                if value is not None:
                    normalizer = normalize_name if "name" in field else normalize_identifier
                    values.setdefault(field, []).append((str(document["document_id"]), value, normalizer(value)))
        result: list[Contradiction] = []
        for field, records in values.items():
            for left_index, left in enumerate(records):
                for right in records[left_index + 1:]:
                    if left[2] != right[2]:
                        result.append(Contradiction(
                            contradiction_id=f"CONTRA-DOCS-{left[0]}-{right[0]}-{field}",
                            type="DOCUMENT_DOCUMENT_MISMATCH",
                            field=field,
                            declared=left[1],
                            observed=right[1],
                            evidence_a=f"EV-DOC-{left[0]}",
                            evidence_b=f"EV-DOC-{right[0]}",
                        ))
        return result

    @staticmethod
    def _document_evidence(document: dict[str, Any]):
        document_id = str(document["document_id"])
        return source_evidence(
            "DOC", document_id, "SHB_KYC_DOCUMENT",
            f"KYC document {document_id}", document,
        )

    def _require_internal(self, entity_id: str) -> None:
        if entity_id.startswith("EXT-"):
            raise EntityScopeViolationError(
                f"{entity_id} has LIMITED_EXTERNAL_IDENTITY and no SHB KYC documents"
            )
