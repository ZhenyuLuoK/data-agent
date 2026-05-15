"""Derive a :class:`DagSnapshot` from accumulated trace ``steps``.

The runner writes ``trace.json`` after the run finishes, but every step
the agent executes is appended to an in-memory ``steps`` list whose
shape we can also reconstruct from the on-disk JSON during/after the
run. This module turns that list into the snapshot the WS / UI consume.

Schema notes (matched against a real trace from
``artifacts/runs/.../task_180/trace.json``):

* The first step has ``action == "__plan__"`` and its ``observation.content.dag``
  contains the initial plan: a list of nodes with
  ``id / goal / depends_on / suggested_tools / expected_output`` plus a
  ``final_node_id``.
* Each subsequent step is a tool call. We only inspect a handful of
  tool names that mutate node lifecycle:
    - ``mark_node_done(node_id, output_summary)`` → status=done
    - ``mark_node_failed(node_id, reason)``       → status=failed
    - ``start_node(node_id)`` (if present)        → status=in_progress
* Re-planning steps (action=="__plan__" appearing again later) replace
  the entire DAG; we preserve already-recorded statuses for nodes whose
  ``id`` survives the re-plan.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from data_agent_baseline.web.schemas import DagEdge, DagNode, DagSnapshot

logger = logging.getLogger("data_agent_baseline.web.dag_builder")

_STATUS_TOOLS = {
    "start_node": "in_progress",
    "mark_node_in_progress": "in_progress",
    "mark_node_done": "done",
    "mark_node_failed": "failed",
}


def build_snapshot_from_steps(steps: list[dict[str, Any]]) -> DagSnapshot:
    """Pure function: ``steps`` (in agent-execution order) → snapshot.

    Defensive against malformed steps — any step that doesn't match the
    expected shape is logged at DEBUG and skipped, never raised.
    """
    nodes_by_id: dict[str, DagNode] = {}
    final_node_id: str | None = None

    for step in steps:
        action = step.get("action")
        if action == "__plan__":
            plan_payload = _extract_plan(step)
            if plan_payload is None:
                continue
            nodes_by_id, final_node_id = _apply_plan(plan_payload, nodes_by_id)
            continue

        if action in _STATUS_TOOLS:
            _apply_status_tool(step, action, nodes_by_id)

    edges: list[DagEdge] = []
    for node in nodes_by_id.values():
        for upstream_id in node.depends_on:
            if upstream_id in nodes_by_id:
                edges.append(DagEdge(src=upstream_id, dst=node.id))

    return DagSnapshot(
        nodes=list(nodes_by_id.values()),
        edges=edges,
        final_node_id=final_node_id,
    )


def diff_node_ids(prev: DagSnapshot | None, curr: DagSnapshot) -> list[str]:
    """Return ids whose status / membership changed between two snapshots."""
    if prev is None:
        return [node.id for node in curr.nodes]
    prev_index: dict[str, DagNode] = {node.id: node for node in prev.nodes}
    changed: list[str] = []
    for node in curr.nodes:
        old = prev_index.get(node.id)
        if old is None:
            changed.append(node.id)
            continue
        if (
            old.status != node.status
            or old.output_summary != node.output_summary
            or old.finished_at != node.finished_at
            or old.started_at != node.started_at
        ):
            changed.append(node.id)
    return changed


# --------------------------------------------------------------------- helpers


def _extract_plan(step: dict[str, Any]) -> dict[str, Any] | None:
    observation = step.get("observation")
    if not isinstance(observation, dict):
        return None
    content = observation.get("content")
    if not isinstance(content, dict):
        return None
    dag_payload = content.get("dag")
    if not isinstance(dag_payload, dict):
        return None
    return dag_payload


def _apply_plan(
    plan_payload: dict[str, Any],
    previous_nodes: dict[str, DagNode],
) -> tuple[dict[str, DagNode], str | None]:
    raw_nodes = plan_payload.get("nodes")
    if not isinstance(raw_nodes, list):
        return previous_nodes, plan_payload.get("final_node_id")

    next_nodes: dict[str, DagNode] = {}
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_id = raw_node.get("id")
        if not isinstance(node_id, str) or not node_id:
            continue
        prior = previous_nodes.get(node_id)
        next_nodes[node_id] = DagNode(
            id=node_id,
            goal=str(raw_node.get("goal", "")),
            depends_on=[d for d in raw_node.get("depends_on", []) if isinstance(d, str)],
            suggested_tools=[
                t for t in raw_node.get("suggested_tools", []) if isinstance(t, str)
            ],
            expected_output=raw_node.get("expected_output"),
            # Preserve runtime status if a previous plan already advanced
            # this node — a re-plan that re-includes ``n1`` shouldn't
            # demote ``done`` back to ``pending``.
            status=prior.status if prior else "pending",
            started_at=prior.started_at if prior else None,
            finished_at=prior.finished_at if prior else None,
            output_summary=prior.output_summary if prior else None,
        )
    final_node_id = plan_payload.get("final_node_id")
    if not isinstance(final_node_id, str):
        final_node_id = None
    return next_nodes, final_node_id


def _apply_status_tool(
    step: dict[str, Any],
    action: str,
    nodes_by_id: dict[str, DagNode],
) -> None:
    action_input = step.get("action_input")
    if not isinstance(action_input, dict):
        return
    node_id = action_input.get("node_id")
    if not isinstance(node_id, str) or node_id not in nodes_by_id:
        return
    new_status = _STATUS_TOOLS[action]
    output_summary = action_input.get("output_summary")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = nodes_by_id[node_id]
    nodes_by_id[node_id] = existing.model_copy(
        update={
            "status": new_status,
            "started_at": existing.started_at or now_iso,
            "finished_at": now_iso if new_status in {"done", "failed"} else existing.finished_at,
            "output_summary": (
                output_summary if isinstance(output_summary, str) else existing.output_summary
            ),
        }
    )
