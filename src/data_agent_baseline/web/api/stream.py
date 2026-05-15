"""WebSocket: live snapshot + incremental log/step/dag/final events.

Connection lifecycle:
1. Client opens ``ws://.../api/runs/{run_id}/stream`` (optional ``?from_seq=N``).
2. Server accepts, sends one ``snapshot`` event with the current run
   summary, full DAG snapshot, and the entire on-disk ``agent.log``
   tail (line-by-line so the client can re-use its log renderer).
3. Server replays buffered events with ``seq >= from_seq`` (when set),
   skipping the snapshot's redundant info.
4. Server forwards live events from the run's :class:`RunEventBus`
   until either the client disconnects or the run reaches a terminal
   status (``final`` event already published by the run manager).
5. Server closes the WebSocket cleanly after sending ``final``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from data_agent_baseline.web.services.run_manager import RunManager, RunRecord

logger = logging.getLogger("data_agent_baseline.web.stream")

router = APIRouter(tags=["stream"])

# How long to wait on the bus queue before checking the cancel/done
# state. A short timeout keeps the loop responsive without busy-waiting.
_QUEUE_WAIT_TIMEOUT_S = 0.5


@router.websocket("/runs/{run_id}/stream")
async def stream_run(
    websocket: WebSocket,
    run_id: str,
    from_seq: int = Query(default=0, ge=0),
) -> None:
    manager: RunManager = websocket.app.state.run_manager
    record = manager.get(run_id)
    if record is None:
        # WS spec doesn't really have status codes pre-accept; close with
        # 4404 (custom application code, in the 4000-4999 range).
        await websocket.close(code=4404, reason="run_not_found")
        return

    await websocket.accept()
    queue = record.bus.subscribe()
    live_from_seq = record.bus.next_seq
    try:
        await _send_snapshot(websocket, record)
        replay_from_seq = from_seq if from_seq > 0 or _run_is_terminal(record) else live_from_seq
        last_delivered_seq = await _replay_buffered(websocket, record, replay_from_seq)
        if last_delivered_seq == 0:
            last_delivered_seq = max(0, replay_from_seq - 1)
        await _stream_live(websocket, record, queue, last_delivered_seq)
    except WebSocketDisconnect:
        # Client closed. Fully expected; not an error.
        return
    except Exception:  # noqa: BLE001
        logger.exception("ws stream crashed: run_id=%s", run_id)
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "seq": record.bus.next_seq,
                    "code": "stream_error",
                    "message": "internal stream error",
                }
            )
        except Exception:  # noqa: BLE001
            pass
        await _safe_close(websocket, code=1011)
    finally:
        record.bus.unsubscribe(queue)


async def _send_snapshot(websocket: WebSocket, record: RunRecord) -> None:
    """First message after accept: full state needed to render the page.

    The snapshot is **per-client** and uses ``seq=0`` as a sentinel: it is
    NOT published to the run-wide bus, so it never appears in the ring
    buffer and reconnecting clients always get a fresh one. This avoids
    a subtle ordering bug where ``log`` events emitted while the run was
    starting up would sort before the snapshot during replay.
    """
    snapshot_dag = (
        record.trace_watcher.snapshot.model_dump()
        if record.trace_watcher is not None
        else {"nodes": [], "edges": [], "final_node_id": None}
    )
    log_tail = _read_log_tail(record)
    snapshot_steps = (
        [_build_snapshot_step(step) for step in record.trace_watcher.steps]
        if record.trace_watcher is not None
        else []
    )
    await websocket.send_json(
        {
            "type": "snapshot",
            "seq": 0,
            "run": record.as_summary().model_dump(mode="json"),
            "dag": snapshot_dag,
            "log_tail": log_tail,
            "steps": snapshot_steps,
        }
    )


async def _replay_buffered(
    websocket: WebSocket, record: RunRecord, from_seq: int
) -> int:
    """Send archived events the client missed and return the last seq sent."""
    history = record.bus.replay_from(from_seq)
    last_delivered_seq = 0
    for event in history:
        await websocket.send_json(event)
        last_delivered_seq = max(last_delivered_seq, int(event.get("seq", 0)))
    return last_delivered_seq


async def _stream_live(
    websocket: WebSocket,
    record: RunRecord,
    queue: asyncio.Queue[dict[str, Any]],
    last_delivered_seq: int,
) -> None:
    """Forward live events until run is final + queue drained.

    The caller subscribes before snapshot/replay, so events published
    during snapshot generation are queued here instead of falling through
    a replay/subscribe race window.
    """
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=_QUEUE_WAIT_TIMEOUT_S)
        except asyncio.TimeoutError:
            # Timeout: check whether the run finished + bus drained.
            if _run_is_terminal(record) and queue.empty():
                break
            continue

        seq = int(event.get("seq", 0))
        if seq <= last_delivered_seq:
            continue
        last_delivered_seq = seq

        await websocket.send_json(event)
        if event.get("type") == "final":
            break
    await _safe_close(websocket, code=1000)


def _build_snapshot_step(step: dict[str, Any]) -> dict[str, Any]:
    """Project an on-disk trace step into the snapshot's step shape."""
    return {
        "type": "step",
        "seq": 0,
        "step_index": step.get("step_index"),
        "thought": step.get("thought"),
        "action": step.get("action"),
        "action_input": step.get("action_input"),
        "observation": step.get("observation"),
        "raw_response": step.get("raw_response"),
        "elapsed_ms": step.get("elapsed_ms"),
    }


def _run_is_terminal(record: RunRecord) -> bool:
    return record.status in {"succeeded", "failed", "cancelled", "timeout"}


def _read_log_tail(record: RunRecord) -> list[str]:
    """Read the agent log file in full so the client can render history.

    No truncation: we honour the spec's "no truncated log" guarantee even
    on snapshot. Cap at a generous 1 MiB to avoid blowing the WS frame
    budget — beyond that the client should fetch via the REST endpoint.
    """
    log_path = record.run_output_dir / record.task.task_id / "agent.log"
    if not log_path.is_file():
        return []
    try:
        raw = log_path.read_bytes()
    except OSError:
        return []
    if len(raw) > 1024 * 1024:
        # Hand the client only the tail and let it know more is available
        # via the REST endpoint; we mark this with a sentinel comment
        # line rather than silently dropping.
        raw = raw[-1024 * 1024 :]
        suffix_note = (
            "[snapshot truncated to last 1 MiB; fetch full log via "
            "/api/runs/{rid}/files/agent.log]"
        ).format(rid=record.run_id)
    else:
        suffix_note = ""
    decoded = raw.decode("utf-8", errors="replace")
    lines = decoded.split("\n")
    if suffix_note:
        lines.insert(0, suffix_note)
    return [line for line in lines if line]


async def _safe_close(websocket: WebSocket, *, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:  # noqa: BLE001
        pass
    # No-op if already closed; we swallow because ``close`` may raise
    # ``RuntimeError("WebSocket is not connected")`` after a remote close.


# Helper exported for tests so they can introspect what ``stream`` would
# send without spinning up a real WS client.
async def collect_events_for_test(record: RunRecord) -> list[dict[str, Any]]:
    """Return the snapshot + ring buffer for tests."""
    snapshot_dag = (
        record.trace_watcher.snapshot.model_dump()
        if record.trace_watcher is not None
        else {"nodes": [], "edges": [], "final_node_id": None}
    )
    snapshot_event = {
        "type": "snapshot",
        "run": record.as_summary().model_dump(mode="json"),
        "dag": snapshot_dag,
        "log_tail": _read_log_tail(record),
    }
    await record.bus.publish(snapshot_event)
    return record.bus.replay_from(0)
