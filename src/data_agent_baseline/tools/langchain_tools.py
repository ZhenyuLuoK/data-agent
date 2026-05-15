"""LangChain-compatible wrappers around the existing tool implementations.

These wrappers preserve the underlying behavior of the legacy
:mod:`data_agent_baseline.tools.registry` handlers but expose them as
``langchain_core.tools.BaseTool`` instances so they can be bound to a
``ChatOpenAI`` model via ``bind_tools`` and executed by a LangGraph
``ToolNode``.

The task-bound parts (paths under the ``context/`` directory, the answer
table assembly) require access to the current :class:`PublicTask`. We
therefore build the tool list per task via :func:`build_langchain_tools`,
which closes over the task and also exposes a small ``ToolRunContext`` that
captures the final ``AnswerTable`` produced by the ``answer`` tool, the
DAG plan produced by the planner, and the node-completion signals emitted
by the ``mark_node_done`` tool.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Same convention as logging_setup.FILE_LOG_FORMAT consumers: keep INFO lines
# short so per-task agent.log files stay under a few hundred KB. DEBUG level
# bypasses these previews and dumps the raw payloads.
_TOOL_LOG_PREVIEW_CHARS = 240


def _tool_preview(value: Any, *, limit: int = _TOOL_LOG_PREVIEW_CHARS) -> str:
    """Single-line, length-capped repr of a tool argument or result."""
    text = value if isinstance(value, str) else repr(value)
    text = text.replace("\n", "\\n").replace("\r", "\\r")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (+{len(text) - limit} chars)"


def _summarise_tool_result(result: Any) -> str:
    """Build a high-signal summary line for a tool's return value.

    For dict-typed returns (the common case) we extract counts/sizes that
    matter most for diagnosing "tool returned nothing" failures (the very
    bug from task_180): row_count, column_mapping presence, error fields.
    """
    if isinstance(result, dict):
        keys: list[str] = []
        for key in (
            "row_count", "rows", "columns", "column_count",
            "tables", "entries", "matches", "status", "error",
        ):
            if key in result:
                value = result[key]
                if isinstance(value, list):
                    keys.append(f"{key}={len(value)}")
                else:
                    keys.append(f"{key}={_tool_preview(value, limit=80)}")
        if keys:
            return " ".join(keys)
    return _tool_preview(result)


def _wrap_tool_with_logging(
    func: Callable[..., Any], *, tool_name: str
) -> Callable[..., Any]:
    """Decorate a tool's underlying ``_run`` with INFO+DEBUG logging.

    The wrapper preserves the original signature so ``StructuredTool.from_function``
    still infers the JSON schema from type hints + ``args_schema``. We log:

    * **before**: ``tool_call_start`` — tool name, every kwarg preview
    * **after success**: ``tool_call_done`` — elapsed_ms + extracted result summary
    * **after error**: ``tool_call_error`` — elapsed_ms + exception type/message

    INFO lines are length-capped (good for grepping a 50-task benchmark);
    set ``DABENCH_LOG_LEVEL=DEBUG`` to also get the raw kwargs/result repr.
    """

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        # StructuredTool always invokes via kwargs, but defensively merge
        # positional args using the function's parameter order so the log
        # line never silently drops an argument.
        merged_args: dict[str, Any] = dict(kwargs)
        if args:
            try:
                param_names = list(func.__code__.co_varnames[: func.__code__.co_argcount])
                for index, value in enumerate(args):
                    if index < len(param_names):
                        merged_args.setdefault(param_names[index], value)
            except AttributeError:
                pass

        # INFO: pre-call line. Each arg gets its own ``key=preview`` token
        # so a `grep "tool_call_start.*tool=query_dataframe"` shows the SQL.
        if logger.isEnabledFor(logging.INFO):
            args_summary = " ".join(
                f"{key}={_tool_preview(value)}" for key, value in merged_args.items()
            ) or "(no args)"
            logger.info("tool_call_start tool=%s args=%s", tool_name, args_summary)
        # DEBUG: full kwargs repr (no truncation).
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tool_call_input_full tool=%s kwargs=%r", tool_name, merged_args
            )

        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            logger.warning(
                "tool_call_error tool=%s elapsed_ms=%.0f exc=%s: %s",
                tool_name,
                elapsed_ms,
                type(exc).__name__,
                exc,
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "tool_call_done tool=%s elapsed_ms=%.0f result=%s",
            tool_name,
            elapsed_ms,
            _summarise_tool_result(result),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tool_call_result_full tool=%s result=%r", tool_name, result
            )
        return result

    # Preserve signature/name so StructuredTool's introspection still works.
    wrapped.__name__ = func.__name__
    wrapped.__doc__ = func.__doc__
    wrapped.__wrapped__ = func  # type: ignore[attr-defined]
    return wrapped

from data_agent_baseline.benchmark.schema import AnswerTable, PublicTask
from data_agent_baseline.tools.data_inspect import inspect_data
from data_agent_baseline.tools.dataframe_query import query_dataframe
from data_agent_baseline.tools.filesystem import (
    glob_files,
    list_context_tree,
    read_csv_preview,
    read_doc_preview,
    read_json_preview,
    resolve_context_path,
)
from data_agent_baseline.tools.python_exec import execute_python_code
from data_agent_baseline.tools.sqlite import execute_read_only_sql, inspect_sqlite_schema

EXECUTE_PYTHON_TIMEOUT_SECONDS = 30
ANSWER_TOOL_NAME = "answer"
MARK_NODE_DONE_TOOL_NAME = "mark_node_done"

# Status string for a single DAG node. Kept as a Literal so dict[str, NodeStatus]
# stays JSON-serialisable for trace export without extra coercion.
NodeStatus = Literal["pending", "in_progress", "done", "failed"]

@dataclass(slots=True)
class PlanNode:
    """A single sub-task in the planner-produced DAG.

    ``suggested_tools`` is informational only — the executor is allowed to
    use any tool, but seeing the suggestion in the focused prompt helps the
    model converge faster.
    """

    id: str
    goal: str
    depends_on: list[str] = field(default_factory=list)
    suggested_tools: list[str] = field(default_factory=list)
    expected_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "depends_on": list(self.depends_on),
            "suggested_tools": list(self.suggested_tools),
            "expected_output": self.expected_output,
        }

@dataclass(slots=True)
class PlanDAG:
    """Structured plan: a DAG of :class:`PlanNode` plus the designated leaf.

    ``final_node_id`` marks the node whose completion implies the agent has
    enough information to call the ``answer`` tool. The graph treats this
    node specially: once it is ``done``, the scheduler routes to the
    reflector instead of looking for more work.
    """

    nodes: list[PlanNode]
    final_node_id: str

    def node_by_id(self, node_id: str) -> PlanNode | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "final_node_id": self.final_node_id,
        }

@dataclass(slots=True)
class DAGRuntimeState:
    """Mutable per-task DAG bookkeeping.

    Lives inside :class:`ToolRunContext` so that the ``mark_node_done`` tool
    (which runs inside ``ToolNode`` and only has access to the closure-bound
    context) can update node status without needing to mutate the LangGraph
    state directly.
    """

    dag: PlanDAG | None = None
    node_status: dict[str, NodeStatus] = field(default_factory=dict)
    node_outputs: dict[str, str] = field(default_factory=dict)
    node_attempts: dict[str, int] = field(default_factory=dict)
    current_node_id: str | None = None
    replan_count: int = 0
    # Audit log of node lifecycle events so _build_step_records can emit
    # synthetic __dag_node_start__ / __dag_node_done__ / __replan__ steps.
    events: list[dict[str, Any]] = field(default_factory=list)
    # Optional callback invoked after each record_event(); used by the web
    # layer to flush a partial trace.json so TraceWatcher can pick up
    # incremental changes while the agent is still running.
    on_event: Callable[[], None] | None = None

    def install(self, dag: PlanDAG) -> None:
        """Install (or replace) the DAG and reset per-node bookkeeping.

        Re-installation is what happens when the planner is invoked again
        via the replanner path. We deliberately reset attempts so the new
        plan starts from a clean slate.
        """

        self.dag = dag
        self.node_status = {node.id: "pending" for node in dag.nodes}
        self.node_outputs = {}
        self.node_attempts = {node.id: 0 for node in dag.nodes}
        self.current_node_id = None

    def record_event(self, kind: str, **payload: Any) -> None:
        self.events.append({"kind": kind, **payload})
        if self.on_event is not None:
            try:
                self.on_event()
            except Exception:  # noqa: BLE001 — never crash the agent
                pass

@dataclass(slots=True)
class ToolRunContext:
    """Mutable context shared by the per-task tool closures.

    The ``answer`` tool stores the final :class:`AnswerTable` here so the
    LangGraph nodes can detect termination and persist the answer alongside
    the trajectory. The ``mark_node_done`` tool stores DAG-node completion
    signals here so the scheduler can advance.
    """

    final_answer: AnswerTable | None = None
    submitted_answers: list[AnswerTable] = field(default_factory=list)
    dag_state: DAGRuntimeState = field(default_factory=DAGRuntimeState)
    # Per-node "done" signals queued by the ``mark_node_done`` tool. The
    # scheduler drains these between executor turns. Each entry is the
    # exact summary the executor submitted, so we can echo it verbatim into
    # downstream nodes' focused prompts.
    pending_node_done_signals: list[dict[str, str]] = field(default_factory=list)
    # Discriminator for *why* the LangGraph terminated. Written by the
    # routers/nodes that decide to bail out (nudge exhaustion, all-DAG-failed,
    # all-DAG-done-no-answer, replan-budget-exhausted, …) and read back by
    # ``LangGraphAgent.run`` so the per-task ``failure_reason`` is no longer a
    # one-size-fits-all "step budget" placeholder.
    exit_reason: str | None = None

# ---------- Pydantic argument schemas (drives JSON Schema for tool calling) ----


class ListContextArgs(BaseModel):
    max_depth: int = Field(
        default=4,
        description="Maximum directory depth to walk while listing context files.",
    )


class GlobFilesArgs(BaseModel):
    pattern: str = Field(
        description=(
            "Path glob anchored at context/, using Python Path.glob syntax. "
            "Use ** for recursive matches. Examples: '*.csv', 'db/*.sqlite', "
            "'**/*.json'. Must be relative — never start with '/'."
        )
    )
    sort_by: str = Field(
        default="name",
        description=(
            "Sort key: 'name' (lexicographic), 'size' (small to large; dirs last), "
            "or 'mtime' (oldest first). Sort is always ascending — for "
            "'biggest file', sort by size and read the last entry."
        ),
    )
    limit: int = Field(default=50, description="Max number of matches to return.")


class QueryDataframeArgs(BaseModel):
    path: str = Field(
        description=(
            "Path of a CSV / TSV / JSON / JSONL / Parquet file relative to "
            "the task context root. For sqlite/db files use execute_context_sql."
        )
    )
    sql: str = Field(
        description=(
            "Read-only SQL (SELECT/WITH/PRAGMA) executed against the loaded "
            "table aliased as `df` (override via `table_alias`). Column names "
            "are auto-sanitised — see `column_mapping` in the response when "
            "your query fails to identify a column."
        )
    )
    table_alias: str = Field(
        default="df",
        description="Alias the loaded file is registered under in SQL. Default 'df'.",
    )
    limit: int = Field(default=200, description="Max rows returned.")


class InspectDataArgs(BaseModel):
    path: str = Field(
        description=(
            "Path of a CSV / TSV / JSON / JSONL / sqlite file relative to the "
            "task context root. For sqlite/db, also pass `table`."
        )
    )
    table: str | None = Field(
        default=None,
        description=(
            "Required for sqlite/db inputs: the table to profile. Ignored "
            "for csv/json/jsonl. Use inspect_sqlite_schema first if you "
            "don't know the table names."
        ),
    )
    sample_size: int = Field(
        default=5,
        description="Number of sample values to return per column.",
    )


class ReadCsvArgs(BaseModel):
    path: str = Field(description="Path of the CSV file relative to the task context root.")
    max_rows: int = Field(default=50, description="Maximum number of data rows to preview.")


class ReadJsonArgs(BaseModel):
    path: str = Field(description="Path of the JSON file relative to the task context root.")
    max_chars: int = Field(default=4000, description="Maximum characters of preview to return.")


class ReadDocArgs(BaseModel):
    path: str = Field(
        description="Path of the text-like document relative to the task context root."
    )
    max_chars: int = Field(
        default=16000,
        description=(
            "Maximum characters to return. Documents <= 32KB are returned in "
            "full regardless. Only relevant for very long docs (slice mode) "
            "or as the total cap on grep results."
        ),
    )
    offset: int = Field(
        default=0,
        description=(
            "0-based starting character index for slice mode. Leave at 0 to "
            "let the tool decide (full vs. slice). To continue reading a "
            "truncated slice, pass the `next_offset` value returned previously. "
            "Ignored in grep mode."
        ),
    )
    grep: str | None = Field(
        default=None,
        description=(
            "Optional regex. When set, switches to grep mode: returns up to "
            "`max_matches` snippets of +-`context_chars` around each match, "
            "joined by '\\n---\\n'. Far cheaper than paginating when you "
            "know a keyword (publisher name, patient id, column header, etc.). "
            "Patterns are Python `re` syntax — escape literal regex metachars."
        ),
    )
    max_matches: int = Field(
        default=20,
        description="Cap on the number of grep matches returned. Ignored when grep is unset.",
    )
    context_chars: int = Field(
        default=400,
        description=(
            "Characters of surrounding context to include before and after "
            "each grep match. Ignored when grep is unset."
        ),
    )


class InspectSqliteSchemaArgs(BaseModel):
    path: str = Field(
        description="Path of the sqlite/db file relative to the task context root."
    )


class ExecuteContextSqlArgs(BaseModel):
    path: str = Field(
        description="Path of the sqlite/db file relative to the task context root."
    )
    sql: str = Field(description="Read-only SQL statement (SELECT/WITH/PRAGMA).")
    limit: int = Field(default=200, description="Maximum number of rows to return.")


class ExecutePythonArgs(BaseModel):
    code: str = Field(
        description=(
            "Python source to execute. The working directory is the task context "
            "directory. Captured stdout is returned as `output`."
        )
    )


class AnswerArgs(BaseModel):
    columns: list[str] = Field(
        description=(
            "Non-empty list of column names for the answer table. "
            "Submit the MINIMAL column set that answers the question — the "
            "grader applies a redundancy penalty (Score = Recall - 0.5 * "
            "extra_columns / predicted_columns), so every column NOT asked "
            "for in the question subtracts from the score. Quick rules: "
            "'how many / average / max / percentage / which had the most' → "
            "1 column; 'list names' → 1 column; 'for each Y, the X' → 2 "
            "columns (Y, X). Do NOT pad with id / name / description / "
            "supporting fields unless the question literally asks for them."
        )
    )
    rows: list[list[Any]] = Field(
        description=(
            "List of rows, each row a list whose length matches `columns`. "
            "Include only the rows the question asks for (e.g. 'top 5' → 5 "
            "rows; 'the winner' → 1 row); do not append extra rows for context. "
            "Format each cell value before submitting: null/missing → empty "
            "string ''; numbers → str(raw_value) WITHOUT rounding or "
            "zero-padding (the grader is byte-level: gold "
            "'52.17391304347826' will NOT match '52.17'; do NOT call "
            "round(), '{:.2f}'.format(), or Decimal.quantize(); the only "
            "exception is bare integer counts where the gold is plainly "
            "integer-typed → '4', not '4.00'); dates → ISO 'YYYY-MM-DD' "
            "('2024-3-1' → '2024-03-01'); datetimes with tz → UTC suffix 'Z'; "
            "strings → strip leading/trailing whitespace and \\r\\n while "
            "PRESERVING source casing (grader is case-sensitive: 'East Asia' "
            "≠ 'east asia'). Convert pandas/numpy values to plain Python "
            "str first — never leave numpy.nan, pandas.NaT, numpy.int64 "
            "etc. in rows. "
            "NEVER include error strings as cell values — do NOT submit "
            "'undefined', 'undefined (division by zero)', 'division by "
            "zero', 'error', '<error>', 'NaN' (as text), '#DIV/0!', or "
            "Python tracebacks. If a computation errored for a row, the "
            "answer for that row is genuinely missing — emit empty string "
            "'' for that cell. If the question expects a single definite "
            "value and your only candidate is an error string, rethink the "
            "calculation and call the relevant tools again instead of "
            "submitting the error text verbatim."
        )
    )

class MarkNodeDoneArgs(BaseModel):
    node_id: str = Field(
        description=(
            "The id of the DAG node that was just completed. Must match the "
            "id shown in the focused prompt (e.g. 'n1', 'n2'). Calling this "
            "for any other node id will fail."
        )
    )
    output_summary: str = Field(
        description=(
            "Concise (1-3 sentences) factual summary of what the node "
            "produced (e.g. 'Hero with id=1 is 3-D Man.', 'Mapped 167 power "
            "ids to power names.'). Downstream nodes will see this verbatim "
            "as their upstream context, so be precise and self-contained. "
            "Do NOT include code, full table dumps, or reasoning."
        )
    )


# ---------- Tool factories --------------------------------------------------


def _build_list_context_tool(task: PublicTask) -> BaseTool:
    def _run(max_depth: int = 4) -> dict[str, Any]:
        return list_context_tree(task, max_depth=max_depth)

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="list_context"),
        name="list_context",
        description="List files and directories available under the task context directory.",
        args_schema=ListContextArgs,
    )


def _build_read_csv_tool(task: PublicTask) -> BaseTool:
    def _run(path: str, max_rows: int = 50) -> dict[str, Any]:
        return read_csv_preview(task, path, max_rows=max_rows)

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="read_csv"),
        name="read_csv",
        description="Read a preview of a CSV file inside the task context directory.",
        args_schema=ReadCsvArgs,
    )


def _build_read_json_tool(task: PublicTask) -> BaseTool:
    def _run(path: str, max_chars: int = 4000) -> dict[str, Any]:
        return read_json_preview(task, path, max_chars=max_chars)

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="read_json"),
        name="read_json",
        description="Read a preview of a JSON file inside the task context directory.",
        args_schema=ReadJsonArgs,
    )


def _build_read_doc_tool(task: PublicTask) -> BaseTool:
    def _run(
        path: str,
        max_chars: int = 16000,
        offset: int = 0,
        grep: str | None = None,
        max_matches: int = 20,
        context_chars: int = 400,
    ) -> dict[str, Any]:
        return read_doc_preview(
            task,
            path,
            max_chars=max_chars,
            offset=offset,
            grep=grep,
            max_matches=max_matches,
            context_chars=context_chars,
        )

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="read_doc"),
        name="read_doc",
        description=(
            "Read a text-like document inside the task context directory. The "
            "response's `mode` field indicates which path was taken:\n"
            "  - full : doc <= 32KB OR slice covers everything; returns whole text.\n"
            "  - slice: paginated; pass `offset=next_offset` to continue.\n"
            "  - grep : activated by passing `grep=<regex>`; returns up to "
            "`max_matches` windows of +-`context_chars` around each hit, joined "
            "by '\\n---\\n'. Prefer grep over pagination when you know a "
            "keyword (name, id, column header). Pattern is Python `re` syntax."
        ),
        args_schema=ReadDocArgs,
    )


def _build_glob_files_tool(task: PublicTask) -> BaseTool:
    def _run(pattern: str, sort_by: str = "name", limit: int = 50) -> dict[str, Any]:
        return glob_files(task, pattern, sort_by=sort_by, limit=limit)

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="glob_files"),
        name="glob_files",
        description=(
            "List files under the task context directory matching a glob "
            "pattern (e.g. '*.csv', 'db/*.sqlite', '**/*.json'). Cheaper "
            "than `list_context` when you only want files of a certain "
            "kind, and avoids dropping into execute_python just to call "
            "os.listdir / glob.glob. Sort by name | size | mtime."
        ),
        args_schema=GlobFilesArgs,
    )


def _build_query_dataframe_tool(task: PublicTask) -> BaseTool:
    def _run(
        path: str,
        sql: str,
        table_alias: str = "df",
        limit: int = 200,
    ) -> dict[str, Any]:
        absolute_path = resolve_context_path(task, path)
        return query_dataframe(
            absolute_path, sql=sql, table_alias=table_alias, limit=limit
        )

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="query_dataframe"),
        name="query_dataframe",
        description=(
            "Run a read-only SQL query over a CSV / TSV / JSON / JSONL / "
            "Parquet file in one call — no need to read_csv first and then "
            "drop into execute_python to load it into pandas. The file is "
            "loaded into an in-memory sqlite table aliased `df` (override "
            "via `table_alias`). When your query fails to find a column, "
            "check `column_mapping` in the response: column names with "
            "spaces/dashes are auto-sanitised. For sqlite/db files use "
            "`execute_context_sql` instead."
        ),
        args_schema=QueryDataframeArgs,
    )


def _build_inspect_data_tool(task: PublicTask) -> BaseTool:
    def _run(
        path: str,
        table: str | None = None,
        sample_size: int = 5,
    ) -> dict[str, Any]:
        absolute_path = resolve_context_path(task, path)
        return inspect_data(absolute_path, table=table, sample_size=sample_size)

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="inspect_data"),
        name="inspect_data",
        description=(
            "One-shot column profile of a CSV / TSV / JSON / JSONL / sqlite "
            "table: per-column dtype, null_count, unique_count, sample_values, "
            "and min/max for numeric columns. Replaces the common pattern "
            "`read_csv` -> `execute_python(df.head(); df.dtypes; df.shape)` "
            "with a single call. For sqlite/db inputs, also pass `table`."
        ),
        args_schema=InspectDataArgs,
    )


def _build_inspect_sqlite_schema_tool(task: PublicTask) -> BaseTool:
    def _run(path: str) -> dict[str, Any]:
        absolute_path = resolve_context_path(task, path)
        return inspect_sqlite_schema(absolute_path)

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="inspect_sqlite_schema"),
        name="inspect_sqlite_schema",
        description="Inspect tables and columns in a sqlite/db file inside the task context.",
        args_schema=InspectSqliteSchemaArgs,
    )


def _build_execute_context_sql_tool(task: PublicTask) -> BaseTool:
    def _run(path: str, sql: str, limit: int = 200) -> dict[str, Any]:
        absolute_path = resolve_context_path(task, path)
        return execute_read_only_sql(absolute_path, sql, limit=limit)

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="execute_context_sql"),
        name="execute_context_sql",
        description="Run a read-only SQL query against a sqlite/db file inside the task context.",
        args_schema=ExecuteContextSqlArgs,
    )


def _build_execute_python_tool(task: PublicTask) -> BaseTool:
    timeout_description = (
        "Execute arbitrary Python code with the task context directory as the "
        "working directory. The tool returns the captured stdout as `output`. "
        f"Execution timeout is fixed at {EXECUTE_PYTHON_TIMEOUT_SECONDS} seconds."
    )

    def _run(code: str) -> dict[str, Any]:
        return execute_python_code(
            context_root=task.context_dir,
            code=code,
            timeout_seconds=EXECUTE_PYTHON_TIMEOUT_SECONDS,
        )

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name="execute_python"),
        name="execute_python",
        description=timeout_description,
        args_schema=ExecutePythonArgs,
    )


def _build_mark_node_done_tool(context: ToolRunContext) -> BaseTool:
    """Build the ``mark_node_done`` tool.

    Validation rules (raise ValueError so ToolNode surfaces them as
    ``ToolMessage(status="error")`` and the executor can self-correct):

    * The DAG must already be installed (planner must have run).
    * ``node_id`` must exist in the DAG.
    * ``node_id`` must equal the currently in-progress node — completing
      out-of-order nodes is forbidden under strict mode.
    * ``output_summary`` must be a non-empty string.

    On success: marks the node ``done``, stores the summary, and queues a
    "done signal" the scheduler will drain on the next routing step.
    """

    def _run(node_id: str, output_summary: str) -> dict[str, Any]:
        dag_state = context.dag_state
        dag = dag_state.dag
        if dag is None:
            raise ValueError(
                "mark_node_done called before the planner produced a DAG."
            )
        if dag.node_by_id(node_id) is None:
            raise ValueError(
                f"Unknown node_id={node_id!r}; valid ids are: "
                f"{[n.id for n in dag.nodes]}"
            )
        if dag_state.current_node_id is not None and node_id != dag_state.current_node_id:
            raise ValueError(
                f"You may only mark the currently in-progress node as done. "
                f"Current node is {dag_state.current_node_id!r}, you tried "
                f"{node_id!r}."
            )
        if not isinstance(output_summary, str) or not output_summary.strip():
            raise ValueError("output_summary must be a non-empty string.")

        summary_text = output_summary.strip()
        dag_state.node_status[node_id] = "done"
        dag_state.node_outputs[node_id] = summary_text
        dag_state.record_event(
            "node_done", node_id=node_id, summary=summary_text
        )
        context.pending_node_done_signals.append(
            {"node_id": node_id, "summary": summary_text}
        )
        # Clear current_node_id so the scheduler is forced to pick the next
        # ready node (or route to reflector if the final node just completed).
        dag_state.current_node_id = None

        remaining = [
            nid for nid, status in dag_state.node_status.items() if status != "done"
        ]
        return {
            "status": "node_done",
            "node_id": node_id,
            "remaining_nodes": remaining,
        }

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name=MARK_NODE_DONE_TOOL_NAME),
        name=MARK_NODE_DONE_TOOL_NAME,
        description=(
            "Signal that the currently focused DAG node is complete. You MUST "
            "call this exactly once per node, after gathering all information "
            "the node's goal requires. Provide a concise factual summary in "
            "`output_summary` — downstream nodes will see it verbatim. Do NOT "
            "call this for the final node; call `answer` instead."
        ),
        args_schema=MarkNodeDoneArgs,
    )

def _build_answer_tool(context: ToolRunContext) -> BaseTool:
    def _run(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
        if not isinstance(columns, list) or not columns or not all(
            isinstance(item, str) for item in columns
        ):
            raise ValueError("answer.columns must be a non-empty list of strings.")
        if not isinstance(rows, list):
            raise ValueError("answer.rows must be a list.")

        normalized_rows: list[list[Any]] = []
        for row in rows:
            if not isinstance(row, list):
                raise ValueError("Each answer row must be a list.")
            if len(row) != len(columns):
                raise ValueError("Each answer row must match the number of columns.")
            normalized_rows.append(list(row))

        answer_table = AnswerTable(columns=list(columns), rows=normalized_rows)
        context.final_answer = answer_table
        context.submitted_answers.append(answer_table)
        return {
            "status": "submitted",
            "column_count": len(columns),
            "row_count": len(normalized_rows),
        }

    return StructuredTool.from_function(
        func=_wrap_tool_with_logging(_run, tool_name=ANSWER_TOOL_NAME),
        name=ANSWER_TOOL_NAME,
        description=(
            "Submit the final answer table. This is the only valid terminating action. "
            "The graph will halt after this tool succeeds. "
            "IMPORTANT: submit only the columns and rows the question asks "
            "for — extra columns are penalised by the grader."
        ),
        args_schema=AnswerArgs,
    )


def build_langchain_tools(
    task: PublicTask, context: ToolRunContext
) -> list[BaseTool]:
    """Return the LangChain tool list bound to ``task`` and ``context``.

    The order roughly matches the legacy registry; LangGraph and the model
    do not depend on the order, but a stable ordering keeps the system
    prompt and tool listings deterministic.
    """

    return [
        _build_list_context_tool(task),
        _build_glob_files_tool(task),
        _build_read_csv_tool(task),
        _build_read_json_tool(task),
        _build_read_doc_tool(task),
        _build_inspect_sqlite_schema_tool(task),
        _build_inspect_data_tool(task),
        _build_execute_context_sql_tool(task),
        _build_query_dataframe_tool(task),
        _build_execute_python_tool(task),
        _build_mark_node_done_tool(context),
        _build_answer_tool(context),
    ]
