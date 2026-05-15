"""Run lifecycle: create / list / get / cancel / file download."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from data_agent_baseline.benchmark.dataset import DABenchPublicDataset
from data_agent_baseline.web.api.tasks import _build_brief
from data_agent_baseline.web.schemas import (
    CreateRunRequest,
    RunStatus,
    RunSummary,
)
from data_agent_baseline.web.services.config_builder import (
    build_run_config,
    load_base_app_config,
)
from data_agent_baseline.web.services.run_manager import RunManager
from data_agent_baseline.web.settings import WebSettings

router = APIRouter(tags=["runs"])

# Plain-text MIME for log so the browser renders it inline instead of
# downloading; CSV stays application/octet-stream so the user always
# gets a file save dialog (mimetypes can pick text/csv otherwise).
_FILENAME_MIME_OVERRIDES = {
    "agent.log": "text/plain; charset=utf-8",
    "trace.json": "application/json",
    "dag.svg": "image/svg+xml",
}


def _resolve_task_brief(
    request: Request, payload: CreateRunRequest, settings: WebSettings
) -> tuple[Path, "object"]:
    """Return (dataset_root, TaskBrief) based on builtin vs upload source."""
    if payload.source == "builtin":
        dataset_root = settings.dataset_root
        dataset = DABenchPublicDataset(dataset_root)
        try:
            task = dataset.get_task(payload.task_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "task_not_found", "message": str(exc)},
            )
        return dataset_root, _build_brief(task, source="builtin")

    # upload source
    if not payload.upload_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_payload",
                "message": "upload_id is required when source=upload",
            },
        )
    upload_root = settings.upload_root / payload.upload_id
    if not upload_root.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"code": "upload_not_found", "message": f"No such upload: {payload.upload_id}"},
        )
    dataset = DABenchPublicDataset(upload_root)
    try:
        task = dataset.get_task(payload.task_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "task_not_found", "message": str(exc)},
        )
    return upload_root, _build_brief(task, source="upload")


@router.post("/runs", response_model=RunSummary, status_code=202)
async def create_run(request: Request, payload: CreateRunRequest) -> RunSummary:
    settings: WebSettings = request.app.state.settings
    manager: RunManager = request.app.state.run_manager

    dataset_root, task_brief = _resolve_task_brief(request, payload, settings)

    base = load_base_app_config(settings.base_config_path)
    config = build_run_config(
        base=base, dataset_root=dataset_root, overrides=payload.agent_overrides
    )
    # Final guard: agent.api_key must be non-empty either via overrides or
    # the base YAML (env-substituted). Surfacing this here prevents the
    # langchain client from raising a less-helpful error inside the worker.
    # NOTE: ``load_app_config`` does ``str(payload.get("api_key", default))``
    # which turns a YAML ``api_key:`` (null) into the literal string
    # ``"None"`` — hence the explicit check against the sentinel below.
    effective_api_key = (config.agent.api_key or "").strip()
    if not effective_api_key or effective_api_key.lower() == "none":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_payload",
                "message": "api_key is required (set via overrides or DABENCH base config)",
            },
        )

    record = await manager.create_and_start(
        task=task_brief, config=config, overrides=payload.agent_overrides
    )
    return record.as_summary()


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    status: RunStatus | None = Query(default=None),
) -> list[RunSummary]:
    manager: RunManager = request.app.state.run_manager
    return manager.list_runs(limit=limit, status=status)


@router.get("/runs/{run_id}", response_model=RunSummary)
async def get_run(request: Request, run_id: str) -> RunSummary:
    manager: RunManager = request.app.state.run_manager
    record = manager.get(run_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "run_not_found", "message": f"No such run: {run_id}"},
        )
    return record.as_summary()


@router.post("/runs/{run_id}/cancel", response_model=RunSummary)
async def cancel_run(request: Request, run_id: str) -> RunSummary:
    manager: RunManager = request.app.state.run_manager
    record = manager.get(run_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "run_not_found", "message": f"No such run: {run_id}"},
        )
    await manager.cancel(run_id)
    return record.as_summary()


@router.get("/runs/{run_id}/files/{name}")
async def download_run_file(request: Request, run_id: str, name: str) -> FileResponse:
    manager: RunManager = request.app.state.run_manager
    file_path = manager.file_path(run_id, name)
    if file_path is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "run_not_found", "message": f"No such run or file: {run_id}/{name}"},
        )
    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": "file_not_found", "message": f"File not yet produced: {name}"},
        )
    media_type = _FILENAME_MIME_OVERRIDES.get(name)
    if media_type is None:
        guessed, _ = mimetypes.guess_type(name)
        media_type = guessed or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type, filename=name)
