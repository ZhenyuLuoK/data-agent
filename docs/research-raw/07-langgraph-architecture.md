# 07 · LangGraph 多节点 Agent 架构详解

> 本文档对应代码版本：DAG 驱动的多节点 LangGraph 实现（在原 LangGraph 基础上引入 **结构化 DAG Planner + 严格模式 Scheduler + Replanner**）
> 适用读者：需要理解、修改、扩展 `data_agent_baseline` 包中 Agent 实现的工程师
> 关联文档：[`05-our-agent-design.md`](./05-our-agent-design.md)（PER-Loop 设计原则）

---

## 0. 一句话总览

**当前 Agent = LangGraph `StateGraph` 编排的 9 节点 DAG-driven 图：`Planner →(JSON DAG)→ Scheduler → Executor ⇄ ToolNode → Scheduler / Reflector / Replanner / NodeFailure → Finalize`**。Planner 一次性产出**结构化 DAG**（`PlanNode` 列表 + `final_node_id`），Scheduler 严格按拓扑序逐节点派发并构造**聚焦 prompt**（仅当前节点 goal + 直接上游产出摘要），Executor 通过新工具 **`mark_node_done`** 显式声明节点完成、通过 `answer` 提交最终表格。失败兜底由 **Replanner** 重新生成 DAG（受 `max_replans` 上限保护）。模型与工具通过 `ChatOpenAI.bind_tools()` 的**原生 `tool_calls` 协议**交互，整套流程产出的轨迹被翻译成与旧 ReAct **完全兼容**的 `AgentRunResult / StepRecord / AnswerTable`，因此 CLI、YAML 配置、`artifacts/runs/<run_id>/<task_id>/{trace.json,prediction.csv}` 落盘格式**全部不变**——只是 `__plan__` 步骤的 `observation.content` 多了 `dag` 字段，且新增了 `__dag_node_start__ / __dag_node_done__ / __replan__ / __node_attempt_failed__` 四类伪 action。

---

## 1. 与旧 ReAct 实现的对比

| 维度 | 旧实现（`agents/react.py`） | 当前实现（`agents/langgraph_agent.py`） |
| --- | --- | --- |
| **编排方式** | 手写 `for step in range(max_steps)` while-loop | LangGraph `StateGraph` + 条件边 |
| **工具协议** | LLM 输出 ```json {thought, action, action_input}``` 文本，正则解析 | 模型原生 `tool_calls` 字段（OpenAI tool calling 协议） |
| **工具定义** | 自写 `ToolSpec` (`name + description + input_schema dict`) | LangChain `StructuredTool` + Pydantic `BaseModel` args schema |
| **消息历史** | 手工拼 `[system, user, assistant, user, ...]` | LangGraph `MessagesState` + `add_messages` reducer 自动累加 |
| **节点数量** | 1（顺序循环） | 9（planner / replanner / scheduler / executor / tools / node_failure / reflector / nudge / finalize） |
| **任务分解** | 无 | Planner 输出**结构化 DAG**（JSON：`{nodes:[{id, goal, depends_on, suggested_tools, expected_output}], final_node_id}`） |
| **执行顺序** | 模型自由发挥 | **严格模式**：Scheduler 按拓扑序派发；Executor 每次只见「当前节点 goal + 直接上游 summary」 |
| **节点完成信号** | 无 | 新工具 `mark_node_done(node_id, summary)`，由 Executor 显式调用 |
| **失败兜底** | nudge / 跳出循环 | + **Replanner**（节点超出步数预算 → 软重试 → 计入 attempt → 超上限 → 重新生成 DAG） |
| **终止条件** | `answer` 工具 `is_terminal=True` 跳出循环 | `answer` 工具回填 `ToolRunContext.final_answer` → 路由到 reflector → finalize → `END` |
| **可恢复性** | 模型一旦输出非 JSON，整步报错 | 多种路由兜底 + nudge 节点对 Qwen 等模型的"空消息"做重试 |
| **依赖** | `openai>=2.28.0` | + `langchain / langchain-core / langchain-openai / langgraph` |
| **CLI / YAML / 落盘格式** | — | **完全保留，零破坏** |

---

## 2. 模块拓扑与文件清单

```
src/data_agent_baseline/
├── cli.py                          # typer CLI: status / inspect-task / run-task / run-benchmark（无改动）
├── config.py                       # YAML → AppConfig（无改动）
├── benchmark/
│   ├── dataset.py                  # 加载 data/public/input/task_<id>/...（无改动）
│   └── schema.py                   # PublicTask / AnswerTable（无改动，下游契约）
├── tools/
│   ├── filesystem.py               # list_context_tree / read_csv_preview / ...（无改动）
│   ├── sqlite.py                   # inspect_sqlite_schema / execute_read_only_sql（无改动）
│   ├── python_exec.py              # execute_python_code (multiprocessing 沙盒)（无改动）
│   ├── registry.py                 # 旧 ToolRegistry（保留，仅旧 ReAct 用）
│   └── langchain_tools.py          # ★ 9 个工具的 LangChain 包装 + PlanNode/PlanDAG/DAGRuntimeState/ToolRunContext
├── agents/
│   ├── runtime.py                  # StepRecord / AgentRunResult / AgentRuntimeState（无改动，落盘契约）
│   ├── model.py                    # 旧 OpenAIModelAdapter（保留，仅旧 ReAct 用）
│   ├── prompt.py                   # 旧 ReAct 提示词（保留）
│   ├── react.py                    # 旧 ReActAgent（保留作为对照）
│   └── langgraph_agent.py          # ★ DAG-driven LangGraphAgent + 9 节点图 + DAG 解析/校验 + 轨迹翻译
├── run/
│   └── runner.py                   # 已切换到 LangGraphAgent（保持外部 API）
└── ...
```

**重要**：旧 `agents/react.py` / `agents/model.py` / `tools/registry.py` 没有被删除，但**当前生产路径不再调用**，仅供对照与未来回退。`runner.py` 已经把 `ReActAgent` 替换为 `LangGraphAgent`，CLI 命令完全无感。

---

## 3. 端到端数据流（DAG-driven 模式）

以 `task_64`（"Please list all the superpowers of 3-D Man."）为例。在 DAG 模式下，Planner 会先把它分解为 3 个节点（典型分解，模型实际产出可能略有差异）：

```jsonc
{
  "nodes": [
    {"id":"n1","goal":"List context to identify available data sources",
     "depends_on":[],"suggested_tools":["list_context"],
     "expected_output":"List of files/dirs under context/"},
    {"id":"n2","goal":"Find hero_id of '3-D Man' in superhero.json and join hero_power+superpower to get power names",
     "depends_on":["n1"],"suggested_tools":["read_json","read_csv","execute_python"],
     "expected_output":"List of superpower names for 3-D Man"},
    {"id":"n3","goal":"Submit the final answer table",
     "depends_on":["n2"],"suggested_tools":["execute_python"],
     "expected_output":"AnswerTable with 1 column 'superpower' and matching rows"}
  ],
  "final_node_id":"n3"
}
```

时序：

```
   user (CLI)                runner.py             LangGraphAgent (graph.invoke)
   ─────────                ──────────            ────────────────────────────
       │                        │                            │
   uv run dabench run-task ──▶ run_single_task               │
       │                  build_chat_openai ───▶ ChatOpenAI  │
       │                  LangGraphAgent.run(task)           │
       │                                                     ▼
       │                                  [planner_node]              ── LLM #1（无 tools，输出 DAG JSON）
       │                                  ToolRunContext.dag_state.install(dag)
       │                                  events += [{"kind":"plan", "dag":...}]
       │                                  trace step 1: __plan__ (observation.content.dag = ...)
       │                                                     ▼
       │                                  [scheduler_node]
       │                                  ready = n1; current_node_id=n1; status[n1]=in_progress
       │                                  注入 HumanMessage("FOCUSED on n1, goal=..., deps=...")
       │                                  events += [{"kind":"node_start", "node_id":"n1"}]
       │                                  trace step 2: __dag_node_start__ (n1)
       │                                                     ▼
       │                                  [executor_node]               ── LLM #2  tool_calls=[list_context]
       │                                                     ▼
       │                                  [tools_node]      list_context  → trace step 3
       │                                                     ▼
       │                                  [executor_node]               ── LLM #3  tool_calls=[mark_node_done(n1, "context has csv/, json/, knowledge.md")]
       │                                                     ▼
       │                                  [tools_node]      mark_node_done(n1)
       │                                  ToolRunContext.dag_state.node_status["n1"]="done"
       │                                  events += [{"kind":"node_done", "node_id":"n1"}]
       │                                  trace step 4: mark_node_done + step 5: __dag_node_done__ (n1)
       │                                                     ▼
       │                                  [scheduler_node]   ready=n2 → 同样的循环
       │                                  trace step 6: __dag_node_start__ (n2)
       │                                  ...read_json + read_csv + execute_python ...
       │                                  trace step 7-12 (各 tool 调用 + mark_node_done(n2))
       │                                  trace step 13: __dag_node_done__ (n2, summary="3-D Man=hero_id 1; powers=[Agility,...]")
       │                                                     ▼
       │                                  [scheduler_node]   ready=n3 (final)
       │                                  注入聚焦 prompt（含 n2 summary，提示用 answer 而非 mark_node_done）
       │                                  trace step 14: __dag_node_start__ (n3, is_final=True)
       │                                                     ▼
       │                                  [executor_node]               ── LLM  tool_calls=[answer]
       │                                                     ▼
       │                                  [tools_node]       answer 写入 ToolRunContext.final_answer
       │                                  trace step 15: answer
       │                                                     ▼
       │                                  route_after_tools: answer → reflector
       │                                                     ▼
       │                                  [reflector_node]  LLM 输出 "OK" → finalized=True
       │                                  trace step 16: __reflect__
       │                                                     ▼
       │                                  [finalize] → END
       │                                                     │
       │                  _build_step_records(messages, dag_events, reflection_notes)
       │                  → AgentRunResult(answer=..., steps=[16 条]).to_dict()
       │                  _write_task_outputs ─▶ artifacts/runs/<run_id>/task_64/{trace.json, prediction.csv}
       ◀────────────────────────│ "succeeded"
```

**注意**：上面是「理想分解」的示意。当前 Qwen 模型若直接输出 1 个 fallback 节点（`_fallback_plan_dag`），轨迹会退化为类似旧线性 ReAct 的形态——`__plan__` 仍存在但 `dag.nodes` 只有 1 项，整个图依然能跑通，只是 DAG 优势不明显。这种情况是预期的 graceful degradation。

---
## 4. LangGraph 状态机详解

### 4.1 图拓扑

```
                          ┌──────────┐
                          │ planner  │   (产 DAG JSON，1 次)
                          └────┬─────┘
                               │
                               ▼
            ┌──────────► ┌────────────┐ ◄──────────────────────┐
            │            │  scheduler │                        │
            │            └─────┬──────┘                        │
            │                  │ route_after_scheduler:        │
            │                  │  ├─ stuck & replan_count<cap → replanner
            │                  │  ├─ stuck & replan_count>=cap → finalize
            │                  │  ├─ all_done & has_answer    → reflector
            │                  │  └─ ready node found          → executor (focused prompt)
            │                  ▼
            │            ┌──────────┐
            │            │ executor │ ◄────── nudge ◄──┐
            │            └────┬─────┘                  │
            │                 │ route_after_executor:  │
            │                 │  ├─ has tool_calls   → tools
            │                 │  ├─ empty & per-node budget exhausted → node_failure
            │                 │  ├─ empty & nudges<cap → nudge ──────┘
            │                 │  └─ empty & nudges>=cap → finalize
            │                 ▼
            │            ┌──────────┐
            │            │  tools   │  (LangGraph ToolNode)
            │            └────┬─────┘
            │                 │ route_after_tools:
            │                 │  ├─ called `answer`         → reflector
            │                 │  ├─ called `mark_node_done` → scheduler ──────┐
            │                 │  ├─ per-node budget exhausted → node_failure  │
            │                 │  └─ otherwise              → executor         │
            │                 ▼                                               │
            │            ┌──────────────┐                                     │
            │            │ node_failure │  (attempt += 1; 软重试 or 标记 failed)
            │            └──────┬───────┘                                     │
            │                   │ route_after_node_failure:                   │
            │                   │  ├─ all attempts done & replan budget done → finalize
            │                   │  └─ otherwise → scheduler ──────────────────┤
            │                                                                 │
            │            ┌──────────┐                                         │
            │            │ replanner│ ─── route_after_replanner: 始终 ───────┘
            │            └──────────┘
            │                  ▲
            │                  │
            │            ┌──────────┐
            │            │reflector │
            │            └────┬─────┘
            │                 │ route_after_reflector:
            │                 │  ├─ finalized=True → finalize
            │                 │  └─ RETRY (reset final node) → scheduler ──────┘
            │                 ▼
            │            ┌──────────┐
            └────────────│ finalize │ ──▶ END
                         └──────────┘
```

`graph.compile()` 之后会得到一个标准 LangGraph `Pregel` 对象，调用 `compiled_graph.invoke(initial_state, {"recursion_limit": N})` 即可端到端执行。`recursion_limit = max(8, max_steps * 6)`（旧实现是 `* 4`；DAG 模式因 scheduler 多了一层，`scheduler → executor → tools → scheduler` 是常态循环）。

### 4.2 共享状态（`AgentState` TypedDict）

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]   # LangGraph 标准 reducer
    reflections_used: int                                  # 已用 reflector retry 次数
    idle_nudges_used: int                                  # 已用 nudge 次数
    steps_in_current_node: int                             # 当前 DAG 节点已用 LLM 步数（scheduler 重置）
    pending_replan_reason: str | None                      # scheduler/node_failure 在卡住时设置，路由器据此走 replanner
    finalized: bool                                        # reflector 是否拍板完结
    failure_reason: str | None                             # 预留
```

- **`messages`** 是图的"主线程"，`add_messages` reducer 会把每个节点 `return {"messages": [m1, m2, ...]}` 的消息**追加**到现有列表（而不是覆盖）。
- 其余字段是普通 `TypedDict` 字段，节点 return 同名 key 时**覆盖**旧值。
- **DAG 状态不在 `AgentState` 里**，而在图外的 `ToolRunContext.dag_state`（`DAGRuntimeState`）中。原因：`mark_node_done` 工具运行在 `ToolNode` 内部，无法直接修改 graph state；让它写入闭包变量是最简洁的方案。这个状态包含：
  - `dag: PlanDAG | None`
  - `node_status: dict[node_id, "pending" | "in_progress" | "done" | "failed"]`
  - `node_outputs: dict[node_id, summary_str]`
  - `node_attempts: dict[node_id, int]`
  - `current_node_id: str | None`
  - `replan_count: int`
  - `events: list[dict]` —— 审计日志（plan / replan / node_start / node_done / node_attempt_failed），供 `_build_step_records` 翻译伪步骤

### 4.3 节点职责详表

| 节点 | 实现位置 | 调用 LLM | 读 state | 写 state / DAGRuntimeState | 副作用 |
| --- | --- | --- | --- | --- | --- |
| **planner** | `planner_node` 闭包 | ✅ 1 次（无 tools） | — | 写入 messages 初始种子；`dag_state.install(dag)`；event "plan" | 新生成 DAG，重置所有节点状态 |
| **replanner** | `replanner_node` 闭包 | ✅ 1 次（无 tools） | 读 `pending_replan_reason` | 重新调用 planner LLM；`dag_state.install(new_dag)`；`replan_count += 1`；event "replan"；重置 messages 为种子 | 同上，并清空 executor 上下文 |
| **scheduler** | `dag_scheduler_node` 闭包 | ❌ | — | 找 ready node → 标 `in_progress`，注入聚焦 HumanMessage，`steps_in_current_node = 0`；或卡住 → 设 `pending_replan_reason` | event "node_start" |
| **executor** | `executor_node` 闭包 | ✅ 1 次（`bind_tools`） | 读 `messages` | 追加 1 条 AIMessage；`steps_in_current_node += 1` | — |
| **tools** | `langgraph.prebuilt.ToolNode` | ❌ | 读 `messages` 末尾 AIMessage 的 `tool_calls` | 追加每个 tool_call 对应的 `ToolMessage` | `answer` → 写 `final_answer`；`mark_node_done` → 改 `node_status[id]="done"`，写 `node_outputs[id]`，event "node_done"；其它工具 → I/O 副作用 |
| **node_failure** | `node_failure_node` 闭包 | ❌ | — | `node_attempts[current] += 1`；若 ≥ cap → 标 `failed` + 设 `pending_replan_reason`；否则把节点状态回退到 `pending`（软重试） | event "node_attempt_failed" |
| **reflector** | `reflector_node` 闭包 | ✅ 1 次（无 tools） | 读 `final_answer` + `dag` | OK → `finalized=True`；RETRY → 把 final node 重置为 `pending`、清空 `final_answer`、追加 retry HumanMessage，`reflections_used += 1` | 把 verdict 文本 `append` 到 `reflection_notes` 列表 |
| **nudge** | `nudge_node` 闭包 | ❌ | 读 `idle_nudges_used`、`current_node_id` | 追加 1 条催促 HumanMessage（提示当前节点 id 和应调用的工具）、`idle_nudges_used += 1` | — |
| **finalize** | `finalizer_node` 闭包 | ❌ | — | — | No-op，仅作为可寻址的 `END` 入口 |

### 4.4 路由函数（条件边）

```python
def route_after_planner(state) -> "scheduler":
    return "scheduler"                                       # 始终

def route_after_scheduler(state) -> "executor"|"reflector"|"replanner"|"finalize":
    if state.get("pending_replan_reason"):
        return "finalize" if dag_state.replan_count >= max_replans else "replanner"
    if _all_nodes_done(dag_state.node_status):
        return "reflector" if final_answer is not None else "finalize"
    return "executor"                                        # 已注入聚焦 prompt

def route_after_executor(state) -> "tools"|"nudge"|"node_failure"|"finalize":
    last_ai = _last_ai_message(state["messages"])
    if last_ai is None:                          return "finalize"
    if _has_pending_tool_calls(last_ai):         return "tools"
    if state.get("steps_in_current_node",0) >= max_steps_per_node:
        return "node_failure"                                # 单节点超预算
    if state.get("idle_nudges_used",0) >= max_idle_nudges:
        return "finalize"
    return "nudge"

def route_after_tools(state) -> "reflector"|"scheduler"|"node_failure"|"executor":
    names = _last_tool_call_names(state["messages"])
    if "answer" in names and final_answer is not None:    return "reflector"
    if "mark_node_done" in names:                         return "scheduler"
    if state.get("steps_in_current_node",0) >= max_steps_per_node:
        return "node_failure"
    return "executor"

def route_after_node_failure(state) -> "scheduler"|"finalize":
    if dag_state.replan_count >= max_replans and any(s == "failed" for s in dag_state.node_status.values()):
        return "finalize"
    return "scheduler"

def route_after_replanner(state) -> "scheduler":
    return "scheduler"                                       # 始终

def route_after_reflector(state) -> "scheduler"|"finalize":
    return "finalize" if state.get("finalized") else "scheduler"   # RETRY 时 final node 已被重置为 pending
```

### 4.5 终止路径（共 4 条）

1. **正常完结**：`planner → scheduler →* executor → tools(mark_node_done) → scheduler →* executor → tools(answer) → reflector("OK") → finalize → END`
2. **反思 retry 后通过**：`... → tools(answer) → reflector("RETRY") → scheduler (final node 重新 ready) → executor → tools(answer) → reflector("OK") → finalize`
3. **节点失败 → replan 后成功**：`... → executor (超 max_steps_per_node) → node_failure (attempts<cap，软重试) → scheduler (同节点重新 ready) → ... → node_failure (attempts==cap，标 failed，设 replan reason) → scheduler → replanner → scheduler → ... → finalize`
4. **彻底放弃**：`scheduler/node_failure 设 replan reason 但 replan_count >= max_replans → finalize`，此时 `final_answer` 多半为 `None`，`failure_reason` 描述为 nudge 用尽或预算耗尽
---

## 5. 工具层（`tools/langchain_tools.py`）

### 5.1 设计动机

LangChain 的 `bind_tools()` 接收 `BaseTool` 列表并把它们转成 OpenAI tool 协议的 JSON Schema 给模型；但**我们的工具是 task-bound 的**——`list_context` 必须知道当前任务的 `context/` 路径，`answer` 必须能把 `AnswerTable` 传出来。所以我们：

1. **每个 task 重新构建一次工具列表**（闭包捕获 `task` 与 `tool_run_context`）。
2. **每个工具的参数用 Pydantic `BaseModel` 显式声明**，让 LangChain 自动派生 JSON Schema。
3. **`answer` 工具通过共享 `ToolRunContext.final_answer` 把 `AnswerTable` 暴露给 graph 节点**。

### 5.2 `ToolRunContext`

```python
@dataclass(slots=True)
class ToolRunContext:
    final_answer: AnswerTable | None = None         # 最近一次成功提交的答案
    submitted_answers: list[AnswerTable] = []       # 历史提交（用于 reflector retry 兜底）
```

`reflector_node` 在判定 RETRY 时会**清空** `final_answer`（强制 executor 重提交），但保留 `submitted_answers` 列表，这样即使后续超出 reflection 预算被强制 finalize，`LangGraphAgent.run` 也能在末尾 fallback 到最后一次提交：

```python
if answer is None and tool_run_context.submitted_answers:
    answer = tool_run_context.submitted_answers[-1]
```

### 5.3 9 个工具的对照表

| LangChain 工具名 | 参数 schema（Pydantic） | 包装的底层函数 | 备注 |
| --- | --- | --- | --- |
| `list_context` | `ListContextArgs(max_depth=4)` | `filesystem.list_context_tree` | 不接受路径，固定从 task context 根目录列 |
| `read_csv` | `ReadCsvArgs(path, max_rows=20)` | `filesystem.read_csv_preview` | preview 模式，会返回前 N 行 + 总行数 |
| `read_json` | `ReadJsonArgs(path, max_chars=4000)` | `filesystem.read_json_preview` | preview 模式，限制返回字符数 |
| `read_doc` | `ReadDocArgs(path, max_chars=4000)` | `filesystem.read_doc_preview` | 用于 markdown / 纯文本文件 |
| `inspect_sqlite_schema` | `InspectSqliteSchemaArgs(path)` | `sqlite.inspect_sqlite_schema` | 通过 `resolve_context_path` 防止越界 |
| `execute_context_sql` | `ExecuteContextSqlArgs(path, sql, limit=200)` | `sqlite.execute_read_only_sql` | 仅允许 `SELECT/WITH/PRAGMA` |
| `execute_python` | `ExecutePythonArgs(code)` | `python_exec.execute_python_code` | 30s 超时，子进程沙盒 |
| `mark_node_done` | `MarkNodeDoneArgs(node_id, output_summary)` | 内联 `_run`，写 `DAGRuntimeState` | **DAG 节点完成信号**。校验 `node_id` 必须等于 `current_node_id`，防止跨节点；置 `node_status="done"`，记录 summary，触发 scheduler 取下一节点 |
| `answer` | `AnswerArgs(columns, rows)` | 内联 `_run`，写 `ToolRunContext` | **唯一的最终终止信号**（仅在 final node 上调用） |

> ⚠️ **强约束**：在非 final 节点上禁止调用 `answer`；在 final 节点上禁止调用 `mark_node_done`（应改用 `answer`）。这两条规则写在 `EXECUTOR_SYSTEM_PROMPT` 里，而 `mark_node_done` 工具内部还会用 `current_node_id` 做硬校验，调错节点 id 会抛 `ValueError` 让 `ToolNode` 返回 `status="error"` 让 executor 自纠。

### 5.4 入口工厂

```python
def build_langchain_tools(task: PublicTask, context: ToolRunContext) -> list[BaseTool]:
    return [
        _build_list_context_tool(task),
        _build_read_csv_tool(task),
        _build_read_json_tool(task),
        _build_read_doc_tool(task),
        _build_inspect_sqlite_schema_tool(task),
        _build_execute_context_sql_tool(task),
        _build_execute_python_tool(task),
        _build_answer_tool(context),                # 唯一一个用 context 而非 task 的工具
    ]
```

工具顺序对功能无影响，但稳定排序使 prompt 中的 tool listing 也是稳定的。

---

## 6. Agent 主体（`agents/langgraph_agent.py`）

### 6.1 配置（`LangGraphAgentConfig`）

```python
@dataclass(frozen=True, slots=True)
class LangGraphAgentConfig:
    max_steps: int = 16            # 等价于旧 ReAct 的 max_steps；recursion_limit = max(8, max_steps*6)
    max_reflections: int = 1       # reflector 最多让 executor 重提交几次
    max_idle_nudges: int = 2       # 对 executor 空消息的最大兜底重试次数
    max_replans: int = 1           # planner 总调用次数 = 1 + max_replans；0 = 禁用 replan
    max_node_attempts: int = 2     # 单节点本地软重试次数；超限 → 标 failed → 触发 replan
    max_steps_per_node: int = 8    # 单节点 LLM 步数预算；超限即视为该节点本次 attempt 失败
```

`runner.py` 当前只把 YAML 的 `agent.max_steps` 传进来，其余项保留默认。如需暴露给 YAML，在 `config.AgentConfig` 增加字段并在 `LangGraphAgentConfig(...)` 实例化处透传。

### 6.2 提示词

| 常量 | 长度 | 角色 | 关键约束 |
| --- | --- | --- | --- |
| `PLANNER_SYSTEM_PROMPT` | ~25 行 | planner system | 输出**严格 JSON DAG**（schema 见 §6.4），id 形如 `n1`/`n2`，`depends_on` 必须引用先前节点（强制拓扑序 + 无环），`final_node_id` 必须是最后一个节点；禁止包含 `answer` 节点；禁止建议 `answer`/`mark_node_done` 工具 |
| `REPLANNER_SYSTEM_PROMPT` | ~6 行 | replanner system | 输入：原问题 + 旧 DAG + 节点状态 + 失败原因；输出：新 DAG（同 schema） |
| `EXECUTOR_SYSTEM_PROMPT` | ~15 行 | executor system | 6 条规则，关键是「FOCUSED on 一个节点」「非 final 节点结束 = `mark_node_done`」「final 节点结束 = `answer`」「禁止跨节点工作」 |
| `REFLECTOR_SYSTEM_PROMPT` | ~6 行 | reflector system | 输出二选一：`OK` 或 `RETRY: <短句>` |

执行时 `planner_node` 只放 `EXECUTOR_SYSTEM_PROMPT` + 通用 question 提示作为 messages 种子；具体的「当前节点 goal + 上游摘要」由 `dag_scheduler_node` 在每次切换节点时**新增一条 HumanMessage** 注入（`_focused_executor_prompt` 函数构造）：

```
Question (for context): {task.question}

You are now FOCUSED on DAG node:
  id: n2
  goal: ...
  expected_output: ...
  suggested_tools: read_csv, execute_python

Upstream nodes you depend on:
- n1 (goal: ...)
  summary: <verbatim mark_node_done summary>

When you have produced the expected output, call `mark_node_done` with node_id='n2' and a concise factual summary.
```

### 6.3 关键函数索引

| 函数 / 类 | 行为 |
| --- | --- |
| `LangGraphAgent.__init__(model, config)` | 持有 `ChatOpenAI` 和配置 |
| `LangGraphAgent._build_graph(...)` | 每个 task 构建一份新的 compiled graph（因为 tools/DAG state 是 task-bound 的） |
| `LangGraphAgent.run(task)` | 端到端入口；初始化 `ToolRunContext`（含全新 `DAGRuntimeState`）→ 构建 tools → 编译 graph → invoke → 收集 `messages` + `dag_state.events` + `reflection_notes` → `_build_step_records` → 返回 `AgentRunResult` |
| `_invoke_planner_llm(system_prompt, user_payload)` | 闭包内 helper：调用 LLM 并 `_parse_plan_dag`；解析失败回落到 `_fallback_plan_dag` 并保留 raw + parse_error 用于 trace |
| `_parse_plan_dag(raw)` | 解析 + 校验 DAG JSON：唯一 id、必填 goal、deps 必须前向引用（一次过排除环）、`final_node_id` 必须是最后一个节点 |
| `_extract_json_object(text)` | 兜底：剥掉 markdown 围栏、用正则取第一个 `{...}` |
| `_fallback_plan_dag(task)` | 解析失败兜底：1 节点 DAG，executor 仍能工作 |
| `_ready_node(dag, status)` | scheduler 用：返回拓扑序中第一个 deps 全 done 且 pending 的节点 |
| `_focused_executor_prompt(...)` | 构造严格模式聚焦 prompt：当前节点 metadata + 上游 summary + 完成方式（`mark_node_done` vs `answer`） |
| `_question_user_message(task)` | 构造 executor 的初始 question 提示（与 DAG 无关的通用部分） |
| `_last_ai_message(messages)` | 反向找最后一条 AIMessage（路由用） |
| `_has_pending_tool_calls(ai)` | 判断 AIMessage 是否带 `tool_calls` |
| `_last_tool_call_names(messages)` | 返回最近一条 AIMessage 的 tool_call 名集合（路由用） |
| `_coerce_observation(message)` | 把 `ToolMessage` 转成旧 `StepRecord.observation` 格式 |
| `_build_step_records(messages, *, dag_events, reflection_notes)` | **轨迹翻译器**：交织消息流和 DAG 事件流，输出 `StepRecord` 列表 |
| `build_chat_openai(model, api_base, api_key, temperature)` | 构造 `ChatOpenAI`，包含占位符校验 |

### 6.4 DAG JSON Schema（planner / replanner 输出契约）

```jsonc
{
  "nodes": [
    {
      "id": "n1",                                  // 唯一短字符串（n1/n2/...）
      "goal": "<imperative sub-task description>", // 必填、非空
      "depends_on": [],                            // list[str]，必须只引用 nodes 中先前出现过的 id
      "suggested_tools": ["list_context"],         // 提示用，executor 仍可用任何工具
      "expected_output": "<one short sentence>"    // 给下游节点的语义契约
    }
    // ... 2~6 个节点为典型规模
  ],
  "final_node_id": "n3"                            // 必须等于 nodes[-1].id
}
```

### 6.5 轨迹翻译规则（`_build_step_records`）

为了让落盘 `trace.json` 完全兼容下游评测/分析脚本，我们把 LangGraph 内部的消息列表 + DAG 事件日志按时序交织成 `StepRecord(step_index, thought, action, action_input, raw_response, observation, ok)`，规则如下：

| 来源事件 | 翻译为 `StepRecord.action` | `observation.content` 内容 |
| --- | --- | --- |
| Planner 输出（`event.kind == "plan"`） | `__plan__` | `{"dag": {...}, "parse_error": null}` |
| Replanner 输出（`event.kind == "replan"`） | `__replan__` | `{"dag": {...}, "failure_reason": "...", "parse_error": null, "attempt": 1}` |
| Scheduler 注入聚焦 prompt（`event.kind == "node_start"`） | `__dag_node_start__` | `{"node_id": "n2", "goal": "...", "is_final": false, "attempt": 1}` |
| `mark_node_done` 工具成功（`event.kind == "node_done"`） | `__dag_node_done__` | `{"node_id": "n2", "summary": "..."}` （紧跟在 mark_node_done 这条 tool step 后） |
| 节点失败（`event.kind == "node_attempt_failed"`） | `__node_attempt_failed__` | `{"node_id": "n2", "attempt": 2, "cap": 2}` |
| AIMessage 含 1 个 `tool_call` | tool 名（如 `read_csv` / `mark_node_done` / `answer`） | 对应 `ToolMessage.content` 转 dict |
| AIMessage 含 N 个 `tool_call` | 拆成 N 条记录，`action` 各为 tool 名 | 每条对应一个 `ToolMessage` |
| AIMessage 仅含文本（无 tool_call） | `__assistant_text__` | `{"text": "<content>"}` |
| Reflector verdict | `__reflect__` | `{"verdict": "OK" | "RETRY: ..."}` |

**插入策略（`_build_step_records` 内部）**：

- `__plan__` / `__replan__` 在 messages 流处理前 / mid-stream（紧随产生它们的 AIMessage）emit
- `__dag_node_start__` 在遇到「FOCUSED on DAG node」HumanMessage 时 emit（这条消息由 scheduler 注入）
- `__dag_node_done__` 在 emit 完 `mark_node_done` 这条 tool step 之后立即 emit，按 `node_id` 配对
- `__reflect__` 在最末尾按 `reflection_notes` 顺序 emit

**示例：`task_64` 在理想 DAG 分解下的 16 条 `StepRecord`**（参见 §3 时序图）：

```
 1: __plan__               (planner，dag JSON 在 observation.content.dag)
 2: __dag_node_start__     (n1, attempt=1)
 3: list_context
 4: mark_node_done         (n1)
 5: __dag_node_done__      (n1, summary="context has csv/, json/, knowledge.md")
 6: __dag_node_start__     (n2, attempt=1)
 7: read_json
 8: read_csv
 9: read_csv
10: execute_python
11: mark_node_done         (n2)
12: __dag_node_done__      (n2, summary="3-D Man=hero_id 1; powers=[...]")
13: __dag_node_start__     (n3, attempt=1, is_final=true)
14: answer
15: __reflect__            (verdict=OK)
```

**fallback 模式（DAG 解析失败 / 1 节点）下 `task_64` 退化为类似旧形态的 9 条**，仅 step 1 的 `observation.content.dag.nodes` 是单元素列表。

---

## 7. 与 Runner / CLI 的对接

### 7.1 `run/runner.py` 的关键改动

```python
# 原来：
from data_agent_baseline.agents.react import ReActAgent, ReActAgentConfig
from data_agent_baseline.agents.model import OpenAIModelAdapter

# 现在：
from data_agent_baseline.agents.langgraph_agent import (
    LangGraphAgent, LangGraphAgentConfig, build_chat_openai,
)

def build_model_adapter(config: AppConfig):
    return build_chat_openai(
        model=config.agent.model,
        api_base=config.agent.api_base,
        api_key=config.agent.api_key,
        temperature=config.agent.temperature,
    )

def _run_single_task_core(*, task_id, config, model=None, tools=None):
    ...
    del tools                                # LangGraph agent 自管 tools
    agent = LangGraphAgent(
        model=model or build_model_adapter(config),
        config=LangGraphAgentConfig(max_steps=config.agent.max_steps),
    )
    return agent.run(task).to_dict()
```

`build_model_adapter` 这个名字保留是为了兼容外部调用（比如 tests）传入的 `model=...` 参数；它现在返回的是 `ChatOpenAI` 而非 `OpenAIModelAdapter`，但 `LangGraphAgent.__init__` 接受的就是 `ChatOpenAI`，所以语义对得上。

### 7.2 任务级超时机制（沿用旧实现）

`runner.py` 的 `_run_single_task_with_timeout` 没改：

- 用 `multiprocessing.Process` 子进程跑单个任务
- 父进程 `process.join(timeout_seconds)`，超时则 `terminate()` → `kill()`
- **注意**：被强杀时 trace 可能落盘为占位空内容（`steps=[]`，`failure_reason: "Task timed out after N seconds."`），因为子进程的 LangGraph state 来不及序列化
- 如需调试超时任务，建议把 `run.task_timeout_seconds` 设为 `0` 让其跑满拿完整 trace

### 7.3 CLI 与 YAML（无任何改动）

```yaml
agent:
  model: qwen-max-latest
  api_base: https://dashscope.aliyuncs.com/compatible-mode/v1
  api_key: sk-xxx
  max_steps: 50            # → recursion_limit = max(8, 50*4) = 200
  temperature: 0.0
```

```bash
uv run dabench status        --config configs/react_baseline.local.yaml
uv run dabench inspect-task <id> --config configs/react_baseline.local.yaml
uv run dabench run-task     <id> --config configs/react_baseline.local.yaml
uv run dabench run-benchmark     --config configs/react_baseline.local.yaml [--limit N]
```

---

## 8. 落盘契约（与旧版 100% 兼容）

`artifacts/runs/<run_id>/<task_id>/`：

```
trace.json          # AgentRunResult.to_dict()
prediction.csv      # AnswerTable (columns + rows) 写入的标准 CSV
```

`trace.json` 的 schema：

```jsonc
{
  "task_id": "task_64",
  "answer": {
    "columns": ["superpower"],
    "rows": [["Agility"], ["Super Strength"], ...]
  } | null,
  "steps": [
    {
      "step_index": 1,
      "thought": "Planner produced an initial plan.",
      "action": "__plan__",
      "action_input": {},
      "raw_response": "{\"nodes\": [...], \"final_node_id\": \"n3\"}",
      "observation": {
        "ok": true,
        "content": {
          "dag": {
            "nodes": [
              {"id": "n1", "goal": "...", "depends_on": [], "suggested_tools": ["list_context"], "expected_output": "..."},
              {"id": "n2", "goal": "...", "depends_on": ["n1"], "suggested_tools": ["read_csv","execute_python"], "expected_output": "..."},
              {"id": "n3", "goal": "...", "depends_on": ["n2"], "suggested_tools": [], "expected_output": "final answer table"}
            ],
            "final_node_id": "n3"
          },
          "parse_error": null
        }
      },
      "ok": true
    },
    {
      "step_index": 2,
      "thought": "Scheduler dispatched DAG node n1.",
      "action": "__dag_node_start__",
      "action_input": {},
      "raw_response": "",
      "observation": {"ok": true, "content": {"node_id": "n1", "goal": "...", "is_final": false, "attempt": 1}},
      "ok": true
    },
    // ... tool steps + mark_node_done + __dag_node_done__ + ... + answer + __reflect__
  ],
  "failure_reason": null | "<string>",
  "succeeded": true | false,
  "e2e_elapsed_seconds": 27.284
}
```

**强约束**：任何对 `agents/runtime.py` 的 `StepRecord / AgentRunResult / AnswerTable` 字段重命名都会破坏下游评测，禁止改动。

**新增伪 action 列表**（DAG 改造后引入；下游分析脚本若不识别可直接按 `action.startswith("__")` 过滤掉，不影响兼容性）：

| 伪 action | 何时出现 | observation.content 关键字段 |
| --- | --- | --- |
| `__plan__` | 仅一次，紧随 planner | `dag`（完整 JSON）、`parse_error` |
| `__replan__` | 0 ~ `max_replans` 次 | `dag`、`failure_reason`、`attempt` |
| `__dag_node_start__` | 每个节点开始 attempt 时各一次 | `node_id`、`goal`、`is_final`、`attempt` |
| `__dag_node_done__` | 每个 `mark_node_done` 工具调用成功后 | `node_id`、`summary` |
| `__node_attempt_failed__` | 节点 attempt 失败时（步数耗尽/工具一直 error/解析失败等） | `node_id`、`attempt`、`cap` |
| `__assistant_text__` | executor 返回空 tool_calls 的 AI 消息时 | `text` |
| `__reflect__` | reflector 每次 verdict | `verdict`（`OK` 或 `RETRY: ...`） |

---

## 9. 错误兜底机制清单

| 失败模式 | 触发条件 | 兜底策略 | 最终结果 |
| --- | --- | --- | --- |
| LLM 配置缺失/占位符 | `api_key/api_base/model` 为空或还是 `YOUR_*` | `build_chat_openai` 抛 `RuntimeError`（带友好提示） | runner 捕获后 `failure_reason="LangGraph execution failed: RuntimeError: Missing or placeholder ..."` |
| LLM 网络/鉴权错误 | OpenAI SDK 抛 `APIConnectionError / AuthenticationError / RateLimitError` | `LangGraphAgent.run` 整体 `try/except` 捕获，`failure_reason="LangGraph execution failed: <ExcType>: <msg>"` | 任务标记失败，但其它任务继续 |
| 模型空消息（Qwen 偶发） | executor 返回 AIMessage 无 `tool_calls` 且无 answer | `nudge_node` 追加催促 user msg，最多 `max_idle_nudges` 次 | 大概率被催醒；用尽后 finalize（无 answer → `failure_reason` 报"未提交答案"） |
| 工具执行抛异常 | `read_csv` 文件不存在、`execute_python` 超时、`answer` schema 不合法等 | `ToolNode` 把异常文本作为 `ToolMessage(status="error")` 反馈给 executor | executor 看到错误后通常会重试或换工具 |
| Reflector 判定 RETRY | reflector LLM 输出以 `RETRY` 开头 | 清空 `ToolRunContext.final_answer`，追加 retry user msg，回 executor 再来一遍 | 受 `max_reflections` 上限保护 |
| Reflector 判定 RETRY 但预算用尽 | `reflections_used >= max_reflections` | 强制 `finalized=True`，但保留最近一次 `submitted_answers` 作为 fallback | 答案仍能落盘 |
| **DAG 节点 attempt 失败** | 单节点连续 `max_steps_per_node` 步未调 `mark_node_done`，或 `mark_node_done` 校验失败 | scheduler 把该 node 的 `attempts++`；若未超 `max_node_attempts` 则原地重试（清空当前节点上下文重新派发）；超限则置 `node_status=failed` 触发 replanner | 多数情况下 1-2 次重试即恢复 |
| **DAG 全局卡住** | 所有未完成节点都 failed/blocked，scheduler 找不到 ready node 且未 all-done | 进入 `replanner_node` 重新生成 DAG；保留已完成节点的 `node_outputs` 作为新 plan 的输入 | 受 `max_replans` 上限保护 |
| **DAG 解析失败（planner 输出非法 JSON）** | `_parse_plan_dag` 抛 `ValueError`（环、id 重复、final_node_id 不匹配等） | `_fallback_plan_dag` 生成 1 节点 DAG（goal=原 question），保留 raw + parse_error 进 trace | executor 仍能完整工作，仅丢失分解优势 |
| **Replan 预算用尽** | `replan_count >= max_replans` 仍卡住 | 跳过 reflector 直接进 finalize；`failure_reason="DAG execution stuck after N replans."` | 任务标记失败 |
| 任务级超时 | `e2e > task_timeout_seconds` | 父进程 `terminate()` 子进程 | trace 退化为占位（steps=[]），`failure_reason="Task timed out after N seconds."` |
| 单任务异常未被 LangGraph 捕获 | 极端 case | `runner._run_single_task_in_subprocess` 的 `BaseException` 兜底，`failure_reason="Task failed with uncaught error: ..."` | 任务标记失败，benchmark 整体不中断 |

---

## 10. 配置项参考

### 10.1 YAML 字段

```yaml
dataset:
  root_path: data/public/input         # 测试数据根目录

agent:
  model: qwen-max-latest               # 任意 OpenAI 兼容模型；必须支持 tool calling
  api_base: https://...                # OpenAI 兼容端点
  api_key: ${API_KEY:-sk-xxx}          # 支持 ${ENV_VAR:-default} 语法
  max_steps: 50                        # → graph recursion_limit = max(8, max_steps*4)
  temperature: 0.0                     # planner / executor / reflector 共用

run:
  output_dir: artifacts/runs           # 输出根
  run_id:                              # 留空 = UTC 时间戳
  max_workers: 4                       # 并行 task 数（ThreadPool）
  task_timeout_seconds: 600            # 0 / 负数 = 禁用超时
```

### 10.2 代码内 hardcoded 限制

| 常量 | 位置 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `EXECUTE_PYTHON_TIMEOUT_SECONDS` | `tools/langchain_tools.py` & `tools/registry.py` | `30` | `execute_python` 单次执行墙钟上限 |
| `LangGraphAgentConfig.max_reflections` | `agents/langgraph_agent.py` | `1` | reflector RETRY 次数上限 |
| `LangGraphAgentConfig.max_idle_nudges` | `agents/langgraph_agent.py` | `2` | nudge 节点重试上限 |
| `LangGraphAgentConfig.max_replans` | `agents/langgraph_agent.py` | `1` | replanner 调用次数上限；`0` 禁用 replan |
| `LangGraphAgentConfig.max_node_attempts` | `agents/langgraph_agent.py` | `2` | 单节点本地软重试次数 |
| `LangGraphAgentConfig.max_steps_per_node` | `agents/langgraph_agent.py` | `8` | 单节点 LLM 步数预算（防节点内死循环） |
| `recursion_limit` 公式 | `LangGraphAgent.run` | `max(8, max_steps * 6)` | 节点级累计上限（DAG 模式下事件较多，已从 *4 提到 *6） |
| `ChatOpenAI` 超时 | `build_chat_openai` | `timeout=60, max_retries=2` | 单次 LLM 调用 |

---

## 11. 扩展点（未来工作）

下面这些都是当前**没做但容易做**的扩展，按优先级排：

### 11.1 把 `max_reflections / max_idle_nudges / max_replans / max_node_attempts / max_steps_per_node` 暴露到 YAML（推荐先做）

**改 3 个地方**：
1. `config.AgentConfig` 增加字段
2. `config.load_app_config` 解析
3. `runner._run_single_task_core` 透传到 `LangGraphAgentConfig`

### 11.2 历史 ToolMessage 滑动窗口（解决长上下文）

`task_64` 跑完一次的 `messages` 长度十几条是小事；遇到复杂任务时，`read_csv` 大文件预览或 `execute_python` 大输出会让 token 飙升。可以在 `executor_node` 里：

```python
def executor_node(state):
    pruned = _prune_history(state["messages"], keep_last=8, always_keep_first=2)
    response = executor_llm.invoke(pruned)
    return {"messages": [response]}
```

注意：被裁掉的 ToolMessage 仍保留在 graph state 里用于 trace；只是不再发给 LLM。

### 11.3 工具调用去重缓存（解决"反复读同一文件"）

在 `ToolRunContext` 里加一个 `recent_tool_calls: dict[str, dict]`（key=`tool_name+args_hash`），如果同一调用在最近 3 步内重复出现，就直接返回上次结果 + 警告。

### 11.4 流式落盘（解决超时 trace 丢失）

把 `compiled_graph.invoke(...)` 换成 `compiled_graph.stream(...)`，每个 step 后增量序列化 `messages` 到 `trace.json.partial`，任务结束时原子 rename。

### 11.5 Best-of-N / Self-Consistency

外层包一个 `for sample in N: run(task, temperature=0.7)`，再用 `answer` 的等价类比较或 LLM judge 投票（对应 PER-Loop 中的 outer loop）。

### 11.6 Multi-Agent / Sub-Graph

把 `executor` 拆成 `code_writer + code_reviewer + retry_planner` 子图，复用 LangGraph 的 `subgraph` 能力。

### 11.7 DAG 节点级并行执行

当前 scheduler 是**串行拓扑序**派发，即使 `n2` 和 `n3` 都依赖 `n1` 且互不依赖，也会被顺序执行。可改造为：

- 把 `dag_scheduler_node` 输出的下一节点从 `str` 升级为 `list[str]`
- 用 LangGraph 的 `Send` API 把多个 ready 节点 fan-out 到独立的 executor 子任务
- 各子任务持有独立的局部 messages（通过 subgraph 隔离），节点完成后 fan-in 回主图

注意：并行后 `messages` 必须按 `node_id` 分桶，否则 `_build_step_records` 的时序会乱；落盘 trace 需要新增 `parent_node_id` 字段维持因果。

### 11.8 DAG 节点级缓存

把每个节点的 `(goal, upstream_summaries)` 哈希作为 key，缓存 `mark_node_done.summary` 到本地磁盘 / Redis。在 benchmark 跨任务存在重复子问题时（比如 "list context" 这种节点几乎每个 task 都有）可以显著省 token。

### 11.9 DAG 可视化

在 trace.json 已经包含完整 DAG JSON 的前提下，可以再接一个 `dabench viz-trace <task_id>` 子命令，用 mermaid / graphviz / matplotlib 渲染：节点 = 圆角矩形，颜色按 `node_status` 着色（done=绿、failed=红、blocked=灰），边 = `depends_on`，节点上叠加 `attempts` 数字和 `summary` tooltip。当前未实现，按需添加。

---

## 12. 调试指南

### 12.1 拿到完整 trace（最常用）

```bash
# 临时禁用任务超时
sed -i '' 's/task_timeout_seconds: 600/task_timeout_seconds: 0/' configs/react_baseline.local.yaml
uv run dabench run-task <id> --config configs/react_baseline.local.yaml
cat artifacts/runs/$(ls -t artifacts/runs/ | head -1)/<id>/trace.json | head -300
```

### 12.2 trace 解读速查

| 看到 `action` 是 | 意味着 |
| --- | --- |
| `__plan__` | planner 阶段 |
| `__assistant_text__` | executor 没调工具（通常是异常情况，看后续是否被 nudge） |
| `__reflect__` | reflector verdict（看 `observation.content.verdict`） |
| `list_context / read_csv / read_json / read_doc / inspect_sqlite_schema / execute_context_sql / execute_python` | 正常工具调用 |
| `answer` | 最终答案提交（紧接着应有 `__reflect__`） |

### 12.3 失败原因速查

| `failure_reason` | 应对 |
| --- | --- |
| `RuntimeError: Missing or placeholder ...` | YAML 配置没填实值 |
| `APIConnectionError: ...` | 网络 / 端点错误 |
| `RateLimitError: ...` | 限流，增加 `max_retries` 或换 key |
| `BadRequestError: ...tool_calls...` | 模型不支持 tool calling，必须换支持的模型 |
| `Agent did not submit an answer within the step budget.` | nudge 用尽仍未调 `answer`，看 trace 里 `__assistant_text__` 出现了几次 |
| `Task timed out after N seconds.` | 任务级超时（trace 一般为空） |
| `LangGraph recursion_limit reached` | `max_steps * 4` 还不够，调大 `agent.max_steps` |

### 12.4 可视化图

```python
from data_agent_baseline.agents.langgraph_agent import LangGraphAgent, build_chat_openai
from data_agent_baseline.tools.langchain_tools import build_langchain_tools, ToolRunContext
from data_agent_baseline.benchmark.dataset import DABenchPublicDataset

ds = DABenchPublicDataset("data/public/input")
task = ds.get_task("task_64")
agent = LangGraphAgent(model=build_chat_openai(model="qwen-max-latest", api_base="...", api_key="...", temperature=0))
ctx = ToolRunContext()
graph = agent._build_graph(
    task=task, tools=build_langchain_tools(task, ctx), tool_run_context=ctx, reflection_notes=[]
)
print(graph.get_graph().draw_mermaid())
```

---

## 13. FAQ

**Q: 为什么不直接用 `langgraph.prebuilt.create_react_agent`？**
A: 那是单节点 ReAct，不能塞 planner / reflector / nudge。本方案是有意做成多节点图，方便后续按 PER-Loop 路线（[`05-our-agent-design.md`](./05-our-agent-design.md)）持续演进（加 verifier、加 BoN、加 sub-graph）。

**Q: 为什么 `answer` 工具走共享 `ToolRunContext` 而不是 graph state？**
A: LangGraph 的 `ToolNode` 默认只把工具返回值写入 `ToolMessage` 内容字段，不会修改自定义 state 字段。要么自己重写 ToolNode（增加复杂度），要么用一个 task 级闭包变量（当前选择）。后者更简洁，且 `ToolRunContext` 生命周期严格等同于一次 `LangGraphAgent.run`，无并发风险（每次 run 都是新实例）。

**Q: 旧的 `ReActAgent` 还能用吗？**
A: 代码还在，但 `runner.py` 已经不调用它。如果想跑老路径做 A/B 对比，把 `_run_single_task_core` 里的 `LangGraphAgent(...)` 临时换回 `ReActAgent(...)` 即可。

**Q: 模型不支持 tool calling 怎么办？**
A: 当前路径**强依赖**模型支持 OpenAI tool calling 协议。如果需要兼容老模型，需要新增一个"prompt-based 协议"分支（让 executor 用旧 ReAct prompt + JSON 解析），并在 `LangGraphAgentConfig` 里加 `tool_protocol: Literal["native", "prompt"]` 开关。

**Q: 我可以把 reflector 换成更强的 verifier 吗？**
A: 可以。reflector 节点是无状态的纯函数，只依赖 `task.question / state.plan / ToolRunContext.final_answer`。换成 self-consistency 投票、Code Verifier 跑 unit test、甚至 LLM-as-Judge with rubric 都不影响图结构。

**Q: 为什么严格模式 + 显式 `mark_node_done`？不能让 scheduler 看 messages 自动判断节点完成吗？**
A: 三个原因：
1. **可观测性**：显式 `mark_node_done(summary)` 强迫 executor 把节点产出**总结成自然语言**，下游节点拿到的是经过模型自己提炼的高密度信息，而不是一长串 tool messages。
2. **可控性**：自动判断意味着要写 heuristic（比如「调用了 answer 算完成」「N 步无进展算失败」），这些规则一旦不准就会导致跨节点污染。显式工具调用是模型自己做承诺，错了立刻能在 trace 里看到。
3. **可回放**：`__dag_node_done__` 事件的 `summary` 会写进 trace，未来可以单独抽出来做 prompt evaluation 数据集。

**Q: 严格模式下，节点 N 真的看不到节点 M（M < N 但非直接依赖）的 raw output 吗？**
A: 是的。`_focused_executor_prompt` 只注入 **直接 `depends_on` 列表中节点的 summary**，间接前驱节点的产出会被「summary 链」逐级传递。如果某个间接前驱产出对当前节点也很重要，**这是 planner 的 DAG 设计错误**——应该把它加到 `depends_on` 里。

**Q: 节点 attempt 失败 vs DAG 全局卡住，分别什么时候触发 replan？**
A:
- 单节点失败 → 先 **本地软重试**（清空当前节点上下文重派发，最多 `max_node_attempts` 次）
- 本地重试用尽 → 节点 `node_status=failed` → scheduler 下一轮发现 **没有 ready 节点**（因为后继依赖一个 failed 节点） → 进入 `replanner_node`
- replanner 拿到「原问题 + 旧 DAG + 各节点 status + 失败节点的最后一条错误信息」重新规划
- 受 `max_replans` 上限保护（默认 1，即总共最多 plan 1 次 + replan 1 次）

**Q: 我可以禁用 DAG 模式回到旧的纯 ReAct 形态吗？**
A: 设 `LangGraphAgentConfig(max_replans=0)` + 把 `PLANNER_SYSTEM_PROMPT` 临时替换为输出 1 节点 DAG 的固定模板，行为上等价于旧的"线性 plan + executor 自由发挥"。但代码层面 scheduler/mark_node_done 的小开销仍存在，约 1-2 个额外 LLM call。

---

## 14. 变更日志

| 日期 | 变更 |
| --- | --- |
| 2026-05-02 | **初版**：从手写 ReAct 完全切换到 LangGraph 多节点图（planner/executor/tools/reflector/nudge/finalize），新增 nudge 兜底节点；落盘格式保持兼容 |
| 2026-05-02 | **DAG 改造**：planner 输出结构化 JSON DAG，新增 `dag_scheduler_node` 严格按拓扑序派发，executor 进入「focused on a single node」严格模式，新增 `mark_node_done` 工具显式声明节点完成；新增 `replanner_node` + `node_failure_node` 失败兜底；trace 新增 `__plan__.observation.dag` + 4 个伪 action（`__replan__` / `__dag_node_start__` / `__dag_node_done__` / `__node_attempt_failed__`）；新增配置项 `max_replans / max_node_attempts / max_steps_per_node` |
