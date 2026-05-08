# 05 · 我们的 Agent 设计方案 · PER-Loop 架构

> 这是从 Baseline 冲到 SOTA 的工程蓝图
> 设计代号：**PER-Loop** = Planner + Executor + Reflector/Verifier，外层包 BoN/MCTS

---

## 1. 设计原则（5 条军规）

1. **可观测先于可优化** — 没有 trace 分析就没有靠谱迭代
2. **小步验证胜过大改** — 每个组件单独 ablation，留到最后再 stack
3. **稳过快** — Verifier 即使慢，也比偶尔拿满分但常崩盘强
4. **复用 > 重写** — 优先 OpenManus / Data Interpreter 的现成模块
5. **顺着主办方的思路走** — 主办方喜欢 Plan + Code + Verify + MCTS 风格

## 2. 总体架构

```
                    ┌────────────────────────────────────────┐
                    │              Outer Loop                │
                    │  Best-of-N (Phase 1) → MCTS (Phase 2)  │
                    └────────────────────────────────────────┘
                                       │
                                       ▼
        ┌──────────────────────────────────────────────────────────┐
        │                    PER-Loop (单轮)                       │
        │                                                          │
        │   ┌───────────────┐                                      │
        │   │  Profiler     │  自动扫描 context/                   │
        │   │  (no-LLM)     │  生成 schema + samples + 文件清单    │
        │   └──────┬────────┘                                      │
        │          ▼                                               │
        │   ┌───────────────┐  生成 DAG plan (JSON):               │
        │   │   Planner     │  - nodes: subtask 列表               │
        │   │  (Claude 4.5) │  - edges: 依赖关系                   │
        │   │               │  - tool_hints: 推荐工具              │
        │   └──────┬────────┘                                      │
        │          ▼                                               │
        │   ┌─────────────────────────────────────────────┐        │
        │   │      Executor (per node, ReAct mini-loop)   │        │
        │   │      - max 4 steps per node                 │        │
        │   │      - CodeAct 优先 (execute_python)        │        │
        │   │      - 用 DeepSeek-V3.2 / Qwen3-Coder       │        │
        │   └──────┬──────────────────────────────────────┘        │
        │          ▼                                               │
        │   ┌─────────────────────────────────────────────┐        │
        │   │       Step-Level Verifier                   │        │
        │   │       OK    → 继续下一节点                  │        │
        │   │       RETRY → Executor 同节点重试           │        │
        │   │       REPLAN → 回 Planner 重规划该节点      │        │
        │   └──────┬──────────────────────────────────────┘        │
        │          ▼                                               │
        │   ┌─────────────────────────────────────────────┐        │
        │   │       Aggregator + Final Verifier           │        │
        │   │       - 合并所有 node 结果                  │        │
        │   │       - 类型/约束/一致性 sanity check       │        │
        │   │       - 通过后调 answer() 提交              │        │
        │   └─────────────────────────────────────────────┘        │
        │                                                          │
        └──────────────────────────────────────────────────────────┘
```

## 3. 模块设计

### 3.1 Profiler（无 LLM，纯代码）

**输入**：`context/` 目录路径
**输出**：JSON profile

```python
@dataclass
class ContextProfile:
    files: list[FileInfo]
    total_size_mb: float
    suggested_tools: list[str]   # 根据文件类型反推

@dataclass
class FileInfo:
    path: str
    type: Literal["csv", "json", "sqlite", "doc"]
    size_kb: float
    # CSV
    columns: list[str] | None
    dtypes: dict[str, str] | None
    n_rows: int | None
    head_5: list[dict] | None
    # SQLite
    tables: dict[str, TableSchema] | None  # table → schema + 5 sample rows
    # JSON
    json_preview: str | None  # 前 1500 chars
    # Doc
    doc_preview: str | None   # 前 3000 chars
    headings: list[str] | None  # markdown headings
```

**实现要点**：
- CSV：用 `pandas.read_csv(nrows=5)` + `wc -l` 估行数
- SQLite：`sqlite3` 直接 dump schema + `SELECT * LIMIT 5`
- JSON：分大小，小的全读，大的取 head
- Markdown：抽 heading 和前 3000 字
- **可选**：用 `tablegpt2` 7B 模型做表格语义摘要

### 3.2 Planner

**模型**：Claude Sonnet 4.5（temperature=0.0）
**输入**：question + ContextProfile
**输出**：DAG JSON

**Prompt 骨架**：
```
You are a senior data analyst planner. Decompose the user's question
into a directed acyclic graph (DAG) of subtasks.

User question:
{question}

Available data:
{context_profile_summary}

Available tools:
- list_context, read_csv, read_json, read_doc
- inspect_sqlite_schema, execute_context_sql
- execute_python (full pandas/numpy)
- answer (final submission, only when ready)

Output JSON with this schema:
{
  "rationale": "1-2 sentences on overall approach",
  "nodes": [
    {
      "id": "n1",
      "task": "specific actionable subtask",
      "depends_on": [],
      "tool_hints": ["execute_python"],
      "expected_output": "what should this node produce, in 1 sentence",
      "verify_criteria": "how to know this node succeeded"
    },
    ...
  ]
}

Guidelines:
- 3-8 nodes typically; more for Extreme tasks.
- Each node should be a specific, verifiable step.
- Prefer execute_python over chains of read_* + manual processing.
- Independent branches enable parallel execution.
- The last node should compose the final answer table.

Output JSON only, no markdown.
```

**实现要点**：
- 用 partial JSON parser（如 `json5`）容错
- DAG 检查：无环、所有 deps 存在
- 失败时降级到一个朴素 plan（exploration → analysis → answer）

### 3.3 Executor

**模型**：DeepSeek-V3.2 / Qwen3-Coder（temperature=0.3）
**输入**：单个 node + 前序 node 的输出（仅必要的）
**输出**：observation（执行结果）

**ReAct mini-loop**（max 4 steps）：

```
System: You are executing one subtask of a larger plan.

This subtask:
{node.task}
Expected output: {node.expected_output}

Context (from previous nodes):
{relevant_prior_results}

Available tools: {full tool list}

Please execute this subtask. Use ReAct format:
Thought: ...
Action: tool_name
Action Input: {...}
... (observation)
Thought: ...
Final: <one-line summary of what you produced + where it's stored>
```

**关键技巧**：
- **scratchpad**：每个 node 输出存到 `runtime["n1"] = ...`，下游节点可以 `runtime["n1"]` 引用
- **避免重复 list_context**：profile 已注入
- **CodeAct first**：在 prompt 中明确"prefer execute_python over multi-step read_*"

### 3.4 Step-Level Verifier

**模型**：Claude Sonnet 4.5（temperature=0.0）
**调用时机**：每个 node 的 ReAct mini-loop 结束后

**Prompt 骨架**：
```
You are a verifier. Decide whether the subtask was completed correctly.

Subtask: {node.task}
Expected output: {node.expected_output}
Verify criteria: {node.verify_criteria}

Execution trace:
{trajectory}

Final observation:
{final_obs}

Output JSON:
{
  "verdict": "OK" | "RETRY" | "REPLAN",
  "reason": "1-2 sentence explanation",
  "hint": "if not OK, one specific suggestion (else null)"
}

Strict rules:
- OK = the produced result genuinely satisfies the verify criteria.
- RETRY = transient issue (timeout, syntax error, parse error). Same approach should work.
- REPLAN = approach is fundamentally wrong; planner should re-plan this node.
```

**Retry 策略**：
- max RETRY per node: 2
- max REPLAN per task: 3
- 超出时跳过该 node（用 fallback 默认值），继续下游

### 3.5 Aggregator + Final Verifier

**Aggregator**：把所有 node 输出按计划组装成最终 answer table

**Final Verifier prompt**：
```
You are doing a final sanity check before submission.

Original question: {question}
Proposed answer:
- columns: {columns}
- n_rows: {n_rows}
- preview: {head_10}

Run the following sanity checks:
1. Does the column structure match what the question requires?
2. Do values look reasonable (no NaN, no obvious errors)?
3. Does the row count match constraints (e.g., "Top 5" → 5 rows)?
4. Is the answer in the right unit / format?

Output JSON:
{
  "submit": true | false,
  "issues": [...],
  "fix_suggestion": "..." (if submit=false)
}
```

如果 `submit=false`，回到 Planner 加一个 fix node 重做。

### 3.6 Outer Loop（Phase 1：BoN；Phase 2：MCTS）

**Phase 1 BoN**：
```python
def solve_with_bon(task, n=3):
    trajectories = []
    for i in range(n):
        # 不同 seed/temperature
        result = per_loop(task, seed=i, temperature=0.0 if i == 0 else 0.3)
        trajectories.append(result)
    
    # 选最优：先看 final verifier 通过的，再看 verifier 给的总分
    return select_best(trajectories)
```

**Phase 2 MCTS**：参考 AFlow / SELA，节点 = workflow 变体，UCB 选择 + 真实评测做 backprop。

## 4. 工程目录建议

```
boost-agent/
├── docs/                              ← 本报告
├── starter_kit/                       ← submodule: KDDCup starter-kit
├── src/
│   └── boost_agent/
│       ├── __init__.py
│       ├── profile/
│       │   └── profiler.py            ← Profiler
│       ├── plan/
│       │   ├── planner.py
│       │   └── prompts.py
│       ├── execute/
│       │   ├── executor.py            ← per-node ReAct
│       │   ├── react.py               ← 复用 starter-kit
│       │   └── codeact.py             ← Python-first 策略
│       ├── verify/
│       │   ├── step_verifier.py
│       │   └── final_verifier.py
│       ├── aggregate/
│       │   └── aggregator.py
│       ├── outer/
│       │   ├── bon.py                 ← Phase 1
│       │   └── mcts.py                ← Phase 2
│       ├── tools/                     ← 复用 starter-kit + 新增
│       │   ├── filesystem.py
│       │   ├── python_exec.py
│       │   ├── sqlite.py
│       │   ├── vision.py              ← Phase 2
│       │   └── registry.py
│       ├── runtime/
│       │   ├── sandbox.py             ← Docker 隔离
│       │   ├── token_budget.py
│       │   └── trace.py               ← 可观测
│       └── llm/
│           ├── client.py              ← 多模型路由 + cache
│           └── retry.py
├── configs/
│   ├── boost_baseline.yaml
│   ├── boost_per_loop.yaml
│   ├── boost_bon.yaml
│   └── boost_mcts.yaml
├── tests/
│   ├── hard_test_set/                 ← 自建 5-10 题硬测试集
│   └── test_per_loop.py
├── analysis/
│   ├── trace_stats.py                 ← 失败类型统计
│   └── ablation.py                    ← 组件 ablation
└── pyproject.toml
```

## 5. 关键实现细节

### 5.1 Prompt Cache（节省 50% 成本）

System prompt + ContextProfile 都用 Anthropic prompt cache：

```python
def build_messages(system, profile, user):
    return {
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": profile, "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [{"role": "user", "content": user}],
    }
```

### 5.2 Sandbox 隔离

```python
class TaskSandbox:
    def __init__(self, task_id):
        self.workdir = f"/tmp/sandbox/{task_id}"
        self.timeout = 60  # per python exec
        self.memory_mb = 4096
    
    def execute(self, code):
        with timeout(self.timeout):
            return subprocess.run(
                ["python", "-c", code],
                cwd=self.workdir,
                capture_output=True,
                env={"PYTHONPATH": self.workdir},
            )
```

### 5.3 Token Budget

```python
class TokenBudget:
    def __init__(self, per_task=80_000, per_step=8_000):
        self.task_budget = per_task
        self.step_budget = per_step
        self.task_used = 0
    
    def can_afford(self, estimated):
        return self.task_used + estimated < self.task_budget
    
    def early_stop_if_overrun(self):
        if self.task_used > self.task_budget * 0.9:
            return True  # 触发 emergency answer
```

### 5.4 多 LLM 路由

```python
class LLMRouter:
    def call(self, role, messages, **kwargs):
        if role == "planner":
            return self.claude_sonnet_45(messages, **kwargs)
        if role == "executor":
            return self.deepseek_v32(messages, **kwargs)
        if role == "verifier":
            return self.claude_sonnet_45(messages, **kwargs)
        if role == "vision":
            return self.claude_opus_4(messages, **kwargs)
        raise ValueError(f"Unknown role {role}")
```

## 6. 5 周迭代路线（与 [00-executive-summary] 对齐）

| 周 | 目标 | 交付物 | 期望分数（基于 baseline X₀） |
|---|---|---|---|
| **W0** (4-23~30) | 跑通 starter-kit baseline | X₀ 基线分数 + 失败类型分析 + 硬测试集 | X₀ |
| **W1** (4-30~5-7) | Profiler + Planner-Executor | X₁，预期 +10~15pp | X₀ + 12pp |
| **W2** (5-7~14) | Step Verifier + Final Verifier + Reflexion | X₂，预期 +5~10pp | X₀ + 20pp |
| **W3** (5-14~21) | BoN(N=3) + Sandbox 加固 + Prompt Cache | X₃，预期 +5~10pp | X₀ + 28pp |
| **W4** (5-21~23) | Phase 1 冲刺 + 多配置 ablation | Phase 1 提交 | 锁定 |
| **W5+** (Phase 2) | Vision tool + MCTS（或 Creative UI） | Phase 2 提交 | +多模态 + AFlow 优化 |

> 假设 baseline X₀ ≈ 30%（与 DA-Agent / DABstep 早期相当），最终预期 60%+，对标 DS-STAR 当前学术 SOTA（44.69%）。

## 7. Ablation 计划

每加一个组件都要做 ablation，确认正贡献：

| 实验 | 配置 | 预期增益 |
|---|---|---|
| E0 | starter-kit baseline | X₀ |
| E1 | + Profiler | +5pp |
| E2 | + Planner-Executor 双层 | +10pp |
| E3 | + Step Verifier | +6pp |
| E4 | + Final Verifier | +3pp |
| E5 | + Reflexion | +4pp |
| E6 | + BoN N=3 | +6pp |
| E7 | + Prompt Cache | -50% 成本，分数不变 |
| E8 | + 多模型路由 | -30% 成本，分数 +1 |
| E9 | + Vision tool（Phase 2） | +多模态题分数 |
| E10 | + AFlow workflow 优化 | +5pp |
| E11 | + MCTS（替代 BoN） | +5pp |

## 8. 立即行动 Checklist（今晚做完）

- [ ] `git clone https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit`
- [ ] `uv sync`
- [ ] 配 `configs/react_baseline.example.yaml` 的 API key（推荐先用 Claude Sonnet 4.5）
- [ ] `uv run dabench run-benchmark --config <yaml>`
- [ ] 分析 `artifacts/runs/*/summary.json` → 得到 X₀
- [ ] 把 Easy/Medium/Hard/Extreme 的失败 case 各挑 2~3 条，**人工读 trace.json**，归类失败原因
- [ ] 写出 5 道"标准硬测试题" 放 `tests/hard_test_set/`，作为后续每次改动的 regression 基准

下一份 → [`06-references.md`](./06-references.md)
