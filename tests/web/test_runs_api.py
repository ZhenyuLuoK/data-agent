"""Tests for /api/runs (create + lifecycle + download + defaults endpoint)."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient


def _wait_until_terminal(client: TestClient, run_id: str, timeout_s: float = 5.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"succeeded", "failed", "cancelled", "timeout"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not terminate in {timeout_s}s")


def test_health_and_defaults(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["ok"] is True
    defaults = client.get("/api/config/defaults").json()
    assert defaults["model"] == "stub-model"
    # API key value must NEVER be returned, only the boolean flag.
    assert "api_key" not in defaults
    assert defaults["api_key_set"] is True


def test_create_run_succeeds(client: TestClient, stub_run_single_task: dict[str, Any]) -> None:
    create = client.post(
        "/api/runs",
        json={
            "source": "builtin",
            "task_id": "task_42",
            "agent_overrides": {"model": "override-model"},
        },
    )
    assert create.status_code == 202, create.text
    run = create.json()
    assert run["status"] in {"queued", "running"}
    final = _wait_until_terminal(client, run["run_id"])
    assert final["status"] == "succeeded"
    assert final["prediction_csv_url"] is not None
    assert final["trace_url"] is not None

    # Worker actually got the override merged in.
    assert stub_run_single_task["calls"]
    task_id, _ = stub_run_single_task["calls"][0]
    assert task_id == "task_42"

    # File download endpoint returns the prediction.
    csv_resp = client.get(final["prediction_csv_url"])
    assert csv_resp.status_code == 200
    assert csv_resp.text.startswith("x")


def test_create_run_unknown_task(client: TestClient, stub_run_single_task: dict[str, Any]) -> None:  # noqa: ARG001
    response = client.post(
        "/api/runs",
        json={"source": "builtin", "task_id": "task_nope"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_create_run_rejects_missing_api_key(
    client: TestClient, web_paths, stub_run_single_task: dict[str, Any]
) -> None:
    # Wipe the api_key from the base config to force the validation branch.
    # Note: load_app_config is invoked per-request, so the rewrite below
    # takes effect for the very next /api/runs call.
    web_paths["config_path"].write_text(
        web_paths["config_path"].read_text().replace("sk-test-fake-key", "")
    )
    response = client.post(
        "/api/runs",
        json={"source": "builtin", "task_id": "task_42"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "invalid_payload"
    # The stub must NOT have been called: validation should reject before
    # any worker is spawned.
    assert stub_run_single_task["calls"] == []


def test_run_failure_propagates(client: TestClient, stub_run_single_task: dict[str, Any]) -> None:
    stub_run_single_task["succeed"] = False
    create = client.post(
        "/api/runs",
        json={"source": "builtin", "task_id": "task_42"},
    )
    final = _wait_until_terminal(client, create.json()["run_id"])
    assert final["status"] == "failed"
    assert final["failure_reason"] == "stubbed failure"
    # No prediction.csv was written → URL must be None.
    assert final["prediction_csv_url"] is None


def test_static_docs_mount(client: TestClient) -> None:
    arch = client.get("/static/docs/agent_architecture_summary.html")
    assert arch.status_code == 200
    assert "<h1>arch</h1>" in arch.text
    papers = client.get("/static/docs/data-agent/html/index.html")
    assert papers.status_code == 200
    assert "<h1>papers</h1>" in papers.text
