"""Shared fixtures for the web-layer test suite.

Each test gets:
* an isolated tmp ``dataset_root`` with a single fake builtin task
* an isolated tmp ``run_root`` and ``upload_root``
* an isolated tmp ``base_config_path`` YAML so we never read real api keys
* a FastAPI ``TestClient`` bound to a fresh ``WebSettings``

The runner is monkeypatched to a deterministic stub that writes a
plausible ``trace.json`` / ``prediction.csv`` / ``agent.log`` so we don't
need a live LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from data_agent_baseline.run.runner import TaskRunArtifacts
from data_agent_baseline.web.app import create_app
from data_agent_baseline.web.settings import WebSettings


def _write_builtin_task(dataset_root: Path, task_id: str = "task_42") -> None:
    task_dir = dataset_root / task_id
    (task_dir / "context").mkdir(parents=True)
    (task_dir / "task.json").write_text(
        json.dumps(
            {"task_id": task_id, "difficulty": "easy", "question": "What is 2 + 2?"},
            ensure_ascii=False,
            indent=2,
        )
    )
    (task_dir / "context" / "data.csv").write_text("x,y\n1,2\n3,4\n")


def _write_base_config(config_path: Path, dataset_root: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "dataset:\n"
        f"  root_path: {dataset_root.as_posix()}\n"
        "agent:\n"
        "  model: stub-model\n"
        "  api_base: https://example.invalid/v1\n"
        "  api_key: sk-test-fake-key\n"
        "  max_steps: 8\n"
        "  temperature: 0.0\n"
        "run:\n"
        "  output_dir: artifacts/runs\n"
        "  task_timeout_seconds: 0\n"
        "  vote_rounds: 1\n"
    )


@pytest.fixture
def web_paths(tmp_path: Path) -> dict[str, Path]:
    dataset_root = tmp_path / "dataset"
    upload_root = tmp_path / "uploads"
    run_root = tmp_path / "runs"
    docs_root = tmp_path / "docs"
    dataset_root.mkdir()
    upload_root.mkdir()
    run_root.mkdir()
    docs_root.mkdir()
    _write_builtin_task(dataset_root)
    config_path = tmp_path / "react_baseline.test.yaml"
    _write_base_config(config_path, dataset_root)
    # Drop a tiny "static doc" so we can verify /static/docs mounting.
    (docs_root / "agent_architecture_summary.html").write_text(
        "<!doctype html><title>arch</title><h1>arch</h1>"
    )
    (docs_root / "data-agent" / "html").mkdir(parents=True)
    (docs_root / "data-agent" / "html" / "index.html").write_text(
        "<!doctype html><title>papers</title><h1>papers</h1>"
    )
    return {
        "dataset_root": dataset_root,
        "upload_root": upload_root,
        "run_root": run_root,
        "docs_root": docs_root,
        "config_path": config_path,
    }


@pytest.fixture
def stub_run_single_task(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``runner.run_single_task`` with a stub that writes fake outputs.

    Returns a dict the test can mutate to control behaviour:
      * ``succeed``: when False, the stub writes a failure trace
      * ``calls``: list of (task_id, run_output_dir) tuples per invocation
    """
    state: dict[str, Any] = {"succeed": True, "calls": []}

    def fake_run_single_task(
        *,
        task_id: str,
        config: Any,
        run_output_dir: Path,
        model: Any = None,
        tools: Any = None,
        prediction_filename: str = "prediction.csv",
        trace_suffix: str = "",
    ) -> TaskRunArtifacts:
        state["calls"].append((task_id, str(run_output_dir)))
        task_dir = Path(run_output_dir) / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        # Fake agent log — multiple lines so we can assert log_tail order.
        log_path = task_dir / "agent.log"
        log_path.write_text(
            "2026-05-08T20:00:00+0800 [INFO   ] stub | start\n"
            f"2026-05-08T20:00:01+0800 [INFO   ] stub | task={task_id}\n"
            "2026-05-08T20:00:02+0800 [INFO   ] stub | done\n"
        )
        # Fake trace with a plan + one tool step so the dag_builder has
        # real material to consume.
        trace_payload = {
            "task_id": task_id,
            "answer": (
                {"columns": ["x"], "rows": [[1], [2]]}
                if state["succeed"]
                else None
            ),
            "steps": [
                {
                    "step_index": 1,
                    "action": "__plan__",
                    "action_input": {},
                    "observation": {
                        "ok": True,
                        "content": {
                            "dag": {
                                "nodes": [
                                    {
                                        "id": "n1",
                                        "goal": "Read csv",
                                        "depends_on": [],
                                        "suggested_tools": ["read_csv"],
                                        "expected_output": "rows",
                                    }
                                ],
                                "final_node_id": "n1",
                            }
                        },
                    },
                    "raw_response": "{...}",
                },
                {
                    "step_index": 2,
                    "action": "mark_node_done",
                    "action_input": {
                        "node_id": "n1",
                        "output_summary": "ok",
                    },
                    "observation": {"ok": True, "content": {"status": "node_done"}},
                    "raw_response": "",
                },
            ],
            "succeeded": state["succeed"],
            "failure_reason": None if state["succeed"] else "stubbed failure",
        }
        (task_dir / "trace.json").write_text(json.dumps(trace_payload, indent=2))
        if state["succeed"]:
            (task_dir / "prediction.csv").write_text("x\n1\n2\n")
        return TaskRunArtifacts(
            task_id=task_id,
            task_output_dir=task_dir,
            prediction_csv_path=task_dir / "prediction.csv" if state["succeed"] else None,
            trace_path=task_dir / "trace.json",
            succeeded=state["succeed"],
            failure_reason=None if state["succeed"] else "stubbed failure",
        )

    # Patch BOTH the source module and the run_manager re-export.
    monkeypatch.setattr(
        "data_agent_baseline.web.services.run_manager.run_single_task",
        fake_run_single_task,
    )
    return state


@pytest.fixture
def client(web_paths: dict[str, Path]) -> Iterator[TestClient]:
    settings = WebSettings(
        host="127.0.0.1",
        port=0,
        base_config_path=web_paths["config_path"],
        dataset_root=web_paths["dataset_root"],
        run_root=web_paths["run_root"],
        upload_root=web_paths["upload_root"],
        docs_root=web_paths["docs_root"],
        max_concurrent_runs=2,
    )
    app = create_app(settings=settings)
    with TestClient(app) as test_client:
        yield test_client
