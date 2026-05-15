"""Tests for /api/tasks and /api/tasks/{id}/context/{path}."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_tasks_returns_builtin(client: TestClient) -> None:
    response = client.get("/api/tasks")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 1
    task = payload[0]
    assert task["task_id"] == "task_42"
    assert task["source"] == "builtin"
    assert task["context_files"][0]["path"] == "data.csv"


def test_list_tasks_keyword_filter(client: TestClient) -> None:
    response = client.get("/api/tasks", params={"keyword": "no-such-keyword"})
    assert response.status_code == 200
    assert response.json() == []


def test_get_task_404(client: TestClient) -> None:
    response = client.get("/api/tasks/task_does_not_exist")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_download_context_file(client: TestClient) -> None:
    response = client.get("/api/tasks/task_42/context/data.csv")
    assert response.status_code == 200
    assert "x,y" in response.text


def test_download_context_path_traversal_rejected(client: TestClient) -> None:
    response = client.get("/api/tasks/task_42/context/../task.json")
    # FastAPI normalises ``..`` in some clients; either 400/404 is acceptable
    # as long as the task.json is NOT served.
    assert response.status_code in {400, 404}
    assert "task_id" not in response.text or response.status_code != 200
