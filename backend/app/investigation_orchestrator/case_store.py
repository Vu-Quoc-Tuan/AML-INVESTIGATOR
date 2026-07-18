"""Revision-checked process-local Shared Case File store for the MVP."""

from threading import RLock
from typing import Protocol

from app.schemas.state import SharedCaseFile


class CaseRevisionConflictError(RuntimeError):
    """Raised when a case replacement observes a stale revision."""


class CaseStateStore(Protocol):
    def get(self, case_id: str) -> SharedCaseFile: ...
    def replace(
        self, case_id: str, expected_revision: int, new_state: SharedCaseFile
    ) -> None: ...


class InMemoryCaseStateStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._cases: dict[str, SharedCaseFile] = {}

    def create(self, case_id: str) -> SharedCaseFile:
        with self._lock:
            case = self._cases.setdefault(case_id, SharedCaseFile(case_id=case_id))
            return case.model_copy(deep=True)

    def get(self, case_id: str) -> SharedCaseFile:
        with self._lock:
            if case_id not in self._cases:
                return self.create(case_id)
            return self._cases[case_id].model_copy(deep=True)

    def replace(
        self, case_id: str, expected_revision: int, new_state: SharedCaseFile
    ) -> None:
        with self._lock:
            current = self._cases.get(case_id)
            current_revision = 0 if current is None else current.revision
            if current_revision != expected_revision:
                raise CaseRevisionConflictError(
                    f"stale case revision: expected {expected_revision}, found {current_revision}"
                )
            if new_state.case_id != case_id:
                raise ValueError("case ID mismatch")
            self._cases[case_id] = new_state.model_copy(deep=True)
