"""Built-in task catalogue + context-file preview routes.

Backed by :class:`DABenchPublicDataset` so the same task layout used by
``dabench run-task`` is exposed to the web UI without duplication.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from data_agent_baseline.benchmark.dataset import DABenchPublicDataset
from data_agent_baseline.benchmark.schema import PublicTask
from data_agent_baseline.web.schemas import ContextFile, TaskBrief
from data_agent_baseline.web.settings import WebSettings

router = APIRouter(tags=["tasks"])


def _build_brief(task: PublicTask, *, source: str = "builtin") -> TaskBrief:
    context_files = _list_context_files(task.context_dir)
    return TaskBrief(
        task_id=task.task_id,
        difficulty=task.difficulty,
        question=task.question,
        source=source,  # type: ignore[arg-type]
        context_files=context_files,
    )


def _list_context_files(context_dir: Path) -> list[ContextFile]:
    """Recursive listing of the task's context dir as a flat file list.

    We deliberately don't use ``tools.filesystem.list_context_tree`` because
    that helper is shaped for the agent's tool API (depth-limited, with
    extra metadata the UI doesn't need). A plain recursive walk is simpler
    and matches the UI's "table of files" rendering.
    """
    if not context_dir.is_dir():
        return []
    files: list[ContextFile] = []
    for path in sorted(context_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        files.append(
            ContextFile(
                path=path.relative_to(context_dir).as_posix(),
                kind=_infer_kind(path),
                size=size,
            )
        )
    return files


def _infer_kind(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "file"


def _dataset(settings: WebSettings) -> DABenchPublicDataset:
    return DABenchPublicDataset(settings.dataset_root)


@router.get("/tasks", response_model=list[TaskBrief])
async def list_tasks(
    request: Request,
    difficulty: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> list[TaskBrief]:
    settings = request.app.state.settings
    dataset = _dataset(settings)
    if not dataset.exists:
        return []
    tasks = dataset.iter_tasks(difficulty=difficulty)
    keyword_l = (keyword or "").strip().lower()
    if keyword_l:
        tasks = [t for t in tasks if keyword_l in t.question.lower() or keyword_l in t.task_id.lower()]
    return [_build_brief(task) for task in tasks]


@router.get("/tasks/{task_id}", response_model=TaskBrief)
async def get_task(request: Request, task_id: str) -> TaskBrief:
    settings = request.app.state.settings
    dataset = _dataset(settings)
    try:
        task = dataset.get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": str(exc)})
    return _build_brief(task)


@router.get("/tasks/{task_id}/context/{path:path}")
async def download_context_file(request: Request, task_id: str, path: str) -> FileResponse:
    settings = request.app.state.settings
    dataset = _dataset(settings)
    try:
        task = dataset.get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": str(exc)})

    context_root = task.context_dir.resolve()
    candidate = (context_root / path).resolve()
    # Strict path traversal guard — the resolved path must live under
    # the context root, not be the root itself, and must exist.
    if context_root not in candidate.parents:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_path", "message": "Path escapes context root"},
        )
    if not candidate.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": "file_not_found", "message": f"No such file: {path}"},
        )
    media_type, _ = mimetypes.guess_type(candidate.name)
    return FileResponse(
        candidate,
        media_type=media_type or "application/octet-stream",
        filename=candidate.name,
    )
