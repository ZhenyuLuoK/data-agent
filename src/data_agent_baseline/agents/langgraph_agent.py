"""LangGraph-based multi-node agent for the DABench baseline.

Pipeline (DAG-driven, strict mode):

    planner ──▶ dag_scheduler ──▶ executor ──▶ tools ──┐
                     ▲   ▲             │ ▲              │
                     │   │             │ └──── nudge ◀──┤ (executor empty)
                     │   │             │                │
                     │   │             │     (mark_node_done) ──┐
                     │   │             │                        │
                     │   └────────────────────────────────── ◀──┘
                     │                  │
                     │                  └─── (answer) ──▶ reflector ──▶ finalize ──▶ END
                     │                                       │
                     │                                       └─ (RETRY) ─▶ executor
                     │
                     └──────  replanner  ◀── (scheduler stuck / node failed)
                                  │
                                  └─ replan_count ≥ max ─▶ finalize

* ``planner``          — Produces a structured DAG plan (JSON) at the start.
                         Each node is a sub-task with goal / depends_on /
                         expected_output. Runs exactly once per fresh plan.
* ``dag_scheduler``    — Picks the next ready DAG node (deps satisfied, status
                         pending) and seeds the executor with a focused
                         prompt: only the current goal + upstream summaries.
                         When the final node is done, routes to reflector.
                         When stuck (no ready node, not all done), routes to
                         replanner.
* ``executor``         — A ChatOpenAI bound to the LangChain-wrapped tools.
                         Calls inspection tools, then ``mark_node_done`` to
                         advance, or ``answer`` for the final submission.
* ``tools`` (ToolNode) — Standard LangGraph tool executor.
* ``reflector``        — Inspects the final answer; emits OK or RETRY.
* ``replanner``        — Re-invokes the planner with a failure context;
                         resets DAG state. Capped by ``max_replans``.
* ``nudge``            — Re-prompts the executor when it returns an
                         empty/no-op turn. Capped by ``max_idle_nudges``.
* ``finalize``         — No-op leaf; presence triggers END.

The conversation is kept in ``state["messages"]`` (LangGraph's standard
``add_messages`` reducer); auxiliary fields track plan text, reflection
budget, idle nudges, and replan count. DAG bookkeeping lives in the
shared :class:`ToolRunContext` because the ``mark_node_done`` tool runs
inside ``ToolNode`` and needs a writable side-channel.
"""

from __future__ import annotations

import json
import logging
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict, TypeVar

logger = logging.getLogger(__name__)

# ---- Exit-reason constants ------------------------------------------------
# These are written to ``tool_run_context.exit_reason`` from inside the
# graph nodes when they decide to stop. ``LangGraphAgent.run`` reads this
# field after ``compiled_graph.invoke`` returns so that the per-task
# trace.json carries an actionable failure_reason instead of the legacy
# misleading "Agent did not submit an answer within the step budget."
# tag, which fired for at least four distinct termination paths.
EXIT_NUDGE_EXHAUSTED = "nudge_exhausted"
EXIT_DAG_ALL_FAILED = "dag_all_failed"
EXIT_DAG_DONE_NO_ANSWER = "dag_done_no_answer"
EXIT_STEP_BUDGET_EXHAUSTED = "step_budget_exhausted"
EXIT_REPLAN_BUDGET_EXHAUSTED = "replan_budget_exhausted"

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from data_agent_baseline.agents.dag_visualizer import render_dag
from data_agent_baseline.agents.runtime import AgentRunResult, StepRecord
from data_agent_baseline.benchmark.schema import AnswerTable, PublicTask
from data_agent_baseline.tools.filesystem import list_context_tree
from data_agent_baseline.tools.langchain_tools import (
    ANSWER_TOOL_NAME,
    MARK_NODE_DONE_TOOL_NAME,
    PlanDAG,
    PlanNode,
    ToolRunContext,
    build_langchain_tools,
)
from data_agent_baseline.tools.sqlite import inspect_sqlite_schema


# --------- Configuration ---------------------------------------------------

@dataclass(frozen=True, slots=True)
class LangGraphAgentConfig:
    """Runtime configuration for :class:`LangGraphAgent`.

    ``max_steps`` is interpreted as the **graph recursion budget**, matching
    the legacy ReAct ``max_steps`` semantics for the YAML config. Each LLM
    invocation, tool execution, planner run, and reflector run consumes one
    unit. We add a safety margin internally so that the recursion limit
    aligns with the user's intuition of "model turns".

    ``max_idle_nudges`` caps how many times we re-prompt the executor when it
    returns a message with neither ``tool_calls`` nor a final answer. Some
    OpenAI-compatible models (notably Qwen via DashScope's compatible mode)
    occasionally emit empty assistant turns mid-conversation; a single nudge
    usually unsticks them.

    ``max_replans`` caps how many times the planner is invoked. The first
    invocation is the initial plan; each additional call is a "replan" that
    reacts to a stuck DAG (no ready node, not all done) or a node that
    exhausted ``max_node_attempts``. ``max_replans = 0`` disables replanning.

    ``max_node_attempts`` is the per-node soft-failure threshold. When the
    executor blows past ``max_steps_per_node`` LLM turns inside a single
    DAG node without calling ``mark_node_done``, that counts as one attempt;
    when attempts reach the cap, the scheduler marks the node failed and
    routes to the replanner.

    ``max_steps_per_node`` bounds executor LLM turns spent on a single DAG
    node so the agent cannot wedge inside one sub-task forever. Exceeding it
    triggers the failed-attempt path described above.
    """

    # NOTE: ``max_steps`` is intentionally hard-coded here and ignored from
    # YAML — see ``runner.py`` where the YAML override has been removed.
    #
    # 历史教训：
    # 1) 旧值 max_steps_per_node × max_node_attempts × max_replans = 50×5×5 = 1250
    #    次 LLM 调用，配合 60s timeout 单 task 最坏吃满 task_timeout_seconds。
    # 2) 上一版收到 16×2×2 = 64 次后，仍出现 4 个 task 撞 1800s 死亡，根因是
    #    单次 LLM 调用因 retry 机制最坏放大到 ~95s（详见 _RETRY_PROFILES 注释）。
    #
    # 现在的预算（与 retry 改造后的数值匹配）：
    #   - max_steps_per_node × max_node_attempts × max_replans = 12×2×3 = 72 次 executor 调用
    #   - 加上 1 + max_replans = 3 次 planner 调用
    #   - 2026-05 更新：每个 LLM 调用点都开了 max_attempts=5 的 retry（含
    #     Timeout），单次调用最坏耗时 ≈ 30s + Σ(1+2+4+8+16) ≈ 30s + 31s
    #     退避 + 5×30s 重新调用 ≈ 211s。这和 task_timeout_seconds 的关系
    #     交给 runner 层的硬超时兜底（防止 retry 串成 task 永远不结束）。
    #   - 总最坏 ≈ 72×211 + 3×211 ≈ 4h+，但 retry 只在真异常时触发，
    #     正常路径仍是 72×~5s + 3×~10s ≈ 6min。
    #
    # max_replans 从 2 → 3：让外层多 replan 一次补偿。
    # max_steps_per_node 从 16 → 12：进一步压缩单节点失控时的爆炸面积。
    # recursion limit 下游 = max(8, 72*6) = 432 仍有 headroom。
    max_steps: int = 500
    max_reflections: int = 2
    max_idle_nudges: int = 30
    max_replans: int = 2
    max_node_attempts: int = 5
    max_steps_per_node: int = 200

# --------- Prompts ---------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """You are the **planner** for a data analysis agent.

You will receive a single question, the names of inspection tools the executor
can call, AND a **dataset profile** that lists the actual files under the task's
`context/` directory (with sqlite tables and json/csv heads where applicable).

**Let's think step by step before producing the plan.** Before emitting JSON,
silently work through this chain of thought (do NOT include it in the final output):
  1. Restate the question in one sentence and identify the entities / metrics /
     filters / aggregations it asks about.
  2. Scan the dataset profile and list which files are relevant, citing each
     file by its EXACT relative path from the profile.
  3. Sketch the data flow: which files feed which join / filter / aggregation,
     and what the final answer's shape (columns, row count) should look like.
  4. Decide the smallest DAG (2-4 nodes when possible) that realises that flow,
     making each node a verifiable intermediate step.
  5. Sanity-check: does every node reference only real files? Are dependencies
     a strict DAG? Does the final node naturally produce the answer table?

After this internal reasoning, emit ONLY the JSON object described below.

Decompose the task into a small Directed Acyclic Graph (DAG) of 2-6 sub-tasks.
Each node must be self-contained, factually verifiable, and listed in topological order.

Output STRICTLY a single JSON object with this exact schema and no extra prose,
no markdown, no code fences:

{
  "nodes": [
    {
      "id": "n1",
      "goal": "<imperative sentence describing the sub-task>",
      "depends_on": [],
      "suggested_tools": ["list_context", "read_csv"],
      "expected_output": "<one short sentence describing what this node should produce>"
    },
    ...
  ],
  "final_node_id": "n3"
}

Hard requirements:
- Node ids are short strings like "n1", "n2", "n3".
- "depends_on" is a (possibly empty) list of earlier node ids; the graph MUST be acyclic.
- "final_node_id" must be the id of the LAST node — the one whose completion means
  the executor has all information needed to call the `answer` tool.
- Do NOT include a separate "answer" node — calling `answer` is the executor's
  responsibility once the final node's `mark_node_done` is signalled.
- Prefer fewer, larger nodes over many tiny ones (2-6 total is typical).
- "suggested_tools" is informational; the executor may use any tool.
- Forbidden tools to suggest: `answer`, `mark_node_done` (these are control-flow tools).

Critical anti-hallucination rules:
- Reference ONLY files that appear in the dataset profile. NEVER invent paths.
- All paths in node goals must be **relative to `context/`** — do NOT prepend
  `context/` or the task id (the tools resolve relative to `context/` already).
- If the profile shows a sqlite database, mention the actual table names from
  the schema. Do not assume table names from the question.
- If no sqlite/csv exists and only json/markdown is present, plan around those
  files — do NOT plan a SQL-based path.
"""

REPLANNER_SYSTEM_PROMPT = """You are the **replanner** for a data analysis agent.

The previous DAG plan got stuck. You will receive: the original question, the
**dataset profile** (real files + schemas), the previous plan (JSON), the
per-node status, and a short failure reason. Produce a NEW DAG plan that
avoids the failure mode (e.g. split a too-broad node into smaller ones, drop
a node that depended on missing data, switch from SQL to JSON parsing if the
context contains no .db file, fix wrong file paths).

**Let's think step by step before producing the new plan.** Silently work
through this chain of thought (do NOT include it in the final output):
  1. Read the failure reason and pinpoint the EXACT root cause (missing path?
     wrong table name? bad join key? misread question?).
  2. Look up the dataset profile and identify the correct path / table / file
     that the previous plan should have used instead.
  3. Identify which previous nodes still produced useful summaries and which
     must be redone — try to keep the parts that worked.
  4. Design a NEW DAG that explicitly avoids the failure (e.g. add an
     intermediate `list_context` node, switch SQL → pandas, etc.).
  5. Sanity-check the new plan against the profile before emitting it.

After this internal reasoning, emit ONLY the JSON object.

Output the same strict JSON schema as the planner. No prose, no markdown, no code fences.

Critical anti-hallucination rules (same as planner):
- Reference ONLY files that appear in the dataset profile. NEVER invent paths.
- All paths must be **relative to `context/`** — do NOT prepend `context/` or
  the task id.
- If a previous node failed because of `Missing context asset` or
  `no such table`, the new plan MUST use a different (real) path / table name
  taken from the profile.
"""

EXECUTOR_SYSTEM_PROMPT = """You are a data analysis agent solving a task from a public dataset.

Your work is organised as a DAG of sub-tasks. At any moment, you are FOCUSED on
exactly one DAG node (you will see its id, goal, expected output, and the verbatim
summaries of any upstream nodes it depends on). You may NOT work on other nodes.

**Let's think step by step before every tool call.** Use this short chain of
thought to keep yourself on track:
  1. Re-read the focused node's `goal` and `expected_output` — what concrete
     fact / table am I supposed to produce?
  2. Look at the upstream summaries — what do I already know from prior nodes?
  3. Decide what is the SINGLE next action that closes the gap: which tool,
     which arguments (paths must match what was given in the upstream summary
     or dataset profile verbatim), and what I expect to learn from it.
  4. After each tool result: did it answer my question? If yes, advance to the
     next sub-step or call `mark_node_done` / `answer`. If no, diagnose what
     went wrong (path typo? wrong column? empty filter?) and adjust — do NOT
     repeat the same failing call.

Workflow inside the focused node:
1. Inspect files only inside the task's `context/` directory using the provided tools.
2. Prefer SQL or pandas via `execute_python` for non-trivial aggregations; do not
   estimate values by eye.
3. When you have produced what the focused node's `expected_output` describes, call
   the `mark_node_done` tool with the node id and a concise factual summary
   (1-3 sentences). The summary will be shown verbatim to downstream nodes — be
   precise, do NOT include code or full table dumps, just facts.
4. Do NOT call `answer` for non-final nodes; do NOT call `mark_node_done` for the
   final node. For the final node, instead call `answer` directly with the result table.
5. The `answer` tool requires `columns` (non-empty list of column names) and `rows`
   (list of rows; each row's length must match `columns`).
6. **CRITICAL — Minimal column set (scoring rule):** the grader matches your
   answer against the gold table by **column-value signatures**, and applies a
   redundancy penalty:
       Score = max(0, Recall - 0.5 * extra_columns / predicted_columns)
   Every column you submit that is NOT in the gold answer subtracts ~0.5/N
   from the score even when the right answer column is also present. Therefore:
     a. Re-read the question literally and ask: "what is the SMALLEST table
        that fully answers it?"
        - "How many X?" / "What is the count of X?" → 1 column with the count.
        - "What is the average / max / min / percentage of X?" → 1 column with the value.
        - "Which X had the most Y?" → 1 column with X (NOT also Y, NOT also id).
        - "List the names of …" → 1 column of names (NOT id + name + extras).
        - "For each Y, the X" → exactly 2 columns (Y, X) — drop everything else.
     b. Do NOT pad the answer with id / description / category / supporting
        columns "for context". They are not asked for and they cost score.
     c. When in doubt between "1 column" and "more columns", PICK FEWER.
        A correct minimal answer scores 1.0; a correct answer with 1 extra
        column on a 1-column gold scores 0.5; with 4 extras it scores ~0.6.
     d. Row count obeys the same minimum-information rule: do NOT include rows
        the question did not ask for (e.g. "winner of race X" → 1 row, not all
        finishers; "top 5" → 5 rows, not all of them).
     e. **Never drop a column the question literally names.** "Minimal" means
        dropping columns NOT in the question — NOT dropping columns the
        question explicitly mentions. If the question says "list schools and
        their funding type", you MUST keep BOTH `school` and `funding type`
        even if `funding type` looks like a "supporting" attribute. When the
        question lists multiple attributes joined by "and" / "with" /
        "along with" / "plus" / "for each X, the Y" / "X by Y", every named
        attribute is part of the answer. Reread the question; underline each
        noun-phrase the user asks about; that set is the FLOOR of your column
        set. Rule (a)-(d) only let you trim ABOVE that floor.
6.5. **CRITICAL — Aggregation literacy (row-count discipline):** A surprising
   number of failures come from submitting raw detail rows when the question
   asks for an aggregate or a deduplicated set. BEFORE writing your SQL /
   pandas, re-read the question and classify it:
     a. "How many / count of X?" → SQL needs `COUNT(*)` (or `len(df)` in
        pandas), submit ONE row with the count. Do NOT submit a list of
        matching ids/rows — that scores 0 even though the rows are right.
     b. "Total / sum of X" / "average X" / "what is the X" → SQL needs
        `SUM(...)` / `AVG(...)`, submit ONE row with the value. Do NOT
        submit the rows that contributed to the sum.
     c. "For each Y, the X" / "group by Y" / "X by Y" / "X per Y" → SQL
        needs `GROUP BY Y`, submit ONE row per distinct Y (not the raw
        ungrouped detail rows). Pandas equivalent:
        `df.groupby("Y")["X"].agg(...)`.
     d. "List the X" / "what are the X" / "which X" → ask whether the
        intended answer is a deduplicated SET (need `DISTINCT` or pandas
        `.drop_duplicates()` / `.unique()`) or a raw detail listing.
        Default to deduplicating when the filter could match multiple rows
        with repeating values; the grader treats a duplicate row as an
        extra row that costs score.
     e. "Which X has the (most/least/highest/lowest) Y" / "top N X by Y" →
        SQL needs `ORDER BY Y DESC LIMIT 1` (or `LIMIT N`). Without an
        explicit ORDER BY you'll submit a random row matching the filter
        and the grader will mark it wrong.
   **Verify your row count against the question's expected shape BEFORE
   calling `answer`:**
     * "how many" question with >1 row in your output → almost certainly
       wrong (you forgot to aggregate); stop and add COUNT/SUM/AVG.
     * "list / what are" question with 1 row when the filter could match
       many → almost certainly wrong (you forgot to broaden the SELECT or
       remove a stray LIMIT 1); stop and re-check.
     * "top 5" / "top 10" question with a row count != N → fix the LIMIT.
     * "winner of race X" → exactly 1 row.
   These checks take 5 seconds and routinely catch a class of failures
   that otherwise score 0 despite the executor having found the right data.
7. **CRITICAL — Cell-value normalisation (grader is byte-level on strings):**
   The grader compares cell values after a tiny normalisation step (whitespace
   strip, and the literals "", "null", "none", "nan", "nat", "<na>"
   case-insensitively become empty string). Everything else is compared
   AS-IS, case-sensitive. So when you fill `rows`, format every cell using
   these rules — do NOT submit raw `df.to_dict()` / repr output:
     * **Null / missing** — emit "" (empty string). Do NOT emit "null", "None",
       "NaN", "NaT", "<NA>", numpy.nan, or pandas NA. Strip them at the
       Python layer before calling `answer`.
     * **Numeric** — emit the RAW computed value as a string, exactly as your
       SQL/pandas computation produced it. Do NOT round, do NOT pad with
       trailing zeros, do NOT reformat. The grader compares cell strings
       byte-for-byte after whitespace strip: a gold of "52.17391304347826"
       will NOT match your "52.17". Specifically: do NOT call `round(value, 2)`;
       do NOT use `f"{value:.2f}"` / `"{:.2f}".format(value)`;
       do NOT call `Decimal(value).quantize(Decimal("0.01"))`. Convert
       pandas/numpy values to plain Python via `str(value)` (or
       `repr()` for floats if you need full precision) and submit the
       result as-is. The ONLY exception: when the question is plainly a
       count ("how many X?") and the gold is unambiguously integer, emit
       the bare integer string ("4", not "4.00") because gold is integer-typed.
       When in doubt, prefer the un-rounded full-precision form — under-padding
       is a guaranteed mismatch, while extra precision is byte-equal when the
       grader's gold also carries it, and at worst no worse than rounding.
     * **Date** — ISO 8601 `YYYY-MM-DD` with zero-padded month/day.
       "2024-3-1" → "2024-03-01"; "March 1, 2024" → "2024-03-01".
     * **DateTime** — if the source has timezone info, convert to UTC and
       suffix `Z` (e.g. "2024-03-01T08:00:00Z"). If no timezone, keep the
       original ISO datetime as-is — do NOT invent a timezone.
     * **String** — strip leading/trailing whitespace and `\\r\\n`; preserve
       the rest verbatim. Comparison is CASE-SENSITIVE: "East Asia" ≠
       "east asia". Whenever you have the source spelling/casing in front of
       you (from a tool result), copy that exact spelling into the answer
       rather than retyping from memory.
     * **Names** — first+last as two columns OR a single full-name column are
       both accepted; pick whichever the question's phrasing implies. Match
       the source spelling.
   When in doubt, format the value as a string in canonical form rather than
   leaving raw numpy / pandas / datetime objects in `rows` — the JSON encoder
   may serialise them in ways that don't match the gold normalisation.
8. Stay within the focused node's scope; if you find you need data the upstream
   summaries lack, that is a planning bug — finish what you can and stop; the
   scheduler will detect the issue and trigger a replan.

Tool-usage rules (avoid wasting your per-node step budget):
- **ALWAYS call `list_context` BEFORE reading any specific file (with depth=2
  or higher).** Context layouts vary across tasks: the same logical file may
  live at `Patient.json`, `json/Patient.json`, `data/Patient.json`,
  `Laboratory.md`, `doc/Laboratory.md`, etc. Guessing the path wastes 3-5
  turns on `FileNotFoundError` / `Missing context asset` errors before the
  executor finally calls `list_context` anyway. ONE `list_context` call
  returns the full layout in <100 tokens — pay that cost up-front. Skip
  `list_context` ONLY when an upstream node's summary explicitly stated
  the verbatim relative path you need (e.g. "see `db/main.sqlite`"); in
  that case, copy the path verbatim and proceed straight to reading.
- Tool-selection cheat sheet (PREFER specialised tools over execute_python):
    * Want files matching a pattern (`*.csv`, `db/*.sqlite`, `**/*.json`)?
      → `glob_files`, NOT `execute_python` with `os.listdir`/`glob.glob`.
    * Want to know a tabular file's schema (columns, dtypes, null counts,
      unique counts, sample values, min/max)?
      → `inspect_data`, NOT `read_csv` followed by `execute_python` with
      `df.head()`/`df.dtypes`/`df.shape`.
    * Want to aggregate / filter / join / group_by a CSV / TSV / JSON /
      JSONL / Parquet file?
      → `query_dataframe(path=..., sql="SELECT ... FROM df ...")`,
      NOT `read_csv` followed by `execute_python` with `pd.read_csv` +
      pandas. The file is loaded into an in-memory sqlite table aliased
      `df`. Check `column_mapping` in the response when a column is not
      found (spaces/dashes get sanitised to `_`).
    * Want to query a sqlite/db file?
      → `execute_context_sql` (unchanged). Use `inspect_data(path=...,
      table=...)` for per-column stats on a sqlite table.
  Drop into `execute_python` ONLY for things none of the above cover:
  custom regex parsing on text, multi-source joins where one side isn't
  a tabular file, statistical tests, etc.
- `read_doc` has THREE modes (see `mode` field in the response):
    * `full` — doc <= 32KB OR your slice already covered the whole file. The
      entire text is in `preview`; do NOT re-read it.
    * `slice` — only for genuinely huge docs. Pagination is now a LAST resort.
      If a slice has `truncated=true`, prefer switching to `grep` mode below
      over calling `read_doc` again with a new offset.
    * `grep` — pass `grep="<regex>"` to jump straight to keyword matches with
      +-`context_chars` (default 400) of surrounding text per hit. Use this
      whenever you know what you're looking for: a name ("Captain Marvel"),
      an id ("rec7BxKpjJ7bNph3O"), a column header, a publisher, a patient
      id, etc. One grep call routinely replaces 5-8 paginated reads.
  Decision rule: if your goal is "find X in a long document", call `read_doc`
  with `grep="X"` BEFORE you ever consider pagination or `execute_python`.
- Never re-run the same tool call with identical arguments. If a result was
  unhelpful, change the path, the SQL, the regex, or the slice — never repeat.
- Never call `read_doc` more than 3 times on the same path — if you can't
  find the answer by then, switch tactics (different regex, switch to
  `execute_python` for parsing, or commit and call `mark_node_done`).
- Aim to finish each node in roughly 4-8 tool calls. If you find yourself on the
  6th call without converging, stop exploring and commit: produce the best
  partial result you have, then call `mark_node_done` (or `answer` for the
  final node) with what you've got. Stalling silently is the #1 way nodes
  exhaust their step budget.
- Empty replies (no text and no tool call) are forbidden. Always either call a
  tool or write a one-sentence reasoning note explaining your next move.
"""

# --------- Tool-error formatting -------------------------------------------


def _format_tool_error(exc: Exception) -> str:
    """Return the message LangGraph's ``ToolNode`` will surface to the LLM.

    We deliberately keep the original exception text intact (it already
    carries the rich context produced by ``resolve_context_path`` /
    sqlite, including the list of available files) and just prefix the
    exception type so the model can branch on the error class. The
    string returned here is wrapped into a ``ToolMessage(status="error")``
    by ``ToolNode``, which the executor sees on its next turn.
    """

    return f"{type(exc).__name__}: {exc}"


# --------- LLM call retry --------------------------------------------------

# 历史教训（请勿回退）：
#   1) 双层重试叠加（外层 5×内层 2 + 60s timeout）让 task_259 跑出 754s。
#      build_chat_openai 已固定 max_retries=0 + timeout=30，避免再次叠加。
#   2) 即便修复了双层叠加，仍出现 4 个 task 撞 1800s 死亡：根因是 Timeout 类
#      异常被无脑重试 —— 模型本身慢的请求重试只会更慢，30s 累加成 90s。
#   3) 三个调用点（planner/executor/reflector）对 task 成败影响差 100×，
#      却共享同一份 retry 预算，浪费 reflector 这种"失败也无伤大雅"的调用。
#
# 现在的设计（按调用点差异化 + Timeout 不重试 + 读 Retry-After）：
#   - planner   : 致命，失败整个 task 死        → 给 2 次重试
#   - executor  : 失败由外层 max_node_attempts × max_replans 兜底 → 给 0 次重试
#   - reflector : 失败完全不影响 prediction.csv → 给 0 次重试
#   - Timeout 类异常一律不重试（首次 30s 已经等够，慢请求重试只会更慢）
#   - 429 / 5xx 继续重试，且优先读响应头 Retry-After，对 429 用更长退避上限
#
# 单次 LLM 调用最坏耗时：
#   planner   ≈ 30 + ~4(退避) + 30 + ~15(429 退避上限) + 30 ≈ 109s
#   executor  ≈ 30s（不重试）
#   reflector ≈ 30s（不重试）
# 与外层叠加：max_steps_per_node × max_node_attempts × max_replans 控制总调用数。

# 默认值（被 _RETRY_PROFILES 覆盖；保留是为了向后兼容旧的 import）。
LLM_RETRY_MAX_ATTEMPTS = 5
LLM_RETRY_INITIAL_DELAY = 1.0
LLM_RETRY_MAX_DELAY = 16.0

# Per-label retry profile: max_attempts / initial_delay_s / max_delay_s.
# 调整原则（2026-05 版）：用户明确要求"每个 LLM 调用点最多 5 次 retry，防止
# 整个任务失败"，因此三个 label 统一 max_attempts=5（= 1 次初始 + 5 次重试 =
# 6 次总尝试）。max_delay=16s 是配合 5 次指数退避选的：1+2+4+8+16 ≈ 31s 总
# 退避，足够熬过短暂的网关抖动；429 仍走单独的 _RATE_LIMIT_MAX_DELAY。
_RETRY_PROFILES: dict[str, dict[str, float]] = {
    "planner":   {"max_attempts": 5.0, "initial_delay": 1.0, "max_delay": 16.0},
    "executor":  {"max_attempts": 5.0, "initial_delay": 1.0, "max_delay": 16.0},
    "reflector": {"max_attempts": 5.0, "initial_delay": 1.0, "max_delay": 16.0},
}
# 429 限流单独的退避上限：上游 token 桶刷新通常 >10s，4s 上限对 429 几乎等于
# "立即重试"，浪费一次重试机会。与各 label 共用此值。
_RATE_LIMIT_MAX_DELAY = 15.0

# Substrings that mark an exception as transient and worth retrying. We match
# on substring so we stay decoupled from the openai / httpx version actually
# installed (the exception class hierarchy churns across releases). Anything
# whose ``type(exc).__name__`` contains one of these is retried; everything
# else (e.g. AuthenticationError, BadRequestError, ToolException, ValueError)
# is re-raised immediately so we don't waste retry budget on un-fixable bugs.
#
# 2026-05 更新：原本"client 端 Timeout 不重试"的策略被推翻 —— 实测中
# Qwen via DashScope 的偶发 30s read timeout 大量打挂本来已经成功提交
# answer 的 task，重试一次就能恢复。Timeout 现在通过 "Timeout" 子串匹配
# 和 408 status code 都纳入白名单。
_RETRYABLE_EXCEPTION_NAME_PARTS: tuple[str, ...] = (
    "Connection",       # APIConnectionError, ConnectionError, ...
    "RateLimit",        # RateLimitError
    "InternalServer",   # InternalServerError (5xx)
    "ServiceUnavailable",
    "BadGateway",       # 502
    "GatewayTimeout",   # 504
    "Timeout",          # APITimeoutError / ReadTimeout / ConnectTimeout（2026-05 新增）
)


_T = TypeVar("_T")


def _is_retryable_llm_error(exc: BaseException) -> bool:
    """Return True if ``exc`` looks like a transient network/server hiccup.

    Client 端 Timeout（APITimeoutError / ReadTimeout / ConnectTimeout）现在
    也会被重试 —— 见上方 _RETRYABLE_EXCEPTION_NAME_PARTS 注释。配合
    max_attempts=5 的 retry 预算，能拦下 DashScope 偶发的网关抖动，避免
    本来已经接近成功的 task 在 reflector 阶段被一次 timeout 直接打挂。
    """

    name = type(exc).__name__
    if any(part in name for part in _RETRYABLE_EXCEPTION_NAME_PARTS):
        return True
    # OpenAI's ``APIStatusError`` 暴露 HTTP status code；对 5xx / 429 / 408 重试。
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and (
        status_code >= 500 or status_code == 429 or status_code == 408
    ):
        return True
    return False


def _extract_retry_after_seconds(exc: BaseException) -> float | None:
    """Try to extract the ``Retry-After`` header from an OpenAI/httpx error.

    Returns ``None`` if no header or unparseable. Clamped to 30s so an upstream
    sending us off into the weeds doesn't burn the whole task budget.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, 30.0)


def _compute_retry_delay(
    exc: BaseException, attempt: int, profile: dict[str, float]
) -> float:
    """Compute the backoff delay before the next retry."""
    # 1) 优先尊重上游 Retry-After 头（限流/过载场景常见）
    retry_after = _extract_retry_after_seconds(exc)
    if retry_after is not None:
        return retry_after

    # 2) 429 用更长的退避上限（默认 max_delay 对限流毫无意义）
    name = type(exc).__name__
    status_code = getattr(exc, "status_code", None)
    is_rate_limit = "RateLimit" in name or status_code == 429
    max_delay = _RATE_LIMIT_MAX_DELAY if is_rate_limit else profile["max_delay"]
    initial = profile["initial_delay"]

    # 3) 指数退避 + full jitter（AWS 推荐，比单向 jitter 防惊群更有效）
    base = min(initial * (2 ** attempt), max_delay)
    return base * random.random() if base > 0 else 0.0


# Maximum chars we keep when previewing message content / tool args / tool
# results inside INFO logs. DEBUG-level logs print the full payload — set
# DABENCH_LOG_LEVEL=DEBUG to enable. This is a soft guard against agent.log
# files growing into the tens of MB on long benchmarks.
_LLM_LOG_PREVIEW_CHARS = 240


def _preview_text(value: Any, *, limit: int = _LLM_LOG_PREVIEW_CHARS) -> str:
    """Render ``value`` as a single-line, length-capped string for INFO logs.

    Newlines are collapsed so each log line stays one record (greppable,
    diff-friendly). Long payloads get a `... (+N chars)` suffix so it's
    obvious they were truncated.
    """
    if value is None:
        return "(none)"
    text = value if isinstance(value, str) else repr(value)
    text = text.replace("\n", "\\n").replace("\r", "\\r")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (+{len(text) - limit} chars)"


def _summarise_message_for_log(message: Any) -> str:
    """One-line summary of a LangChain message for the per-call DEBUG dump.

    Distinguishes role + content length + tool-call count, since the raw
    ``repr(message)`` is long and noisy.
    """
    role = type(message).__name__
    content = getattr(message, "content", "")
    content_len = len(content) if isinstance(content, str) else len(str(content))
    tool_calls = getattr(message, "tool_calls", None) or []
    tool_call_part = f" tool_calls={len(tool_calls)}" if tool_calls else ""
    return (
        f"{role}(content_len={content_len}{tool_call_part}): "
        f"{_preview_text(content)}"
    )


def _summarise_llm_response(response: Any) -> dict[str, Any]:
    """Pull the fields we want to log out of a ChatOpenAI response."""
    content = getattr(response, "content", "")
    if not isinstance(content, str):
        content = str(content)
    tool_calls = getattr(response, "tool_calls", None) or []
    tool_call_names = [
        getattr(call, "name", None) or call.get("name", "?")
        for call in tool_calls
    ]
    return {
        "content_len": len(content),
        "content_preview": _preview_text(content),
        "tool_calls": tool_call_names,
        "tool_call_count": len(tool_calls),
    }


def _invoke_with_retry(
    fn: Callable[[], _T],
    *,
    label: str,
    max_attempts: int | None = None,
    input_messages: list[Any] | None = None,
) -> _T:
    """Call ``fn`` with exponential backoff on transient LLM errors.

    The retry budget is selected per ``label`` from ``_RETRY_PROFILES`` —
    planner is critical (gets retries); executor/reflector default to 0
    retries because their failures are absorbed by the outer DAG loop /
    are non-essential. Pass ``max_attempts`` explicitly to override.
    Non-retryable exceptions are re-raised immediately.

    ``input_messages`` is optional but strongly recommended: when provided,
    a one-line INFO summary of the call is logged BEFORE the network round-
    trip, and a DEBUG dump of every message + the response payload is
    logged AFTER. Pass ``None`` only from call-sites where surfacing the
    prompt would be redundant (none today).
    """

    profile = _RETRY_PROFILES.get(label, _RETRY_PROFILES["planner"])
    if max_attempts is None:
        max_attempts = int(profile["max_attempts"])

    # ---- Pre-call INFO log: summarise the input prompt -----------------
    # Keep this one line so the agent.log timeline reads top-to-bottom as a
    # narrative ("we're about to ask the planner ..." → "planner returned").
    if input_messages is not None and logger.isEnabledFor(logging.INFO):
        last_message = input_messages[-1] if input_messages else None
        last_content = getattr(last_message, "content", "") if last_message else ""
        if not isinstance(last_content, str):
            last_content = str(last_content)
        logger.info(
            "llm_call_start label=%s input_msgs=%d last_role=%s last_preview=%s",
            label,
            len(input_messages),
            type(last_message).__name__ if last_message else "(none)",
            _preview_text(last_content),
        )
    # DEBUG: dump every message in the prompt so a `grep label=executor`
    # post-mortem can reproduce exactly what the model was asked.
    if input_messages is not None and logger.isEnabledFor(logging.DEBUG):
        for index, message in enumerate(input_messages):
            logger.debug(
                "llm_call_input label=%s idx=%d %s",
                label,
                index,
                _summarise_message_for_log(message),
            )

    last_exc: BaseException | None = None
    for attempt in range(max_attempts + 1):  # 1 initial + max_attempts retries
        attempt_start = time.perf_counter()
        try:
            response = fn()
        except Exception as exc:  # noqa: BLE001 — classify below
            elapsed_ms = (time.perf_counter() - attempt_start) * 1000.0
            last_exc = exc
            if attempt >= max_attempts or not _is_retryable_llm_error(exc):
                logger.error(
                    "llm_call_failed label=%s attempt=%d/%d elapsed_ms=%.0f "
                    "exc=%s: %s",
                    label,
                    attempt + 1,
                    max_attempts + 1,
                    elapsed_ms,
                    type(exc).__name__,
                    exc,
                )
                raise
            delay = _compute_retry_delay(exc, attempt, profile)
            logger.warning(
                "llm_call_retry label=%s attempt=%d/%d elapsed_ms=%.0f "
                "exc=%s next_delay_s=%.1f",
                label,
                attempt + 1,
                max_attempts + 1,
                elapsed_ms,
                type(exc).__name__,
                delay,
            )
            # Keep the legacy stderr line so anybody tail-ing stderr without
            # the structured logger still sees retries (entrypoint.sh, CI).
            print(
                f"[langgraph_agent] {label} LLM call failed "
                f"(attempt {attempt + 1}/{max_attempts + 1}): "
                f"{type(exc).__name__}: {exc}. Retrying in {delay:.1f}s...",
                file=sys.stderr,
            )
            if delay > 0:
                time.sleep(delay)
            continue

        # ---- Post-call success logs ------------------------------------
        elapsed_ms = (time.perf_counter() - attempt_start) * 1000.0
        summary = _summarise_llm_response(response)
        logger.info(
            "llm_call_done label=%s attempt=%d/%d elapsed_ms=%.0f "
            "out_chars=%d tool_calls=%s out_preview=%s",
            label,
            attempt + 1,
            max_attempts + 1,
            elapsed_ms,
            summary["content_len"],
            summary["tool_calls"] or "(none)",
            summary["content_preview"],
        )
        if logger.isEnabledFor(logging.DEBUG):
            # Full text (no preview cap) at DEBUG level.
            full_content = getattr(response, "content", "")
            if not isinstance(full_content, str):
                full_content = str(full_content)
            logger.debug(
                "llm_call_output label=%s attempt=%d full_content=%r tool_calls_full=%r",
                label,
                attempt + 1,
                full_content,
                getattr(response, "tool_calls", None) or [],
            )
        return response  # type: ignore[return-value]
    # Defensive: the loop above always either returns or re-raises.
    raise RuntimeError(  # pragma: no cover
        f"_invoke_with_retry exited without returning; last_exc={last_exc!r}"
    )


# --------- Dataset profiling (anti-hallucination prelude to the planner) ---

# Concrete-file extensions we treat as SQLite databases when building the
# profile. Some tasks ship .sqlite/.sqlite3 in addition to .db.
_SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
_JSON_EXTENSIONS = {".json"}
_CSV_EXTENSIONS = {".csv"}
_DOC_EXTENSIONS = {".md", ".txt"}


def _build_dataset_profile(task: PublicTask, *, max_depth: int = 4) -> str:
    """Render a compact, planner-friendly summary of the task's `context/`.

    Why this exists: ~80% of failures in our last benchmark run were the
    planner / executor inventing file paths that don't exist (e.g. asking
    for ``context/data.db`` when the directory only holds JSON files).
    Injecting a real listing — plus sqlite schemas and short json/csv heads
    — into the planner prompt eliminates that whole class of error.

    The output is plain text (Markdown-ish but not rendered) so it slots
    cleanly into a HumanMessage. We deliberately keep it under ~3 KB
    typical so it doesn't dominate the planner's context window:
      * Sqlite: only table names + the first column line of CREATE TABLE.
      * JSON: first 400 chars of the pretty-printed payload.
      * CSV: header row + the first 3 data rows.
      * Markdown/txt: first 400 chars.
    """

    lines: list[str] = []
    try:
        listing = list_context_tree(task, max_depth=max_depth)
    except OSError as exc:  # pragma: no cover — context dir disappeared
        return f"(failed to list context dir: {exc})"

    entries = listing.get("entries", []) or []
    lines.append(
        "Files under context/ (each line shows the EXACT path to use as the "
        "tool `path` argument — copy these strings verbatim, do NOT strip the "
        "subdirectory prefix and do NOT prepend `context/`):"
    )
    if not entries:
        lines.append("  (empty)")
    for entry in entries:
        kind = entry.get("kind")
        path = entry.get("path", "")
        size = entry.get("size")
        if kind == "dir":
            lines.append(f"  [DIR ] {path}/")
        else:
            size_hint = f" ({size} bytes)" if isinstance(size, int) else ""
            lines.append(f"  [FILE] {path}{size_hint}")

    # Per-file deep dive for the formats most likely to mislead the planner.
    file_entries = [e for e in entries if e.get("kind") == "file"]
    detail_sections: list[str] = []
    for entry in file_entries:
        rel_path = entry.get("path", "")
        suffix = Path(rel_path).suffix.lower()
        try:
            if suffix in _SQLITE_EXTENSIONS:
                detail_sections.append(_profile_sqlite(task, rel_path))
            elif suffix in _JSON_EXTENSIONS:
                detail_sections.append(_profile_json(task, rel_path))
            elif suffix in _CSV_EXTENSIONS:
                detail_sections.append(_profile_csv(task, rel_path))
            elif suffix in _DOC_EXTENSIONS:
                detail_sections.append(_profile_doc(task, rel_path))
        except Exception as exc:  # noqa: BLE001 — profiling must never crash planner
            detail_sections.append(
                f"\n### {rel_path}\n  (could not profile: {type(exc).__name__}: {exc})"
            )

    if detail_sections:
        lines.append("")
        lines.append("File previews:")
        lines.extend(detail_sections)

    return "\n".join(lines)


def _profile_sqlite(task: PublicTask, rel_path: str) -> str:
    absolute_path = task.context_dir / rel_path
    schema = inspect_sqlite_schema(absolute_path)
    tables = schema.get("tables", []) or []
    if not tables:
        return f"\nFile path: `{rel_path}` (sqlite, 0 tables)"
    table_lines = [
        f"\nFile path: `{rel_path}` (sqlite, {len(tables)} tables; "
        f"pass exactly `{rel_path}` as the tool `path` argument)"
    ]
    for table in tables:
        name = table.get("name", "?")
        create_sql = (table.get("create_sql") or "").strip()
        # Keep CREATE TABLE compact: collapse whitespace and clip.
        compact = " ".join(create_sql.split())
        if len(compact) > 240:
            compact = compact[:240] + "..."
        table_lines.append(f"  - table `{name}`: {compact}")
    return "\n".join(table_lines)


def _profile_json(task: PublicTask, rel_path: str, *, max_chars: int = 400) -> str:
    absolute_path = task.context_dir / rel_path
    text = absolute_path.read_text(errors="replace")
    try:
        payload = json.loads(text)
        pretty = json.dumps(payload, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        pretty = text  # not JSON; show raw head anyway
    head = pretty[:max_chars]
    suffix = "..." if len(pretty) > max_chars else ""
    return (
        f"\nFile path: `{rel_path}` (json; pass exactly `{rel_path}` as the "
        f"tool `path` argument)\nHead:\n```\n{head}{suffix}\n```"
    )


def _profile_csv(task: PublicTask, rel_path: str, *, max_rows: int = 3) -> str:
    import csv

    absolute_path = task.context_dir / rel_path
    with absolute_path.open(newline="") as handle:
        reader = csv.reader(handle)
        rows = []
        for idx, row in enumerate(reader):
            if idx > max_rows:
                break
            rows.append(row)
    if not rows:
        return f"\nFile path: `{rel_path}` (csv, empty)"
    header = rows[0]
    body = rows[1:]
    body_repr = "\n".join("  " + ", ".join(map(str, r)) for r in body)
    return (
        f"\nFile path: `{rel_path}` (csv; pass exactly `{rel_path}` as the "
        f"tool `path` argument)\n"
        f"columns={header}\nfirst {len(body)} rows:\n{body_repr}"
    )


def _profile_doc(task: PublicTask, rel_path: str, *, max_chars: int = 400) -> str:
    absolute_path = task.context_dir / rel_path
    text = absolute_path.read_text(errors="replace")
    head = text[:max_chars]
    suffix = "..." if len(text) > max_chars else ""
    return (
        f"\nFile path: `{rel_path}` (text; pass exactly `{rel_path}` as the "
        f"tool `path` argument)\nHead:\n```\n{head}{suffix}\n```"
    )


REASONING_SYSTEM_PROMPT = """You are the **reasoning narrator** for a data analysis agent.

The executor model just decided to call one or more tools, but it returned an
empty `content` field — only the structured tool_calls, no human-readable
explanation. Your job: produce that missing explanation so the trace shows a
proper Reason → Act loop instead of a stream of opaque tool calls.

You will see the full conversation history followed by the executor's most
recent tool_call(s). Output 1-3 sentences in plain English that:
  1. summarise what the most recent tool result told us (if any), in one short
     clause — e.g. "The previous query returned 153 matching CustomerIDs."
  2. state what gap still needs to be closed for the focused DAG node, in one
     short clause — e.g. "We still need their August 2012 consumption."
  3. explain WHY the specific tool + arguments the executor just chose closes
     that gap — e.g. "Querying yearmonth.csv filtered to Date=201208 and
     CustomerID IN (...) gives the consumption rows for exactly the customers
     identified upstream."

STRICT FORMAT RULES:
- Output plain prose ONLY. No markdown headings, no bullet lists, no JSON.
- Do NOT call any tool. Do NOT propose changes to the tool_call. Your job is
  purely to NARRATE the executor's intent, not to second-guess it.
- Do NOT repeat the tool_call arguments verbatim — refer to them at a higher
  level ("query yearmonth.csv for August 2012 consumption", not
  "execute SELECT CustomerID, Consumption FROM df WHERE Date = ...").
- Keep the whole reply under 80 words. Brevity matters: this text gets
  prepended into the assistant turn for downstream review.
"""


REFLECTOR_SYSTEM_PROMPT = """You are the **reflector** for a data analysis agent.

You receive: the original question, the plan, and the answer the executor just submitted
(via the `answer` tool). Decide whether the answer is plausible and well-formed.

**Let's think step by step before issuing a verdict.** Silently walk through:
  1. Restate what the question asks for in one sentence (entity, metric, filter,
     expected shape — single value? list? table?).
  2. Check the answer's structural shape: do the column names match what the
     question asks about? Is the row count plausible (e.g. "top 5" → 5 rows)?
  3. **Check column count against the question (HIGH PRIORITY).** The grader
     penalises every extra column: a 1-column gold answered with 4 columns
     scores ~0.6 even when correct. Apply this rule:
        - "How many / count / average / max / percentage / what is the X" → 1 column.
        - "Which X had the most Y" → 1 column (just X).
        - "List names of X" → 1 column.
        - "For each Y, the X" → exactly 2 columns.
     If the executor submitted MORE columns than the question literally asks
     for (typically padding with id / name / description / supporting fields),
     emit RETRY telling them to drop the extras and resubmit with the
     minimal column set.
     **But also**: do NOT issue RETRY-drop-column when the dropped column
     is an attribute the question literally names. Re-read the question:
     if it says "list X and Y" / "for each X, the Y" / "X by Y" / "X with
     Y", every named attribute is REQUIRED. Telling the executor to drop
     a question-named column makes recall fall to 0; only suggest dropping
     columns that are NOT in the question text (id, raw timestamp,
     description-style padding columns).
  4. Check the values: are units / types consistent? Is the answer empty when
     data clearly exists, or absurdly large/small for the question?
  4.5. **Aggregation check (catches a class of zero-score bugs):** Compare the
     row count in the submitted answer against what the question's wording
     implies:
        - "How many / count / total / sum / average / what is the X" → 1 row.
          If the answer has >1 row, the executor likely dumped raw detail
          rows instead of aggregating → emit
          `RETRY: aggregate the result (COUNT/SUM/AVG) and submit one row`.
        - "List / what are the / which X" → if the executor submitted only 1
          row when the filter could plausibly match many, ask them to drop
          the LIMIT 1 / extra WHERE clause and resubmit the full set
          (with DISTINCT if duplicates are likely).
        - "Top N" / "first N" / "N largest" → exactly N rows. If row count
          differs, emit `RETRY: fix the LIMIT to match N`.
        - "For each Y, the X" / "X by Y" → one row per distinct Y. If
          row count looks like a flat detail dump (much larger than the
          plausible number of distinct Y values), ask for a `GROUP BY Y`.
     Important: do NOT issue this RETRY when the row count IS plausibly
     correct — only when there's a clear shape mismatch with the question.
  5. **Check cell-value formatting (grader is case-sensitive on strings):**
        - Numeric cells should be the RAW computed value as a string, NOT
          rounded. The grader compares cell strings byte-for-byte: if gold
          is "52.17391304347826" and the executor submitted "52.17", that
          row mismatches. So if the executor's number is suspiciously short
          (e.g. "52.17" / "0.32" / "63.50") AND the underlying division
          could have produced more digits, emit RETRY-don't-round telling
          them to resubmit `str(raw_value)` without round/quantize/format.
          Conversely, do NOT ask the executor to round a long-precision
          value down to 2 decimals — that is the failure mode we are
          actively avoiding. Integer counts ("how many X?") are fine as
          bare integers.
        - Dates must be ISO `YYYY-MM-DD` with zero-padded parts ("2024-03-01",
          NOT "2024-3-1" / "March 1, 2024"). DateTimes with timezone must end
          in `Z` after UTC conversion.
        - Null-ish values must be empty strings, not "None"/"NaN"/"<NA>".
        - String cells must keep the source spelling and casing
          ("East Asia" ≠ "east asia"); whitespace-only differences are fine.
  6. Decide: is there a CONCRETE, FIXABLE issue, or just minor stylistic
     differences? Lean towards `OK` unless something is clearly wrong.

After this internal reasoning, emit only the verdict line.

Reply with EXACTLY one of two single-line verdicts:
- `OK` — the answer looks good; finalize it.
- `RETRY: <one short sentence telling the executor what to fix>` — the executor
  must call `answer` again with corrections.

Emit `RETRY` whenever there is a concrete, fixable issue:
  * the answer has more columns than the question asks for (drop extras),
  * numbers not formatted as 2-decimal strings (use Decimal ROUND_HALF_UP),
  * dates not in ISO `YYYY-MM-DD` form,
  * "None" / "NaN" / "<NA>" leaking into cells instead of empty string,
  * string casing/spacing diverges from the source values seen in tool results,
  * wrong column count / wrong unit / empty rows when data clearly exists,
  * obvious value mismatch (e.g. percentage off by 100x).
Otherwise emit `OK`.
"""

# --------- Graph state -----------------------------------------------------

class AgentState(TypedDict, total=False):
    """LangGraph state shared across nodes.

    ``messages`` accumulates the executor's conversation (system + user +
    AIMessage with tool_calls + ToolMessage). The auxiliary fields are
    bookkeeping for the planner/reflector loop, idle/replan budgets, and
    the per-node turn counter used to detect a stuck executor.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    reflections_used: int
    idle_nudges_used: int
    # Number of executor LLM turns spent on the currently focused DAG node.
    # Reset by the scheduler each time it focuses a (possibly different) node.
    steps_in_current_node: int
    # Cause of the latest soft failure that should trigger a replan.
    pending_replan_reason: str | None
    finalized: bool
    failure_reason: str | None

# --------- Helpers ---------------------------------------------------------

def _question_user_message(task: PublicTask) -> HumanMessage:
    return HumanMessage(
        content=(
            f"Question: {task.question}\n\n"
            "All tool file paths are relative to the task context directory. "
            "Follow the focused DAG node instructions from the scheduler. "
            "When the FINAL node is focused, call the `answer` tool instead "
            "of `mark_node_done`."
        )
    )

def _last_ai_message(messages: list[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None

def _has_pending_tool_calls(message: AIMessage) -> bool:
    tool_calls = getattr(message, "tool_calls", None) or []
    return bool(tool_calls)

def _ai_message_text(message: AIMessage) -> str:
    """Best-effort extraction of human-readable text from an AIMessage.

    Mirrors the chunk-flattening logic used in trace conversion so the
    runtime "is this turn useful?" check stays consistent with what
    eventually shows up in trace.json under `__assistant_text__`.
    """

    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for chunk in content:
            if isinstance(chunk, dict):
                text = chunk.get("text", "")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunk for chunk in chunks if chunk)
    return ""

def _is_useful_executor_turn(message: AIMessage) -> bool:
    """True if this AIMessage made a tool call OR produced non-empty text.

    A "useful" turn is one that actually advanced the work — calling a tool
    or at least emitting content the user / next node can read. Empty turns
    (no tool_calls AND no text) are model glitches (notably observed on
    Qwen via the OpenAI-compatible endpoint) that should be recovered by
    the `nudge` node WITHOUT consuming the per-node step budget.
    """

    if _has_pending_tool_calls(message):
        return True
    return bool(_ai_message_text(message).strip())

def _last_tool_call_names(messages: list[BaseMessage]) -> set[str]:
    """Return the set of tool names invoked by the most recent AIMessage."""

    last_ai = _last_ai_message(messages)
    if last_ai is None:
        return set()
    return {
        call.get("name", "")
        for call in (getattr(last_ai, "tool_calls", None) or [])
    }


def _normalize_tool_call(call: dict[str, Any]) -> tuple[str, str]:
    """Reduce a tool_call dict to a hashable (name, args_json) pair.

    Args are JSON-dumped with ``sort_keys=True`` so trivial key-order
    differences don't make two semantically identical calls look distinct.
    Returns ``("", "")`` for malformed calls (defensive — never raises).
    """
    name = call.get("name", "") if isinstance(call, dict) else ""
    args = call.get("args", {}) if isinstance(call, dict) else {}
    try:
        args_repr = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        args_repr = repr(args)
    return name, args_repr


def _detect_repeated_tool_calls(
    messages: list[BaseMessage],
    *,
    window: int = 3,
) -> tuple[str, str] | None:
    """Detect that the last ``window`` AIMessages all called the same tool with same args.

    Returns the offending ``(tool_name, args_json)`` pair, or ``None`` when:
      * fewer than ``window`` AIMessages exist in the trace,
      * any of those AIMessages had no tool_calls (e.g. textual turn),
      * any of those AIMessages had multiple or differing tool_calls,
      * the (name, args) signatures don't all match.

    This is used by ``executor_node`` to inject a one-shot SystemMessage
    nudge when the executor falls into a single-action loop (notably
    observed on task_80: 4× ``query_dataframe`` with identical args).

    Conservative on purpose:
      * window=3 to avoid false positives on 2-call coincidences.
      * Only fires when EVERY recent AIMessage made exactly ONE tool call
        and they all share the same signature — multi-tool turns and any
        textual reasoning interleaved between them break the pattern.
    """
    recent_ai: list[AIMessage] = []
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        recent_ai.append(message)
        if len(recent_ai) >= window:
            break

    if len(recent_ai) < window:
        return None

    signatures: list[tuple[str, str]] = []
    for ai in recent_ai:
        tool_calls = getattr(ai, "tool_calls", None) or []
        if len(tool_calls) != 1:
            return None
        sig = _normalize_tool_call(tool_calls[0])
        if not sig[0]:
            return None
        signatures.append(sig)

    first = signatures[0]
    if all(sig == first for sig in signatures[1:]):
        return first
    return None


def _count_tool_in_current_node(
    messages: list[BaseMessage],
    tool_name: str,
    *,
    max_lookback: int = 200,
) -> int:
    """Count how many times ``tool_name`` was invoked in the CURRENT DAG node.

    Walks ``messages`` in reverse from the tail and stops counting when it
    hits the most recent ``HumanMessage`` (which the scheduler emits at the
    start of every focused node — see ``_focused_executor_prompt``). That
    HumanMessage acts as the node-scope boundary: anything earlier is from
    a previous node and must NOT be counted, otherwise the threshold would
    fire across nodes (which already get ``steps_in_current_node`` reset
    by the scheduler).

    Why not require the strict step counter?
      * The state's ``steps_in_current_node`` only counts USEFUL turns and
        only since the scheduler last focused the node, while we want to
        count every actual tool call (failed empty turns can sit between).
      * Walking the message tail to the latest HumanMessage is O(n) but n
        is bounded by ``max_lookback``, so this is cheap.

    Sizing of ``max_lookback`` (200): each executor turn produces 1 AIMessage
    + 1 ToolMessage = 2 messages, plus occasional injected SystemMessage
    nudges (~1 every 5 turns). The dynamic per-node step cap caps useful
    turns at ~25-30 in the worst case (see _dynamic_node_step_cap). With
    safety margin for nudges + retries + reflector retry messages we expect
    at most ~60-80 messages per node; 200 keeps a comfortable 2.5x cushion.
    Empirical baseline data (run 20260506T151838Z, 113 node executions):
    max observed step count was 29, so the boundary HumanMessage is always
    reachable within the lookback window. The hard cap exists purely as a
    defence against pathological future runaways and must NOT silently
    truncate normal-sized nodes — if it ever does, the threshold check
    becomes incorrect (over-counts: we'd start from somewhere mid-stream
    instead of at the node boundary). Bump the cap rather than tightening
    if dynamic cap grows.

    The function counts a tool call iff:
      * the message is an ``AIMessage`` with at least one ``tool_calls``
        entry whose ``name`` equals ``tool_name``, OR
      * a multi-tool turn whose tool_calls include ``tool_name`` (each call
        contributes 1 to the count — multi-tool turns are unusual but we
        do not want to miss them for the threshold).

    Returns 0 when no boundary HumanMessage exists yet (executor has not
    been focused on a node) or when no matching tool calls were made.
    """
    count = 0
    scanned = 0
    for message in reversed(messages):
        scanned += 1
        if scanned > max_lookback:
            # Defensive cap reached without finding the node-boundary
            # HumanMessage. Returning the partial count would over-count
            # (we'd start from somewhere mid-stream instead of the actual
            # node boundary), causing the threshold check to fire too
            # eagerly. Returning 0 fails-safe: no nudge fires, but the
            # subsequent dynamic-step-cap warning will still kick in if
            # the executor genuinely stalls. Prefer fail-safe over false
            # positives — a missed nudge is recoverable, an incorrect
            # nudge spams the LLM with a misleading hint.
            return 0
        # HumanMessage marks the start of the current focused-node scope —
        # earlier messages belong to a previous node and must be excluded.
        if isinstance(message, HumanMessage):
            break
        if not isinstance(message, AIMessage):
            continue
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if isinstance(call, dict) and call.get("name") == tool_name:
                count += 1
    return count


def _detect_tool_overuse(
    messages: list[BaseMessage],
    *,
    tool_name: str = "read_doc",
    threshold: int = 4,
) -> bool:
    """Whether ``tool_name`` has been called >= ``threshold`` times in this node.

    Different from ``_detect_repeated_tool_calls``: that function only fires
    on the much narrower pattern "same tool + IDENTICAL args N turns in a
    row". The motivating bug for this helper (task_344 / 352 / 418) is the
    OPPOSITE pattern — the executor varies its ``read_doc`` arguments every
    turn (different offset, different grep, different file slice) but never
    converges on an answer, burning 8-12 calls before the per-node budget
    finally kills the node.

    The threshold defaults to 4 to give the executor 3 honest tries before
    the warning fires (matches the existing prompt rule "never call read_doc
    more than 3 times on the same path"). Caller is responsible for the
    "already warned recently" idempotency guard — see ``executor_node``.
    """
    return _count_tool_in_current_node(messages, tool_name) >= threshold

# --------- DAG parsing & validation --------------------------------------

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

class PlanParseError(ValueError):
    """Raised when the planner LLM output cannot be coerced into a PlanDAG."""

def _extract_json_object(text: str) -> str:
    """Best-effort extraction of the first balanced JSON object from ``text``.

    The planner prompt forbids markdown fences, but small models occasionally
    wrap output in ``` blocks anyway. We strip those and then take the first
    ``{...}`` match. If no JSON object is present we raise so the caller can
    surface a clear error.
    """

    stripped = text.strip()
    # Drop common markdown fences if present.
    if stripped.startswith("```"):
        # Handle ```json ... ``` and ``` ... ``` uniformly by stripping the
        # first line and the trailing ``` if any.
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -3]
    match = _JSON_OBJECT_RE.search(stripped)
    if match is None:
        raise PlanParseError("Planner output contained no JSON object.")
    return match.group(0)

def _parse_plan_dag(raw: str) -> PlanDAG:
    """Parse the planner output into a validated :class:`PlanDAG`.

    Validations performed:
    * JSON is parseable.
    * ``nodes`` is a non-empty list of objects.
    * Each node has unique string id, non-empty goal, list ``depends_on``.
    * All ``depends_on`` ids reference earlier nodes (forces topological order
      and rejects cycles in one pass).
    * ``final_node_id`` exists and is the last node.

    Raises :class:`PlanParseError` with an explanatory message on failure.
    """

    try:
        data = json.loads(_extract_json_object(raw))
    except json.JSONDecodeError as exc:
        raise PlanParseError(f"Planner output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanParseError("Planner output must be a JSON object.")

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise PlanParseError("Planner output must include a non-empty 'nodes' list.")

    seen_ids: set[str] = set()
    nodes: list[PlanNode] = []
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise PlanParseError(f"Node #{index} is not an object.")
        node_id = raw_node.get("id")
        goal = raw_node.get("goal")
        if not isinstance(node_id, str) or not node_id.strip():
            raise PlanParseError(f"Node #{index} has missing/empty 'id'.")
        if node_id in seen_ids:
            raise PlanParseError(f"Duplicate node id {node_id!r}.")
        if not isinstance(goal, str) or not goal.strip():
            raise PlanParseError(f"Node {node_id!r} has missing/empty 'goal'.")

        deps_raw = raw_node.get("depends_on", [])
        if not isinstance(deps_raw, list) or not all(isinstance(d, str) for d in deps_raw):
            raise PlanParseError(
                f"Node {node_id!r}.depends_on must be a list of strings."
            )
        for dep in deps_raw:
            if dep not in seen_ids:
                raise PlanParseError(
                    f"Node {node_id!r} depends on {dep!r}, which has not been "
                    "declared yet (forward references and cycles are forbidden)."
                )

        suggested_raw = raw_node.get("suggested_tools", [])
        if not isinstance(suggested_raw, list) or not all(
            isinstance(t, str) for t in suggested_raw
        ):
            raise PlanParseError(
                f"Node {node_id!r}.suggested_tools must be a list of strings."
            )
        expected_output_raw = raw_node.get("expected_output", "")
        if not isinstance(expected_output_raw, str):
            raise PlanParseError(
                f"Node {node_id!r}.expected_output must be a string."
            )

        nodes.append(
            PlanNode(
                id=node_id,
                goal=goal.strip(),
                depends_on=list(deps_raw),
                suggested_tools=list(suggested_raw),
                expected_output=expected_output_raw.strip(),
            )
        )
        seen_ids.add(node_id)

    final_node_id = data.get("final_node_id")
    if not isinstance(final_node_id, str) or final_node_id not in seen_ids:
        raise PlanParseError(
            "Planner output must include 'final_node_id' referencing an "
            f"existing node. Got: {final_node_id!r}; valid: {sorted(seen_ids)}."
        )
    if final_node_id != nodes[-1].id:
        raise PlanParseError(
            f"final_node_id={final_node_id!r} must equal the last node's id "
            f"({nodes[-1].id!r}). Reorder the plan so the final node is last."
        )

    return PlanDAG(nodes=nodes, final_node_id=final_node_id)

def _fallback_plan_dag(task: PublicTask) -> PlanDAG:
    """A trivial single-node DAG used when planner output is unparseable.

    Falling back to a 1-node DAG preserves the strict-mode invariants: the
    executor still has a focused goal and a final node id, and the rest of
    the graph (scheduler, reflector, finalize) keeps working unchanged.
    """

    del task  # The fallback goal is generic; the executor sees the question.
    return PlanDAG(
        nodes=[
            PlanNode(
                id="n1",
                goal=(
                    "Inspect the task context and produce the final answer "
                    "table that answers the user's question."
                ),
                depends_on=[],
                suggested_tools=[
                    "list_context",
                    "read_csv",
                    "read_json",
                    "execute_python",
                ],
                expected_output=(
                    "The final result table required by the user's question."
                ),
            )
        ],
        final_node_id="n1",
    )

def _ready_node(dag: PlanDAG, status: dict[str, str]) -> PlanNode | None:
    """First (in declaration order) node whose deps are all done and is pending."""

    for node in dag.nodes:
        if status.get(node.id) != "pending":
            continue
        if all(status.get(dep) == "done" for dep in node.depends_on):
            return node
    return None

def _all_nodes_done(status: dict[str, str]) -> bool:
    return bool(status) and all(value == "done" for value in status.values())

def _focused_executor_prompt(
    *,
    task: PublicTask,
    dag: PlanDAG,
    node: PlanNode,
    upstream_summaries: dict[str, str],
    is_final: bool,
) -> HumanMessage:
    """Build the strict-mode focused prompt for one DAG node.

    The executor only sees the question, the focused node's metadata, and
    the verbatim ``mark_node_done`` summaries of the upstream nodes it
    depends on (transitively, but only the *direct* deps' summaries — keeps
    context lean; transitive info is already baked into direct deps' summaries).
    """

    deps_block_lines: list[str] = []
    if node.depends_on:
        for dep_id in node.depends_on:
            summary = upstream_summaries.get(dep_id, "(no summary recorded)")
            dep_node = dag.node_by_id(dep_id)
            dep_goal = dep_node.goal if dep_node is not None else ""
            deps_block_lines.append(f"- {dep_id} (goal: {dep_goal})\n  summary: {summary}")
        deps_block = "\n".join(deps_block_lines)
    else:
        deps_block = "(this node has no upstream dependencies)"

    # P4.2 — list_context priority hint:
    # If the upstream summaries do NOT contain any relative-path-shaped token
    # (e.g. `csv/foo.csv`, `db/main.sqlite`, `doc/Laboratory.md`), the
    # executor is at high risk of path-hallucination (task_25 / task_11 /
    # task_418 failure mode: tried to read `Patient.json` / `expense.json` /
    # `Laboratory.md` at the root when they were under `json/` / `csv/` /
    # `doc/`). Inject a one-liner reminder.
    #
    # Heuristic correctness note: an early version of this check used
    # `"/" in blob or "." in blob`, but English summaries almost always
    # contain a sentence-ending period — empirically that triggered "has
    # explicit path" for 91.7% of baseline summaries (55/60), making the
    # hint a no-op. We now require a real path-shaped token: a regex
    # match for either
    #   * a token containing a forward slash (e.g. `csv/income.csv`,
    #     `db/main.sqlite`, `json/Patient.json`), OR
    #   * a known-file-extension token at word boundary (e.g. `posts.json`,
    #     `sets.db`, `expense.csv`, `Laboratory.md`).
    # File extension whitelist matches the tools the agent actually uses
    # (read_csv / read_json / read_doc / inspect_sqlite_schema / etc.);
    # extending it is safe (only changes whether we inject a redundant
    # hint vs not).
    summaries_blob = (
        " ".join(upstream_summaries.values()) if upstream_summaries else ""
    )
    # Match: any token with a slash that has at least one alnum on each side.
    # E.g. matches `csv/foo.csv`, `db/main.sqlite`; rejects `/`, `and/or`.
    _slash_path_re = re.compile(r"[A-Za-z0-9_\-]+/[A-Za-z0-9_./\-]+")
    # Match: a filename with a known data-file extension. Bounded by
    # whitespace / start / end / quote / comma / parenthesis to avoid
    # matching inside arbitrary words. Extensions match the tool surface.
    _file_ext_re = re.compile(
        r"(?:^|[\s'\"`(\[,])"
        r"[A-Za-z0-9_\-]+\.(?:csv|tsv|json|jsonl|parquet|sqlite|db|md|txt|xml|yaml|yml|html|xlsx|xls|pdf)"
        r"(?:$|[\s'\"`)\],.;:!?])"
    )
    upstream_has_explicit_path = bool(
        _slash_path_re.search(summaries_blob)
        or _file_ext_re.search(summaries_blob)
    )
    path_hint = ""
    if not upstream_has_explicit_path:
        path_hint = (
            "\n\nNote: the upstream summaries above do NOT state file paths "
            "verbatim. Before reading any file, call `list_context` (depth=2 "
            "or higher) to discover the actual layout — files often live "
            "under subdirs like `csv/`, `json/`, `doc/`, `db/`, not at the "
            "context root. Guessing the path will cost 3-5 turns on "
            "FileNotFoundError; one `list_context` call is far cheaper."
        )

    suggested_tools = ", ".join(node.suggested_tools) if node.suggested_tools else "(none)"

    if is_final:
        completion_instruction = (
            "This is the FINAL node. After you have the result table, call the "
            "`answer` tool directly. Do NOT call `mark_node_done` for this node.\n"
            "\n"
            "**Before calling `answer`, decide the MINIMAL column set:** the\n"
            "grader penalises every column not in the gold answer. Re-read the\n"
            "question literally and pick the smallest table that fully answers it.\n"
            "Defaults by question pattern (deviate only with strong evidence):\n"
            "  * 'how many / count / average / max / min / percentage / what is the X'\n"
            "    → 1 column (just the value/count, no id, no name, no labels).\n"
            "  * 'which X had the most/least Y' → 1 column (just X).\n"
            "  * 'list the names / ids of X' → 1 column.\n"
            "  * 'for each Y, the X' → exactly 2 columns (Y, X).\n"
            "Do NOT pad with id, description, category, supporting fields, or\n"
            "raw timestamps unless the question literally asks for them. When\n"
            "torn between fewer and more columns, ALWAYS pick fewer.\n"
            "\n"
            "**But never drop a column the question literally names.** The\n"
            "'minimal' rule only trims columns NOT in the question — it does\n"
            "NOT trim columns the question explicitly asks for. If the\n"
            "question says 'list schools and their funding type' you MUST\n"
            "keep both `school` and `funding type` (2 columns). If it says\n"
            "'for each athlete, their height and weight' you MUST keep all\n"
            "three (athlete, height, weight). Re-read the question; every\n"
            "noun-phrase joined by 'and' / 'with' / 'along with' / 'plus' /\n"
            "'for each X, the Y' is a required column. Trimming below that\n"
            "floor causes recall=0 even when your numbers are correct.\n"
            "\n"
            "**Format every cell before submitting:**\n"
            "  * Null / missing → empty string \"\" (NOT \"None\" / \"NaN\" / \"<NA>\").\n"
            "  * Numbers → str(raw_value) WITHOUT rounding or zero-padding;\n"
            "    the grader is byte-level so a gold of \"52.17391304347826\"\n"
            "    will not match \"52.17\". Do NOT call round(), \"{:.2f}\".format(),\n"
            "    or Decimal.quantize(). Bare integers for plain counts\n"
            "    (\"how many X?\" → \"4\", not \"4.00\") are the only exception.\n"
            "  * Dates → ISO `YYYY-MM-DD` with zero-padded month/day\n"
            "    (\"2024-3-1\" → \"2024-03-01\").\n"
            "  * DateTime with timezone → convert to UTC and suffix `Z`;\n"
            "    DateTime without timezone → keep original ISO format.\n"
            "  * Strings → strip leading/trailing whitespace and \\r\\n; preserve\n"
            "    the source casing exactly (\"East Asia\" ≠ \"east asia\").\n"
            "Convert pandas/numpy values to plain Python str / int / float\n"
            "(or formatted strings) before calling `answer` — never leave\n"
            "numpy.int64 / numpy.nan / pandas.Timestamp / NaT in `rows`.\n"
            "\n"
            "**Row-count sanity check (catches a class of zero-score bugs):**\n"
            "  * 'how many / count / total / sum / average / what is the X'\n"
            "    → exactly 1 row. If your answer has >1 row, you forgot to\n"
            "    aggregate (add COUNT/SUM/AVG or len(df)).\n"
            "  * 'list / what are the / which X' → check whether the result\n"
            "    needs DISTINCT / drop_duplicates; if the filter could match\n"
            "    many rows but you only have 1, you likely have a stray\n"
            "    LIMIT 1 or wrong grouping.\n"
            "  * 'top N' / 'first N' / 'N largest' → exactly N rows.\n"
            "  * 'for each Y, the X' / 'X by Y' → one row per distinct Y\n"
            "    (need GROUP BY Y, not raw detail rows).\n"
            "  * 'winner of / which X had the most Y' → exactly 1 row\n"
            "    (need ORDER BY Y DESC LIMIT 1)."
        )
    else:
        completion_instruction = (
            f"When you have produced the expected output, call `mark_node_done` "
            f"with node_id='{node.id}' and a concise factual summary."
        )

    return HumanMessage(
        content=(
            f"Question (for context): {task.question}\n\n"
            f"You are now FOCUSED on DAG node:\n"
            f"  id: {node.id}\n"
            f"  goal: {node.goal}\n"
            f"  expected_output: {node.expected_output or '(unspecified)'}\n"
            f"  suggested_tools: {suggested_tools}\n\n"
            f"Upstream nodes you depend on:\n{deps_block}"
            f"{path_hint}\n\n"
            f"{completion_instruction}"
        )
    )

# --------- Trace conversion -----------------------------------------------


def _render_tool_calls_for_trace(tool_calls: list[Any]) -> str:
    """Render an AIMessage's ``tool_calls`` array into a human-readable JSON string.

    Used as the fallback for ``raw_response`` on tool-call trace rows whose
    AIMessage carried no natural-language ``content`` (the common case for
    Qwen via DashScope's OpenAI-compatible endpoint, which leaves ``content``
    empty whenever the model decides to call a tool). Without this fallback,
    ~95% of trace.json's tool-call rows showed ``raw_response: ""`` even
    though the model DID respond — just structurally instead of textually.

    Output shape (multi-call AIMessages produce a JSON array, single-call
    produces a single object so the common case stays compact):

        {"name": "execute_context_sql", "args": {"path": "...", "sql": "..."}}

    The ``id`` field is dropped: it is a tracing-only opaque string that
    adds noise without helping a human reader understand the call.
    """

    if not tool_calls:
        return ""

    rendered: list[dict[str, Any]] = []
    for call in tool_calls:
        # tool_calls items can be either LangChain ``ToolCall`` TypedDicts
        # (common case) or attribute-style objects depending on the chat
        # model adapter; getattr-then-fallback keeps both shapes working.
        if hasattr(call, "get"):
            name = call.get("name", "")
            args = call.get("args") or {}
        else:
            name = getattr(call, "name", "")
            args = getattr(call, "args", None) or {}
        rendered.append({"name": name, "args": args})

    payload: Any = rendered[0] if len(rendered) == 1 else rendered
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        # Last-ditch fallback: ``args`` may contain non-JSON-serialisable
        # objects (rare — args usually pass through Pydantic). repr() keeps
        # the trace row non-empty without crashing trace generation.
        return repr(payload)


def _coerce_observation(message: BaseMessage) -> dict[str, Any]:
    """Best-effort conversion of a LangChain message to the legacy observation dict."""

    if isinstance(message, ToolMessage):
        content = message.content
        # Tool returns are usually dict|str; keep dict shape if available.
        if isinstance(content, dict):
            payload: dict[str, Any] = dict(content)
        else:
            payload = {"content": content}
        return {
            "ok": getattr(message, "status", "success") != "error",
            "tool": getattr(message, "name", None),
            "content": payload,
        }
    return {"ok": True, "content": {"raw": str(message.content)}}


def _build_step_records(
    messages: list[BaseMessage],
    *,
    dag_events: list[dict[str, Any]],
    reflection_notes: list[str],
) -> list[StepRecord]:
    """Convert LangGraph messages + DAG audit log into legacy ``StepRecord`` list.

    Strategy:
    1. The full ordering of "what happened in time" is reconstructed by
       weaving two streams together:

       * **Tool stream**: every ``AIMessage`` (paired with its following
         ``ToolMessage``) — produces real tool-call steps and pure-text
         "assistant text" steps.
       * **DAG stream**: events recorded by planner / scheduler / replanner
         / mark_node_done — produces synthetic ``__plan__`` /
         ``__dag_node_start__`` / ``__dag_node_done__`` / ``__replan__``
         steps.

       Because the DAG stream is "infrequent control-flow events" while the
       tool stream is "fine-grained per-message events", we interleave by
       inserting DAG events at coarse boundaries:

       * ``__plan__`` and any leading ``__replan__`` events go BEFORE the
         tool stream.
       * ``__dag_node_start__`` is inserted just before the first AIMessage
         that follows the corresponding scheduler turn; we approximate this
         by emitting all queued ``node_start`` events whenever we encounter
         a HumanMessage that looks like a focused-node prompt.
       * ``__dag_node_done__`` is emitted right after the AIMessage whose
         tool_calls included ``mark_node_done``.

       This is approximate but matches reality closely enough for trace
       visualisation; the per-event payloads carry the canonical info.

    2. Reflection verdicts are appended at the very end as before.
    """

    records: list[StepRecord] = []
    step_index = 0

    # ---- 1. Bucket DAG events by kind --------------------------------------
    plan_events = [e for e in dag_events if e["kind"] == "plan"]
    replan_events = [e for e in dag_events if e["kind"] == "replan"]
    node_start_events = [e for e in dag_events if e["kind"] == "node_start"]
    node_done_events = [e for e in dag_events if e["kind"] == "node_done"]
    node_attempt_failed_events = [
        e for e in dag_events if e["kind"] == "node_attempt_failed"
    ]
    graph_node_events = [e for e in dag_events if e["kind"] == "graph_node"]

    # ---- 2. Emit the initial plan step (always present after planner runs) -
    if plan_events:
        first_plan = plan_events[0]
        step_index += 1
        records.append(
            StepRecord(
                step_index=step_index,
                thought="Planner produced an initial DAG plan.",
                action="__plan__",
                action_input={},
                raw_response=first_plan.get("raw", ""),
                observation={
                    "ok": first_plan.get("parse_error") is None,
                    "content": {
                        "dag": first_plan.get("dag", {}),
                        "parse_error": first_plan.get("parse_error"),
                    },
                },
                ok=first_plan.get("parse_error") is None,
            )
        )

    # ---- 3. Index ToolMessages by tool_call_id for O(1) pairing -----------
    tool_messages_by_call_id: dict[str, ToolMessage] = {}
    for message in messages:
        if isinstance(message, ToolMessage) and message.tool_call_id:
            tool_messages_by_call_id[message.tool_call_id] = message

    # Iterators we drain as we walk the message stream.
    pending_node_starts = list(node_start_events)
    pending_node_done = {e["node_id"]: e for e in node_done_events}
    pending_replans = list(replan_events)
    pending_attempt_failures = list(node_attempt_failed_events)

    def _emit_pending_node_starts() -> None:
        """Emit __dag_node_start__ for every queued node_start event."""

        nonlocal step_index
        while pending_node_starts:
            event = pending_node_starts.pop(0)
            step_index += 1
            records.append(
                StepRecord(
                    step_index=step_index,
                    thought=(
                        f"Scheduler focused DAG node {event.get('node_id')}."
                    ),
                    action="__dag_node_start__",
                    action_input={"node_id": event.get("node_id", "")},
                    raw_response="",
                    observation={
                        "ok": True,
                        "content": {
                            "node_id": event.get("node_id"),
                            "goal": event.get("goal"),
                            "is_final": event.get("is_final"),
                            "attempt": event.get("attempt"),
                        },
                    },
                    ok=True,
                )
            )

    def _emit_pending_replans() -> None:
        """Emit __replan__ events for any queued replans."""

        nonlocal step_index
        while pending_replans:
            event = pending_replans.pop(0)
            step_index += 1
            records.append(
                StepRecord(
                    step_index=step_index,
                    thought="Replanner produced a new DAG plan.",
                    action="__replan__",
                    action_input={},
                    raw_response=event.get("raw", ""),
                    observation={
                        "ok": event.get("parse_error") is None,
                        "content": {
                            "dag": event.get("dag", {}),
                            "failure_reason": event.get("failure_reason"),
                            "parse_error": event.get("parse_error"),
                            "attempt": event.get("attempt"),
                        },
                    },
                    ok=event.get("parse_error") is None,
                )
            )

    def _emit_pending_attempt_failures() -> None:
        nonlocal step_index
        while pending_attempt_failures:
            event = pending_attempt_failures.pop(0)
            step_index += 1
            records.append(
                StepRecord(
                    step_index=step_index,
                    thought=(
                        f"Node {event.get('node_id')} attempt #{event.get('attempt')} "
                        "exhausted its step budget."
                    ),
                    action="__node_attempt_failed__",
                    action_input={"node_id": event.get("node_id", "")},
                    raw_response="",
                    observation={
                        "ok": False,
                        "content": {
                            "node_id": event.get("node_id"),
                            "attempt": event.get("attempt"),
                            "cap": event.get("cap"),
                        },
                    },
                    ok=False,
                )
            )

    def _append_graph_node_event(event: dict[str, Any]) -> None:
        nonlocal step_index
        graph_node = str(event.get("graph_node", ""))
        if not graph_node:
            return
        step_index += 1
        records.append(
            StepRecord(
                step_index=step_index,
                thought=(
                    str(event.get("description"))
                    if event.get("description")
                    else f"LangGraph node {graph_node} is active."
                ),
                action="__graph_node__",
                action_input={
                    "graph_node": graph_node,
                    "node_id": event.get("node_id", ""),
                },
                raw_response="",
                observation={"ok": True, "content": {}},
                ok=True,
            )
        )

    # ---- 4. Walk the message stream, weaving in DAG events ----------------
    # Heuristic: a HumanMessage starting with "You are now FOCUSED on DAG node"
    # is the focused-node prompt installed by the scheduler. Use it as the
    # signal to flush queued node_start events. (Independent of LLM output.)
    for message in messages:
        if isinstance(message, HumanMessage):
            text = (
                message.content
                if isinstance(message.content, str)
                else str(message.content)
            )
            if "You are now FOCUSED on DAG node" in text:
                _emit_pending_node_starts()
            continue

        if not isinstance(message, AIMessage):
            continue

        thought_text = ""
        if isinstance(message.content, str):
            thought_text = message.content
        elif isinstance(message.content, list):
            text_chunks = [
                chunk.get("text", "")
                for chunk in message.content
                if isinstance(chunk, dict)
            ]
            thought_text = "\n".join(chunk for chunk in text_chunks if chunk)

        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            # Pure assistant text without tool calls (e.g. early stop / nudge target).
            # Skip totally empty turns: they are LLM glitches that the runtime
            # already recovers via the `nudge` node, and recording them in
            # the trace just adds noise + makes the agent look like it
            # "wasted steps" when in fact the per-node budget was not charged
            # (see executor_node's _is_useful_executor_turn check).
            if not thought_text.strip():
                continue
            step_index += 1
            records.append(
                StepRecord(
                    step_index=step_index,
                    thought=thought_text,
                    action="__assistant_text__",
                    action_input={},
                    raw_response=thought_text,
                    observation={"ok": True, "content": {"text": thought_text}},
                    ok=True,
                )
            )
            continue

        # Pre-render a JSON view of the entire tool_calls array. We use this
        # as the fallback ``raw_response`` for tool-call steps when the
        # AIMessage carried no natural-language ``content`` — the common
        # case for Qwen via DashScope's OpenAI-compatible endpoint, which
        # returns empty ``content`` whenever the assistant decides to call
        # a tool. Without this fallback, ~95% of trace.json's tool-call
        # rows had ``raw_response: ""`` even though the model DID respond
        # (just structurally instead of textually), making the trace look
        # like the LLM was silent.
        tool_calls_json = _render_tool_calls_for_trace(tool_calls)

        finished_node_ids: list[str] = []
        for call in tool_calls:
            step_index += 1
            tool_name = call.get("name", "")
            tool_args = call.get("args") or {}
            call_id = call.get("id", "")
            paired = tool_messages_by_call_id.get(call_id)
            observation = (
                _coerce_observation(paired)
                if paired is not None
                else {"ok": False, "content": {"error": "Tool result missing."}}
            )
            # Prefer the model's natural-language thought when present; fall
            # back to the structural tool_calls JSON so a human skimming the
            # trace can always see "what the model actually responded with".
            # Same string is used for every call in a multi-call AIMessage
            # because ``raw_response`` represents the whole assistant turn,
            # not a per-call slice (matches the legacy 1-call-per-turn case).
            raw_response_text = thought_text if thought_text else tool_calls_json
            records.append(
                StepRecord(
                    step_index=step_index,
                    thought=thought_text if thought_text else "",
                    action=tool_name,
                    action_input=dict(tool_args) if isinstance(tool_args, dict) else {},
                    raw_response=raw_response_text,
                    observation=observation,
                    ok=bool(observation.get("ok", True)),
                )
            )
            if (
                tool_name == "mark_node_done"
                and bool(observation.get("ok", True))
                and isinstance(tool_args, dict)
            ):
                finished_node_ids.append(str(tool_args.get("node_id", "")))

        # After every AIMessage that finished one or more nodes, emit the
        # corresponding __dag_node_done__ steps in the order they were called.
        for node_id in finished_node_ids:
            event = pending_node_done.pop(node_id, None)
            if event is None:
                continue
            step_index += 1
            records.append(
                StepRecord(
                    step_index=step_index,
                    thought=f"Executor signalled DAG node {node_id} as done.",
                    action="__dag_node_done__",
                    action_input={"node_id": node_id},
                    raw_response=event.get("summary", ""),
                    observation={
                        "ok": True,
                        "content": {
                            "node_id": node_id,
                            "summary": event.get("summary"),
                        },
                    },
                    ok=True,
                )
            )
        # Replans usually follow a node_attempt_failed; emit any queued
        # control-flow events here so they appear in roughly the right place.
        _emit_pending_attempt_failures()
        _emit_pending_replans()
        # A replan re-focuses a node; flush any newly queued node_starts too.
        _emit_pending_node_starts()

    # ---- 5. Drain anything left (defensive) -------------------------------
    _emit_pending_attempt_failures()
    _emit_pending_replans()
    _emit_pending_node_starts()

    # ---- 6. Reflection verdicts at the tail -------------------------------
    for note in reflection_notes:
        step_index += 1
        records.append(
            StepRecord(
                step_index=step_index,
                thought="Reflector verdict.",
                action="__reflect__",
                action_input={},
                raw_response=note,
                observation={"ok": True, "content": {"verdict": note}},
                ok=True,
            )
        )

    # ---- 7. LangGraph node markers at the final tail -----------------------
    # Partial trace writes these markers live during execution. The final
    # trace is rebuilt from messages + dag_events after invoke returns, so we
    # must preserve them here as well; otherwise a terminal `finalize` marker
    # can be visible live and then disappear when trace.json is finalized.
    # Keep these after reflection verdicts so the UI's "last recognizable
    # graph node" remains `finalize` at terminal state.
    for event in graph_node_events:
        _append_graph_node_event(event)

    return records


# --------- Agent ----------------------------------------------------------


class LangGraphAgent:
    """Multi-node LangGraph agent that mirrors the legacy ``ReActAgent`` API."""

    def __init__(
        self,
        *,
        model: ChatOpenAI,
        config: LangGraphAgentConfig | None = None,
    ) -> None:
        self.model = model
        self.config = config or LangGraphAgentConfig()

    # --- Per-task graph wiring ------------------------------------------

    def _build_graph(
        self,
        *,
        task: PublicTask,
        tools: list[BaseTool],
        tool_run_context: ToolRunContext,
        reflection_notes: list[str],
        task_output_dir: Path | None = None,
    ) -> Any:
        executor_llm = self.model.bind_tools(tools)
        # ``handle_tool_errors`` keeps tool exceptions inside the graph: each
        # exception becomes a ToolMessage(status="error") fed back to the
        # executor on the next turn so it can self-correct (e.g. retry with
        # the right path). Without this, a single FileNotFoundError from
        # ``read_csv`` escapes the StateGraph and crashes the whole task,
        # which is exactly what we observed wiping out 23/50 tasks in the
        # 20260502T060003Z run.
        tool_node = ToolNode(tools, handle_tool_errors=_format_tool_error)
        max_reflections = self.config.max_reflections
        max_idle_nudges = self.config.max_idle_nudges
        max_replans = self.config.max_replans
        max_node_attempts = self.config.max_node_attempts
        max_steps_per_node = self.config.max_steps_per_node

        # Dynamic per-node cap. The static `max_steps_per_node=12` is sized for
        # a typical 3-4 node DAG where each node has a single, well-scoped job.
        # Two failure modes pushed real tasks past the cap:
        #   (a) Tiny DAGs (1-2 nodes): each node has to do MORE work because
        #       the planner couldn't decompose further. We give those a 1.5×
        #       multiplier so the executor has room to inspect, parse, and
        #       summarise within a single node.
        #   (b) Aggregation / final nodes with many upstream dependencies:
        #       cross-referencing N upstream summaries naturally costs more
        #       turns. We add +3 turns per direct dependency beyond the first.
        # The result is clamped to [base, 2×base] so a planner that emits a
        # pathological "1 mega-node" DAG still can't blow past the global
        # budget (max_replans × max_node_attempts × cap).
        def _dynamic_node_step_cap() -> int:
            dag_state = tool_run_context.dag_state
            dag = dag_state.dag
            base = max_steps_per_node
            if dag is None:
                return base

            cap = base
            node_count = len(dag.nodes)
            if node_count <= 2:
                cap = int(round(base * 1.5))

            current_id = dag_state.current_node_id
            if current_id is not None:
                current_node = dag.node_by_id(current_id)
                if current_node is not None:
                    extra_deps = max(0, len(current_node.depends_on) - 1)
                    cap += 3 * extra_deps
                    # The final node tends to also be the answer-producing node;
                    # give it a small flat boost so it isn't starved by an
                    # otherwise long upstream chain.
                    if current_id == dag.final_node_id and node_count >= 3:
                        cap += 2

            absolute_max = base * 2
            return max(base, min(cap, absolute_max))

        def _render_dag_if_enabled(title: str | None = None) -> None:
            """Best-effort live DAG visualization → ``<task_output_dir>/dag.svg``.

            No-op when ``task_output_dir`` was not provided (e.g. unit
            tests). All rendering exceptions are caught here so that
            visualization side-effects can never crash an in-flight task.
            """

            if task_output_dir is None:
                return
            dag_state = tool_run_context.dag_state
            if dag_state.dag is None:
                return
            try:
                render_dag(
                    output_dir=task_output_dir,
                    dag=dag_state.dag,
                    dag_state=dag_state,
                    title=title,
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[langgraph_agent] DAG visualization failed: {exc}",
                    file=sys.stderr,
                )

        # Helper used by both planner_node and replanner_node.
        def _invoke_planner_llm(
            *, system_prompt: str, user_payload: str
        ) -> tuple[PlanDAG, str, str | None]:
            """Run an LLM planner round. Returns (dag, raw_text, parse_error)."""
            response = _invoke_with_retry(
                lambda: self.model.invoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_payload),
                    ]
                ),
                label="planner",
            )
            raw_text = (
                response.content
                if isinstance(response.content, str)
                else str(response.content)
            )
            try:
                return _parse_plan_dag(raw_text), raw_text, None
            except PlanParseError as exc:
                # Fall back to the trivial 1-node DAG so the rest of the graph
                # can still make progress; record the reason for the trace.
                return _fallback_plan_dag(task), raw_text, str(exc)

        # ------- Nodes -------

        def planner_node(state: AgentState) -> dict[str, Any]:
            tool_names = ", ".join(
                sorted(
                    tool.name
                    for tool in tools
                    if tool.name not in {ANSWER_TOOL_NAME, MARK_NODE_DONE_TOOL_NAME}
                )
            )
            # Anti-hallucination prelude: hand the planner the actual file
            # layout + sqlite schemas + json/csv heads so it never invents
            # a path. See docs/00-executive-summary.md §4 (Schema Profiling).
            dataset_profile = _build_dataset_profile(task)
            user_payload = (
                f"Question: {task.question}\n"
                f"Available inspection tools: {tool_names}\n\n"
                f"Dataset profile (REAL files under context/):\n"
                f"{dataset_profile}\n\n"
                "Produce the DAG plan now (JSON only). "
                "Use ONLY paths and table names that appear in the profile above."
            )
            dag, raw_text, parse_error = _invoke_planner_llm(
                system_prompt=PLANNER_SYSTEM_PROMPT, user_payload=user_payload
            )
            tool_run_context.dag_state.install(dag)
            tool_run_context.dag_state.record_event(
                "plan",
                raw=raw_text,
                dag=dag.to_dict(),
                parse_error=parse_error,
            )
            logger.info(
                "planner task_id=%s nodes=%d final=%s parse_error=%s",
                task.task_id,
                len(dag.nodes),
                dag.final_node_id,
                parse_error or "none",
            )
            _render_dag_if_enabled(title=f"Plan — {task.task_id}")

            executor_seed: list[BaseMessage] = [
                SystemMessage(content=EXECUTOR_SYSTEM_PROMPT),
                _question_user_message(task),
            ]
            return {
                "messages": executor_seed,
                "reflections_used": 0,
                "idle_nudges_used": 0,
                "steps_in_current_node": 0,
                "pending_replan_reason": None,
                "finalized": False,
            }

        def replanner_node(state: AgentState) -> dict[str, Any]:
            dag_state = tool_run_context.dag_state
            previous_dag_dict = (
                dag_state.dag.to_dict() if dag_state.dag is not None else None
            )
            failure_reason = state.get("pending_replan_reason") or "(unspecified)"
            # Re-build the dataset profile so the replanner can fix path /
            # table-name hallucinations that caused the previous failure.
            dataset_profile = _build_dataset_profile(task)
            user_payload = (
                f"Question: {task.question}\n\n"
                f"Dataset profile (REAL files under context/):\n"
                f"{dataset_profile}\n\n"
                f"Previous DAG plan (JSON):\n{json.dumps(previous_dag_dict, indent=2)}\n\n"
                f"Per-node status: {dict(dag_state.node_status)}\n"
                f"Per-node summaries: {dict(dag_state.node_outputs)}\n"
                f"Failure reason: {failure_reason}\n\n"
                "Produce a NEW DAG plan now (JSON only). "
                "Use ONLY paths and table names that appear in the profile above."
            )
            dag, raw_text, parse_error = _invoke_planner_llm(
                system_prompt=REPLANNER_SYSTEM_PROMPT, user_payload=user_payload
            )
            dag_state.install(dag)
            dag_state.replan_count += 1
            dag_state.record_event(
                "replan",
                raw=raw_text,
                dag=dag.to_dict(),
                failure_reason=failure_reason,
                parse_error=parse_error,
                attempt=dag_state.replan_count,
            )
            logger.warning(
                "replanner task_id=%s attempt=%d/%d trigger=%s nodes=%d",
                task.task_id,
                dag_state.replan_count,
                max_replans,
                failure_reason,
                len(dag.nodes),
            )
            _render_dag_if_enabled(
                title=f"Replan #{dag_state.replan_count} — {task.task_id}"
            )
            # The executor's prior conversation no longer matches the new DAG;
            # reset to the seed so it doesn't try to "continue" old work.
            executor_seed: list[BaseMessage] = [
                SystemMessage(content=EXECUTOR_SYSTEM_PROMPT),
                _question_user_message(task),
            ]
            return {
                "messages": executor_seed,
                "idle_nudges_used": 0,
                "steps_in_current_node": 0,
                "pending_replan_reason": None,
            }

        def dag_scheduler_node(state: AgentState) -> dict[str, Any]:
            """Pick the next ready DAG node and seed the executor with a focused prompt.

            Drains any pending ``mark_node_done`` signals (already applied by
            the tool itself; this is just for the trace event log). Then:

            * If the final node is done → no-op (router will go to reflector).
            * If a ready node exists → focus it, seed prompt, return.
            * Otherwise (stuck) → set ``pending_replan_reason`` so the router
              picks the replanner branch.
            """

            del state  # status comes from tool_run_context, not from graph state
            dag_state = tool_run_context.dag_state
            dag = dag_state.dag
            if dag is None:
                # Should not happen: planner runs first.
                return {"pending_replan_reason": "DAG not initialised"}

            # Drain done signals (just for tracing — status was already updated).
            tool_run_context.pending_node_done_signals.clear()

            # All nodes done → router will route to reflector via _scheduler_route.
            if _all_nodes_done(dag_state.node_status):
                return {"steps_in_current_node": 0}

            ready = _ready_node(dag, dag_state.node_status)
            if ready is None:
                # No ready node and not all done — stuck. Trigger replan.
                return {
                    "pending_replan_reason": (
                        "Scheduler stuck: no ready node found, "
                        f"status={dict(dag_state.node_status)}"
                    )
                }

            dag_state.node_status[ready.id] = "in_progress"
            dag_state.current_node_id = ready.id
            is_final = ready.id == dag.final_node_id
            upstream_summaries = {
                dep_id: dag_state.node_outputs.get(dep_id, "")
                for dep_id in ready.depends_on
            }
            focused_message = _focused_executor_prompt(
                task=task,
                dag=dag,
                node=ready,
                upstream_summaries=upstream_summaries,
                is_final=is_final,
            )
            dag_state.record_event(
                "node_start",
                node_id=ready.id,
                goal=ready.goal,
                is_final=is_final,
                attempt=dag_state.node_attempts.get(ready.id, 0) + 1,
            )
            _render_dag_if_enabled(title=f"Running {ready.id} — {task.task_id}")
            return {
                "messages": [focused_message],
                "steps_in_current_node": 0,
            }

        def executor_node(state: AgentState) -> dict[str, Any]:
            # ---- Soft guards: pre-LLM message injection -------------------
            # Two cheap interventions to prevent stuck-loop / budget-blowout
            # patterns observed on prior runs:
            #   1. **Repeated tool-call detection** (task_80 style): the
            #      executor called `query_dataframe` 4× with identical args
            #      and burned ~22 step budget exploring nothing new.
            #   2. **Step-budget soft warning** (task_396 / task_418 style):
            #      executor was still on `execute_python` exploration at
            #      step 25/30 instead of submitting its best answer.
            # Both guards inject a one-shot SystemMessage *before* the LLM
            # is invoked, so the model sees the warning as part of context
            # for THIS turn. We also persist the injected message in state
            # via the returned ``messages`` list so trace.json captures the
            # nudge for debugging.
            existing_messages = state["messages"]
            extra_pre_messages: list[BaseMessage] = []

            repeat_sig = _detect_repeated_tool_calls(existing_messages, window=3)
            if repeat_sig is not None:
                tool_name, _args = repeat_sig
                # Avoid re-injecting on every executor turn once the warning
                # already sits in the trail: if the most recent SystemMessage
                # was already a repeat-detection nudge, skip — the model
                # has seen it and either honoured or ignored it.
                already_warned = any(
                    isinstance(m, SystemMessage)
                    and isinstance(m.content, str)
                    and "called `" in m.content
                    and "with identical args" in m.content
                    for m in existing_messages[-5:]
                )
                if not already_warned:
                    extra_pre_messages.append(
                        SystemMessage(
                            content=(
                                f"You have called `{tool_name}` with IDENTICAL "
                                "arguments three turns in a row. Repeating the "
                                "same call will not return different data. You "
                                "MUST either (a) change at least one parameter "
                                "(different path, different SQL/regex, different "
                                "slice), (b) switch to a different tool, or (c) "
                                "stop exploring and call `answer` (final node) / "
                                "`mark_node_done` (other nodes) with your best "
                                "current result right now."
                            )
                        )
                    )

            # ---- read_doc overuse detection (task_344 / 352 / 418) -------
            # Different from the IDENTICAL-args repeat above: here the
            # executor varies the args every turn (offset / grep / slice)
            # but never converges, and burns 8-12 read_doc calls before
            # the per-node budget kills the node. Threshold=4 gives 3
            # honest tries before nudging (matches the existing prompt
            # "never call read_doc more than 3 times on the same path").
            if _detect_tool_overuse(
                existing_messages, tool_name="read_doc", threshold=4
            ):
                already_overuse_warned = any(
                    isinstance(m, SystemMessage)
                    and isinstance(m.content, str)
                    and "called `read_doc`" in m.content
                    and "Switch tactics" in m.content
                    for m in existing_messages[-5:]
                )
                if not already_overuse_warned:
                    extra_pre_messages.append(
                        SystemMessage(
                            content=(
                                "You have called `read_doc` 4+ times in this "
                                "DAG node and still don't have the answer. "
                                "More pagination/grep on the same doc family "
                                "is unlikely to help. Switch tactics NOW: "
                                "(a) call `list_context` to confirm you are "
                                "reading the right file (the doc you need "
                                "may live under a different subdirectory), "
                                "(b) use `execute_python` to load the file "
                                "with custom regex / structured parsing for "
                                "a one-shot extraction, or (c) commit your "
                                "best partial result via `mark_node_done` "
                                "(non-final node) / `answer` (final node) "
                                "so downstream can proceed. Do NOT call "
                                "`read_doc` again."
                            )
                        )
                    )

            # Step-budget soft warning. Use the same dynamic cap the router
            # uses so the threshold tracks node-specific budgets (tiny DAGs
            # get 1.5×, multi-dep nodes get +3 per dep).
            step_index = state.get("steps_in_current_node", 0)
            dynamic_cap = _dynamic_node_step_cap()
            warn_threshold = max(1, int(dynamic_cap * 0.7))
            if step_index >= warn_threshold:
                already_budget_warned = any(
                    isinstance(m, SystemMessage)
                    and isinstance(m.content, str)
                    and "low on per-node steps" in m.content
                    for m in existing_messages[-3:]
                )
                if not already_budget_warned:
                    extra_pre_messages.append(
                        SystemMessage(
                            content=(
                                f"You are running low on per-node steps "
                                f"({step_index}/{dynamic_cap} used). Stop "
                                "exploring; commit your best current result "
                                "now — call `answer` (final node) or "
                                "`mark_node_done` (other nodes) with what you "
                                "have, even if it is partial. Spending the "
                                "remaining budget on more inspection will "
                                "leave you with NO answer."
                            )
                        )
                    )

            tool_run_context.dag_state.record_event(
                "graph_node",
                graph_node="executor",
                node_id=tool_run_context.dag_state.current_node_id or "",
                description="Executor is deciding the next action.",
            )
            invoke_messages = existing_messages + extra_pre_messages
            response = _invoke_with_retry(
                lambda: executor_llm.invoke(invoke_messages),
                label="executor",
            )
            # Bug fix: empty AIMessage turns (no tool_calls AND no textual
            # content) used to consume one unit of `steps_in_current_node`,
            # which caused real tool-using turns to be starved out by a few
            # spurious empty turns from the LLM (observed on Qwen via the
            # OpenAI-compatible endpoint). The `nudge` node will recover such
            # idle turns cheaply via `max_idle_nudges`, so we only charge the
            # per-node budget when the executor actually produced something
            # useful (tool call or non-empty text).
            if _is_useful_executor_turn(response):
                step_delta = 1
            else:
                step_delta = 0

            # ---- Live flush: record executor turn for real-time UI --------
            # Extract tool call names for the partial trace so Timeline /
            # AgentGraph update during the run, not only after it finishes.
            tool_call_names: list[str] = []
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_call_names = [tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in response.tool_calls]
            response_text = ""
            if hasattr(response, "content") and isinstance(response.content, str):
                response_text = response.content[:200]
            tool_run_context.dag_state.record_event(
                "executor_turn",
                node_id=tool_run_context.dag_state.current_node_id or "",
                tool_calls=tool_call_names,
                text_preview=response_text,
                step_in_node=state.get("steps_in_current_node", 0) + step_delta,
            )

            # Persist injected guard messages alongside the response so
            # trace.json + reflector both see the warning. ``add_messages``
            # reducer concatenates the list to state["messages"].
            return {
                "messages": [*extra_pre_messages, response],
                "steps_in_current_node": state.get("steps_in_current_node", 0) + step_delta,
            }

        def reasoning_node(state: AgentState) -> dict[str, Any]:
            """Force a textual Reason → Act trail in front of every tool call.

            Why this exists: Qwen via DashScope's OpenAI-compatible endpoint
            almost always returns ``content=""`` when it decides to call a
            tool — only the structured tool_calls come back. The trace then
            looks like a stream of opaque actions with no thought attached,
            which (a) makes debugging miserable and (b) starves the
            reflector of reasoning to judge against. This node intercepts
            executor turns that have tool_calls but no content, asks a
            second LLM call to narrate the intent in 1-3 sentences, and
            REPLACES the executor's AIMessage in-place (same id → the
            ``add_messages`` reducer overwrites instead of appending) so
            the conversation still reads as a single assistant turn whose
            content + tool_calls are aligned. The OpenAI tool-message
            pairing protocol stays intact (no extra AIMessage between
            tool_calls and their ToolMessage replies).

            Short-circuit: when the executor already provided non-empty
            content (rare on Qwen, common on GPT-4 / Claude), we return
            ``{}`` and skip the LLM round-trip entirely — no need to spend
            tokens narrating reasoning the model already produced.
            """

            last_ai = _last_ai_message(state["messages"])
            if last_ai is None or not _has_pending_tool_calls(last_ai):
                # Nothing to narrate. Defensive: route_after_executor only
                # routes here when both conditions hold, but stay safe.
                return {}

            def _record_tools_node() -> None:
                tool_run_context.dag_state.record_event(
                    "graph_node",
                    graph_node="tools",
                    node_id=tool_run_context.dag_state.current_node_id or "",
                    description="Tools is executing the selected tool call.",
                )

            # Short-circuit: model already gave us a thought. Trace will
            # render it as the tool-call row's `thought` / `raw_response`.
            if _ai_message_text(last_ai).strip():
                _record_tools_node()
                return {}

            # Build the narration prompt. We pass the message history MINUS
            # the executor's last AIMessage and re-encode its tool_calls as
            # plain text inside the trailing HumanMessage. Why: the
            # narrator LLM is invoked WITHOUT bind_tools, and OpenAI-style
            # backends (incl. DashScope) reject a request whose final
            # message is an `AIMessage(tool_calls=[...])` not followed by
            # a matching ToolMessage — the protocol assumes tool_calls are
            # always either being declared (with `tools=[...]`) or being
            # answered. Stripping the AIMessage and inlining the call as
            # text sidesteps both constraints, while still giving the
            # narrator the full upstream context (focused-node prompt,
            # prior tool results) it needs to produce specific reasoning.
            tool_run_context.dag_state.record_event(
                "graph_node",
                graph_node="reasoning",
                node_id=tool_run_context.dag_state.current_node_id or "",
                description="Reasoning is narrating why the selected tool call is needed.",
            )
            tool_calls_summary = _render_tool_calls_for_trace(
                list(last_ai.tool_calls or [])
            )
            narration_response = _invoke_with_retry(
                lambda: self.model.invoke(
                    [
                        SystemMessage(content=REASONING_SYSTEM_PROMPT),
                        *state["messages"][:-1],
                        HumanMessage(
                            content=(
                                "The assistant just decided to make the "
                                "following tool call(s):\n\n"
                                f"{tool_calls_summary}\n\n"
                                "Narrate, in 1-3 plain-English sentences, "
                                "WHY this specific call (those exact "
                                "arguments) was the right next move given "
                                "the conversation above. Output prose only "
                                "— no markdown, no JSON, no second-guessing "
                                "the call itself."
                            )
                        ),
                    ]
                ),
                label="reasoning",
            )
            narration_text = (
                narration_response.content
                if isinstance(narration_response.content, str)
                else str(narration_response.content)
            ).strip()

            if not narration_text:
                # Narrator itself blanked out (rare). Skip the rewrite —
                # leaving the original empty-content AIMessage is no worse
                # than what we had before this node existed.
                _record_tools_node()
                return {}

            # Replace executor's AIMessage in-place: same id triggers the
            # ``add_messages`` reducer's "overwrite by id" path (verified
            # against langgraph 0.2+ in unit tests during development).
            # We preserve tool_calls verbatim so ToolNode still executes
            # exactly what the executor decided.
            replacement = AIMessage(
                id=last_ai.id,
                content=narration_text,
                tool_calls=last_ai.tool_calls,
                additional_kwargs={
                    **(getattr(last_ai, "additional_kwargs", None) or {}),
                    "reasoning_injected": True,
                },
            )
            _record_tools_node()
            return {"messages": [replacement]}

        def node_failure_node(state: AgentState) -> dict[str, Any]:
            """Handle a soft failure for the currently focused DAG node.

            Triggered when the executor exhausts ``max_steps_per_node`` without
            calling ``mark_node_done`` (or ``answer`` for the final node).
            Increments the per-node attempt counter; if the attempt cap is
            also exceeded, the node is marked failed and we set up the
            replanner trigger. Otherwise, we re-focus the same node so the
            executor gets another chance.
            """

            del state
            dag_state = tool_run_context.dag_state
            current_id = dag_state.current_node_id
            if current_id is None or dag_state.dag is None:
                return {
                    "pending_replan_reason": (
                        "node_failure invoked without a current node"
                    )
                }
            attempts = dag_state.node_attempts.get(current_id, 0) + 1
            dag_state.node_attempts[current_id] = attempts
            dag_state.record_event(
                "node_attempt_failed",
                node_id=current_id,
                attempt=attempts,
                cap=max_node_attempts,
            )
            if attempts >= max_node_attempts:
                dag_state.node_status[current_id] = "failed"
                dag_state.current_node_id = None
                _render_dag_if_enabled(
                    title=f"Node {current_id} FAILED — {task.task_id}"
                )
                return {
                    "pending_replan_reason": (
                        f"Node {current_id} failed after {attempts} attempts."
                    ),
                    "steps_in_current_node": 0,
                }
            # Soft retry: keep the node "in_progress", reset step counter, and
            # let the scheduler re-issue the focused prompt next round.
            dag_state.node_status[current_id] = "pending"
            dag_state.current_node_id = None
            _render_dag_if_enabled(
                title=f"Node {current_id} retry {attempts}/{max_node_attempts} — {task.task_id}"
            )
            return {
                "steps_in_current_node": 0,
            }

        def reflector_node(state: AgentState) -> dict[str, Any]:
            answer = tool_run_context.final_answer
            if answer is None:
                # Should not happen — router only sends us here after answer.
                return {"finalized": True}

            preview_columns = answer.columns
            preview_rows = answer.rows[:5]
            preview_text = (
                f"columns={preview_columns}\nrows(first 5)={preview_rows}\n"
                f"total_rows={len(answer.rows)}"
            )
            dag_summary = (
                tool_run_context.dag_state.dag.to_dict()
                if tool_run_context.dag_state.dag is not None
                else {}
            )
            tool_run_context.dag_state.record_event(
                "graph_node",
                graph_node="reflector",
                node_id=tool_run_context.dag_state.current_node_id or "",
                description="Reflector is checking whether the submitted answer is good enough.",
            )
            verdict_response = _invoke_with_retry(
                lambda: self.model.invoke(
                    [
                        SystemMessage(content=REFLECTOR_SYSTEM_PROMPT),
                        HumanMessage(
                            content=(
                                f"Question: {task.question}\n\n"
                                f"Plan (DAG): {json.dumps(dag_summary)}\n\n"
                                f"Submitted answer:\n{preview_text}\n\n"
                                "Verdict:"
                            )
                        ),
                    ]
                ),
                label="reflector",
            )
            verdict_text = (
                verdict_response.content
                if isinstance(verdict_response.content, str)
                else str(verdict_response.content)
            ).strip()
            reflection_notes.append(verdict_text)

            reflections_used = state.get("reflections_used", 0)
            verdict_upper = verdict_text.upper()
            should_retry = verdict_upper.startswith("RETRY") and reflections_used < max_reflections

            if not should_retry:
                return {"finalized": True}

            # Reset the captured answer + final node status so the scheduler
            # re-focuses the final node and the executor submits a new answer.
            tool_run_context.final_answer = None
            dag_state = tool_run_context.dag_state
            if dag_state.dag is not None:
                final_id = dag_state.dag.final_node_id
                dag_state.node_status[final_id] = "pending"
                dag_state.current_node_id = None
            retry_message = HumanMessage(
                content=(
                    "Reflector requested a revision. The scheduler will "
                    "re-focus the final DAG node so you can call `answer` "
                    "again with the corrected table.\n"
                    f"Reflector note: {verdict_text}"
                )
            )
            return {
                "messages": [retry_message],
                "reflections_used": reflections_used + 1,
                "steps_in_current_node": 0,
                "finalized": False,
            }

        def finalizer_node(state: AgentState) -> dict[str, Any]:
            # No-op node: presence in the graph is what triggers END routing.
            del state
            tool_run_context.dag_state.record_event(
                "graph_node",
                graph_node="finalize",
                node_id=tool_run_context.dag_state.current_node_id or "",
                description="Finalize is closing the LangGraph run.",
            )
            return {}

        def nudge_node(state: AgentState) -> dict[str, Any]:
            """Re-prompt the executor when it returns an empty/no-op turn.

            Some OpenAI-compatible models (notably Qwen via DashScope) will
            occasionally produce an AIMessage with empty ``content`` and no
            ``tool_calls`` mid-conversation, even when more work is clearly
            needed. We append a short, explicit reminder and let the executor
            try again. Repeated idle turns are capped by ``max_idle_nudges``.
            """

            idle_used = state.get("idle_nudges_used", 0)
            dag_state = tool_run_context.dag_state
            current_id = dag_state.current_node_id or "(no current node)"
            is_final = (
                dag_state.dag is not None
                and current_id == dag_state.dag.final_node_id
            )
            completion_hint = (
                "call `answer` with the final result table"
                if is_final
                else f"call `mark_node_done` for node_id='{current_id}' once you have the summary"
            )
            nudge_message = HumanMessage(
                content=(
                    "Your previous reply was empty and called no tool. You must "
                    "either (a) call one of the inspection tools to gather more "
                    f"information for node '{current_id}', or (b) {completion_hint}. "
                    "Do not produce empty replies. Continue now."
                )
            )
            return {
                "messages": [nudge_message],
                "idle_nudges_used": idle_used + 1,
            }

        # ------- Routers -------

        def route_after_planner(state: AgentState) -> str:
            del state
            return "scheduler"

        def route_after_scheduler(state: AgentState) -> str:
            """Decide where to go after the scheduler ran.

            Priority order:
            1. If scheduler set ``pending_replan_reason`` → either replan or
               (if the budget is exhausted) finalize.
            2. If all DAG nodes are done → reflector (the executor has
               already called `answer`, since the final node's "done" path
               IS calling `answer`).
            3. Otherwise the scheduler installed a focused prompt → executor.
            """

            dag_state = tool_run_context.dag_state
            if state.get("pending_replan_reason"):
                if dag_state.replan_count >= max_replans:
                    return "finalize"
                return "replanner"
            if _all_nodes_done(dag_state.node_status):
                # Edge case: all nodes done via mark_node_done but the final
                # node's executor never called `answer`. The reflector will
                # see no answer and we'll fall through to finalize. In normal
                # flow the route_after_tools branch handles `answer` directly.
                if tool_run_context.final_answer is not None:
                    return "reflector"
                return "finalize"
            return "executor"

        def route_after_executor(state: AgentState) -> str:
            last_ai = _last_ai_message(state["messages"])
            if last_ai is None:
                return "finalize"
            if _has_pending_tool_calls(last_ai):
                # Always go through `reasoning` first so every tool call has
                # a textual rationale attached. The reasoning node itself
                # short-circuits when the executor already produced content,
                # so the only added cost is one extra LLM call on the (very
                # common, on Qwen) empty-content tool-call turns.
                return "reasoning"
            # No tool_calls. Either the executor finished (rare — model returned
            # a textual conclusion without calling `answer`) or it stalled with
            # an empty turn. Try to nudge a few times before giving up; if the
            # current-node step budget is also exhausted, escalate to the
            # node-failure handler instead.
            if state.get("steps_in_current_node", 0) >= _dynamic_node_step_cap():
                return "node_failure"
            if state.get("idle_nudges_used", 0) >= max_idle_nudges:
                return "finalize"
            return "nudge"

        def route_after_tools(state: AgentState) -> str:
            """Decide where to go after the tool node ran.

            * If the executor just called `answer` → reflector.
            * If the executor called `mark_node_done` → scheduler (next node).
            * If the per-node step budget is exhausted → node_failure.
            * Otherwise → executor (continue working on the current node).
            """

            tool_names = _last_tool_call_names(state["messages"])
            if ANSWER_TOOL_NAME in tool_names and tool_run_context.final_answer is not None:
                return "reflector"
            if MARK_NODE_DONE_TOOL_NAME in tool_names:
                return "scheduler"
            if state.get("steps_in_current_node", 0) >= _dynamic_node_step_cap():
                return "node_failure"
            return "executor"

        def route_after_node_failure(state: AgentState) -> str:
            del state
            dag_state = tool_run_context.dag_state
            if dag_state.replan_count >= max_replans and any(
                status == "failed" for status in dag_state.node_status.values()
            ):
                return "finalize"
            # Either we're soft-retrying the same node (status reverted to
            # pending), or one node is failed but we still have replan budget.
            return "scheduler"

        def route_after_replanner(state: AgentState) -> str:
            del state
            return "scheduler"

        def route_after_reflector(state: AgentState) -> str:
            if state.get("finalized"):
                return "finalize"
            return "scheduler"

        # ------- Wire the graph -------

        graph = StateGraph(AgentState)
        graph.add_node("planner", planner_node)
        graph.add_node("replanner", replanner_node)
        graph.add_node("scheduler", dag_scheduler_node)
        graph.add_node("executor", executor_node)
        graph.add_node("reasoning", reasoning_node)
        graph.add_node("tools", tool_node)
        graph.add_node("node_failure", node_failure_node)
        graph.add_node("reflector", reflector_node)
        graph.add_node("nudge", nudge_node)
        graph.add_node("finalize", finalizer_node)

        graph.set_entry_point("planner")
        graph.add_conditional_edges(
            "planner", route_after_planner, {"scheduler": "scheduler"}
        )
        graph.add_conditional_edges(
            "scheduler",
            route_after_scheduler,
            {
                "executor": "executor",
                "reflector": "reflector",
                "replanner": "replanner",
                "finalize": "finalize",
            },
        )
        graph.add_conditional_edges(
            "executor",
            route_after_executor,
            {
                "reasoning": "reasoning",
                "nudge": "nudge",
                "node_failure": "node_failure",
                "finalize": "finalize",
            },
        )
        # `reasoning` always falls through to `tools`: by the time we get
        # here the executor already chose tool_calls, the reasoning node
        # only annotates them with a textual rationale (or no-ops on
        # short-circuit). Routing back through executor would loop.
        graph.add_edge("reasoning", "tools")
        graph.add_edge("nudge", "executor")
        graph.add_conditional_edges(
            "tools",
            route_after_tools,
            {
                "executor": "executor",
                "scheduler": "scheduler",
                "reflector": "reflector",
                "node_failure": "node_failure",
            },
        )
        graph.add_conditional_edges(
            "node_failure",
            route_after_node_failure,
            {"scheduler": "scheduler", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "replanner", route_after_replanner, {"scheduler": "scheduler"}
        )
        graph.add_conditional_edges(
            "reflector",
            route_after_reflector,
            {"scheduler": "scheduler", "finalize": "finalize"},
        )
        graph.add_edge("finalize", END)

        return graph.compile()

    # --- Public API ------------------------------------------------------

    def run(
        self,
        task: PublicTask,
        *,
        task_output_dir: Path | None = None,
    ) -> AgentRunResult:
        """Run the agent end-to-end on ``task``.

        Args:
            task: The task to solve.
            task_output_dir: Optional. If provided, the DAG visualizer
                writes ``dag.svg`` into this directory each time the
                planner / replanner / scheduler / node_failure node
                changes the DAG topology or per-node status. The caller
                is responsible for ``mkdir`` ing the directory first.
        """

        tool_run_context = ToolRunContext()
        reflection_notes: list[str] = []
        tools = build_langchain_tools(task, tool_run_context)

        # ---- Live partial-trace flushing ------------------------------------
        # The web UI's TraceWatcher polls trace.json every 0.25 s and pushes
        # incremental ``step`` / ``dag_update`` WS events to the frontend.
        # Previously trace.json was only written AFTER ``invoke()`` returned,
        # so the UI showed nothing until the run finished.  Now we hook into
        # DAGRuntimeState.on_event and flush a lightweight partial trace on
        # every plan / node_start / node_done / replan event so the watcher
        # picks up changes in near-real-time.
        if task_output_dir is not None:
            _partial_trace_path = task_output_dir / "trace.json"

            def _flush_partial_trace() -> None:
                """Write a partial trace.json from dag + executor events.

                Emits DAG lifecycle steps (plan / node_start / node_done /
                replan / node_attempt_failed) AND executor tool-call steps
                so the UI's Timeline, AgentGraph, and DAG all update in
                real-time during the run — not only after it finishes.
                """
                dag_state = tool_run_context.dag_state
                events = dag_state.events
                if not events:
                    return
                partial_steps: list[dict[str, Any]] = []
                step_idx = 0
                for event in events:
                    kind = event.get("kind")
                    if kind == "plan" or kind == "replan":
                        step_idx += 1
                        partial_steps.append({
                            "step_index": step_idx,
                            "thought": "Planner produced a DAG plan." if kind == "plan" else "Replanner produced a new DAG plan.",
                            "action": "__plan__",
                            "action_input": {},
                            "raw_response": event.get("raw", ""),
                            "observation": {
                                "ok": event.get("parse_error") is None,
                                "content": {
                                    "dag": event.get("dag", {}),
                                    "parse_error": event.get("parse_error"),
                                },
                            },
                        })
                    elif kind == "node_start":
                        step_idx += 1
                        partial_steps.append({
                            "step_index": step_idx,
                            "thought": f"Scheduler focused DAG node {event.get('node_id')}.",
                            "action": "start_node",
                            "action_input": {"node_id": event.get("node_id", "")},
                            "raw_response": "",
                            "observation": {
                                "ok": True,
                                "content": {
                                    "node_id": event.get("node_id"),
                                    "goal": event.get("goal"),
                                    "is_final": event.get("is_final"),
                                },
                            },
                        })
                    elif kind == "node_done":
                        step_idx += 1
                        partial_steps.append({
                            "step_index": step_idx,
                            "thought": f"Executor signalled DAG node {event.get('node_id')} as done.",
                            "action": "mark_node_done",
                            "action_input": {
                                "node_id": event.get("node_id", ""),
                                "output_summary": event.get("summary", ""),
                            },
                            "raw_response": event.get("summary", ""),
                            "observation": {"ok": True, "content": {}},
                        })
                    elif kind == "node_attempt_failed":
                        step_idx += 1
                        partial_steps.append({
                            "step_index": step_idx,
                            "thought": f"Node {event.get('node_id')} attempt #{event.get('attempt')} exhausted its step budget.",
                            "action": "mark_node_failed",
                            "action_input": {"node_id": event.get("node_id", "")},
                            "raw_response": "",
                            "observation": {"ok": False, "content": {}},
                        })
                    elif kind == "graph_node":
                        graph_node = event.get("graph_node", "")
                        step_idx += 1
                        partial_steps.append({
                            "step_index": step_idx,
                            "thought": event.get("description") or f"LangGraph node {graph_node} is active.",
                            "action": "__graph_node__",
                            "action_input": {
                                "graph_node": graph_node,
                                "node_id": event.get("node_id", ""),
                            },
                            "raw_response": "",
                            "observation": {"ok": True, "content": {}},
                        })
                    elif kind == "executor_turn":
                        # Executor LLM call — emit tool calls for live
                        # Timeline + AgentGraph updates.
                        tool_calls = event.get("tool_calls", [])
                        text_preview = event.get("text_preview", "")
                        node_id = event.get("node_id", "")
                        if tool_calls:
                            for tc_name in tool_calls:
                                step_idx += 1
                                partial_steps.append({
                                    "step_index": step_idx,
                                    "thought": text_preview or f"Executor calling tool on node {node_id}.",
                                    "action": tc_name,
                                    "action_input": {"node_id": node_id},
                                    "raw_response": "",
                                    "observation": {"ok": True, "content": {}},
                                })
                        elif text_preview:
                            step_idx += 1
                            partial_steps.append({
                                "step_index": step_idx,
                                "thought": text_preview,
                                "action": "__assistant_text__",
                                "action_input": {"node_id": node_id},
                                "raw_response": text_preview,
                                "observation": {"ok": True, "content": {}},
                            })

                try:
                    payload = json.dumps(
                        {"task_id": task.task_id, "steps": partial_steps},
                        ensure_ascii=False,
                    )
                    _partial_trace_path.write_text(payload + "\n", encoding="utf-8")
                except OSError:
                    pass

            tool_run_context.dag_state.on_event = _flush_partial_trace

        compiled_graph = self._build_graph(
            task=task,
            tools=tools,
            tool_run_context=tool_run_context,
            reflection_notes=reflection_notes,
            task_output_dir=task_output_dir,
        )

        # We give the recursion budget some slack because the DAG-driven
        # graph has more node hops per "model turn" than the legacy ReAct
        # agent did (planner/scheduler/executor/tools/reflector chain).
        # Empirically: ~6 graph steps per "model turn" in the worst case.
        recursion_limit = max(8, self.config.max_steps * 6)

        final_state: AgentState | None = None
        failure_reason: str | None = None
        try:
            final_state = compiled_graph.invoke(
                {
                    "messages": [],
                    "reflections_used": 0,
                    "idle_nudges_used": 0,
                    "steps_in_current_node": 0,
                    "pending_replan_reason": None,
                    "finalized": False,
                },
                {"recursion_limit": recursion_limit},
            )
        except Exception as exc:  # noqa: BLE001
            # Surface the underlying exception type so transport-level errors
            # (e.g. openai.APIConnectionError raised as bare "Connection error.")
            # become diagnosable from trace.json without re-running.
            failure_reason = (
                f"LangGraph execution failed: {type(exc).__name__}: {exc}"
            )

        messages = list(final_state["messages"]) if final_state else []
        if not any(
            event.get("kind") == "graph_node"
            and event.get("graph_node") == "finalize"
            for event in tool_run_context.dag_state.events
        ):
            tool_run_context.dag_state.record_event(
                "graph_node",
                graph_node="finalize",
                node_id=tool_run_context.dag_state.current_node_id or "",
                description="Finalize is closing the LangGraph run.",
            )
        # Take a snapshot copy of the DAG event log so step-record translation
        # never sees later mutations (defensive — events list is normally
        # write-only after invoke returns, but copying is cheap).
        dag_events = list(tool_run_context.dag_state.events)
        step_records = _build_step_records(
            messages,
            dag_events=dag_events,
            reflection_notes=reflection_notes,
        )

        answer: AnswerTable | None = tool_run_context.final_answer
        # If reflector cleared the latest answer for retry but we ran out of
        # budget, fall back to the most recent submitted answer (if any).
        if answer is None and tool_run_context.submitted_answers:
            answer = tool_run_context.submitted_answers[-1]

        if answer is None and failure_reason is None:
            failure_reason = "Agent did not submit an answer within the step budget."

        return AgentRunResult(
            task_id=task.task_id,
            answer=answer,
            steps=step_records,
            failure_reason=failure_reason,
        )


def build_chat_openai(
    *,
    model: str,
    api_base: str,
    api_key: str,
    temperature: float,
) -> ChatOpenAI:
    """Construct the ``ChatOpenAI`` client used by :class:`LangGraphAgent`.

    Mirrors the parameter surface of the legacy ``OpenAIModelAdapter`` so the
    YAML config schema (``agent.model`` / ``agent.api_base`` / ``agent.api_key``
    / ``agent.temperature``) keeps working unchanged.

    Validates required fields up-front so misconfiguration produces a clear
    error instead of a downstream ``Connection error.`` from the OpenAI SDK.
    """

    if not api_key or api_key.strip() in {"", "YOUR_API_KEY"}:
        raise RuntimeError(
            "Missing or placeholder model API key in config.agent.api_key. "
            "Set agent.api_key in your YAML to a real value (or use ${ENV_VAR})."
        )
    if not api_base or api_base.strip() in {"", "YOUR_API_BASE_URL"}:
        raise RuntimeError(
            "Missing or placeholder model API base URL in config.agent.api_base."
        )
    if not model or model.strip() in {"", "YOUR_MODEL_NAME"}:
        raise RuntimeError(
            "Missing or placeholder model name in config.agent.model."
        )

    return ChatOpenAI(
        model=model,
        base_url=api_base.rstrip("/"),
        api_key=api_key,
        temperature=temperature,
        # Default httpx timeout in langchain-openai is generous, but we set an
        # explicit one so connection issues fail fast and produce a clear error.
        # 注意：max_retries 必须设为 0，否则会和 _invoke_with_retry 形成双层叠加重试，
        # 单次卡顿可放大到 (1+2)×(1+N)×timeout 秒，详见 LLM_RETRY_MAX_ATTEMPTS 注释。
        # 2026-05 调整：30s → 60s。原因：DashScope 上 reflector / 长 prompt 调用
        # 经常单次响应 >30s（task_199 实测连续 6 次卡 30s 才超时），把客户端
        # timeout 拉长一倍能把"上游真的在慢慢生成"和"上游断了"两类情况区分开，
        # 显著降低不必要的应用层 retry 次数。最坏单次 LLM 调用耗时随之放大到
        # 60s × 6 次 + ~31s 退避 ≈ 391s，配合 _invoke_with_retry 的 5 次重试预算。
        timeout=120,
        max_retries=3,
    )
