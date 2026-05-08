# boost-agent 架构说明文档

> 本文档描述 `boost-agent` 仓库当前线上版本的系统架构。代码以 KDD Cup 2026 DataAgent-Bench Starter Kit 为基础，已经被深度改造为一套基于 **LangGraph DAG 编排 + 多轮投票 + 失败重试** 的数据分析 Agent。

---

## 目录

- [1. 项目概览](#1-项目概览)
- [2. 顶层架构图](#2-顶层架构图)
- [3. 仓库目录结构](#3-仓库目录结构)
- [4. CLI / 配置层 / 数据集层](#4-cli--配置层--数据集层)
- [5. Agent 核心：LangGraph DAG 流水线](#5-agent-核心langgraph-dag-流水线)
- [6. 工具层（12 个工具）](#6-工具层12-个工具)
- [7. 运行调度层：Runner / 多轮投票 / Retry / 评分](#7-运行调度层runner--多轮投票--retry--评分)
- [8. 提交流水线：Docker / entrypoint / 评测平台对接](#8-提交流水线docker--entrypoint--评测平台对接)
- [9. 端到端时序与数据流](#9-端到端时序与数据流)
- [10. 关键设计决策与历史教训](#10-关键设计决策与历史教训)

---

## 1. 项目概览

### 1.1 业务目标

参加 KDD Cup 2026 **DataAgent-Bench** 比赛：评测系统给出一道数据分析题（自然语言问题 + 一个 `context/` 目录，目录里可能放着 CSV / JSON / SQLite / Markdown 文档），Agent 必须仅通过提供的工具读取这些文件、推理并产出一张最简表格作为答案。评测器按列签名做集合匹配，并对**多余列**施加惩罚：

\[
\text{Score} = \max\left(0,\ \text{Recall} - \lambda \cdot \frac{\text{extra}}{\text{predicted}}\right),\quad \lambda = 0.5
\]

### 1.2 技术栈

| 层 | 选型 | 说明 |
| --- | --- | --- |
| **Agent 编排** | `langgraph` + `langchain-core` | 用 StateGraph 把 planner/scheduler/executor/tools/reflector 等节点接成有条件路由的图 |
| **LLM 客户端** | `langchain-openai` (`ChatOpenAI`) | OpenAI 兼容协议，支持 Qwen 等替代后端 |
| **CLI** | `typer` + `rich` | `dabench` 入口，进度条、表格输出 |
| **数据处理** | `pandas` / `polars` / `duckdb` / `pyarrow` | 主要供 `execute_python` / `query_dataframe` 工具内部使用 |
| **可视化** | `matplotlib` / `networkx` | DAG 可视化（`dag.svg` 写入每个 task 的 run 目录） |
| **配置/构建** | `pydantic` v2 + `pyyaml` + `hatchling` + `uv` | YAML + 环境变量展开，依赖通过 `uv sync` 安装 |

### 1.3 核心设计原则

1. **DAG-driven**：planner 把题目拆成 2-6 个有依赖关系的子任务节点，executor 一次只看一个 focused 节点；避免长上下文中迷失。
2. **失败兜底层层叠加**：每节点 `max_steps_per_node` → 多次节点 `max_node_attempts` → 整体 `max_replans` → 多轮投票 → 失败 task 单独 retry pass。
3. **保底输出语义**：`prediction.csv` 一旦写出就立刻被 entrypoint 同步到 `/output`；后续轮次的胜出者再用 `os.replace` 原子覆盖。即使评测平台中途 `kill -TERM`，已落盘的 prediction.csv 仍参与评分。
4. **强反幻觉**：planner prompt 注入真实的 `context/` 文件清单 + sqlite schema + json/csv head（dataset profile），杜绝"凭空捏造路径"。
5. **签名规范化**：投票和评分都基于"sorted(per-column-cells)"的列签名，自动忽略列顺序、行顺序、数字精度、日期格式差异。

---

## 2. 顶层架构图

```
                         ┌──────────────────────────────────────────────┐
                         │              评测平台 / 本地用户              │
                         │  注入：MODEL_API_URL / MODEL_NAME / ...      │
                         │  挂载：/input (任务集) / /output (结果)      │
                         └───────────────────┬──────────────────────────┘
                                             │ docker run
                                             ▼
                ┌────────────────────────────────────────────────────────┐
                │                   entrypoint.sh                         │
                │  - 后台循环 5s 把 /artifacts/runs/*/task_*/prediction │
                │    .csv 拍平到 /output/task_*/prediction.csv          │
                │  - 启动 `uv run dabench run-benchmark`                 │
                └───────────────────┬────────────────────────────────────┘
                                    ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │                            CLI (cli.py)                                     │
   │   status | inspect-task | run-task | run-benchmark | score                  │
   └────────────────────────┬─────────────────────────┬─────────────────────────┘
                            │ 加载 YAML+env           │ 进度条 / 表格
                            ▼                          ▼
   ┌──────────────────────────────────┐   ┌─────────────────────────────────┐
   │      Config (config.py)          │   │  Dataset (benchmark/)            │
   │  AppConfig                        │   │  DABenchPublicDataset            │
   │  ├── DatasetConfig                │   │  ├── task_dirs() / iter_tasks()  │
   │  ├── AgentConfig                  │   │  └── PublicTask (task.json+ctx) │
   │  └── RunConfig (vote_rounds, …)   │   │                                 │
   └──────────────────────────────────┘   └─────────────────────────────────┘
                                                          │
                                                          ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │                      Run Orchestration (run/runner.py)                      │
   │                                                                             │
   │  for round in 1..vote_rounds:                                               │
   │      _execute_one_round(round_idx)                                          │
   │          ThreadPoolExecutor(max_workers)  ──►  run_single_task(task_id)    │
   │              │                                  │                          │
   │              │                                  ▼                          │
   │              │              multiprocessing.Process + timeout                │
   │              │                                  │                          │
   │              │                                  ▼                          │
   │              │              ┌─────────────────────────────────────────┐    │
   │              │              │  LangGraphAgent.run(task) ◄──────────── │    │
   │              │              │  (见第 5 章 DAG 流水线)                  │    │
   │              │              └─────────────────────────────────────────┘    │
   │              │                                                              │
   │              ▼                                                              │
   │      _round_artifact_filename:                                              │
   │        round 1 → prediction.csv                                             │
   │        round N≥2:  prediction.csv 已存在 → rN.csv                            │
   │                    否则               → prediction.csv (back-fill)          │
   │      round ≥ 4 → 增量 vote_task_with_candidates 立即覆盖 prediction.csv     │
   │                                                                             │
   │  vote_all_tasks(run_output_dir)   ── 多数投票 + earliest tiebreak           │
   │  _execute_retry_pass()            ── 对仍失败 task 再跑一次到 _retry.csv    │
   └────────────────────────────────────────────────────────────────────────────┘
                                                          │
                                                          ▼
                              artifacts/runs/<run_id>/task_<id>/
                                ├── prediction.csv   (评测系统读取)
                                ├── trace.json
                                ├── r2.csv / r3.csv  (候选)
                                └── dag.svg
```

> 详细的子流水线（DAG 内部 9 节点路由、工具调用细节、投票规则）见后续章节。

---

## 3. 仓库目录结构

```
boost-agent/
├── src/data_agent_baseline/        ← 全部 Python 源码（包名 = data_agent_baseline）
│   ├── cli.py                       ← typer 命令行入口
│   ├── config.py                    ← AppConfig + ${VAR:-default} 环境变量展开
│   ├── benchmark/
│   │   ├── dataset.py               ← DABenchPublicDataset：读 /input，列 task_*
│   │   └── schema.py                ← TaskRecord / PublicTask / AnswerTable dataclass
│   ├── agents/
│   │   ├── langgraph_agent.py       ← 核心：LangGraph DAG agent（~1500 行）
│   │   ├── runtime.py               ← StepRecord / AgentRunResult
│   │   ├── prompt.py                ← legacy ReAct prompt（保留）
│   │   ├── react.py                 ← legacy ReAct runtime（保留）
│   │   ├── model.py                 ← 兼容旧 ToolRegistry 的 ChatOpenAI 适配
│   │   └── dag_visualizer.py        ← networkx + matplotlib 渲染 dag.svg
│   ├── tools/
│   │   ├── langchain_tools.py       ← 12 个 LangChain StructuredTool 工厂
│   │   ├── registry.py              ← legacy 工具注册（ReAct 路径用）
│   │   ├── filesystem.py            ← list_context / read_csv / read_json / read_doc / glob_files
│   │   ├── sqlite.py                ← inspect_sqlite_schema / execute_read_only_sql
│   │   ├── data_inspect.py          ← inspect_data（CSV/JSON/SQLite 列画像）
│   │   ├── dataframe_query.py       ← query_dataframe（CSV/JSON/Parquet → 内存 SQLite）
│   │   └── python_exec.py           ← execute_python（受限子进程，30s 超时）
│   └── run/
│       ├── runner.py                ← run_single_task / run_benchmark + 多轮 + retry
│       ├── vote.py                  ← vote_task_with_candidates / vote_all_tasks
│       ├── table_signature.py       ← normalize_cell + compute_table_signature
│       └── scoring.py               ← KDD Cup 评分公式
├── configs/
│   ├── react_baseline.example.yaml  ← 官方示例配置
│   ├── react_baseline.local.yaml    ← 本地开发配置
│   └── react_baseline.submit.yaml   ← 提交镜像用配置（${VAR:-default} 占位）
├── data/public/                     ← 公开 demo 数据集（input/ + output/gold.csv）
├── artifacts/runs/                  ← 本地运行产物（按 run_id 分目录）
├── docs/                            ← 设计文档（含本文件、研究综述、langgraph 架构图）
├── scripts/                         ← visualize_agent_workflow.py 等辅助脚本
├── tests/                           ← pytest 单测
├── entrypoint.sh                    ← Docker ENTRYPOINT：后台同步 + 启动 benchmark
├── Dockerfile                       ← 镜像构建脚本（基础镜像 + uv sync）
├── pyproject.toml                   ← 依赖 + dabench 命令注册
└── README.md / README.zh.md         ← 用户向 README
```

后续章节将按照「**配置/数据集 → Agent → 工具 → Runner → 提交**」的方向逐层展开。

---

## 4. CLI / 配置层 / 数据集层

### 4.1 CLI（`src/data_agent_baseline/cli.py`）

通过 `pyproject.toml` 注册的入口：

```toml
[project.scripts]
dabench = "data_agent_baseline.cli:main"
```

`main()` 启动一个 `typer.Typer` app，目前提供 5 个子命令：

| 子命令 | 用途 | 关键依赖 |
| --- | --- | --- |
| `status` | 打印项目路径、配置路径、数据集存在状态、各难度题数 | `DABenchPublicDataset.task_counts()` |
| `inspect-task <task_id>` | 打印某道题的元数据 + `context/` 文件树 | `list_context_tree(task)` |
| `run-task <task_id>` | 单题跑 LangGraph agent，落 `prediction.csv` 与 `trace.json` | `run.runner.run_single_task` |
| `run-benchmark` | 整个数据集跑（多轮投票 + retry），实时进度条 | `run.runner.run_benchmark` |
| `score` | 用 gold 表计算每个 task 的分数（Recall − λ·extra/predicted） | `run.scoring.score_run` |

**懒加载策略**：`run-task` / `run-benchmark` 才会 `from data_agent_baseline.run.runner import ...`。这是因为 `runner` 间接依赖 `langgraph_agent` → `dag_visualizer` → `matplotlib`，而 `score` / `status` / `inspect-task` 不需要这些重依赖。

**进度条设计**（`run-benchmark`）：

```text
Benchmark (round 2/3) ⠋ ████████████░░░░░░░░  62/150  | ok=58 fail=4 run=2 queue=86
| rate=12.3 task/min | elapsed 0:05:18 | eta 0:07:02 | last=task_42 (ok)
```

进度条总量 = `task_count_per_round × vote_rounds`，每完成一个 (task, round) 就触发 `on_task_complete` 回调一次，`current_round` 从累计完成数除以单轮 task 数推算（worker 内乱序，但每轮边界精确）。

### 4.2 配置层（`src/data_agent_baseline/config.py`）

核心类是不可变 `dataclass(frozen=True, slots=True)`：

```python
@dataclass(frozen=True, slots=True)
class AppConfig:
    dataset: DatasetConfig    # root_path
    agent:   AgentConfig      # model / api_base / api_key / max_steps / temperature
    run:     RunConfig        # output_dir / run_id / max_workers /
                              #   task_timeout_seconds / vote_rounds
```

#### 4.2.1 环境变量展开

YAML 字段中允许 `${VAR}` 或 `${VAR:-default}` 语法：

```python
_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")
```

只对 `agent.model` / `agent.api_base` / `agent.api_key` 三个字段做展开。这是 KDD Cup 提交规则的硬性要求（API key 不能硬编码进镜像）。注意当前实现**不支持嵌套**，如 `${A:-${B:-x}}` 会被错误解析（已在 `react_baseline.submit.yaml` 注释中显式声明）。

#### 4.2.2 路径解析

`_path_value(raw, default)` 把 YAML 中的相对路径以 `PROJECT_ROOT` 为基准解析为绝对路径，绝对路径直接保留。这样 `dataset.root_path: data/public/input` 在任何 cwd 下运行都指向同一处，而提交场景的 `/input` 不会被错误前缀。

#### 4.2.3 `vote_rounds` 校验

```python
if not 1 <= vote_rounds <= 3:
    raise ValueError(...)
```

上限 3 是有意设计的：投票协议中"全异 → 取 earliest" 的 tiebreak 仅适合 ≤3 个候选；超过会因 incremental vote 路径行为不同（详见 §7）。

#### 4.2.4 三套配置文件

| 文件 | 用途 | 关键差异 |
| --- | --- | --- |
| `react_baseline.example.yaml` | 官方示例 | `model: YOUR_MODEL_NAME` 占位，`vote_rounds` 默认 1 |
| `react_baseline.local.yaml` | 本地开发 | 真实 API key，`max_workers: 8`，方便快速冒烟 |
| `react_baseline.submit.yaml` | 提交镜像 | `${MODEL_API_URL:-...}` 等占位、`/input` 与 `/output` 绝对路径、`vote_rounds: 3`、`max_workers: 2`、`task_timeout_seconds: 600` |

`submit.yaml` 内的注释详细记录了多次提交回归的经验值（如：`task_timeout=1800` 会让 4 worker 同时卡死吃光预算，所以收紧到 `360s` 让长尾任务主动放弃）。

### 4.3 数据集层（`src/data_agent_baseline/benchmark/`）

#### 4.3.1 Schema（`schema.py`）

3 个不可变 dataclass：

```python
TaskRecord(task_id, difficulty, question)        # 来自 task.json 的 3 个字段
TaskAssets(task_dir, context_dir)                # 路径快照
PublicTask(record, assets)                       # 组合，提供 .question / .context_dir 等便捷属性
AnswerTable(columns, rows)                       # answer 工具产出的最终表格
```

`PublicTask` 是工具层、agent 层、runner 层共用的核心数据载体，所有"context 路径"概念都从 `task.context_dir` 派生。

#### 4.3.2 数据集索引器（`dataset.py`）

`DABenchPublicDataset(root_dir)` 提供：

- `exists`：`/input` 是否存在；
- `task_dirs() / list_task_ids()`：扫描 `task_<n>` 目录，按 **n 的整数大小**（不是字典序）排序；
- `get_task(task_id)`：读取 `task.json`，校验 `expected_keys == {"task_id","difficulty","question"}` —— 任何字段名漂移都会立刻 fail-fast；
- `iter_tasks(task_ids=, difficulty=, difficulties=)`：支持按白名单或难度筛选。

#### 4.3.3 task 目录契约

```text
data/public/input/task_42/
├── task.json              # {"task_id":"task_42","difficulty":"medium","question":"..."}
└── context/               # 工具能看到的全部输入
    ├── *.csv | *.json | *.db | *.sqlite | *.md | *.txt | ...
    └── （任意子目录嵌套）
```

**关键不变量**：所有工具 `path` 参数都是相对于 `task.context_dir` 的相对路径；底层用 `resolve_context_path` 校验路径不会通过 `..` 或符号链接逃逸出 `context/`。


---

## 5. Agent 核心：LangGraph DAG 流水线

`src/data_agent_baseline/agents/langgraph_agent.py` 是整个项目的"大脑"，约 1500 行。它把传统的 ReAct 单循环换成了 **DAG 驱动 + 多节点协作 + 失败自愈** 的状态机。

### 5.1 LangGraph 节点拓扑

```
                                ┌───────────────────────────────┐
                                ▼                               │
   START ──► planner ──► dag_scheduler ──► executor ──► tools ──┤
                ▲             │   │           │ ▲               │
                │             │   │           │ └──── nudge ◀───┤ (executor 空响应)
                │             │   │           │                 │
                │             │   │           │   (mark_node_done)
                │             │   │           │                 │
                │             │   │           └─ (answer) ─► reflector ──► finalize ──► END
                │             │   │                              │
                │             │   │                              └─ (RETRY) ─► scheduler
                │             │   │
                │             │   └─ 卡住 / 节点失败 ─► node_failure ──► scheduler
                │             │                                              │
                │             │                                              ▼
                │             │                                         (replan_count>=max?)
                │             │                                              │
                │             ▼                                              ▼
                │         replanner ◄───────────────────────────────────── finalize
                │             │
                └─────────────┘
```

涉及 **9 个节点**（在 `_build_graph` 中通过 `StateGraph(AgentState)` 拼接）：

| 节点 | 职责 | 关键状态 |
| --- | --- | --- |
| `planner` | 第一次拆题：产出 JSON DAG 计划（2-6 节点） | 仅运行一次（除非 replan）；写 `tool_run_context.dag_state.dag` |
| `replanner` | 失败兜底：吃前一版计划 + 失败原因，重新出 DAG | `dag_state.replan_count++`，重置节点状态 |
| `dag_scheduler` | 选下一个 ready 节点，给 executor 注入聚焦提示 | 写 `dag_state.current_node_id`，重置 `steps_in_current_node` |
| `executor` | LLM + 工具，单一节点内推进 | 累加 `steps_in_current_node`；空响应不计步 |
| `tools` | LangGraph `ToolNode`：执行工具调用 | 处理 `mark_node_done`/`answer`/inspection 工具 |
| `nudge` | 空响应救援：注入"请继续"消息 | 累加 `idle_nudges_used` |
| `node_failure` | 节点 step 预算耗尽时的软失败处理 | `node_attempts++`，到上限就 mark failed |
| `reflector` | 校验最终答案，OK 即结束，RETRY 让 executor 重新提交 | 累加 `reflections_used` |
| `finalize` | 终止节点（占位，触发 `END`） | — |

### 5.2 共享状态：`AgentState` + `ToolRunContext`

LangGraph 用 `TypedDict` 定义图内消息流：

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]   # add_messages reducer 自动追加
    reflections_used: int
    idle_nudges_used: int
    steps_in_current_node: int
    pending_replan_reason: str | None
    finalized: bool
    failure_reason: str | None
```

但 LangGraph 的状态有一个限制：工具节点（`ToolNode`）内部产生的副作用只能通过返回值进入状态。`mark_node_done` / `answer` 这种"控制流"工具需要写 DAG 状态、最终答案等，单靠 `messages` 字段表达不下。因此设计了一个**侧通道** `ToolRunContext`（在 `tools/langchain_tools.py` 中定义），由 graph 构造期和工具共享同一个实例：

```python
@dataclass(slots=True)
class ToolRunContext:
    dag_state: DAGState                       # 包含 dag / node_status / node_outputs / events / replan_count ...
    final_answer: AnswerTable | None
    submitted_answers: list[AnswerTable]      # 历史所有 answer，便于回溯
    pending_node_done_signals: list[dict]     # 工具→scheduler 的一次性消息
```

每次 `LangGraphAgent.run(task)`：
1. **新建** 一个 `ToolRunContext`（per-task 隔离）；
2. 用 `build_langchain_tools(task, context)` 把所有工具绑定到这个 context；
3. 构图时所有节点也闭包捕获同一个 context 引用；
4. 工具调用直接写 `context.dag_state.node_status[...]`，scheduler 下一拍就能感知到。

### 5.3 节点 1：`planner` — Dataset profile 反幻觉

**最大坑**（提交回归发现）：模型会凭空捏造文件路径，比如题目里有 sqlite，模型会去读 `data.db`，但实际目录里只有 `db/main.sqlite`。

解决方案是在调用 planner LLM 之前，先用 `_build_dataset_profile(task)` 扫一遍 `context/`，把真实文件清单 + sqlite schema + json/csv head 喂给 planner，并在 prompt 中**强制要求** "仅引用 profile 中出现的文件"：

```text
Files under context/ (each line shows the EXACT path to use as the tool `path` argument):
  [DIR ] db/
  [FILE] db/main.sqlite (45123 bytes)
  [FILE] doc/Laboratory.md (8201 bytes)

File previews:
File path: `db/main.sqlite` (sqlite, 3 tables; pass exactly `db/main.sqlite` as the tool `path` argument)
  - table `patients`: CREATE TABLE patients (id INTEGER PRIMARY KEY, name TEXT, ...)
  - table `labs`: CREATE TABLE labs (...)
  ...

File path: `doc/Laboratory.md` (text; pass exactly `doc/Laboratory.md` as the tool `path` argument)
Head:
```
# Laboratory Reference
...
```
```

文件大小阈值（`SHORT_DOC_FULL_RETURN_THRESHOLD = 32_000`）：≤32KB 文档全量返回，否则只取头 400 字符。

**输出契约**（planner system prompt 强制）：
```json
{
  "nodes": [
    {"id": "n1", "goal": "...", "depends_on": [], "suggested_tools": [...], "expected_output": "..."},
    {"id": "n2", "goal": "...", "depends_on": ["n1"], ...},
    ...
  ],
  "final_node_id": "n3"
}
```

`final_node_id` 必须是最后一个节点 —— 它的"完成"等价于 executor 已经收齐所有信息可以调用 `answer`。**不允许**有专门的 "answer 节点"，避免歧义。

### 5.4 节点 2：`dag_scheduler` — 聚焦提示与就绪选择

scheduler 每次被路由到时做三件事：

1. **drain 完成信号**：把 `pending_node_done_signals` 取出来，记录到 `dag_state.events`；
2. **选 ready 节点**：从 `node_status` 中找一个 `pending` 且所有 `depends_on` 都 `done` 的节点；如果找不到，看是不是全 `done` → 走 reflector，否则触发 replan；
3. **注入 focused prompt**：往 `messages` 追加一条 `HumanMessage`，只包含当前节点 goal、expected_output、和**所依赖节点的 output_summary 原文**：

```text
You are now focused on node `n2`.
Goal: Compute average platelet count grouped by hospital.
Expected output: a 2-column table (hospital_name, avg_platelets).

Upstream summaries you may rely on:
- n1 said: "Found 3 hospitals: Mercy / SunTzu / RDH; patients table joined on patient_id."

When this node is done, call `mark_node_done(node_id="n2", output_summary="...")`.
```

这是把"长上下文 ReAct"压缩成"短上下文焦点"的关键：上游节点的工具调用日志、消息历史**都不会**进入下游节点的 LLM 输入，只透传 `output_summary` 一段 1-3 句的事实摘要，从而让一个 task 的总 token 消耗保持在可控范围。

scheduler 还会调用 `_render_dag_if_enabled`（`dag_visualizer.py`），用 `networkx + matplotlib` 把当前 DAG 拓扑 + 节点状态渲染成 `dag.svg` 落到 task 输出目录，便于事后调试。

### 5.5 节点 3：`executor` — 工具调用 + 三类自我保护

executor 是 `ChatOpenAI.bind_tools(...)` 的常规 LLM 调用，但被三层保护包裹：

#### 5.5.1 重复调用检测（identical args）

```python
already_warned = any(
    isinstance(m, SystemMessage) and "called `" in m.content and "with identical args" in m.content
    for m in messages[-5:]
)
```

如果模型连续 3 轮用**完全相同**的参数调同一个工具，注入一条强 SystemMessage：

> You have called `read_csv` with IDENTICAL arguments three turns in a row. Repeating the same call will not return different data. You MUST either (a) change at least one parameter, (b) switch to a different tool, or (c) stop exploring and call `answer` / `mark_node_done` with your best current result right now.

#### 5.5.2 `read_doc` 过用检测

阈值 4：连续 4 次 `read_doc`（哪怕参数不同 —— offset/grep 都不行）就建议改用 `list_context` / `execute_python` 或干脆 `mark_node_done`。

历史教训：task_344/352/418 都因为 executor 在同一个长 markdown 上反复 paginate 8-12 次，把 step 预算耗光。

#### 5.5.3 步数预算软警告

`steps_in_current_node` 达到 `max_steps_per_node × 0.7` 时注入：

> You are running low on per-node steps (12/16 used). Stop exploring; commit your best current result now — call `answer` (final node) or `mark_node_done` (other nodes) with what you have, even if it is partial.

#### 5.5.4 空响应不计步（关键 bug fix）

Qwen 经 OpenAI-compatible 端点偶尔返回 `AIMessage(content="", tool_calls=[])`。如果按常规给 `steps_in_current_node += 1`，几次空响应就把 step 预算耗光。改造后：

```python
if _is_useful_executor_turn(response):
    step_delta = 1   # 调了工具或写了非空文本
else:
    step_delta = 0   # 空响应留给 nudge 节点低成本恢复
```

### 5.6 节点 4：`tools` — LangGraph 标准 ToolNode

直接复用 `langgraph.prebuilt.ToolNode`。错误格式由 `_format_tool_error` 控制，把异常类型 + 异常消息原样转给模型：

```python
return f"{type(exc).__name__}: {exc}"
```

这样 `FileNotFoundError: Missing context asset: data.db. Available top-level entries under context/: ['db/', 'doc/']. Tip: call list_context first ...` 之类的丰富错误消息能直接驱动模型自我修正。

### 5.7 节点 5：`reflector` — 答案校验

executor 调 `answer` 后路由到 reflector。reflector 用一段独立的 system prompt（`REFLECTOR_SYSTEM_PROMPT`）让 LLM 检查：

1. **结构**：列名/列数/行数与问题语义匹配吗？
2. **冗余列**：多余列会被打分公式扣 `λ × extra/predicted`，所以问"how many"返回多列会被建议 RETRY；
3. **聚合检查**：问"how many"却返回 >1 行，肯定是忘了 `COUNT(*)`；
4. **格式**：日期是否 ISO、null 是否变空串、字符串大小写是否被改、数字是否被错误舍入；

reflector 仅输出一行：`OK` 或 `RETRY: <修复建议>`。

`RETRY` 时清空 `tool_run_context.final_answer`，把 final 节点状态重置为 `pending`，scheduler 下一拍重新 focus 终节点，executor 拿到 `RETRY: drop the extras column` 再调一次 `answer`。最多重试 `max_reflections`（默认 2）次。

### 5.8 节点 6：`replanner` — 计划级兜底

触发条件：scheduler 发现"无 ready 节点 + 还有未完成节点"，或某节点 attempts ≥ `max_node_attempts`。

`replanner` 收到的 prompt 比 planner 多一段：原计划 JSON、各节点状态、失败原因。要求"找出根因 → 设计避开根因的新 DAG"。

`max_replans = 2`（提交配置）—— 加上首次 plan，全 task 最多 3 次 LLM-级规划。

### 5.9 节点 7-9：`nudge` / `node_failure` / `finalize`

- **`nudge`**：executor 空响应时注入一条具体的"call a tool or call mark_node_done"提示，最多 `max_idle_nudges = 2` 次；
- **`node_failure`**：节点 step 用尽时增加 attempts，未达上限就重置 `steps_in_current_node = 0` 软重试同节点，达到上限就 mark failed 并触发 replan；
- **`finalize`**：空 dict 节点，存在的意义只是接 `add_edge("finalize", END)`。

### 5.10 LLM 重试：差异化 retry profile

**`_invoke_with_retry(fn, label=...)`** 是所有 LLM 调用的统一入口。三个调用点（planner / executor / reflector）共享代码但用不同 retry profile：

```python
_RETRY_PROFILES = {
    "planner":   {"max_attempts": 2, "initial_delay": 1.0, "max_delay":  4.0},
    "executor":  {"max_attempts": 0, "initial_delay": 0.0, "max_delay":  0.0},
    "reflector": {"max_attempts": 0, "initial_delay": 0.0, "max_delay":  0.0},
}
_RATE_LIMIT_MAX_DELAY = 15.0   # 429 单独走更长上限
```

设计依据：
- **planner 致命**：失败整个 task 死 → 给 2 次重试；
- **executor 失败有外层兜底**（`max_node_attempts × max_replans`）→ 0 次重试；
- **reflector 失败无伤大雅**（prediction.csv 已经被写出去了）→ 0 次重试；
- **client-side Timeout 一律不重试**（`_is_retryable_llm_error`）：模型本身慢，重试只会再 timeout；
- **429 优先读 `Retry-After` 头**（`_extract_retry_after_seconds`）；
- **指数退避 + full jitter**（AWS 推荐，防惊群最优）。

`build_chat_openai` 里 `ChatOpenAI(max_retries=0, timeout=30)` 强制关掉 langchain-openai 内置的重试，避免和 `_invoke_with_retry` 形成"5×2=10 次重试"的双层叠加。

### 5.11 输出：`AgentRunResult` + StepRecord

run 结束后从 `tool_run_context` 取出 `final_answer`，从 `state["messages"]` 反推每个 LLM 回合 → `StepRecord(step_index, thought, action, action_input, raw_response, observation, ok)`。

```python
@dataclass(frozen=True)
class AgentRunResult:
    task_id: str
    answer: AnswerTable | None
    steps: list[StepRecord]
    failure_reason: str | None
    @property
    def succeeded(self) -> bool:
        return self.answer is not None and self.failure_reason is None
```

`runner` 把它 `to_dict()` 后落盘到 `trace.json`，`prediction.csv` 则从 `answer.columns` / `answer.rows` 写出。

---

## 6. 工具层（12 个工具）

工具层在 `src/data_agent_baseline/tools/` 下，整体被 LangChain 的 `StructuredTool` 体系包装。每个工具在 `langchain_tools.py` 中通过工厂函数 `_build_xxx_tool(task)` 绑定到当前 task 的 `context_dir`，并通过 pydantic v2 模型声明输入 schema（让 LLM 拿到结构化的 args 描述）。

### 6.1 工具一览

| # | 工具名 | 类别 | 入参 | 输出 | 主要实现位置 |
| --- | --- | --- | --- | --- | --- |
| 1 | `list_context` | 文件 | `max_depth` | `{root, entries:[{path,kind,size}]}` | `filesystem.list_context_tree` |
| 2 | `glob_files` | 文件 | `pattern, sort_by, limit` | `{root,pattern,matches:[...]}` | `filesystem.glob_files` |
| 3 | `read_csv` | 预览 | `path, max_rows` | `{path,columns,rows,row_count}` | `filesystem.read_csv_preview` |
| 4 | `read_json` | 预览 | `path, max_chars` | `{path,preview,truncated}` | `filesystem.read_json_preview` |
| 5 | `read_doc` | 预览 | `path, max_chars, offset, grep, ...` | `{path,mode,preview,...}` | `filesystem.read_doc_preview` |
| 6 | `inspect_sqlite_schema` | 探索 | `path` | `{tables:[{name, create_sql, columns}]}` | `sqlite.inspect_sqlite_schema` |
| 7 | `inspect_data` | 探索 | `path, table?, sample_size` | 列画像 (dtype/null/unique/min/max/samples) | `data_inspect.inspect_data` |
| 8 | `execute_context_sql` | 计算 | `path, sql, limit` | `{columns,rows}` | `sqlite.execute_read_only_sql` |
| 9 | `query_dataframe` | 计算 | `path, sql, table_alias, limit` | `{columns,rows,column_mapping}` | `dataframe_query.query_dataframe` |
| 10 | `execute_python` | 计算 | `code` | `{success, output, error?}` | `python_exec.execute_python_code` |
| 11 | `mark_node_done` | 控制流 | `node_id, output_summary` | `{status,remaining_nodes}` | `langchain_tools._build_mark_node_done_tool` |
| 12 | `answer` | 控制流 | `columns, rows` | `{status,column_count,row_count}` | `langchain_tools._build_answer_tool` |

### 6.2 路径安全：`resolve_context_path`

所有需要落到磁盘上的工具入口都调用 `filesystem.resolve_context_path(task, relative_path)`：

```python
def resolve_context_path(task, relative_path):
    candidate = (task.context_dir / relative_path).resolve()
    context_root = task.context_dir.resolve()
    if context_root not in candidate.parents and candidate != context_root:
        raise ValueError(f"Path escapes context dir: {relative_path}")
    if not candidate.exists():
        # 关键：把目录里实际有什么列出来，让模型自我修正
        available = _shallow_listing(context_root)
        raise FileNotFoundError(
            f"Missing context asset: {relative_path}. "
            f"Available top-level entries under context/: {available}. "
            f"Tip: call `list_context` first ..."
        )
    return candidate
```

两层防御：
1. **路径逃逸**：`..` 或符号链接试图跳出 `context/` 时直接 `ValueError`；
2. **缺失文件友好提示**：错误消息携带真实目录清单，模型下一拍就能修正路径，省一次重规划。

### 6.3 文件类工具：`list_context` / `glob_files` / `read_csv` / `read_json` / `read_doc`

#### `list_context`

用途：递归列 `context/` 下的所有文件和子目录（默认深度 4），每个 entry 含 `{path, kind, size}`。这是 executor 进入新节点时的"必做第一步"（system prompt 强制）。

#### `glob_files`

用途：按 glob 模式筛文件（如 `**/*.json` / `db/*.sqlite`），可按 `name|size|mtime` 排序、`limit` 截断。诞生背景：从历史 trace 看，~7 次 `execute_python` 调用就是封装 `os.listdir / glob.glob`，专门加这个工具替代。

支持安全约束：拒绝绝对路径（`pattern.startswith("/")`），符号链接逃逸的 match 静默丢弃。

#### `read_csv`

简单 CSV 预览，header + 前 `max_rows`（默认 50）行，外加全量 row_count。

#### `read_json`

把 JSON 文件 pretty-print 后取头 `max_chars`（默认 4000）。`truncated` 标记是否被截断。

#### `read_doc` — 三模式自适应

`read_doc` 是设计上最精细的工具，对应 `mode` 字段三种行为：

```text
read_doc(path="doc/x.md")                          → mode="full" 直接全文（≤32KB）
read_doc(path="doc/x.md", offset=8000)             → mode="slice" 经典分页
read_doc(path="doc/x.md", grep="Captain Marvel")   → mode="grep"  正则跳到匹配±400 字符
```

| 模式 | 触发条件 | 输出 | 备注 |
| --- | --- | --- | --- |
| `full` | 文档 ≤ `SHORT_DOC_FULL_RETURN_THRESHOLD = 32000` 字符 OR 一次切片就到底 | 全文 | 大多数 medium 文档命中 |
| `slice` | 长文档 + `offset > 0` | `text[offset:offset+max_chars]` + `next_offset` | LLM 罕见地需要 paginate 时用 |
| `grep` | 传 `grep=<regex>` | 至多 `max_matches` 个 ±`context_chars` 窗口，用 `\n---\n` 分隔 | 关键性能优化 |

历史教训：task_396 用 8 次 `execute_python` 反复 grep `superhero.md`，加了 grep 模式后单次工具调用搞定。grep 模式同时受 `max_matches=20` 和 `max_chars` 双重上限保护，防止模型用 `grep="."` 之类的贪心 pattern 把整个文档拉回来。

### 6.4 探索类工具：`inspect_sqlite_schema` / `inspect_data`

#### `inspect_sqlite_schema`

返回 sqlite 文件中所有表的 `name`、`create_sql`（CREATE TABLE 原文，便于看类型/约束）、列清单。Planner 的 dataset profile 也在内部调它给 sqlite 做摘要。

#### `inspect_data`

一站式列画像，对 CSV/JSON/JSONL/Parquet/SQLite 表统一接口：每列返回 `dtype, null_count, unique_count, sample_values, min/max(数值列)`。

设计动机：替代 LLM 常见的 `read_csv → execute_python(df.head(); df.dtypes; df.shape)` 三连击，省 2-3 个 step。

### 6.5 计算类工具：`execute_context_sql` / `query_dataframe` / `execute_python`

#### `execute_context_sql`

只读 SQL（`SELECT/WITH/PRAGMA`）执行在 sqlite/db 文件上。`limit` 默认 200 防止意外拉回大表。

#### `query_dataframe`

把 CSV/TSV/JSON/JSONL/Parquet 文件用 duckdb/polars 等加载到内存 sqlite 表（默认别名 `df`），用 SQL 查询。返回结果时还附带 `column_mapping`：因为列名带空格、连字符会被自动 sanitize 为下划线，模型如果用原列名查不到，能从 `column_mapping` 看到映射关系。

设计动机：把 "读 CSV → pandas group_by → to_dict" 这种典型工作流压缩成一次工具调用，并且强类型（SQL 报错信息比 Python KeyError 更明确）。

#### `execute_python`

最后兜底：在 task `context/` 当前工作目录下执行任意 Python 代码，捕获 stdout 作为 `output`。

关键约束：
- **30 秒硬超时**（`EXECUTE_PYTHON_TIMEOUT_SECONDS = 30`），通过 `subprocess.run(timeout=...)` 实现；
- 工作目录强制锁在 `task.context_dir`，禁止 chdir 到外部；
- 沙箱不强制（不是安全工具，用于分析受控数据集）；
- 30 秒不够时模型应该改用 SQL 工具或 chunked 处理，而不是放大 timeout。

### 6.6 控制流工具：`mark_node_done` / `answer`

这两个工具不读不写文件，纯粹改 `ToolRunContext` 状态，是 DAG 流转的关键。

#### `mark_node_done(node_id, output_summary)`

强校验：
1. DAG 必须存在（planner 已跑过）；
2. `node_id` 必须在 DAG 中；
3. `node_id` 必须等于 `dag_state.current_node_id`（不能跨节点 mark）；
4. `output_summary` 必须非空字符串。

任一不满足就 `raise ValueError`，LangGraph 的 `ToolNode` 会把它转成 `ToolMessage(status="error")`，executor 下一拍就能看到具体报错并修正。

成功时副作用：
- `dag_state.node_status[node_id] = "done"`；
- `dag_state.node_outputs[node_id] = summary_text`（下游节点 focused prompt 会原文引用）；
- `pending_node_done_signals.append(...)`（scheduler 下一拍 drain）；
- `dag_state.current_node_id = None`（强制 scheduler 重新选下一个 ready 节点）；
- 记录 `dag_state.events.append("node_done", node_id=..., summary=...)`。

#### `answer(columns, rows)`

格式校验：
- `columns`：非空 list of str；
- `rows`：list of list，每行长度 == `len(columns)`；
- 失败一律 `raise ValueError`。

成功后：
- 构造 `AnswerTable`；
- 写 `tool_run_context.final_answer`；
- 追加到 `submitted_answers`（reflector 重试时能回退到上次提交的答案）；
- 路由层（`route_after_tools`）看到 `ANSWER_TOOL_NAME ∈ tool_names` 后转给 reflector。

### 6.7 Legacy ReAct 工具注册（`tools/registry.py`）

旧的 `ToolRegistry` 用 `dataclass` 形式保存 `name → spec / handler`，配合 `agents/react.py` 走经典 ReAct 单循环（每轮 LLM 输出 JSON action → 工具执行 → 把 observation 喂回去）。

它当前**仍被保留但未投产**，主要原因：
- 提供 `describe_for_prompt()`，给老的 ReAct system prompt 用；
- 单元测试覆盖 `_answer` 校验逻辑等；
- 万一 LangGraph 出现致命问题，`runner.run_single_task` 仍能通过显式传 `model + tools` 切回单线程 ReAct 模式（见 `runner._run_single_task_core` 的兼容分支）。

实际投产路径完全走 `langchain_tools.build_langchain_tools`。

---

## 7. 运行调度层：Runner / 多轮投票 / Retry / 评分

`src/data_agent_baseline/run/` 下的 4 个文件（`runner.py` / `vote.py` / `table_signature.py` / `scoring.py`）共同构成"评测就绪"层：把 agent 的随机性压成可投票的多份候选、用规范化签名做多数投票、对仍失败的任务做最后一次救援、并按 KDD Cup 评分公式给出本地 self-eval。

### 7.1 单 task 执行：`run_single_task`

入口签名（`runner.py`）：

```python
def run_single_task(
    *, task_id, config, run_output_dir,
    model=None, tools=None,
    prediction_filename: str = "prediction.csv",
    trace_suffix: str = "",
) -> TaskRunArtifacts: ...
```

行为分两条路径：

**路径 A：默认（model/tools 都为 None）**

进入 `_run_single_task_with_timeout`：

```python
queue = multiprocessing.Queue()
process = multiprocessing.Process(target=_run_single_task_in_subprocess, ...)
process.start()
process.join(timeout_seconds)        # 来自 config.run.task_timeout_seconds
if process.is_alive():
    process.terminate(); process.join(1.0)
    if process.is_alive():
        process.kill(); process.join()
    return _failure_run_result_payload(task_id, "Task timed out after Ns.")
```

为什么用 `multiprocessing.Process` 而不是 `threading`：
- Python 的 LangGraph + ChatOpenAI 调用栈在某些异常路径下会陷入纯 C 扩展（如 SSL handshake），`KeyboardInterrupt` 都未必能打断；
- `Process.terminate()` 直接 SIGTERM，30s 后还活着就 `kill()` 发 SIGKILL，强制收尸；
- 子进程崩溃（OOM、segfault 等）能被父进程捕获到 `exitcode != 0`，转成 failure_reason 而不是让整个 benchmark 挂掉。

**路径 B：显式传 `model + tools`**

进入 `_run_single_task_core` 直接在当前进程跑（适合 legacy ReAct / 单线程调试 / 单测）。Runner 检测到 `model is not None or tools is not None` 时强制把 `effective_workers = 1`，避免共享同一个 ChatOpenAI 实例的线程不安全问题。

#### 产物：`TaskRunArtifacts`

```python
@dataclass(frozen=True)
class TaskRunArtifacts:
    task_id: str
    task_output_dir: Path                      # artifacts/runs/<run_id>/task_<id>/
    prediction_csv_path: Path | None           # 仅在 agent 真给出 answer 时存在
    trace_path: Path                           # trace.json 或 trace_r2.json 等
    succeeded: bool
    failure_reason: str | None
```

落盘 2-3 个文件：
- `trace<suffix>.json`：完整的 `AgentRunResult.to_dict()`（含每一步 thought/action/observation）；
- `prediction<custom>.csv`：`AnswerTable` 的 columns + rows；
- `dag.svg`：每次 DAG 状态变化时由 `dag_visualizer` 增量重绘。

### 7.2 文件命名协议：`_round_artifact_filename`

多轮投票要求"轮次输出不互相覆盖"，但又要保证 entrypoint 同步进程随时能拿到一份保底答案：

```python
def _round_artifact_filename(round_idx, base_already_exists):
    if round_idx <= 1:
        return "prediction.csv"            # 轮 1 永远写 prediction.csv（保底）
    if base_already_exists:
        return f"r{round_idx}.csv"          # 轮 N≥2 且 prediction.csv 已存在 → 写 rN.csv（候选）
    return "prediction.csv"                # 轮 N≥2 且轮 1-N-1 都没产出 → back-fill prediction.csv
```

**关键不变量**：`prediction.csv` 是"当前最佳"的语义。entrypoint.sh 后台 5s 一次扫 `artifacts/runs/*/task_*/prediction.csv` 拍平到 `/output/`，所以只要这个文件存在评测就有分。轮 2/3 写 `rN.csv` 时 `prediction.csv` 不变；末尾 `vote_all_tasks` 才会用胜者**原子覆盖**它。

trace 文件用同一套规则：`trace.json` / `trace_r2.json` / `trace_r3.json`，便于事后 diff "三轮答案为何不同"。

### 7.3 单轮调度：`_execute_one_round`

签名核心是 `effective_workers` 和 round-aware 的文件名解析：

```python
def _resolve_filename(task_id):
    base_path = run_output_dir / task_id / "prediction.csv"
    return _round_artifact_filename(round_idx, base_already_exists=base_path.exists())
```

**关键并发安全约束**：必须在**主线程的 submit 循环中**预先解析每个 task 的目标文件名，而不是在 worker 内部解析。否则 N 个轮 2 的 worker 同时启动时，每个 worker 都看到 `prediction.csv` 不存在（因为它们都还没写完），全都 back-fill，互相覆盖。在 submit 时确定就避免了这个 race。

并发模型：
- `effective_workers == 1`：纯顺序执行，复用 shared model + tools；
- `effective_workers > 1`：`ThreadPoolExecutor(max_workers=...)`，每个 task 独立子进程跑 agent，主线程通过 `as_completed` 串行处理 callback。

为什么 vote 也只能在主线程做：`_maybe_incremental_vote`（轮 ≥4 时触发）会原子覆盖 `prediction.csv`，必须串行；`as_completed` 的 single consumer 天然保证了同一 task_dir 不会被两次并发投票。

### 7.4 多轮投票：`vote_task_with_candidates`

`run/vote.py` 的核心算法：

```python
candidate_filenames = ("prediction.csv", "r2.csv", "r3.csv", ...)   # 优先级顺序，越前越优先
signatures = [_signature_for(p) for p in paths]                     # 不可解析返回 None
present = [i for i, s in enumerate(signatures) if s is not None]

if len(present) == 0:
    rule = "no_candidates"
elif len(present) <= 2:
    winner = present[0]                                              # earliest 胜
    rule = "single_candidate" 或 "two_candidates"
else:
    # 3+ 候选：按签名 Counter
    if max(counts.values()) == 1:
        winner = present[0]                                          # 全异 → earliest 胜
        rule = "all_different"
    else:
        majority_sig = (那个出现次数最多的签名)
        winner = (signatures 中第一个等于 majority_sig 的下标)
        rule = "majority"

if winner != 0:                                                      # 胜者不是 prediction.csv
    _atomic_overwrite(paths[winner], paths[0])                       # 写 .tmp + os.replace
```

**为什么 ≤2 候选不投票**：三个里挑两个相同的最有意义；只有 2 个时谁对谁错没法判断，按 earliest 是简单稳妥的策略（轮 1 先跑，通常最稳定）。

**为什么用 atomic replace**：entrypoint 同步进程可能正好在读 `prediction.csv` 时我们要覆盖它。`shutil.copyfile + os.replace`保证读端要么看到旧内容、要么看到新内容，绝不会读到半截。

#### 7.4.1 表签名规范化：`compute_table_signature`

`run/table_signature.py` 是投票的"等价性判断器"：

```python
def compute_table_signature(columns, rows):
    per_column = []
    for col_index in range(len(columns)):
        cells = [normalize_cell(row[col_index]) for row in rows]
        per_column.append(tuple(sorted(cells)))     # 行无序
    return tuple(sorted(per_column))                # 列无序
```

得到的签名同时**忽略列顺序、行顺序、列名**。两份答案签名相等 ⟺ 它们用列签名匹配的方式打分时会得到相同结果。

`normalize_cell(value)` 的规范化规则（按优先级）：

1. `None` / `"null"` / `"none"` / `"nan"` / `"nat"` / `"<na>"`（大小写不敏感）→ `""`；
2. `bool` → `"True"` / `"False"`（**故意不**当作数字 1.0 / 0.0）；
3. 数字（int / float / Decimal / 数字字符串）→ `Decimal.quantize(0.01, ROUND_HALF_UP)`，所以 `"4200000"` 与 `"4200000.00"` 等价；
4. 含 `T` 或空格的字符串尝试 `datetime.fromisoformat`（带时区 → 转 UTC + `Z` 后缀；naive → 保持 ISO）；
5. 形如 `YYYY-M-D` / `YYYY/M/D` 的尝试零填充为 `YYYY-MM-DD`；
6. 长形式英文日期 `March 1, 2024` / `Mar 1 2024` / `1 March 2024` 尝试 `strptime` 转 `YYYY-MM-DD`；
7. 上面都失败 → strip + 去 `\r\n` 后保持原文。

**安全设计**：US `MM/DD/YYYY` vs EU `DD/MM/YYYY` 的歧义日期一律不动，避免静默换月日。

#### 7.4.2 落盘前的最终规范化：`normalize_prediction_csv`

投票胜者覆盖 `prediction.csv` 后，`runner` 还会调一次 `normalize_prediction_csv(path)` 把每个 cell 走一遍 `normalize_cell` 写回。这是"评测系统看到的字节"层最后的格式统一，让模型写的 `5519.475171445073` / `+14.925` / `2024-3-1` / `null` 都被规整成评分器期望的形式。

#### 7.4.3 Audit-only 字段：`candidate_status`

`VoteResult.candidate_status: tuple[FileStatus, ...]` 把每个候选文件分类：

```text
"ok"         — 签名解析成功
"missing"    — 文件不存在（多半是该轮被 RateLimit 直接 kill）
"empty"      — 文件存在但 0 字节（写入器到了但内容为空）
"unparseable"— 非空但 CSV 损坏（缺 header、行长不齐等）
```

**注意**：这个字段**不参与投票**，纯粹 observability，写到 `vote_summary.json` 帮助事后定位"为什么轮 2 全军覆没"。

### 7.5 Retry pass：失败 task 最后一搏

所有投票轮跑完后（注意是**多轮投票之后**），`_execute_retry_pass` 扫一遍最后一轮的 artifacts，把 `succeeded == False` 的 task 拎出来再跑一次：

```python
prediction_filename = "prediction_retry.csv"
trace_suffix       = "_retry"
```

写到独立文件名是为了"失败的 retry 不会污染原本的失败状态"。两种结局：

| Retry 结果 | 处理 |
| --- | --- |
| **成功** | `_promote_retry_artifacts`：把 `prediction_retry.csv` 用 `Path.replace` 原子重命名为 `prediction.csv`，`trace_retry.json` 同样覆盖 `trace.json` |
| **失败** | `_discard_retry_artifacts`：删除 `prediction_retry.csv` 和 `trace_retry.json`，原本的失败状态保持不变 |

并发同样支持：`ThreadPoolExecutor(max_workers=effective_workers)`。

最终 `summary.json` 里有一段：

```json
"retry_pass": {
  "retried_task_count": 4,
  "promoted_task_count": 2,
  "still_failed_task_count": 2,
  "retried_task_ids": ["task_42", "task_88", ...]
}
```

### 7.6 整轮 benchmark 入口：`run_benchmark`

```python
def run_benchmark(*, config, model=None, tools=None, limit=None, progress_callback=None):
    effective_run_id, run_output_dir = create_run_output_dir(...)   # YYYYMMDDTHHMMSSZ 格式 / 用户指定 ID
    tasks = DABenchPublicDataset(config.dataset.root_path).iter_tasks()[:limit]

    for round_idx in 1..vote_rounds:
        round_artifacts = _execute_one_round(...)
        rounds_summary.append({"round": round_idx, "task_count": ..., "succeeded_task_count": ...})

    last_round_artifacts, retry_pass_summary = _execute_retry_pass(last_round_artifacts, ...)

    if vote_rounds >= 2:
        vote_results = vote_all_tasks(run_output_dir)               # 全表 sweep + vote_summary.json

    _write_json(run_output_dir / "summary.json", {
        "run_id": ..., "task_count": ..., "succeeded_task_count": ...,
        "rounds": rounds_summary, "retry_pass": retry_pass_summary,
        "vote_summary": vote_results, "tasks": [a.to_dict() for a in last_round_artifacts],
    })
```

`create_run_output_dir`：
- `run_id is None` → 用 UTC 时间戳 `YYYYMMDDTHHMMSSZ` 自动命名；
- `run_id` 已存在的目录 → `FileExistsError`（防止两次评测撞目录覆盖产物）；
- `run_id` 包含 `/` 等非法字符 → `ValueError`。

### 7.7 评分：`scoring.score_run`

`run/scoring.py` 是**本地 self-eval**，对应 KDD Cup 6.2 / 6.3 评分规则：

```python
gold_signatures = column_signatures(gold_csv)        # 每列 sorted-tuple
pred_signatures = column_signatures(prediction_csv)
gold_counter = Counter(gold_signatures)              # 列签名 multiset
pred_counter = Counter(pred_signatures)

matched = sum(min(gold_counter[s], pred_counter[s]) for s in gold_counter)
extra   = predicted_columns - matched
recall  = matched / gold_columns
score   = max(0, recall - λ * (extra / predicted_columns))
```

**注意**：`scoring.column_signatures` 用的是**它自己的** `normalise_cell`（只 strip + 处理少量 null literals），**不**与 `table_signature.normalize_cell` 共用。这是有意设计：

- `table_signature` 是**投票域**，可以做激进的规范化（数字四舍五入、日期归一）让"看似不同实则同义"的答案合并；
- `scoring` 是**评测域**，必须保守 —— 真实评测器规范化什么样，这里就只做什么。两者不混用避免本地分数虚高。

CLI 的 `dabench score` 会把结果以 rich Table 形式输出：

```
                Score Summary  (run=20260507T204312Z, λ=0.5)
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Metric         ┃                  Value ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Tasks          │                     50 │
│ Total score    │                42.7833 │
│ Average score  │   0.8557  (×100 = 85.57)│
│ Perfect (=1.0) │             40 (80.0%) │
│ Partial (0,1)  │              5 (10.0%) │
│ Zero (=0.0)    │              5 (10.0%) │
└────────────────┴────────────────────────┘
```

并把所有非满分 task 按 score 升序展开，方便快速定位回归。完整 `score_report.json` 落到 `<run_dir>/score_report.json`。

---

## 8. 提交流水线：Docker / entrypoint / 评测平台对接

### 8.1 评测平台契约

KDD Cup 2026 DataAgent-Bench 评测时：

1. 评测系统会用 `docker run` 启动我们提交的镜像，并：
   - 挂载数据集到 `/input`（每个 task 一个 `task_<id>/` 子目录）；
   - 挂载结果目录到 `/output`，最终读取 `/output/task_<id>/prediction.csv` 作为答案；
   - 注入 3 个环境变量：`MODEL_NAME` / `MODEL_API_URL` / `MODEL_API_KEY`；
   - 在外层套 `timeout --signal=TERM --kill-after=30s ${MAX_RUNTIME_SECONDS}s`（A 榜 7200s，B 榜 12h）；
2. 评测期间镜像**不能联网**（除调用 `MODEL_API_URL` 之外），否则按规则违规。

### 8.2 Dockerfile

构建分 4 步（充分利用 docker layer cache）：

```dockerfile
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

# 1. 锁死运行环境
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

# 2. 复制依赖描述（先于源码，便于 cache）
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY configs/react_baseline.submit.yaml ./configs/react_baseline.submit.yaml

# 3. pip install . 让 hatchling 安装当前包 + 它声明的所有依赖
RUN pip install --upgrade pip && pip install .

# 4. 安装完后清空 PIP_INDEX_URL，避免运行期意外联网
ENV PIP_INDEX_URL= PIP_TRUSTED_HOST=

RUN mkdir -p /input /output
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
```

设计要点：

- **依赖列表只在 `pyproject.toml` 里维护**（曾经手写到 Dockerfile 漏装 langgraph，运行时 ImportError）；
- **基础镜像可注入**（`ARG BASE_IMAGE`），国内网络可换镜像源；
- **运行期清空 PIP_INDEX_URL**（`ENV PIP_INDEX_URL=`），评测期任何隐式联网会被判违规；
- **不预创建 `run_id` 目录**：runner 每次启动会自己生成 UTC 时间戳目录，避免重复评测撞目录。

### 8.3 entrypoint.sh

`entrypoint.sh` 是镜像 `ENTRYPOINT`，做四件事：

#### 8.3.1 环境变量自检

```bash
echo "[entrypoint] MODEL_NAME=${MODEL_NAME:-<unset>}"
[ -n "${MODEL_API_URL:-}" ] && echo "<set>" || echo "<unset>"
ls -1 /input | head -20
```

只打印 "set / unset"，**不打印 key 本身**，避免泄漏到评测日志。

#### 8.3.2 后台同步守护进程（核心创新）

```bash
sync_predictions() {
  shopt -s nullglob
  for src in /output/*/task_*/prediction.csv; do
    task_id="$(basename "$(dirname "${src}")")"
    case "${task_id}" in task_*) ;; *) continue ;; esac
    dst_dir="/output/${task_id}"
    dst="${dst_dir}/prediction.csv"
    mkdir -p "${dst_dir}"
    cp "${src}" "${dst}.tmp" && mv "${dst}.tmp" "${dst}"
  done
}

(while true; do sync_predictions || true; sleep 5; done) &
SYNC_PID=$!
```

**为什么需要这个**：runner 把所有 task 写到 `/output/<run_id>/task_<id>/prediction.csv`，但评测系统按规则只读 `/output/task_<id>/prediction.csv` —— 顶层路径**没有 run_id**。两种解决方案：

| 方案 | 缺点 |
| --- | --- |
| Runner 直接写 `/output/task_<id>/` | 多轮投票时 `prediction.csv` 与 `r2.csv` 都暴露给评测，违反"只读 prediction.csv"语义；中间状态被评测看到 |
| 跑完后再统一拷贝 | 12h 上限 SIGKILL 时所有未拷贝答案丢失 |

**第三方案（采用）**：runner 仍写到 `<run_id>/` 子目录隔离多轮产物，**后台进程 5 秒一次原子拷贝**到顶层。这样：
- 第 1 轮一旦写出 `prediction.csv`，5 秒内就同步到顶层，就算后续被 SIGKILL 也已经有保底答案；
- 多轮投票胜者覆盖 `<run_id>/task_*/prediction.csv` 后，下一个 5 秒同步周期把胜者拍上去；
- `r2.csv` / `r3.csv` 永远不会出现在顶层，符合"只读 prediction.csv"。

`cp ... .tmp && mv .tmp dst` 是 POSIX 原子语义，避免评测系统读到半截文件。

#### 8.3.3 Trap 收尾

```bash
cleanup() {
  sync_predictions || true
  if kill -0 "${SYNC_PID}" 2>/dev/null; then kill "${SYNC_PID}" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
```

`SIGTERM`（评测系统在 `MAX_RUNTIME_SECONDS` 时发的）能被 trap，做最后一次 sync；
`SIGKILL`（再过 30s 仍没退出）无法 trap，但 5s 轮询已经把损失下限到 5 秒内。

#### 8.3.4 启动 dabench

```bash
dabench run-benchmark --config "${CONFIG_PATH}"
```

`CONFIG_PATH` 默认 `configs/react_baseline.submit.yaml`，可以通过 `docker run -e CONFIG_PATH=...` 临时覆盖。

---

## 9. 端到端时序与数据流

把以上各层串起来看，一次完整的评测流程：

```
                          ┌─ KDD Cup 评测系统 ─┐
                          │ docker run image \  │
                          │   -v /input -v /output \
                          │   -e MODEL_NAME=qwen3-... -e MODEL_API_URL=... -e MODEL_API_KEY=...
                          │   --timeout 7200s
                          └──────────┬──────────┘
                                     │
                                     ▼
                          /app/entrypoint.sh
                          ├─ 校验环境变量、ls /input
                          ├─ 后台 (while sleep 5; do sync_predictions; done) &
                          └─ exec dabench run-benchmark --config submit.yaml
                                     │
                                     ▼
                          dabench (cli.py:run_benchmark_command)
                          ├─ load_app_config()  → 解析 ${VAR:-default}
                          ├─ DABenchPublicDataset(/input).iter_tasks()
                          ├─ create_run_output_dir(/output, run_id=None)  → /output/20260507T204312Z/
                          └─ 进入 run_benchmark()
                                     │
            ┌────────────────────────┼─────────────────────────────────────┐
            │                        ▼                                     │
            │        ─────── 第 1 轮（vote_rounds=3 中的 1） ─────────       │
            │        ThreadPoolExecutor(max_workers=2)                     │
            │            for task_id in tasks:                             │
            │                future = executor.submit(run_single_task,    │
            │                    prediction_filename="prediction.csv",     │
            │                    trace_suffix="")                          │
            │            for future in as_completed(...):                  │
            │                artifact = future.result()                    │
            │                progress_callback(artifact)                   │
            │                                                              │
            │        每个 task 内：                                          │
            │            multiprocessing.Process(_run_single_task_in_subprocess) │
            │            ┃   queue.put(LangGraphAgent(task).run().to_dict())     │
            │            ┃                                                  │
            │            ┃   LangGraphAgent.run():                          │
            │            ┃   ┌── planner ── 产出 DAG JSON                  │
            │            ┃   │  (含 dataset_profile，禁止幻觉路径)         │
            │            ┃   ├── scheduler ── 选 ready 节点 n1              │
            │            ┃   ├── executor + tools ── 工具循环                │
            │            ┃   │   list_context / read_csv / execute_python   │
            │            ┃   ├── mark_node_done(n1, summary) ─► scheduler   │
            │            ┃   ├── ... (n2, n3...)                            │
            │            ┃   ├── final node 调 answer(columns, rows)        │
            │            ┃   ├── reflector 校验  ─ OK → END                  │
            │            ┃   │                  └ RETRY → executor 再来      │
            │            ┃   └── 异常 → replanner 兜底（最多 2 次）          │
            │            ┃                                                  │
            │            ┃   process.join(task_timeout_seconds=600)         │
            │            ┃   超时 → terminate / kill / failure_run_result   │
            │            ┃                                                  │
            │            ▼                                                  │
            │        _write_task_outputs(...)                              │
            │            落 /output/<run_id>/task_<id>/prediction.csv      │
            │            落 /output/<run_id>/task_<id>/trace.json          │
            │                                                              │
            │        ╔══════════════════════════════════════════════╗      │
            │        ║ 此时，后台 sync_predictions 5s 内会把这个    ║      │
            │        ║ prediction.csv 拍到 /output/task_<id>/      ║      │
            │        ║ 评测系统立刻能读到答案（保底）              ║      │
            │        ╚══════════════════════════════════════════════╝      │
            │                                                              │
            │        ─────── 第 2 轮 ────────                                │
            │        for task_id in tasks:                                 │
            │            base_already_exists = (..._/prediction.csv).exists() │
            │            prediction_filename = "r2.csv" if base_already_exists │
            │                                  else "prediction.csv"  # back-fill │
            │            run_single_task(...)                              │
            │                                                              │
            │        ─────── 第 3 轮 同上 ────                              │
            │                                                              │
            │        ─────── Retry pass ────                                │
            │        for task in [a for a in last_round if not a.succeeded]:│
            │            run_single_task(prediction_filename="prediction_retry.csv", │
            │                            trace_suffix="_retry")            │
            │            if succeeded:                                     │
            │                Path("prediction_retry.csv").replace("prediction.csv") │
            │                Path("trace_retry.json").replace("trace.json")│
            │            else:                                             │
            │                unlink("prediction_retry.csv")                │
            │                                                              │
            │        ─────── vote_all_tasks ────                             │
            │        for task_dir in run_output_dir.iterdir():             │
            │            candidates = (prediction.csv, r2.csv, r3.csv)     │
            │            signatures = [_signature_for(p) for p in candidates] │
            │            apply rules: majority / all_different / etc.       │
            │            if winner != prediction.csv:                      │
            │                _atomic_overwrite(winner, prediction.csv)     │
            │            normalize_prediction_csv(prediction.csv)          │
            │                                                              │
            │        ─────── 落 summary.json ────                            │
            │            run_id / task_count / succeeded_task_count        │
            │            rounds[] / retry_pass / vote_summary / tasks[]    │
            └──────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                          dabench 退出 → entrypoint.sh trap cleanup
                                     ├─ 最后一次 sync_predictions
                                     └─ kill SYNC_PID
                                     │
                                     ▼
                          docker exit
                                     │
                                     ▼
                          KDD Cup 评测系统读 /output/task_<id>/prediction.csv
                          按 Score = max(0, Recall - 0.5 × extra/predicted) 评分
```

### 9.1 关键时序数据点

基于本地 50 题完整 run 的实测（`artifacts/runs/20260501T154359Z`）：

| 指标 | 值 |
| --- | --- |
| 单 task P50 耗时 | 36s |
| 单 task P75 耗时 | 67s |
| 单 task P95 耗时 | ≈356s |
| 串行总耗时（50 题） | 5853s ≈ 1.63h |
| `max_workers=4` 并行总耗时 | ≈ 24min |
| A 榜总预算 | 7200s = 2h |
| B 榜总预算 | 12h |

设计选择：A 榜 7200s 预算极宽松，单 worker 都能跑完串行任务。所以提交配置选择 `max_workers=2` + `task_timeout_seconds=600` + `vote_rounds=3`，**把预算花在让慢任务多跑一会儿、且每个任务投 3 票**而非盲目拉并发。

---

## 10. 关键设计决策与历史教训

> 这部分把代码注释里散落的回归经验集中起来，方便后续维护者快速看到"为什么是这样"。

### 10.1 为什么从 ReAct 单循环切换到 LangGraph DAG

**ReAct 经典版本**（`agents/react.py`，已 legacy）：单一循环，LLM 输出 `{thought, action, action_input}` JSON，工具执行，observation 喂回。

**遇到的问题**：
- 长上下文（>20 步）模型迷失，反复读同一个文件；
- 无法表达"先读 A 再读 B 再 join"这种依赖关系，全靠 LLM 隐式记忆；
- 一旦中间走错，整段对话被污染，没法局部回滚。

**LangGraph DAG 解法**：
- planner 用结构化 JSON 显式画出依赖图；
- 每个节点的对话**只看自己的 goal + 上游 summary**，不看上游的工具调用日志；
- 节点失败可以单独 retry，不污染其他节点。

### 10.2 为什么用子进程而不是线程跑单个 task

`Process.terminate()` + `kill()` 在 LangChain/openai 卡死在 SSL handshake 之类的纯 C 代码时仍能强制收尸。`Thread` 没有 `terminate`，`KeyboardInterrupt` 在 C 扩展里也未必生效，会让整个 benchmark 挂掉。

实测之前用线程时遇到过单个 task 卡 754s，根因就是 OpenAI SDK 内部双层 retry 叠加无法被 Python 层中断。改子进程后所有这种"地狱级"卡死都能被 600s 硬 timeout 干净杀掉。

### 10.3 为什么 LLM 重试要按调用点差异化

历史 bug：之前 `langchain-openai` 内置的 `max_retries=2` + 自己写的 `_invoke_with_retry(max_attempts=5)` 双层叠加，单次卡顿被放大到 `(1+2)*(1+5)*30s ≈ 540s`。

现在：
- `ChatOpenAI(max_retries=0, timeout=30)` 强制关掉内置重试；
- planner 致命，给 2 次重试；executor / reflector 失败有外层兜底，0 次重试；
- 客户端 Timeout 一律不重试（模型本身慢，重试只会再 timeout）；
- 429 单独走 `Retry-After` 头 + 15s 退避上限。

详细参数见 `langgraph_agent.py` 的 `_RETRY_PROFILES` 注释。

### 10.4 为什么 `prediction.csv` 是"保底/补位"而不是"轮 1 结果"

最初的设计是"`prediction.csv` 永远 = 轮 1 结果"，轮 2/3 都是补充候选。问题：如果轮 1 因为 RateLimit 直接全军覆没，最终 vote 时会因为 `prediction.csv` 不存在而无法以"earliest"原则裁决。

改成现在的语义后：
- 轮 1 写 `prediction.csv`（最常见路径）；
- 轮 1 该 task 啥也没写出来 → 轮 2 补位写 `prediction.csv`（不是 `r2.csv`）；
- 轮 2 也没写 → 轮 3 补位；
- 三轮都没写 → retry pass 再来一次写 `prediction.csv`。

任何阶段，**只要存在 `prediction.csv` 就有保底分**，后续轮次只能在保底之上做加法（投票胜者或 retry 提升）而不会让结果变更糟。

### 10.5 为什么投票要做"全异 → earliest"

投票面板上有 3 个候选 a/b/c，签名两两不同时，理论上没有信号判断谁对。三种 tiebreak 选项：

| 策略 | 优点 | 缺点 |
| --- | --- | --- |
| 取轮 1 (`earliest`) | 轮 1 最稳定（无并发干扰） | 轮 1 错时一直错 |
| 取最长答案 | 暗示"信息更全" | 容易被冗余列拖低分（评分有惩罚） |
| 取最短答案 | 评分公式偏好少列 | 容易丢列导致 recall=0 |

实际选择 **earliest**：不引入新的偏置，简单可解释，且和"`prediction.csv` 是保底"的语义一致。

### 10.6 为什么列签名既忽略列名又忽略列顺序

KDD Cup 评分规则 6.2 明确说"列签名匹配，忽略列名"。所以模型把列名写成 `avg` / `平均值` / `mean` 都不影响分数 —— 只要那一列的值和 gold 某一列的值集合一致。

`compute_table_signature` 同时忽略行序也是有意：很多 SQL 查询在没有 `ORDER BY` 时返回顺序未定义，强制要求行序匹配会让正确答案被误判。

### 10.7 为什么数字规范化用 ROUND_HALF_UP 到 2 位

注意这只发生在**投票域**（`table_signature.normalize_cell`），不发生在评分域（`scoring.normalise_cell`）。

设计权衡：
- 不规范化：`5519.475171445073` 与 `5519.48` 投票时被当作不同答案 → 永远投不出多数；
- 太激进规范化：评测器若按字节比较，本地把 `5519.475` 规范成 `5519.48` 反而和 gold 错位。

折衷：投票时按 2 位四舍五入合并近似答案（提高聚合能力），但 prompt 反复强调"不要主动 round 到 2 位提交答案，提交原始精度"（让 executor 把 `str(raw_value)` 直接交，评分时按字节比 gold）。

### 10.8 为什么文档 ≤32KB 全文返回

历史 trace 分析（`20260506T010810Z`）：5/8 step-budget failure 都是 executor 用 `read_doc` paginate 一个 20-30KB markdown 文档 5-9 次。每次 paginate 都要 LLM 决策一次，浪费严重。

`SHORT_DOC_FULL_RETURN_THRESHOLD = 32_000` 对绝大多数 dabench 文档（5-30KB）一次性返回，把这一类的 step 浪费降到 1 次。32KB 上限避免真正巨大的患者病历（几百 KB）一次性炸 LLM 上下文。

### 10.9 文件命名表（debug 速查）

| 文件 | 来源 | 用途 |
| --- | --- | --- |
| `prediction.csv` | 各轮"保底/胜者" | 评测系统读取 |
| `r2.csv` / `r3.csv` | 第 2/3 轮 trace 候选 | 投票输入 |
| `prediction_retry.csv` | retry pass 写出（成功后会被重命名走） | 临时文件 |
| `trace.json` / `trace_r2.json` / `trace_r3.json` / `trace_retry.json` | 各轮的完整对话 + step 记录 | 事后调试 |
| `dag.svg` | dag_visualizer 增量重绘 | 看 DAG 拓扑和节点状态 |
| `summary.json` | run_benchmark 末尾统一落 | 全 run 元信息（rounds / retry_pass / vote_summary） |
| `vote_summary.json` | vote_all_tasks 落 | 每 task 的 candidate 状态、签名、应用规则 |
| `score_report.json` | `dabench score` 落 | 本地 self-eval 详情 |

---

## 附录 A：相关文档

仓库已有的研究/设计文档（`docs/`）：

| 文档 | 内容 |
| --- | --- |
| `00-executive-summary.md` | 项目执行摘要 |
| `01-competition-analysis.md` | KDD Cup 比赛与对手分析 |
| `02-academic-research.md` | 数据 agent 学术综述 |
| `03-open-source-agents.md` | 开源 agent 调研 |
| `04-sota-techniques.md` | SOTA 技术清单 |
| `05-our-agent-design.md` | 我方 agent 设计文档 |
| `06-references.md` | 参考文献 |
| `07-langgraph-architecture.md` | LangGraph 架构对比 |
| `agent-workflow.svg` | 流程图（`scripts/visualize_agent_workflow.py` 生成） |

本文档（`architecture.md`）专注**当前线上代码的实现细节**，与设计 RFC 类文档互补。

---

> 文档维护：当 `langgraph_agent.py` / `runner.py` / `vote.py` 行为发生变化时，请同步更新对应章节，保持文档与代码 100% 一致。
