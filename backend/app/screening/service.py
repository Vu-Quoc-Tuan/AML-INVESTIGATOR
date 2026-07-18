"""Deterministic sanctions and PEP candidate evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol

from app.schemas.screening import (
    ScreeningCandidate,
    ScreeningEvidence,
    ScreeningRequest,
    ScreeningResponse,
)

from .config import ScreeningConfig
from .normalization import normalize_country, normalize_identifier, normalize_name


class CandidateProvider(Protocol):
    def candidates(
        self,
        normalized_name: str,
        entity_type: str,
        nationalities: list[str] | None = None,
        date_of_birth: date | None = None,
        list_types: list[str] | None = None,
    ) -> list[dict[str, object]]: ...


class ScreeningService:
    def __init__(
        self,
        candidate_provider: CandidateProvider,
        config: ScreeningConfig | None = None,
    ) -> None:
        self.candidate_provider = candidate_provider
        self.config = config or ScreeningConfig()

    def screen(self, request: ScreeningRequest) -> ScreeningResponse:
        raw_candidates = self._retrieve_candidates(request)
        if any(
            candidate.get("screening_dependency") == "unavailable"
            for candidate in raw_candidates
        ):
            return self._response(
                request,
                status="INCONCLUSIVE",
                conclusion="UNABLE_TO_SCREEN",
                warnings=["SCREENING_DEPENDENCY_UNAVAILABLE"],
            )
        active_candidates = [
            candidate
            for candidate in raw_candidates
            if self._active_as_of(candidate, request.as_of_date)
        ]
        if not active_candidates:
            return self._response(
                request,
                status="SUCCESS" if raw_candidates else "NO_DATA",
                conclusion="NO_MATCH" if raw_candidates else "UNABLE_TO_SCREEN",
                warnings=["NO_ACTIVE_CANDIDATES"] if raw_candidates else ["NO_CANDIDATE_DATA"],
            )

        evaluated: list[ScreeningCandidate] = []
        evidence: list[ScreeningEvidence] = []
        for candidate in active_candidates[: request.candidate_limit]:
            result, item_evidence = self._evaluate(request, candidate)
            evaluated.append(result)
            evidence.append(item_evidence)
        evaluated.sort(key=lambda item: (-item.score, item.candidate_id))

        strong = [
            candidate
            for candidate in evaluated
            if candidate.match_basis in {"IDENTIFIER", "MULTI_ATTRIBUTE"}
            and candidate.score >= self.config.confirmed_score
            and not candidate.conflicting_attributes
        ]
        potential = [
            candidate
            for candidate in evaluated
            if candidate.score >= self.config.potential_score
        ]
        if strong:
            status, conclusion = "SUCCESS", "CONFIRMED_MATCH"
        elif potential:
            status, conclusion = "INCONCLUSIVE", "POTENTIAL_MATCH"
        else:
            status, conclusion = "SUCCESS", "NO_MATCH"
        warnings = []
        if len(raw_candidates) > request.candidate_limit:
            warnings.append("CANDIDATE_LIMIT_REACHED")
        return self._response(
            request,
            status=status,
            conclusion=conclusion,
            candidates=evaluated,
            evidence=evidence,
            warnings=warnings,
        )

    def _retrieve_candidates(self, request: ScreeningRequest) -> list[dict[str, Any]]:
        subject = request.subject
        query_names = {
            normalized
            for name in (subject.name, *subject.aliases)
            if (normalized := normalize_name(name))
        }
        entity_type = "INDIVIDUAL" if subject.entity_type == "INDIVIDUAL" else "COMPANY"
        by_id: dict[str, dict[str, Any]] = {}
        for name in sorted(query_names):
            rows = self.candidate_provider.candidates(
                name,
                entity_type,
                list_types=list(request.screening_types),
            )
            for row in rows:
                record = dict(row)
                record_id = str(record.get("watchlist_id") or "")
                if not record_id:
                    raise ValueError("screening candidate requires watchlist_id")
                by_id[record_id] = record
        return [by_id[key] for key in sorted(by_id)]

    def _evaluate(
        self, request: ScreeningRequest, candidate: Mapping[str, Any]
    ) -> tuple[ScreeningCandidate, ScreeningEvidence]:
        subject = request.subject
        candidate_id = str(candidate["watchlist_id"])
        subject_names = {
            normalized
            for name in (subject.name, *subject.aliases)
            if (normalized := normalize_name(name))
        }
        candidate_aliases = candidate.get("aliases") or []
        candidate_names = {
            normalized
            for name in (candidate.get("full_name"), *candidate_aliases)
            if (normalized := normalize_name(name))
        }
        matched: list[str] = []
        conflicts: list[str] = []
        score = 0.0
        if subject_names & candidate_names:
            matched.append("name")
            score += self.config.name_weight

        subject_identifiers = self._subject_identifiers(request)
        candidate_identifiers = self._candidate_identifiers(candidate)
        identifier_match = bool(subject_identifiers & candidate_identifiers)
        if identifier_match:
            matched.append("identifier")
            score += self.config.identifier_weight
        elif subject_identifiers and candidate_identifiers:
            conflicts.append("identifier")

        candidate_dob = self._date(candidate.get("date_of_birth"))
        if subject.date_of_birth and candidate_dob:
            if subject.date_of_birth == candidate_dob:
                matched.append("date_of_birth")
                score += self.config.date_of_birth_weight
            else:
                conflicts.append("date_of_birth")

        subject_nationalities = {
            normalized
            for value in [*subject.nationalities, subject.country]
            if (normalized := normalize_country(value))
        }
        candidate_nationalities = {
            normalized
            for value in (candidate.get("nationalities") or [])
            if (normalized := normalize_country(value))
        }
        if subject_nationalities and candidate_nationalities:
            if subject_nationalities & candidate_nationalities:
                matched.append("nationality")
                score += self.config.nationality_weight
            else:
                conflicts.append("nationality")

        score = min(round(score, 4), 1.0)
        if identifier_match:
            basis = "IDENTIFIER"
        elif "name" in matched and len(matched) >= 2:
            basis = "MULTI_ATTRIBUTE"
        elif matched == ["name"] or "name" in matched:
            basis = "NAME_ONLY"
        else:
            basis = "INSUFFICIENT_DATA"

        evidence_id = f"EV-SCREENING-{candidate_id}"
        evidence = ScreeningEvidence(
            evidence_id=evidence_id,
            source_system=str(candidate.get("source_name") or "UNKNOWN_SCREENING_SOURCE"),
            source_record_id=candidate_id,
            visibility_level=subject.entity_scope,
            payload={
                "list_type": str(candidate.get("list_type") or "WATCHLIST"),
                "status": str(candidate.get("status") or "UNKNOWN"),
                "effective_from": self._json_value(candidate.get("effective_from")),
                "effective_to": self._json_value(candidate.get("effective_to")),
            },
        )
        result = ScreeningCandidate(
            candidate_id=candidate_id,
            list_type=str(candidate.get("list_type") or "WATCHLIST").upper(),
            source_name=str(candidate.get("source_name") or "UNKNOWN_SCREENING_SOURCE"),
            matched_name=str(candidate.get("full_name") or "UNKNOWN"),
            score=score,
            match_basis=basis,
            matched_attributes=matched,
            conflicting_attributes=conflicts,
            evidence_ids=[evidence_id],
        )
        return result, evidence

    @staticmethod
    def _subject_identifiers(request: ScreeningRequest) -> set[str]:
        subject = request.subject
        return {
            normalized
            for value in (
                subject.national_id,
                subject.passport_number,
                subject.registration_number,
            )
            if (normalized := normalize_identifier(value))
        }

    @staticmethod
    def _candidate_identifiers(candidate: Mapping[str, Any]) -> set[str]:
        values = list(candidate.get("document_numbers") or [])
        values.append(candidate.get("company_registration_number"))
        return {
            normalized
            for value in values
            if (normalized := normalize_identifier(value))
        }

    @staticmethod
    def _date(value: Any) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    @classmethod
    def _active_as_of(cls, candidate: Mapping[str, Any], as_of_date: date) -> bool:
        if str(candidate.get("status") or "ACTIVE").upper() != "ACTIVE":
            return False
        effective_from = cls._date(candidate.get("effective_from"))
        effective_to = cls._date(candidate.get("effective_to"))
        return (effective_from is None or effective_from <= as_of_date) and (
            effective_to is None or as_of_date <= effective_to
        )

    @staticmethod
    def _json_value(value: Any) -> str | int | float | bool | None:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _response(
        request: ScreeningRequest,
        *,
        status: str,
        conclusion: str,
        candidates: list[ScreeningCandidate] | None = None,
        evidence: list[ScreeningEvidence] | None = None,
        warnings: list[str] | None = None,
    ) -> ScreeningResponse:
        return ScreeningResponse(
            request_id=request.request_id,
            subject_id=request.subject.subject_id,
            entity_scope=request.subject.entity_scope,
            status=status,
            conclusion=conclusion,
            candidates=candidates or [],
            evidence=evidence or [],
            warnings=warnings or [],
        )
