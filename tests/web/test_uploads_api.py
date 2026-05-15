"""Tests for /api/uploads (create / get / delete + extension whitelist)."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient


def test_upload_creates_task(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        data={"question": "What's in the file?", "difficulty": "custom"},
        files=[("files", ("hello.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv"))],
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert "upload_id" in payload
    task = payload["task"]
    assert task["source"] == "upload"
    assert task["question"] == "What's in the file?"
    assert task["context_files"][0]["path"] == "hello.csv"

    # GET round-trip
    fetched = client.get(f"/api/uploads/{payload['upload_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["task_id"] == task["task_id"]


def test_upload_rejects_unknown_extension(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        data={"question": "x", "difficulty": "easy"},
        files=[("files", ("bad.exe", io.BytesIO(b"MZ"), "application/octet-stream"))],
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"


def test_upload_rejects_path_traversal(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        data={"question": "x", "difficulty": "easy"},
        files=[
            ("files", ("../escape.csv", io.BytesIO(b"a\n1\n"), "text/csv")),
        ],
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_payload"


def test_upload_delete(client: TestClient) -> None:
    create = client.post(
        "/api/uploads",
        data={"question": "delete me"},
        files=[("files", ("a.csv", io.BytesIO(b"a\n1\n"), "text/csv"))],
    )
    upload_id = create.json()["upload_id"]
    delete = client.delete(f"/api/uploads/{upload_id}")
    assert delete.status_code == 204
    again = client.get(f"/api/uploads/{upload_id}")
    assert again.status_code == 404
