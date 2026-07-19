"""Operational API for deferred investigation mode, runs, and soft prompts."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.detection.config import DetectionSettings
from app.detection.contracts import RunMode, RunTrigger
from app.detection.repository import DetectionRepository
from app.investigation_control.contracts import InvestigationRun
from app.investigation_control.coordinator import InvestigationRunCoordinator
from app.investigation_control.repository import (
    ControlConflictError,
    InvestigationControlRepository,
)

router = APIRouter(prefix="/investigation-control", tags=["Investigation Control"])


class ModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: RunMode


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: RunTrigger


class ConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    soft_prompt: str | None = None

    @field_validator("soft_prompt")
    @classmethod
    def validate_soft_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > 4_000:
            raise ValueError("soft_prompt must contain at most 4000 characters")
        return normalized


class RunResponse(BaseModel):
    run_id: str
    trigger: RunTrigger
    status: str
    completed_count: int
    failed_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


def get_candidate_repository() -> DetectionRepository:
    settings = DetectionSettings.from_env()
    return DetectionRepository(
        settings.db_path,
        initial_mode=settings.initial_run_mode,
        lease_seconds=settings.claim_lease_seconds,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
    )


def get_control_repository() -> InvestigationControlRepository:
    settings = DetectionSettings.from_env()
    get_candidate_repository()
    return InvestigationControlRepository(settings.db_path)


def get_run_coordinator(
    control_repository: InvestigationControlRepository = Depends(
        get_control_repository
    ),
    candidate_repository: DetectionRepository = Depends(get_candidate_repository),
) -> InvestigationRunCoordinator:
    return InvestigationRunCoordinator(control_repository, candidate_repository)


def _run_response(run: InvestigationRun) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        trigger=run.trigger,
        status=run.status.value,
        completed_count=run.completed_count,
        failed_count=run.failed_count,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
    )


def _conflict(exc: ControlConflictError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "CONTROL_CONFLICT", "message": str(exc)},
    )


@router.get("")
async def get_summary(
    repository: InvestigationControlRepository = Depends(get_control_repository),
):
    return repository.get_summary()


@router.put("/mode")
async def update_mode(
    request: ModeRequest,
    repository: InvestigationControlRepository = Depends(get_control_repository),
) -> dict[str, RunMode]:
    try:
        mode = repository.set_mode(request.mode)
    except ControlConflictError as exc:
        raise _conflict(exc) from exc
    return {"mode": mode}


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    request: RunRequest,
    background_tasks: BackgroundTasks,
    repository: InvestigationControlRepository = Depends(get_control_repository),
    candidate_repository: DetectionRepository = Depends(get_candidate_repository),
    coordinator: InvestigationRunCoordinator = Depends(get_run_coordinator),
) -> RunResponse:
    # Mode conflicts before empty-queue so operators get a precise reason.
    current_mode = candidate_repository.get_mode()
    if request.trigger.value != current_mode.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONTROL_CONFLICT",
                "message": (
                    f"trigger {request.trigger.value} conflicts with "
                    f"persisted mode {current_mode.value}"
                ),
            },
        )

    # MANUAL batch is discouraged (operators run one PENDING ticket from History).
    # AUTO may still be invoked by cron with an empty queue (noop COMPLETED 0/0).
    claimable = candidate_repository.count_claimable()
    if request.trigger is RunTrigger.MANUAL and claimable <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMPTY_QUEUE",
                "message": (
                    "MANUAL batch refused: queue empty. Open History and run one "
                    "PENDING ticket at a time, or wait for detection to enqueue."
                ),
            },
        )
    try:
        run = repository.create_run(request.trigger)
    except ControlConflictError as exc:
        raise _conflict(exc) from exc
    try:
        background_tasks.add_task(coordinator.execute, run.run_id)
    except Exception as exc:
        repository.fail_run(run.run_id, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="background run could not be scheduled",
        ) from exc
    return _run_response(run)


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    repository: InvestigationControlRepository = Depends(get_control_repository),
) -> dict[str, list[RunResponse]]:
    return {"items": [_run_response(item) for item in repository.list_runs(limit)]}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    repository: InvestigationControlRepository = Depends(get_control_repository),
) -> RunResponse:
    run = repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="investigation run not found")
    return _run_response(run)


@router.get("/configuration")
async def get_configuration(
    repository: InvestigationControlRepository = Depends(get_control_repository),
):
    return repository.get_configuration()


@router.put("/configuration")
async def update_configuration(
    request: ConfigurationRequest,
    repository: InvestigationControlRepository = Depends(get_control_repository),
):
    return repository.set_soft_prompt(request.soft_prompt)
