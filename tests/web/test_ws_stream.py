"""WebSocket stream tests: snapshot + log/step/dag_update + final."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def _drain_until_final(ws, *, max_events: int = 200) -> list[dict[str, Any]]:
    """Read events from a starlette TestClient WebSocket until ``final`` arrives."""
    events: list[dict[str, Any]] = []
    for _ in range(max_events):
        raw = ws.receive_text()
        event = json.loads(raw)
        events.append(event)
        if event.get("type") == "final":
            return events
    raise AssertionError("WebSocket did not deliver a 'final' event in time")


def _post_run(client: TestClient) -> str:
    response = client.post(
        "/api/runs",
        json={"source": "builtin", "task_id": "task_42"},
    )
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_ws_delivers_snapshot_log_step_and_final(
    client: TestClient, stub_run_single_task: dict[str, Any]
) -> None:
    run_id = _post_run(client)
    # Give the worker a moment to write trace.json + agent.log so the
    # snapshot has real content. The watchers poll every 100/250 ms; a
    # short sleep avoids a flaky snapshot=empty path.
    time.sleep(0.4)

    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        events = _drain_until_final(ws)

    types = [event["type"] for event in events]
    # Snapshot must be present and first.
    assert types[0] == "snapshot"
    assert types[-1] == "final"
    # Sequence numbers are monotonically increasing.
    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "no duplicate seqs"
    # We should see at least one log + one step + one dag_update from the
    # stub trace.
    assert "log" in types
    assert "step" in types
    assert "dag_update" in types

    # The final event includes the terminal RunSummary.
    final_event = events[-1]
    assert final_event["run"]["status"] == "succeeded"
    assert final_event["run"]["run_id"] == run_id
    # stub_run_single_task fixture is referenced to keep the patch active.
    assert stub_run_single_task["calls"]


def test_ws_rejects_unknown_run(client: TestClient) -> None:
    # Starlette's TestClient raises on close-before-accept; we expect
    # the server to close with code 4404 immediately.
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect("/api/runs/does-not-exist/stream"):
            raise AssertionError("should have closed before accepting")
    except WebSocketDisconnect as exc:
        assert exc.code == 4404


def test_ws_long_log_line_is_chunked(
    client: TestClient, stub_run_single_task: dict[str, Any], web_paths
) -> None:
    """Spec §6.4: long lines must be sliced into 64 KiB chunks, never truncated."""
    # Override the stub to write a >120 KiB line so we cross the 64 KiB
    # chunk boundary at least once.
    huge_line = "X" * (130 * 1024)

    original_calls = stub_run_single_task["calls"]

    def write_huge_log(run_output_dir: Path, task_id: str) -> None:
        task_dir = run_output_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "agent.log").write_text(huge_line + "\n")
        (task_dir / "trace.json").write_text(
            json.dumps({"task_id": task_id, "answer": None, "steps": [], "succeeded": True})
        )

    # Replace the stub with one that ONLY writes the huge log.
    from data_agent_baseline.run.runner import TaskRunArtifacts

    def fake(*, task_id, config, run_output_dir, model=None, tools=None,
             prediction_filename="prediction.csv", trace_suffix="") -> TaskRunArtifacts:  # noqa: ARG001
        original_calls.append((task_id, str(run_output_dir)))
        write_huge_log(Path(run_output_dir), task_id)
        return TaskRunArtifacts(
            task_id=task_id,
            task_output_dir=Path(run_output_dir) / task_id,
            prediction_csv_path=None,
            trace_path=Path(run_output_dir) / task_id / "trace.json",
            succeeded=True,
            failure_reason=None,
        )

    import data_agent_baseline.web.services.run_manager as rm
    rm.run_single_task = fake  # type: ignore[assignment]

    run_id = _post_run(client)
    time.sleep(0.4)
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        events = _drain_until_final(ws)

    log_events = [event for event in events if event["type"] == "log"]
    assert log_events, "expected at least one log chunk"
    # All chunks for the huge line must share a line_id and the union of
    # their ``line`` payloads must equal the original (no truncation).
    huge_chunks = [event for event in log_events if event["chunk_total"] > 1]
    assert huge_chunks, "expected the huge line to be sliced (chunk_total > 1)"
    line_ids = {event["line_id"] for event in huge_chunks}
    assert len(line_ids) == 1
    huge_chunks.sort(key=lambda event: event["chunk_index"])
    indices = [event["chunk_index"] for event in huge_chunks]
    assert indices == list(range(huge_chunks[0]["chunk_total"]))
    reassembled = "".join(event["line"] for event in huge_chunks)
    assert reassembled == huge_line, "log chunks must reassemble bit-for-bit"
    _ = web_paths  # silence unused-arg lint
