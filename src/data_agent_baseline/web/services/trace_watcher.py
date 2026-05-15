"""Watch ``trace.json`` for new ``steps`` and emit ``step``/``dag_update`` events.

The runner only finalises ``trace.json`` after the run, but the
``LangGraphAgent`` writes a partial trace inside the per-task directory
as it goes (see ``runner.run_single_task``: ``task_output_dir`` is
created before the agent starts and the agent flushes intermediate
state). The watcher polls the file mtime/size, parses the JSON when it
changes, diffs the ``steps`` list, and publishes:

* one ``step`` event per newly appended step
* one ``dag_update`` event whenever the derived DAG snapshot mutates
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from data_agent_baseline.web.schemas import DagSnapshot
from data_agent_baseline.web.services.dag_builder import (
    build_snapshot_from_steps,
    diff_node_ids,
)
from data_agent_baseline.web.services.event_bus import RunEventBus

logger = logging.getLogger("data_agent_baseline.web.trace_watcher")

_DEFAULT_POLL_INTERVAL_S = 0.25


class TraceWatcher:
    def __init__(
        self,
        *,
        trace_path: Path,
        bus: RunEventBus,
        poll_interval: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._trace_path = trace_path
        self._bus = bus
        self._poll_interval = poll_interval
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_step_count = 0
        self._last_mtime_ns: int | None = None
        self._last_size: int | None = None
        self._last_snapshot: DagSnapshot | None = None
        self._last_steps: list[dict[str, Any]] = []

    @property
    def snapshot(self) -> DagSnapshot:
        return self._last_snapshot or DagSnapshot()

    @property
    def steps(self) -> list[dict[str, Any]]:
        return list(self._last_steps)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._run(), name=f"trace-watcher:{self._trace_path.name}"
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            except Exception:  # noqa: BLE001
                logger.exception("trace_watcher task raised on shutdown: %s", self._trace_path)
            self._task = None
        # Final drain so the snapshot reflects whatever the runner wrote
        # between the last poll and the stop signal.
        await self._drain_once()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await self._drain_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                continue

    async def _drain_once(self) -> None:
        try:
            if not self._trace_path.exists():
                return
            stat = self._trace_path.stat()
        except OSError:
            return
        # Use nanosecond mtime + file size for change detection.
        # macOS st_mtime has only 1-second resolution, so rapid writes
        # within the same second were invisible to the old check.
        cur_mtime_ns = stat.st_mtime_ns
        cur_size = stat.st_size
        if (
            self._last_mtime_ns is not None
            and cur_mtime_ns == self._last_mtime_ns
            and cur_size == self._last_size
        ):
            return
        try:
            payload = json.loads(self._trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Mid-write: try again next tick. Do not advance the observed
            # file version until parsing succeeds, otherwise a partial write
            # can be mistaken for a fully processed update.
            return
        steps = payload.get("steps")
        if not isinstance(steps, list):
            return
        parsed_steps = [step for step in steps if isinstance(step, dict)]
        self._last_mtime_ns = cur_mtime_ns
        self._last_size = cur_size
        self._last_steps = parsed_steps

        # Emit only newly appended steps. The runner never reorders or
        # rewrites past steps, so step_index strictly increases.
        new_steps = parsed_steps[self._last_step_count :]
        for step in new_steps:
            await self._bus.publish(_build_step_event(step))
        if new_steps:
            self._last_step_count = len(parsed_steps)

        # Always recompute the snapshot from the full step list — cheap
        # and avoids subtle bugs when re-plans rewrite earlier nodes.
        snapshot = build_snapshot_from_steps(parsed_steps)
        if _snapshot_changed(self._last_snapshot, snapshot):
            updated_ids = diff_node_ids(self._last_snapshot, snapshot)
            await self._bus.publish(
                {
                    "type": "dag_update",
                    "nodes": [node.model_dump() for node in snapshot.nodes],
                    "edges": [edge.model_dump(by_alias=True) for edge in snapshot.edges],
                    "final_node_id": snapshot.final_node_id,
                    "updated_node_ids": updated_ids,
                }
            )
            self._last_snapshot = snapshot


def _build_step_event(step: dict[str, Any]) -> dict[str, Any]:
    """Project the on-disk step shape onto the WS ``step`` event schema."""
    return {
        "type": "step",
        "step_index": step.get("step_index"),
        "thought": step.get("thought"),
        "action": step.get("action"),
        "action_input": step.get("action_input"),
        "observation": step.get("observation"),
        "raw_response": step.get("raw_response"),
        "elapsed_ms": step.get("elapsed_ms"),
    }


def _snapshot_changed(prev: DagSnapshot | None, curr: DagSnapshot) -> bool:
    if prev is None:
        return bool(curr.nodes)
    if len(prev.nodes) != len(curr.nodes) or len(prev.edges) != len(curr.edges):
        return True
    if prev.final_node_id != curr.final_node_id:
        return True
    prev_index = {node.id: node for node in prev.nodes}
    for node in curr.nodes:
        old = prev_index.get(node.id)
        if old is None:
            return True
        if (
            old.status != node.status
            or old.output_summary != node.output_summary
            or old.goal != node.goal
            or old.depends_on != node.depends_on
        ):
            return True
    return False
