"""User-uploaded ad-hoc tasks: ``task.json`` + arbitrary ``context/`` files."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from data_agent_baseline.web.api.tasks import _build_brief, _list_context_files
from data_agent_baseline.web.schemas import TaskBrief, UploadResponse
from data_agent_baseline.web.services.run_manager import make_unique_upload_id
from data_agent_baseline.web.settings import WebSettings

router = APIRouter(tags=["uploads"])

# Matches "task_<digits>" or "task_<word>" — strict so users can't smuggle
# weird characters into a directory name. We always re-prefix with "task_"
# when the user-supplied id doesn't start with it.
_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _normalise_task_id(raw: str | None) -> str:
    candidate = (raw or "").strip()
    if not candidate:
        return f"task_upload_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    if not _TASK_ID_PATTERN.fullmatch(candidate):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_payload",
                "message": "task_id must match [A-Za-z0-9_]{1,64}",
            },
        )
    if not candidate.startswith("task_"):
        candidate = f"task_{candidate}"
    return candidate


def _safe_relative_path(filename: str, settings: WebSettings) -> Path:
    """Sanitise an UploadFile.filename into a safe relative path.

    ``UploadFile.filename`` may include directory components (e.g. when the
    browser uploads a folder via ``webkitdirectory``). We:
      - strip any leading absolute/`..` segments
      - reject path components that are empty / `.` / `..`
      - enforce the extension whitelist on the final segment
    """
    if not filename:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_payload", "message": "Upload missing filename"},
        )
    raw = filename.replace("\\", "/").lstrip("/")
    parts = [segment for segment in raw.split("/") if segment]
    cleaned: list[str] = []
    for part in parts:
        if part in {".", ".."}:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_payload", "message": f"Unsafe path segment: {part}"},
            )
        cleaned.append(part)
    if not cleaned:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_payload", "message": "Empty filename"},
        )
    leaf = cleaned[-1]
    suffix = Path(leaf).suffix.lower().lstrip(".")
    if suffix and suffix not in settings.upload_extension_whitelist:
        raise HTTPException(
            status_code=415,
            detail={
                "code": "unsupported_file_type",
                "message": f"Extension '.{suffix}' is not in the whitelist",
            },
        )
    return Path(*cleaned)


@router.post("/uploads", response_model=UploadResponse, status_code=201)
async def create_upload(
    request: Request,
    question: str = Form(..., min_length=1),
    difficulty: str = Form("custom"),
    task_id: str | None = Form(None),
    files: list[UploadFile] = File(default_factory=list),
) -> UploadResponse:
    settings: WebSettings = request.app.state.settings
    if not files:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_payload", "message": "At least one context file is required"},
        )

    final_task_id = _normalise_task_id(task_id)
    upload_id = make_unique_upload_id()
    upload_root = settings.upload_root / upload_id
    task_dir = upload_root / final_task_id
    context_dir = task_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=False)

    total_bytes_written = 0
    for upload_file in files:
        relative_path = _safe_relative_path(upload_file.filename or "", settings)
        destination = context_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Stream-copy in 1 MiB chunks; enforce per-file and total caps.
        bytes_written = 0
        with destination.open("wb") as out:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > settings.max_upload_file_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "code": "file_too_large",
                            "message": (
                                f"File exceeds {settings.max_upload_file_bytes} bytes: "
                                f"{relative_path.as_posix()}"
                            ),
                        },
                    )
                total_bytes_written += len(chunk)
                if total_bytes_written > settings.max_upload_total_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "code": "file_too_large",
                            "message": (
                                f"Aggregate upload exceeds "
                                f"{settings.max_upload_total_bytes} bytes"
                            ),
                        },
                    )
                out.write(chunk)
        await upload_file.close()

    # task.json mirrors the schema validated by ``DABenchPublicDataset``:
    # exactly the keys ``task_id`` / ``difficulty`` / ``question``.
    task_json_payload = {
        "task_id": final_task_id,
        "difficulty": difficulty.strip() or "custom",
        "question": question,
    }
    (task_dir / "task.json").write_text(
        json.dumps(task_json_payload, ensure_ascii=False, indent=2) + "\n"
    )

    brief = TaskBrief(
        task_id=final_task_id,
        difficulty=task_json_payload["difficulty"],
        question=question,
        source="upload",
        context_files=_list_context_files(context_dir),
    )
    return UploadResponse(upload_id=upload_id, task=brief)


@router.get("/uploads/{upload_id}", response_model=TaskBrief)
async def get_upload(request: Request, upload_id: str) -> TaskBrief:
    settings: WebSettings = request.app.state.settings
    upload_root = settings.upload_root / upload_id
    if not upload_root.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"code": "upload_not_found", "message": f"No such upload: {upload_id}"},
        )
    # Each upload contains exactly one ``task_<id>`` subdir.
    task_dirs = [p for p in upload_root.iterdir() if p.is_dir() and p.name.startswith("task_")]
    if not task_dirs:
        raise HTTPException(
            status_code=404,
            detail={"code": "upload_not_found", "message": "Upload has no task_ subdir"},
        )
    task_dir = task_dirs[0]
    from data_agent_baseline.benchmark.dataset import DABenchPublicDataset

    dataset = DABenchPublicDataset(upload_root)
    task = dataset.get_task(task_dir.name)
    return _build_brief(task, source="upload")


@router.delete("/uploads/{upload_id}", status_code=204)
async def delete_upload(request: Request, upload_id: str) -> None:
    import shutil

    settings: WebSettings = request.app.state.settings
    upload_root = settings.upload_root / upload_id
    if not upload_root.exists():
        raise HTTPException(
            status_code=404,
            detail={"code": "upload_not_found", "message": f"No such upload: {upload_id}"},
        )
    # Defensive: ensure the resolved path is genuinely inside the upload
    # root (prevents a crafted ``upload_id`` containing ``..``).
    resolved = upload_root.resolve()
    base = settings.upload_root.resolve()
    if base not in resolved.parents:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_path", "message": "upload_id escapes upload root"},
        )
    shutil.rmtree(resolved)
