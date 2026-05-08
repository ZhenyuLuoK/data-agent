"""Render the LangGraphAgent's StateGraph topology to ``docs/agent-workflow.svg``.

This is a one-shot, offline visualization script. It builds the same
graph that :class:`LangGraphAgent._build_graph` constructs at runtime,
then walks ``compiled_graph.get_graph()`` (LangGraph's internal
``DrawableGraph``) for the canonical node + edge list and renders the
result with networkx + matplotlib.

Why not use LangGraph's own ``draw_mermaid_png`` helper? It calls out
to the public ``mermaid.ink`` service over HTTP, which (a) needs network
access and (b) means the output isn't reproducible in a Docker build.
This script stays fully offline using deps already in ``pyproject.toml``.

Run from the repo root:

    uv run python scripts/visualize_agent_workflow.py

Output: ``docs/agent-workflow.svg`` (overwritten on each run).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import matplotlib

matplotlib.use("Agg")

import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402

# Make the project package importable when run as a plain script.
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from data_agent_baseline.agents.langgraph_agent import (  # noqa: E402
    LangGraphAgent,
    LangGraphAgentConfig,
)
from data_agent_baseline.benchmark.schema import (  # noqa: E402
    PublicTask,
    TaskAssets,
    TaskRecord,
)
from data_agent_baseline.tools.langchain_tools import (  # noqa: E402
    ToolRunContext,
    build_langchain_tools,
)


# ---- Visual styling --------------------------------------------------------

# Group nodes by responsibility so we can colour-code the figure.
# Keep this in sync with `_build_graph` in agents/langgraph_agent.py.
_NODE_GROUP: dict[str, str] = {
    "__start__": "control",
    "__end__": "control",
    "planner": "planning",
    "replanner": "planning",
    "scheduler": "planning",
    "executor": "execution",
    "tools": "execution",
    "node_failure": "recovery",
    "nudge": "recovery",
    "reflector": "verification",
    "finalize": "control",
}

_GROUP_FILL: dict[str, str] = {
    "control": "#cfd8dc",       # control flow (start/end/finalize) — neutral grey
    "planning": "#bbdefb",      # planner / replanner / scheduler — blue
    "execution": "#c8e6c9",     # executor / tools — green
    "recovery": "#ffe0b2",      # node_failure / nudge — amber
    "verification": "#e1bee7",  # reflector — purple
}

_GROUP_LABEL: dict[str, str] = {
    "control": "Control flow",
    "planning": "Planning (DAG)",
    "execution": "Execution",
    "recovery": "Recovery",
    "verification": "Verification",
}


# ---- Build a real graph using a stubbed model + dummy task -----------------


def _build_dummy_task() -> PublicTask:
    """Construct a ``PublicTask`` good enough for ``build_langchain_tools``.

    We only need the task object so the agent can wire the same node
    set it would at runtime; nothing actually executes against it.
    """

    record = TaskRecord(
        task_id="viz_dummy_task",
        difficulty="easy",
        question="(workflow visualization stub — no real task is run)",
    )
    assets = TaskAssets(
        task_dir=REPO_ROOT,           # any existing dir works for the stub
        context_dir=REPO_ROOT,
    )
    return PublicTask(record=record, assets=assets)


def _build_compiled_graph():
    """Mirror :func:`LangGraphAgent.run` up to the ``compile()`` call."""

    # The model only needs ``bind_tools`` to be callable; we never invoke
    # the LLM. A ``MagicMock`` returns another MagicMock for any attr.
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = MagicMock()

    agent = LangGraphAgent(model=fake_model, config=LangGraphAgentConfig())

    task = _build_dummy_task()
    tool_run_context = ToolRunContext()
    tools = build_langchain_tools(task, tool_run_context)
    return agent._build_graph(  # noqa: SLF001 — intentional: visualizing internals
        task=task,
        tools=tools,
        tool_run_context=tool_run_context,
        reflection_notes=[],
        task_output_dir=None,
    )


# ---- Layout: hand-tuned grid -----------------------------------------------

# Manual placement keyed by node id → (column, row). Both axes use
# integer-ish slots; the renderer below multiplies by physical spacing.
#
# Layout intent (top → bottom):
#   row 0:  entry
#   row 1:  initial planning
#   row 2:  recovery + scheduling axis (replan ← scheduler → reflector)
#   row 3:  executor focus column (node_failure ← executor → nudge)
#   row 4:  tools (LangGraph ToolNode)
#   row 5:  finish line
#
# Columns are signed offsets from a centre column (col 0). Negative =
# left, positive = right. The executor → tools → executor loop is the
# spine of the diagram and stays on the centre column.
_MANUAL_LAYOUT: dict[str, tuple[int, int]] = {
    "__start__":     (0, 0),
    "planner":       (0, 1),
    "replanner":    (-2, 2),
    "scheduler":     (0, 2),
    "reflector":    (+2, 2),
    "node_failure": (-2, 3),
    "executor":      (0, 3),
    "nudge":        (+2, 3),
    "tools":         (0, 4),
    "finalize":      (0, 5),
    "__end__":       (0, 6),
}


def _layered_positions(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Use the hand-tuned grid in :data:`_MANUAL_LAYOUT`.

    The compiled LangGraph topology is small (~11 nodes) but cyclic
    (``executor ⇄ tools``, ``scheduler ↔ node_failure``, ...). Algorithmic
    layouts (BFS depth, ``spring_layout``, ``multipartite_layout``) all
    end up tangled because the cycles break their layering invariants.
    A handful of manual coordinates produces a much more readable
    diagram and stays trivial to maintain — there are only 11 nodes.
    """

    col_dx = 2.6   # horizontal spacing between sibling columns
    row_dy = 1.5   # vertical spacing between rows
    positions: dict[str, tuple[float, float]] = {}
    for node in graph.nodes:
        if node not in _MANUAL_LAYOUT:
            # Defensive: a future _build_graph addition will land at the
            # bottom-right corner so the new node is at least visible.
            col, row = 0, max(r for _, r in _MANUAL_LAYOUT.values()) + 1
        else:
            col, row = _MANUAL_LAYOUT[node]
        positions[node] = (col * col_dx, -row * row_dy)
    return positions


# ---- Drawing ---------------------------------------------------------------


def _draw_workflow(graph: nx.DiGraph, output_path: Path) -> None:
    positions = _layered_positions(graph)

    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]
    fig_w = max(10.0, (max(xs) - min(xs)) * 1.0 + 6)
    fig_h = max(7.0, (max(ys) - min(ys)) * 1.0 + 3)

    fig = plt.figure(figsize=(fig_w, fig_h))
    main_ax = fig.add_axes((0.02, 0.04, 0.74, 0.92))
    legend_ax = fig.add_axes((0.78, 0.04, 0.20, 0.92))

    main_ax.set_title(
        "LangGraphAgent workflow (StateGraph topology)", fontsize=13
    )
    main_ax.set_axis_off()
    main_ax.set_aspect("equal")

    # Draw edges in two passes so that:
    #   1. Bidirectional pairs (e.g. executor ↔ tools, executor ↔ nudge)
    #      are drawn with mirror-image curvature so the two arrows don't
    #      sit on top of each other.
    #   2. Cross-column "back" edges (e.g. tools → scheduler, executor →
    #      node_failure) get a subtle curve so they don't slice through
    #      neighbouring node boxes.
    bidir_pairs: set[tuple[str, str]] = set()
    for u, v in graph.edges:
        if graph.has_edge(v, u):
            bidir_pairs.add(tuple(sorted((u, v))))

    straight_edges: list[tuple[str, str]] = []
    curved_edges_left: list[tuple[str, str]] = []
    curved_edges_right: list[tuple[str, str]] = []
    for u, v in graph.edges:
        key = tuple(sorted((u, v)))
        if key in bidir_pairs:
            # First direction (u→v) bends left, second (v→u) bends right.
            if u == key[0]:
                curved_edges_left.append((u, v))
            else:
                curved_edges_right.append((u, v))
            continue
        # Cross-column back edges: any edge where source row > target row
        # OR where the absolute column distance is ≥ 2 (i.e. it would
        # otherwise visually cut across an unrelated node box).
        u_col, u_row = _MANUAL_LAYOUT.get(u, (0, 0))
        v_col, v_row = _MANUAL_LAYOUT.get(v, (0, 0))
        is_back = v_row < u_row
        is_long_horizontal = abs(u_col - v_col) >= 2
        if is_back or is_long_horizontal:
            curved_edges_left.append((u, v))
        else:
            straight_edges.append((u, v))

    common_edge_kwargs = {
        "ax": main_ax,
        "arrows": True,
        "arrowstyle": "-|>",
        "arrowsize": 16,
        "edge_color": "#666666",
        "width": 1.2,
        "min_source_margin": 22,
        "min_target_margin": 22,
    }
    if straight_edges:
        nx.draw_networkx_edges(
            graph, positions, edgelist=straight_edges, **common_edge_kwargs
        )
    if curved_edges_left:
        nx.draw_networkx_edges(
            graph,
            positions,
            edgelist=curved_edges_left,
            connectionstyle="arc3,rad=0.22",
            **common_edge_kwargs,
        )
    if curved_edges_right:
        nx.draw_networkx_edges(
            graph,
            positions,
            edgelist=curved_edges_right,
            connectionstyle="arc3,rad=-0.22",
            **common_edge_kwargs,
        )

    # Nodes: rounded boxes coloured by responsibility group.
    box_w, box_h = 1.6, 0.7
    for node, (x, y) in positions.items():
        group = _NODE_GROUP.get(node, "control")
        fill = _GROUP_FILL[group]
        is_terminus = node in {"__start__", "__end__"}

        main_ax.add_patch(
            mpatches.FancyBboxPatch(
                (x - box_w / 2, y - box_h / 2),
                box_w,
                box_h,
                boxstyle="round,pad=0.05,rounding_size=0.18",
                facecolor=fill,
                edgecolor="#000000" if is_terminus else "#444444",
                linewidth=2.0 if is_terminus else 1.0,
                zorder=3,
            )
        )
        main_ax.text(
            x,
            y,
            node,
            ha="center",
            va="center",
            fontsize=10,
            fontweight="bold" if is_terminus else "normal",
            zorder=4,
        )

    # Pad the axes so boxes near the edge aren't clipped by bbox_inches.
    pad_x, pad_y = box_w * 1.2, box_h * 2
    main_ax.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
    main_ax.set_ylim(min(ys) - pad_y, max(ys) + pad_y)

    # ---- Right-side legend ----
    legend_ax.set_axis_off()
    legend_ax.set_xlim(0, 1)
    legend_ax.set_ylim(0, 1)

    cursor_y = 0.96
    legend_ax.text(
        0.0, cursor_y, "Node groups",
        fontsize=11, fontweight="bold", va="center",
    )
    cursor_y -= 0.06
    for group, fill in _GROUP_FILL.items():
        legend_ax.add_patch(
            mpatches.FancyBboxPatch(
                (0.02, cursor_y - 0.025),
                0.10,
                0.05,
                boxstyle="round,pad=0.01,rounding_size=0.015",
                facecolor=fill,
                edgecolor="#444444",
                linewidth=0.8,
                transform=legend_ax.transAxes,
            )
        )
        legend_ax.text(
            0.16, cursor_y,
            f"{_GROUP_LABEL[group]}",
            fontsize=9, va="center",
        )
        # List the nodes that belong to this group beneath the label.
        members = [n for n, g in _NODE_GROUP.items() if g == group]
        cursor_y -= 0.04
        legend_ax.text(
            0.16, cursor_y,
            ", ".join(sorted(members)),
            fontsize=8, va="center", color="#555555",
        )
        cursor_y -= 0.07

    cursor_y -= 0.02
    legend_ax.text(
        0.0, cursor_y, "Reading the graph",
        fontsize=11, fontweight="bold", va="center",
    )
    cursor_y -= 0.05
    notes = [
        "Top-down layering = BFS depth",
        "from `__start__`. Edges are",
        "drawn straight even when",
        "they form cycles (e.g.",
        "executor ⇄ tools).",
        "",
        "Source: built by calling",
        "`LangGraphAgent._build_graph`",
        "with a stub model + dummy",
        "task — no real LLM is run.",
    ]
    for line in notes:
        legend_ax.text(
            0.0, cursor_y, line,
            fontsize=8, va="center", color="#333333",
        )
        cursor_y -= 0.035

    fig.savefig(output_path, format="svg", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    compiled = _build_compiled_graph()
    drawable = compiled.get_graph()

    # Translate LangGraph's DrawableGraph into a networkx DiGraph so we
    # can reuse our standard layout/drawing helpers.
    graph = nx.DiGraph()
    for node_id in drawable.nodes:
        graph.add_node(node_id)
    for edge in drawable.edges:
        # ``drawable.edges`` items have ``.source`` and ``.target``.
        graph.add_edge(edge.source, edge.target)

    output_path = REPO_ROOT / "docs" / "agent-workflow.svg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _draw_workflow(graph, output_path)
    print(f"Wrote {output_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
