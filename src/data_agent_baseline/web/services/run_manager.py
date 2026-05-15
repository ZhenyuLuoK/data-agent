"""In-memory run registry + orchestrator.

Responsibilities:
* hold the active/recent runs (id → :class:`RunRecord`)
* spawn a worker thread that calls ``runner.run_single_task``
* expose the per-run :class:`RunEventBus` to the WS layer
* persist ``run_meta.json`` so a restarted server can list past runs
* enforce a hard concurrency cap (``max_concurrent_runs`` semaphore)
* attach a per-run :class:`LogTailer` + :class:`TraceWatcher` so events
  flow into the bus from the moment the run starts
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_agent_baseline.config import AppConfig
from data_agent_baseline.run.runner import (
    TaskRunArtifacts,
    create_run_id,
    run_single_task,
)
from data_agent_baseline.web.schemas import (
    AgentOverrides,
    RunStatus,
    RunSummary,
    TaskBrief,
)
from data_agent_baseline.web.security import fingerprint_api_key
from data_agent_baseline.web.services.event_bus import RunEventBus
from data_agent_baseline.web.services.log_tailer import LogTailer
from data_agent_baseline.web.services.trace_watcher import TraceWatcher
from data_agent_baseline.web.settings import WebSettings

logger = logging.getLogger("data_agent_baseline.web.run_manager")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class RunRecord:
    run_id: str
    task: TaskBrief
    status: RunStatus
    run_output_dir: Path
    bus: RunEventBus
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    failure_reason: str | None = None
    api_key_fingerprint: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    log_tailer: LogTailer | None = None
    trace_watcher: TraceWatcher | None = None
    worker_future: Any = None  # concurrent.futures.Future, kept loose to avoid import cycle

    def as_summary(self) -> RunSummary:
        prefix = f"/api/runs/{self.run_id}/files"
        # Files only exist once the agent emits them; surface URLs only
        # when the corresponding file is on disk so the UI can grey out
        # download buttons for unfinished runs.
        prediction_path = self.run_output_dir / self.task.task_id / "prediction.csv"
        trace_path = self.run_output_dir / self.task.task_id / "trace.json"
        dag_path = self.run_output_dir / self.task.task_id / "dag.svg"
        log_path = self.run_output_dir / self.task.task_id / "agent.log"
        return RunSummary(
            run_id=self.run_id,
            task_id=self.task.task_id,
            source=self.task.source,
            status=self.status,
            started_at=self.started_at,
            finished_at=self.finished_at,
            duration_ms=self.duration_ms,
            prediction_csv_url=f"{prefix}/prediction.csv" if prediction_path.exists() else None,
            trace_url=f"{prefix}/trace.json" if trace_path.exists() else None,
            dag_svg_url=f"{prefix}/dag.svg" if dag_path.exists() else None,
            log_url=f"{prefix}/agent.log" if log_path.exists() else None,
            failure_reason=self.failure_reason,
        )


class RunManager:
    """Tracks runs in memory, drives workers, fans out events."""

    def __init__(self, *, settings: WebSettings) -> None:
        self._settings = settings
        # Thread-pool size mirrors the concurrency cap. The actual ``run`` is
        # CPU-light (LLM is remote) so threads are fine; we keep workers=1
        # at the uvicorn layer specifically so this registry is a single
        # source of truth.
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, settings.max_concurrent_runs),
            thread_name_prefix="dabench-run",
        )
        self._records: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        # Capture the loop the manager was constructed on so worker
        # threads can schedule async callbacks back into it.
        self._loop: asyncio.AbstractEventLoop | None = None

    # -------- lifecycle -----------------------------------------------------

    @property
    def settings(self) -> WebSettings:
        return self._settings

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        return self._loop

    async def shutdown(self) -> None:
        """Best-effort cancel all in-flight runs and shut the executor.

        Worker threads can't be force-killed in Python; we set the cancel
        flag and rely on the runner's own timeout to bound shutdown time.
        """
        async with self._lock:
            for record in self._records.values():
                if record.status in {"queued", "running"}:
                    record.cancel_event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -------- create / lookup ----------------------------------------------

    def list_runs(self, *, limit: int = 50, status: RunStatus | None = None) -> list[RunSummary]:
        records = list(self._records.values())
        # Sort newest first; ``started_at`` may be None for queued runs
        # so fall back to run_id which is a UTC timestamp.
        records.sort(key=lambda r: (r.started_at or "", r.run_id), reverse=True)
        if status is not None:
            records = [r for r in records if r.status == status]
        return [record.as_summary() for record in records[:limit]]

    def get(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)

    def file_path(self, run_id: str, name: str) -> Path | None:
        record = self.get(run_id)
        if record is None:
            return None
        # Only allow whitelisted product files — never serve arbitrary
        # paths under run_output_dir.
        if name not in {"prediction.csv", "trace.json", "dag.svg", "agent.log"}:
            return None
        return record.run_output_dir / record.task.task_id / name

    async def create_and_start(
        self,
        *,
        task: TaskBrief,
        config: AppConfig,
        overrides: AgentOverrides,
    ) -> RunRecord:
        """Allocate a run_id + output dir, register, spawn worker, return."""
        loop = self._ensure_loop()
        run_id, run_output_dir = await asyncio.to_thread(
            self._allocate_run_dir, self._settings.run_root
        )
        bus = RunEventBus()
        record = RunRecord(
            run_id=run_id,
            task=task,
            status="queued",
            run_output_dir=run_output_dir,
            bus=bus,
            api_key_fingerprint=fingerprint_api_key(overrides.api_key or config.agent.api_key),
        )
        async with self._lock:
            self._records[run_id] = record

        await asyncio.to_thread(_write_run_meta, record, config, overrides)

        # Pre-create the per-task output directory so log_tailer /
        # trace_watcher have a stable base path before the runner
        # touches the filesystem.
        task_output_dir = run_output_dir / task.task_id
        task_output_dir.mkdir(parents=True, exist_ok=True)
        record.log_tailer = LogTailer(
            log_path=task_output_dir / "agent.log",
            bus=bus,
        )
        record.trace_watcher = TraceWatcher(
            trace_path=task_output_dir / "trace.json",
            bus=bus,
        )
        await record.log_tailer.start()
        await record.trace_watcher.start()

        # Hand off to a worker thread. The worker calls back into the
        # event loop via ``call_soon_threadsafe`` to flip statuses and
        # publish the final ``final`` event.
        future = self._executor.submit(
            self._worker, record, config, task.task_id, loop
        )
        record.worker_future = future
        return record

    @staticmethod
    def _allocate_run_dir(run_root: Path) -> tuple[str, Path]:
        """Pick a run_id; on collision append a 4-char suffix and retry."""
        run_root.mkdir(parents=True, exist_ok=True)
        for attempt in range(8):
            base_id = create_run_id()
            run_id = base_id if attempt == 0 else f"{base_id}-{secrets.token_hex(2)}"
            candidate = run_root / run_id
            try:
                candidate.mkdir(parents=True, exist_ok=False)
                return run_id, candidate
            except FileExistsError:
                continue
        raise RuntimeError(
            f"Unable to allocate a unique run_id under {run_root} after 8 attempts"
        )

    # -------- cancel --------------------------------------------------------

    async def cancel(self, run_id: str) -> bool:
        record = self.get(run_id)
        if record is None or record.status not in {"queued", "running"}:
            return False
        record.cancel_event.set()
        # Mark cancelled optimistically; the worker will overwrite to
        # ``failed`` only if the cancel signal arrived after completion.
        record.status = "cancelled"
        record.failure_reason = record.failure_reason or "cancelled by user"
        await record.bus.publish(
            {"type": "final", "run": record.as_summary().model_dump(mode="json")}
        )
        await self._teardown_watchers(record)
        return True

    # -------- worker --------------------------------------------------------

    def _worker(
        self,
        record: RunRecord,
        config: AppConfig,
        task_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Runs in a thread. Bridges sync runner → async event bus."""
        record.status = "running"
        record.started_at = _utc_iso()
        start_perf = datetime.now(timezone.utc)

        if record.cancel_event.is_set():
            self._finalise(record, loop, "cancelled", "cancelled before start")
            return

        try:
            artifacts: TaskRunArtifacts = run_single_task(
                task_id=task_id,
                config=config,
                run_output_dir=record.run_output_dir,
            )
        except Exception as exc:  # noqa: BLE001 — surface every failure to the user
            logger.exception("run_single_task crashed: run_id=%s", record.run_id)
            duration_ms = int((datetime.now(timezone.utc) - start_perf).total_seconds() * 1000)
            record.duration_ms = duration_ms
            self._finalise(record, loop, "failed", f"runner crashed: {exc}")
            return

        duration_ms = int((datetime.now(timezone.utc) - start_perf).total_seconds() * 1000)
        record.duration_ms = duration_ms
        if record.cancel_event.is_set():
            # User cancelled while the runner was still finishing; honour it.
            self._finalise(record, loop, "cancelled", "cancelled by user")
            return
        if artifacts.succeeded:
            self._finalise(record, loop, "succeeded", None)
        else:
            self._finalise(
                record,
                loop,
                "failed",
                artifacts.failure_reason or "agent reported failure",
            )

    def _finalise(
        self,
        record: RunRecord,
        loop: asyncio.AbstractEventLoop,
        status: RunStatus,
        failure_reason: str | None,
    ) -> None:
        record.status = status
        record.failure_reason = failure_reason
        record.finished_at = _utc_iso()
        # Schedule async cleanup back on the event loop.
        asyncio.run_coroutine_threadsafe(self._async_finalise(record), loop)

    async def _async_finalise(self, record: RunRecord) -> None:
        await self._teardown_watchers(record)
        await record.bus.publish(
            {"type": "final", "run": record.as_summary().model_dump(mode="json")}
        )
        # Persist the final summary so a restarted server can recover it.
        await asyncio.to_thread(_update_run_meta_status, record)

    async def _teardown_watchers(self, record: RunRecord) -> None:
        if record.log_tailer is not None:
            try:
                await record.log_tailer.stop()
            except Exception:  # noqa: BLE001
                logger.exception("log_tailer stop failed: run_id=%s", record.run_id)
        if record.trace_watcher is not None:
            try:
                await record.trace_watcher.stop()
            except Exception:  # noqa: BLE001
                logger.exception("trace_watcher stop failed: run_id=%s", record.run_id)


# --------------------------------------------------------------------------- helpers


def _write_run_meta(
    record: RunRecord, config: AppConfig, overrides: AgentOverrides
) -> None:
    """Write ``run_meta.json`` at run-creation time (status=queued).

    Overrides are stored sans ``api_key`` (we keep only the fingerprint).
    """
    overrides_payload = overrides.model_dump(exclude={"api_key"})
    payload: dict[str, Any] = {
        "run_id": record.run_id,
        "task_id": record.task.task_id,
        "source": record.task.source,
        "status": record.status,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_ms": record.duration_ms,
        "failure_reason": record.failure_reason,
        "agent": {
            "model": config.agent.model,
            "api_base": config.agent.api_base,
            "max_steps": config.agent.max_steps,
            "temperature": config.agent.temperature,
            "api_key_fingerprint": record.api_key_fingerprint,
        },
        "run": {
            "task_timeout_seconds": config.run.task_timeout_seconds,
            "vote_rounds": config.run.vote_rounds,
        },
        "overrides": overrides_payload,
        "created_at": _utc_iso(),
    }
    meta_path = record.run_output_dir / "run_meta.json"
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _update_run_meta_status(record: RunRecord) -> None:
    meta_path = record.run_output_dir / "run_meta.json"
    if not meta_path.exists():
        return
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    payload.update(
        {
            "status": record.status,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "duration_ms": record.duration_ms,
            "failure_reason": record.failure_reason,
        }
    )
    tmp_path = meta_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    tmp_path.replace(meta_path)


def make_unique_upload_id() -> str:
    """Short, URL-safe id for an uploaded ad-hoc task."""
    return uuid.uuid4().hex[:12]
