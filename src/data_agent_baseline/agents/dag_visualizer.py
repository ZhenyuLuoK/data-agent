"""Minimal DAG visualizer — render the planner DAG to a single SVG.

Design intent (deliberately tiny):

* **One file output**: ``<output_dir>/dag.svg``, overwritten on each call.
* **Node label inside the circle = node_id only** (e.g. ``n1``); goals
  are too long to fit on a node without overlapping neighbours.
* **Right-side legend** lists ``node_id → goal`` for every node so the
  figure is self-contained — readers don't have to grep ``trace.json``
  to know what each node does.
* **Status encoded by fill colour** + a thicker border for the final
  node. A small status legend sits at the bottom of the goal legend.
* **Layered top-to-bottom layout** with explicit pixel-space coordinates
  (not ``multipartite_layout``'s normalized output, which causes node
  overlap when boxes are larger than inter-node spacing).

Rendering uses ``networkx`` for the graph object + ``matplotlib`` for
drawing — both are declared dependencies in ``pyproject.toml``, so the
visualizer ships with the project's venv / Docker image without any
system-level packages. Failures are swallowed so visualization side
effects can never crash an in-flight task.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend; safe in subprocess + Docker

import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402

from data_agent_baseline.tools.langchain_tools import DAGRuntimeState, PlanDAG

# Status → fill colour. Border + text are constant across statuses
# (the figure is small enough that a single accent dimension is enough).
_FILL_BY_STATUS: dict[str, str] = {
    "pending": "#e0e0e0",
    "in_progress": "#64b5f6",
    "done": "#81c784",
    "failed": "#e57373",
}

# Geometry constants (matplotlib data units). Tuned so that even with
# many siblings on the same layer, node circles stay well separated.
_NODE_RADIUS = 0.35
_LAYER_DX = 1.6  # horizontal distance between siblings on the same layer
_LAYER_DY = 1.4  # vertical distance between layers

# Legend rendering. The right-side panel that lists "node_id → goal"
# for every node, plus a compact colour key for status at the bottom.
_LEGEND_GOAL_WRAP_CHARS = 60   # soft-wrap width for goal text in legend
_LEGEND_LINE_HEIGHT = 0.32     # vertical spacing between legend entries
_LEGEND_FONT_SIZE = 9
_LEGEND_TITLE_FONT_SIZE = 10


def _layer_of_each_node(dag: PlanDAG) -> dict[str, int]:
    """Layer = longest dependency depth from any root. Pure DAG required."""

    layer: dict[str, int] = {}
    for node in dag.nodes:
        layer[node.id] = (
            0 if not node.depends_on else max(layer[d] for d in node.depends_on) + 1
        )
    return layer


def _layout(dag: PlanDAG) -> dict[str, tuple[float, float]]:
    """Place nodes on a fixed pixel-space grid: layer = row, sibling = column.

    Bypasses ``nx.multipartite_layout`` which returns normalized
    coordinates that ignore actual node sizes (causing overlap).
    """

    layer_of = _layer_of_each_node(dag)
    nodes_per_layer: dict[int, list[str]] = {}
    for nid, layer in layer_of.items():
        nodes_per_layer.setdefault(layer, []).append(nid)

    positions: dict[str, tuple[float, float]] = {}
    for layer, node_ids in nodes_per_layer.items():
        # Center the layer's nodes around x=0.
        offset = (len(node_ids) - 1) / 2.0
        for col, nid in enumerate(node_ids):
            x = (col - offset) * _LAYER_DX
            y = -layer * _LAYER_DY  # negate so layer 0 ends up on top
            positions[nid] = (x, y)
    return positions


def _wrap(text: str, width: int) -> list[str]:
    """Soft-wrap by words, returning the lines as a list (no newline join)."""

    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_legend(
    *,
    legend_ax: plt.Axes,
    dag: PlanDAG,
    dag_state: DAGRuntimeState,
) -> None:
    """Populate the right-side legend axis with node→goal entries + status key.

    Layout (top-down):
        [Title: "Nodes"]
        ● n1   <wrapped goal line 1>
               <wrapped goal line 2>
        ● n2   <goal>
        ...
        [Title: "Status"]
        ● pending  ● in_progress  ● done  ● failed
    """

    legend_ax.set_axis_off()
    legend_ax.set_xlim(0, 1)
    # Y axis grows downward visually: we manually track ``cursor_y`` from
    # the top (1.0) toward the bottom (0.0).
    legend_ax.set_ylim(0, 1)

    # Pre-compute total content height in "line units" so we can map to [0, 1].
    line_units = 1.0  # 1 line for "Nodes" title
    wrapped_goals: list[tuple[str, list[str]]] = []
    for node in dag.nodes:
        lines = _wrap(node.goal or "(no goal)", _LEGEND_GOAL_WRAP_CHARS)
        wrapped_goals.append((node.id, lines))
        line_units += max(1, len(lines))
    line_units += 1.5  # gap before status legend
    line_units += 1.0  # "Status" title
    line_units += 1.0  # status colour row

    unit = 1.0 / max(line_units, 1.0) * 0.95  # leave a 5% top/bottom margin
    cursor_y = 1.0 - unit * 0.5  # start a half-line below the very top

    # --- "Nodes" title ---
    legend_ax.text(
        0.0,
        cursor_y,
        "Nodes",
        fontsize=_LEGEND_TITLE_FONT_SIZE,
        fontweight="bold",
        va="center",
    )
    cursor_y -= unit * 1.2

    # --- One row per DAG node ---
    for node_id, goal_lines in wrapped_goals:
        status = dag_state.node_status.get(node_id, "pending")
        fill = _FILL_BY_STATUS.get(status, _FILL_BY_STATUS["pending"])
        is_final = node_id == dag.final_node_id

        # Coloured circle marker, aligned with the first goal line.
        legend_ax.scatter(
            [0.02],
            [cursor_y],
            s=140,
            facecolor=fill,
            edgecolor="#000000" if is_final else "#444444",
            linewidth=2.0 if is_final else 0.8,
            zorder=3,
        )
        # node_id label.
        prefix = f"★{node_id}" if is_final else node_id
        legend_ax.text(
            0.06,
            cursor_y,
            prefix,
            fontsize=_LEGEND_FONT_SIZE,
            fontweight="bold",
            va="center",
        )
        # First goal line on the same row as the circle/id.
        if goal_lines:
            legend_ax.text(
                0.18,
                cursor_y,
                goal_lines[0],
                fontsize=_LEGEND_FONT_SIZE,
                va="center",
            )
        # Subsequent wrapped lines indented under the goal column.
        for extra_line in goal_lines[1:]:
            cursor_y -= unit
            legend_ax.text(
                0.18,
                cursor_y,
                extra_line,
                fontsize=_LEGEND_FONT_SIZE,
                va="center",
                color="#444444",
            )
        cursor_y -= unit * 1.2

    # --- Gap, then status legend ---
    cursor_y -= unit * 0.6
    legend_ax.text(
        0.0,
        cursor_y,
        "Status",
        fontsize=_LEGEND_TITLE_FONT_SIZE,
        fontweight="bold",
        va="center",
    )
    cursor_y -= unit * 1.2

    # Single row with four colour swatches.
    swatch_x = 0.02
    text_x_offset = 0.05
    spacing = 0.24
    for i, (status, fill) in enumerate(_FILL_BY_STATUS.items()):
        legend_ax.add_patch(
            mpatches.Circle(
                (swatch_x + i * spacing, cursor_y),
                0.018,
                facecolor=fill,
                edgecolor="#444444",
                linewidth=0.8,
                transform=legend_ax.transAxes,
            )
        )
        legend_ax.text(
            swatch_x + i * spacing + text_x_offset,
            cursor_y,
            status,
            fontsize=_LEGEND_FONT_SIZE - 1,
            va="center",
        )


def render_dag(
    *,
    output_dir: Path,
    dag: PlanDAG,
    dag_state: DAGRuntimeState,
    title: str | None = None,
) -> Path | None:
    """Render ``dag`` (coloured by ``dag_state``) to ``<output_dir>/dag.svg``.

    Returns the written path on success, ``None`` on failure (logged once
    to stderr). Always overwrites; no versioned snapshots.
    """

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        graph = nx.DiGraph()
        graph.add_nodes_from(node.id for node in dag.nodes)
        graph.add_edges_from(
            (dep, node.id) for node in dag.nodes for dep in node.depends_on
        )

        positions = _layout(dag)

        # Figure size scales with the data-space extent so the SVG never
        # clips nodes. Width gets an extra +6 inches reserved for the
        # right-side legend, and height grows with node count so wrapped
        # goals always fit.
        xs = [x for x, _ in positions.values()]
        ys = [y for _, y in positions.values()]
        x_span = (max(xs) - min(xs)) if xs else 0
        y_span = (max(ys) - min(ys)) if ys else 0
        graph_w = max(4.0, x_span * 0.9 + 2)
        legend_w = 6.0
        fig_w = graph_w + legend_w
        # Height has to accommodate either the graph or the legend,
        # whichever is taller. Each legend entry takes ~0.45 inches.
        legend_h_est = 1.5 + 0.55 * len(dag.nodes) + 1.5
        fig_h = max(3.0, y_span * 0.9 + 2, legend_h_est)

        # Two-axis layout: left = graph, right = legend.
        fig = plt.figure(figsize=(fig_w, fig_h))
        graph_ax = fig.add_axes(
            (0.02, 0.02, graph_w / fig_w - 0.04, 0.96)
        )
        legend_ax = fig.add_axes(
            (graph_w / fig_w + 0.01, 0.02, legend_w / fig_w - 0.03, 0.96)
        )

        if title:
            graph_ax.set_title(title, fontsize=11)
        graph_ax.set_axis_off()
        graph_ax.set_aspect("equal")

        # Edges first so node circles overlay arrowheads cleanly.
        nx.draw_networkx_edges(
            graph,
            positions,
            ax=graph_ax,
            arrows=True,
            arrowstyle="-|>",
            arrowsize=18,
            edge_color="#666666",
            width=1.4,
            min_source_margin=14,
            min_target_margin=14,
        )

        # Nodes: one circle each, filled by status, ★-marked + thick
        # border for the final node. Label inside circle = node_id only.
        for node in dag.nodes:
            x, y = positions[node.id]
            status = dag_state.node_status.get(node.id, "pending")
            fill = _FILL_BY_STATUS.get(status, _FILL_BY_STATUS["pending"])
            is_final = node.id == dag.final_node_id

            graph_ax.add_patch(
                plt.Circle(
                    (x, y),
                    _NODE_RADIUS,
                    facecolor=fill,
                    edgecolor="#000000" if is_final else "#444444",
                    linewidth=2.5 if is_final else 1.2,
                    zorder=3,
                )
            )
            label = f"★{node.id}" if is_final else node.id
            graph_ax.text(
                x,
                y,
                label,
                ha="center",
                va="center",
                fontsize=10,
                fontweight="bold" if is_final else "normal",
                zorder=4,
            )

        # Pad graph axes so circles near the boundary aren't clipped.
        graph_ax.set_xlim(min(xs) - _LAYER_DX, max(xs) + _LAYER_DX)
        graph_ax.set_ylim(min(ys) - _LAYER_DY, max(ys) + _LAYER_DY)

        # Right-side legend: node_id → goal + status colour key.
        _draw_legend(legend_ax=legend_ax, dag=dag, dag_state=dag_state)

        out_path = output_dir / "dag.svg"
        fig.savefig(out_path, format="svg", bbox_inches="tight")
        plt.close(fig)
        return out_path
    except Exception as exc:  # noqa: BLE001
        print(f"[dag_visualizer] render failed: {exc}", file=sys.stderr)
        try:
            plt.close("all")
        except Exception:  # noqa: BLE001
            pass
        return None
