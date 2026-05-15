"""Pydantic DTOs shared by the REST API and the WebSocket stream.

Field names match the contracts in ``docs/backend_requirements.md`` §4.
Keep this module dependency-free (no service imports) so it can be reused
from tests and from a future SDK without dragging in run-manager state.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------- task / context ---------------------------------------------------


class ContextFile(BaseModel):
    path: str
    kind: str
    size: int | None = None


class TaskBrief(BaseModel):
    task_id: str
    difficulty: str
    question: str
    source: Literal["builtin", "upload"]
    context_files: list[ContextFile] = Field(default_factory=list)


# ---------- agent overrides --------------------------------------------------


class AgentOverrides(BaseModel):
    """Per-run overrides; missing fields fall back to the server defaults.

    ``api_key`` is intentionally a plain ``str``: pydantic's ``SecretStr``
    would force callers to ``.get_secret_value()`` everywhere and the
    benefit (repr masking) is irrelevant — we strip the field from logs
    via :class:`security.ApiKeyRedactingFilter` at the logging layer.
    """

    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=1000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    task_timeout_seconds: int | None = Field(default=None, ge=0)
    vote_rounds: int | None = Field(default=None, ge=1, le=3)


class DefaultsResponse(BaseModel):
    """Server-side defaults exposed to the frontend.

    ``api_key`` is **never** echoed; only ``api_key_set`` indicates whether
    a default key is configured (so the UI can decide whether to require
    one from the user).
    """

    model: str
    api_base: str
    api_key_set: bool
    max_steps: int
    temperature: float
    task_timeout_seconds: int
    vote_rounds: int
    max_concurrent_runs: int


# ---------- runs -------------------------------------------------------------


RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "timeout"]


class CreateRunRequest(BaseModel):
    source: Literal["builtin", "upload"]
    task_id: str
    upload_id: str | None = None
    agent_overrides: AgentOverrides = Field(default_factory=AgentOverrides)


class RunSummary(BaseModel):
    run_id: str
    task_id: str
    source: Literal["builtin", "upload"]
    status: RunStatus
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    prediction_csv_url: str | None = None
    trace_url: str | None = None
    dag_svg_url: str | None = None
    log_url: str | None = None
    failure_reason: str | None = None


# ---------- DAG snapshot -----------------------------------------------------


DagNodeStatus = Literal["pending", "in_progress", "done", "failed"]


class DagNode(BaseModel):
    id: str
    goal: str
    depends_on: list[str] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list)
    expected_output: str | None = None
    status: DagNodeStatus = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    output_summary: str | None = None


class DagEdge(BaseModel):
    src: str = Field(alias="from")
    dst: str = Field(alias="to")

    model_config = {"populate_by_name": True}


class DagSnapshot(BaseModel):
    nodes: list[DagNode] = Field(default_factory=list)
    edges: list[DagEdge] = Field(default_factory=list)
    final_node_id: str | None = None


# ---------- upload responses -------------------------------------------------


class UploadResponse(BaseModel):
    upload_id: str
    task: TaskBrief


# ---------- WebSocket events -------------------------------------------------
#
# Each WS message is ``{"type": "...", "seq": N, ...payload}``. We don't
# model these as a discriminated union because the payload shape evolves
# faster than the protocol and FastAPI doesn't validate WS sends anyway —
# this is documentation in code form.


class WSLogChunk(BaseModel):
    """Sliced log line: re-assembled by the client via ``line_id``."""

    type: Literal["log"] = "log"
    seq: int
    ts: str
    line_id: int
    chunk_index: int
    chunk_total: int
    line: str


class WSStep(BaseModel):
    type: Literal["step"] = "step"
    seq: int
    step_index: int
    thought: str | None = None
    action: str | None = None
    action_input: Any = None
    observation: Any = None
    raw_response: str | None = None
    elapsed_ms: int | None = None


class WSDagUpdate(BaseModel):
    type: Literal["dag_update"] = "dag_update"
    seq: int
    nodes: list[DagNode]
    edges: list[DagEdge]
    final_node_id: str | None = None
    updated_node_ids: list[str] = Field(default_factory=list)


class WSSnapshot(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    seq: int
    run: RunSummary
    dag: DagSnapshot
    log_tail: list[str]
    steps: list[WSStep] = Field(default_factory=list)


class WSFinal(BaseModel):
    type: Literal["final"] = "final"
    seq: int
    run: RunSummary


class WSError(BaseModel):
    type: Literal["error"] = "error"
    seq: int
    code: str
    message: str
