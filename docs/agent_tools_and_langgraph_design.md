## Data-Agent 工具调用设计与 LangGraph Agent 原理总结

本文档总结当前项目中两部分内容：

- **工具调用设计**：项目设计了哪些工具，为什么这样分层。
- **`src/data_agent_baseline/agents/langgraph_agent.py` 设计原理**：LangGraph Agent 如何规划、调度、执行、反思与收尾。
- **答辩问答**：给出可能被问到的问题，并提供简洁中英文回答。

## 1. 项目整体定位

本项目是 KDD Cup 2026 DataAgent-Bench 的数据分析 Agent baseline。它的目标是让大模型自动完成：

```text
读取数据 → 规划任务 → 多步推理 → 调用工具分析 → 生成 prediction.csv
```

项目支持两种主要运行形态：

- **CLI Agent**：用于批量评测、单任务运行、提交镜像。
- **Web Console**：用于可视化调试、任务上传、实时轨迹和 DAG 展示。

Agent 的核心不只是让模型直接写答案，而是通过工具系统把数据访问、数据分析、SQL 查询、Python 执行、最终答案提交等动作结构化，并通过 LangGraph 把规划、执行、反思、重试组织成稳定流程。

## 2. 工具调用设计

### 2.1 工具体系的两层设计

项目中同时存在两套工具组织方式：

- **Legacy `ToolRegistry`**：位于 `src/data_agent_baseline/tools/registry.py`，主要服务旧版 ReAct Agent。
- **LangChain `StructuredTool` 工具列表**：位于 `src/data_agent_baseline/tools/langchain_tools.py`，主要服务新版 LangGraph Agent。

两者底层复用同一批工具实现，例如：

- `src/data_agent_baseline/tools/filesystem.py`
- `src/data_agent_baseline/tools/data_inspect.py`
- `src/data_agent_baseline/tools/dataframe_query.py`
- `src/data_agent_baseline/tools/sqlite.py`
- `src/data_agent_baseline/tools/python_exec.py`

这种设计的好处是：

- **向后兼容**：旧版 `react` agent 仍然可以通过 `ToolRegistry` 工作。
- **平滑升级**：新版 `langgraph` agent 可以把同样的能力包装成 LangChain tool，绑定到 `ChatOpenAI.bind_tools()`。
- **职责清晰**：工具实现只关心数据操作，Agent 编排只关心流程控制。

### 2.2 工具列表

新版 LangGraph Agent 通过 `build_langchain_tools(task, context)` 为每个任务构建一组工具。每个工具都绑定当前 `PublicTask`，因此路径会被限制在该任务的 `context/` 目录内。

| 工具名 | 类型 | 主要作用 |
|---|---|---|
| `list_context` | 文件发现 | 列出 `context/` 下的文件和目录，避免模型猜路径。 |
| `glob_files` | 文件发现 | 按 glob 模式查找文件，例如 `*.csv`、`db/*.sqlite`、`**/*.json`。 |
| `read_csv` | 数据预览 | 读取 CSV 的列名和前若干行。 |
| `read_json` | 数据预览 | 读取 JSON 的部分内容。 |
| `read_doc` | 文档读取 | 读取 Markdown/TXT 等文本文件，支持全文、切片和 grep 三种模式。 |
| `inspect_sqlite_schema` | SQLite 结构检查 | 查看 SQLite/DB 文件中的表和建表语句。 |
| `inspect_data` | 表结构画像 | 一次性返回列类型、空值数、唯一值、样例值、数值范围等。 |
| `execute_context_sql` | SQLite 查询 | 对 SQLite/DB 文件执行只读 SQL。 |
| `query_dataframe` | 文件 SQL 查询 | 把 CSV/TSV/JSON/JSONL/Parquet 加载为内存 SQLite 表 `df` 后执行 SQL。 |
| `execute_python` | Python 执行 | 在任务 `context/` 下执行 Python 代码，适合复杂解析或特殊计算。 |
| `mark_node_done` | DAG 控制 | 标记当前非最终 DAG 节点完成，并保存节点摘要。 |
| `answer` | 最终提交 | 提交最终答案表，写入 `ToolRunContext.final_answer`。 |

### 2.3 工具设计的核心原则

#### 2.3.1 路径安全

所有访问数据的工具都通过 `resolve_context_path(task, relative_path)` 解析路径。它会确保：

- 路径必须位于当前任务的 `context/` 目录内。
- 不允许通过 `../` 或绝对路径逃逸。
- 文件不存在时，会返回可用顶层文件提示，帮助模型自我修正。

这降低了两个风险：

- 模型幻觉路径导致任务失败。
- 工具访问任务目录外的数据。

#### 2.3.2 优先使用专用工具，减少 Python 滥用

项目不是只提供 `execute_python` 一个万能工具，而是增加了多个专用工具：

- `inspect_data` 替代 `df.head()` / `df.dtypes` / `df.shape` 这类探查代码。
- `query_dataframe` 替代简单的 pandas 过滤、聚合、分组。
- `glob_files` 替代 Python 中的 `os.listdir()` / `glob.glob()`。
- `read_doc(grep=...)` 替代长文档反复分页阅读。

这样可以减少 LLM 回合数，提高稳定性，并让工具返回结构化结果。

#### 2.3.3 只读查询优先

`execute_context_sql` 和 `query_dataframe` 都只允许 `SELECT`、`WITH`、`PRAGMA` 这类只读语句。这样既满足分析需求，也避免修改数据。

#### 2.3.4 工具错误可恢复

LangGraph 中的 `ToolNode` 设置了 `handle_tool_errors=_format_tool_error`。工具异常不会直接让任务崩溃，而是转换成 `ToolMessage(status="error")` 返回给模型。

这让模型可以根据错误继续修正，例如：

- 文件不存在 → 先调用 `list_context`。
- SQL 表名错误 → 调用 `inspect_sqlite_schema`。
- 列名错误 → 查看 `column_mapping` 或 `inspect_data`。

#### 2.3.5 控制工具和分析工具分离

工具中有两类特殊工具：

- `mark_node_done`：不是数据分析工具，而是 DAG 节点完成信号。
- `answer`：不是中间分析工具，而是最终提交信号。

这种设计把“任务流程控制”和“数据分析动作”统一放进工具调用协议里，但语义上仍然清晰分离。

## 3. `langgraph_agent.py` 设计原理

### 3.1 核心思想

`src/data_agent_baseline/agents/langgraph_agent.py` 实现了一个 DAG 驱动的多节点 Agent。它不是让模型用一个长 ReAct 轨迹解决所有问题，而是先规划 DAG，再逐个执行节点。

整体流程可以概括为：

```text
planner → scheduler → executor → reasoning → tools
          ↑             ↓          ↓
          │             nudge      reflector → finalize
          │             ↓          ↑
          └── replanner ← node_failure
```

核心设计目标是：

- **先规划再执行**：减少盲目探索。
- **DAG 拆分任务**：把复杂数据分析拆成可验证子任务。
- **节点级调度**：每次只聚焦一个子任务。
- **工具闭环**：执行器调用工具，工具结果继续反馈给执行器。
- **反思修正**：最终答案提交后由 reflector 检查格式和形状。
- **失败可恢复**：节点卡住时可重试或重新规划。

### 3.2 状态设计

LangGraph 的状态类型是 `AgentState`，主要字段包括：

- `messages`：标准对话消息，由 `add_messages` reducer 追加或覆盖。
- `reflections_used`：已经使用的反思次数。
- `idle_nudges_used`：空回复 nudge 次数。
- `steps_in_current_node`：当前 DAG 节点内执行器 LLM 回合数。
- `pending_replan_reason`：触发重新规划的原因。
- `finalized`：是否进入最终结束状态。
- `failure_reason`：失败原因。

DAG 本身不直接放在 `AgentState` 中，而是放在 `ToolRunContext.dag_state` 中。原因是 `mark_node_done` 运行在 `ToolNode` 里，需要通过闭包可写的共享对象更新 DAG 节点状态。

`ToolRunContext` 保存：

- `final_answer`：最终答案。
- `submitted_answers`：历史提交答案，用于 fallback。
- `dag_state`：DAG 状态、节点状态、节点摘要、重规划次数、事件日志。
- `pending_node_done_signals`：节点完成信号。
- `exit_reason`：退出原因。

### 3.3 Planner：生成 DAG 计划

`planner_node` 会先构造数据集画像 `_build_dataset_profile(task)`，内容包括：

- `context/` 下真实文件列表。
- SQLite 表结构。
- JSON/CSV/文本文档的简短预览。

然后把问题、可用工具、数据集画像一起交给 planner LLM，要求输出严格 JSON：

```json
{
  "nodes": [
    {
      "id": "n1",
      "goal": "...",
      "depends_on": [],
      "suggested_tools": ["list_context"],
      "expected_output": "..."
    }
  ],
  "final_node_id": "n1"
}
```

解析后会通过 `_parse_plan_dag()` 校验：

- JSON 可解析。
- 节点非空。
- 节点 id 唯一。
- 依赖只能指向之前节点，保证拓扑顺序和无环。
- `final_node_id` 必须存在，并且必须是最后一个节点。

如果解析失败，会退化为 `_fallback_plan_dag()` 的单节点计划，避免整个任务直接失败。

### 3.4 Scheduler：选择下一个可执行节点

`dag_scheduler_node` 负责挑选下一个 ready 节点：

- 如果所有节点完成，进入反思或结束。
- 如果存在依赖已完成且状态为 `pending` 的节点，就把它设为 `in_progress`。
- 如果没有 ready 节点但任务未完成，说明 DAG 卡住，设置 `pending_replan_reason`，进入 replanner。

Scheduler 会生成聚焦提示 `_focused_executor_prompt()`，其中包含：

- 原始问题。
- 当前节点 id、goal、expected output。
- 当前节点建议工具。
- 上游节点的摘要。
- 当前节点完成方式：
  - 非最终节点：调用 `mark_node_done`。
  - 最终节点：调用 `answer`。

这个设计让 executor 每次只关注一个子目标，减少上下文混乱。

### 3.5 Executor：调用工具完成当前节点

`executor_node` 是实际执行者。它使用 `self.model.bind_tools(tools)` 绑定工具后，让模型选择工具调用。

Executor 内部有多个防卡死机制：

- **重复工具调用检测**：如果连续多次调用同一工具且参数相同，会注入系统提醒，要求换参数、换工具或提交当前结果。
- **`read_doc` 过度使用检测**：如果一个节点内多次读文档仍无结果，会提醒切换策略。
- **节点步数软提醒**：当当前节点消耗到动态预算的约 70% 时，提醒模型尽快提交结果。
- **空回复不计步**：模型空回复且无工具调用时，不消耗节点步数，而是进入 `nudge`。

### 3.6 Reasoning：补齐工具调用理由

很多 OpenAI-compatible 模型在调用工具时，`content` 为空，只返回结构化 `tool_calls`。这样 trace 中会缺少“为什么调用工具”的说明。

因此 `reasoning_node` 会拦截“有工具调用但没有文本内容”的消息，调用一次普通 LLM，把工具调用补写成 1-3 句简短理由。它会用相同 message id 替换原 AIMessage，保留原 tool_calls。

这样做的好处是：

- trace 更可读。
- Web UI 更容易展示 Reason → Act 轨迹。
- 不破坏 OpenAI 工具调用协议。

### 3.7 Tools：执行工具并返回结果

`tools` 节点是 LangGraph 的 `ToolNode`。它负责执行 executor 选择的工具。

工具结果进入 `ToolMessage` 后，路由会判断：

- 如果调用了 `answer` 且有 `final_answer`，进入 `reflector`。
- 如果调用了 `mark_node_done`，回到 `scheduler` 选择下一个节点。
- 如果当前节点步数超限，进入 `node_failure`。
- 否则回到 `executor` 继续当前节点。

### 3.8 Reflector：检查最终答案

`reflector_node` 会在最终答案提交后检查答案是否合理，重点关注：

- 列数是否符合问题。
- 是否提交了多余列。
- 行数是否符合问题，例如 count 类问题应该只有一行。
- 数值、日期、空值、字符串大小写格式是否合理。

如果判断 `OK`，进入 `finalize`。

如果判断 `RETRY` 且反思次数未超限，会清空当前 `final_answer`，把最终节点重新设为 `pending`，让 scheduler 重新聚焦最终节点并要求 executor 再次调用 `answer`。

### 3.9 Replanner 与 Node Failure

当 executor 在一个节点内耗尽步数，`node_failure_node` 会记录一次节点失败尝试。

- 如果还没达到 `max_node_attempts`，该节点重新设为 `pending`，允许再次尝试。
- 如果达到上限，该节点设为 `failed`，触发 replanner。

`replanner_node` 会收到：

- 原始问题。
- 最新数据集画像。
- 上一次 DAG。
- 每个节点状态。
- 已完成节点摘要。
- 失败原因。

然后生成新的 DAG，并重置执行对话，使 Agent 用新的计划继续。

### 3.10 Run：运行和结果收集

`LangGraphAgent.run()` 会：

1. 创建 `ToolRunContext`。
2. 为当前任务构建 LangChain tools。
3. 如果提供 `task_output_dir`，注册 partial trace flush，用于 Web 实时展示。
4. 编译并执行 LangGraph。
5. 从 `ToolRunContext.final_answer` 取最终答案。
6. 如果 reflector 清空了最新答案但任务耗尽预算，则回退到最近一次 `submitted_answers`。
7. 将消息和 DAG 事件转换为 `StepRecord`，写入结构化 trace。
8. 返回 `AgentRunResult`。

### 3.11 设计优势

- **抗幻觉**：planner 前置数据集画像，工具路径校验，错误信息带真实文件提示。
- **可解释**：DAG 事件、工具调用、reasoning 文本都会进入 trace。
- **可恢复**：工具错误可反馈给模型，节点失败可重试，整体失败可 replan。
- **可控预算**：每节点步数、空回复 nudge、反思次数、replan 次数都有上限。
- **评测友好**：`answer` 工具强制结构化答案表，并强调最小列集、格式规范。
- **可视化友好**：DAG 状态和 partial trace 可实时写入，支持 Web Console 展示。

## 4. 答辩可能问题与简洁答案
### Q7：这个设计有哪些工具？
- **中文**：主要有文件发现工具、数据预览工具、表结构画像工具、SQL 查询工具、Python 执行工具、DAG 控制工具和最终答案工具。
- **English**: It has file tools, preview tools, data profile tools, SQL tools, Python tool, DAG control tool, and final answer tool.


### Q8：如何保证工具访问安全？

- **中文**：路径会通过 `resolve_context_path` 校验，只能访问当前任务的 `context/` 目录，SQL 工具也只允许只读查询。
- **English**: Paths are checked by `resolve_context_path`, so tools only access the task `context/` folder. SQL tools are read-only.


### Q11：为什么用 LangGraph？

- **中文**：LangGraph 可以把 planner、scheduler、executor、tools、reflector 等步骤组织成显式状态机，比单纯 ReAct 更可控。
- **English**: LangGraph lets us build an explicit state machine with planner, scheduler, executor, tools, and reflector. It is more controllable than plain ReAct.

### Q12：`langgraph_agent.py` 的核心流程是什么？

- **中文**：先由 planner 生成 DAG，再由 scheduler 选择节点，executor 调工具执行，最终 answer 后由 reflector 检查，最后 finalize。
- **English**: The planner creates a DAG. The scheduler picks a node. The executor uses tools. After answer, the reflector checks it, then finalize ends the run.

### Q13：为什么要先生成 DAG？

- **中文**：DAG 把复杂问题拆成可验证的子任务，减少长链推理混乱，也方便失败后局部重试或重规划。
- **English**: A DAG splits a hard task into smaller checkable parts. It reduces confusion and supports retry or replan.

### Q14：Scheduler 的作用是什么？

- **中文**：它根据依赖关系选择下一个可执行节点，并给 executor 一个只关注当前节点的提示。
- **English**: It picks the next ready node by dependencies and gives the executor a focused prompt for that node.

### Q15：Executor 如何避免一直卡住？

- **中文**：它有重复工具调用检测、文档读取过度检测、节点步数提醒和空回复 nudge 机制。
- **English**: It uses repeated-call checks, read-doc overuse checks, step warnings, and empty-reply nudges.

### Q16：Reasoning 节点为什么存在？

- **中文**：有些模型调用工具时没有文本说明。Reasoning 节点补一句工具调用理由，让 trace 更容易理解。
- **English**: Some models call tools with no text. The reasoning node adds a short reason, so the trace is easier to read.

### Q17：Reflector 检查什么？

- **中文**：它检查答案的列数、行数、格式和值是否符合题意，发现可修复问题时要求重新提交。
- **English**: It checks columns, rows, format, and values. If there is a fixable issue, it asks for a new answer.

### Q18：什么时候会 Replan？

- **中文**：当 DAG 卡住，或某个节点多次失败超过上限时，会触发 replanner 生成新计划。
- **English**: Replan happens when the DAG is stuck or a node fails too many times.

### Q19：这个设计相比普通 ReAct 的优势是什么？

- **中文**：它有明确计划、节点级状态、失败恢复、答案反思和可视化轨迹，整体更稳定、更可解释。
- **English**: It has a clear plan, node states, failure recovery, answer reflection, and visual trace. It is more stable and explainable.

### Q20：为什么答案要强调最小列集？

- **中文**：评测会惩罚多余列。只提交问题真正需要的列，可以提高得分。
- **English**: The grader penalizes extra columns. Submitting only needed columns improves the score.

### Q21：如果工具报错会怎样？

- **中文**：错误会变成 ToolMessage 返回给模型，模型可以根据错误调整路径、表名、SQL 或工具选择。
- **English**: The error becomes a ToolMessage. The model can fix the path, table, SQL, or tool choice.

### Q22：为什么要做数据集画像？

- **中文**：画像把真实文件、表结构和数据预览交给 planner，减少路径和表名幻觉。
- **English**: The profile gives real files, schemas, and previews to the planner. It reduces fake paths and table names.

### Q23：Web Console 如何获得实时轨迹？

- **中文**：DAG 状态变化时会写 partial `trace.json`，前端可以轮询并实时展示执行过程。
- **English**: The agent writes partial `trace.json` during DAG events. The frontend can poll it and show live progress.


### Q25：这个 Agent 最重要的工程取舍是什么？

- **中文**：它用更多结构化流程换取稳定性和可解释性，同时保留 Python 作为兜底能力。
- **English**: It uses more structure for stability and explainability, while keeping Python as a fallback.

## 5. 一句话总结

本项目的核心设计是：**用专用工具降低数据分析中的不确定性，用 DAG + LangGraph 管理多步推理过程，用反思和重规划提高失败恢复能力，最终产出结构化、可评测的答案表。**

In short: **the project uses tools to reduce uncertainty, DAG + LangGraph to control multi-step reasoning, reflection and replanning to recover from failures, and structured answer tables for evaluation.**
