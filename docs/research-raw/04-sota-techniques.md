# 04 · SOTA 技巧手册 · 一线 Agent 冲分秘籍

> 本手册总结当前（2026-Q2）所有 SOTA Data/Code Agent 的共性技巧，按"使用时机"分类，每条都给出**出处**与**预期增益**。

---

## 1. 技巧速查表（按 ROI 排序）

| 技巧 | 增益 | 实现难度 | 出处 |
|---|---|---|---|
| **Schema/Dataset Profiling 注入** | +5~10pp | ★ | DA-Agent / DS-STAR |
| **Planner-Executor 双层** | +10~20pp | ★★ | Data Interpreter / Plan-and-Act |
| **CodeAct 统一动作空间** | +5~10pp | ★★ | OpenHands / CodeAct |
| **LLM Judge Verifier** | +5~15pp | ★★ | DS-STAR (核心) |
| **Self-Debug / Reflexion** | +3~10pp | ★ | Reflexion |
| **Best-of-N Trajectory** | +5~15pp | ★★ | AIDE / Multi-Agent Verification |
| **MCTS Tree Search** | +5~15pp | ★★★ | SELA / AFlow / Alpha-SQL |
| **Schema Linking RAG** | +3~8pp | ★★ | Spider 2.0 / DeepEye-SQL |
| **Sandbox 隔离 + Resource Cap** | 防 0 分 | ★ | OpenHands |
| **Prompt Cache (Anthropic)** | -50% 成本 | ★ | Anthropic 官方 |
| **Multi-Agent Debate** | +2~8pp | ★★★ | MAD / Multi-Agent Verification |
| **小模型 Verifier 蒸馏** | -80% Verifier 成本 | ★★★ | Reward-SQL |
| **Atom of Thoughts (Markov 风格)** | +3~10pp | ★★ | AoT NeurIPS 2025 |
| **Hierarchical Graph Plan** | +10~25pp | ★★★ | Data Interpreter |

---

## 2. Pre-Execution（执行前）

### 2.1 Schema/Dataset Profiling（必做）

**做什么**：进入 ReAct loop 之前，自动跑一遍数据集探查，把摘要塞进 system prompt。

**模板**：
```python
def profile_context(context_dir):
    summary = {"files": []}
    for path in walk(context_dir):
        if path.endswith(".csv"):
            df = pd.read_csv(path, nrows=5)
            summary["files"].append({
                "path": path, "type": "csv",
                "columns": df.columns.tolist(),
                "dtypes": df.dtypes.astype(str).to_dict(),
                "n_rows": count_rows(path),
                "head": df.to_dict("records"),
            })
        elif path.endswith(".sqlite") or path.endswith(".db"):
            schema = dump_sqlite_schema(path)
            samples = {tbl: sample_rows(path, tbl, 5) for tbl in schema}
            summary["files"].append({...})
        elif path.endswith(".json"):
            summary["files"].append({"path": path, "preview": read_first_n(path, 2000)})
        elif path.endswith((".md", ".txt")):
            summary["files"].append({"path": path, "preview": read_first_n(path, 3000)})
    return summary
```

**注入位置**：System prompt 末尾，作为"Available Data"附录。

**为什么有用**：避免 ReAct 在前 5 步浪费在 `list_context` + `read_*` 探索上，节省步数 + 直接给 Planner 完整视野。

**数据**：DA-Agent 论文报告，加 profiling 后准确率 +6pp。

### 2.2 Schema Linking（结构化数据子任务必做）

**做什么**：对 SQLite/CSV，先用 LLM 提取问题中提到的 entity，匹配到具体 table.column。

**模板**：
```python
def schema_linking(question, schema):
    return llm_call(f"""
Question: {question}
Schema: {schema}
List the tables and columns relevant to this question, in JSON.
""")
```

**为什么有用**：减少 SQL 写错列名的错误（DA-Agent 失败的主要类型之一）。

**SOTA 做法**：DeepEye-SQL（SIGMOD 2026）用了 SE 风格的 schema understanding。

## 3. Planning Phase（规划阶段）

### 3.1 Planner-Executor 双层架构（强烈推荐）

**核心思想**：把"规划"和"执行"分离。

```
[Planner LLM]
  - 输入: task + 数据 profile
  - 输出: JSON DAG (subtask 列表)
  ↓
[Executor (per subtask)]
  - 每个 subtask 一个独立的 ReAct mini-loop（max 3-5 steps）
  - 用 CodeAct 风格执行
  ↓
[Aggregator]
  - 收集所有 subtask 结果
  - 调 answer tool 提交
```

**优点**：
- **避免 long-horizon 漂移**：单 ReAct loop 长了容易跑偏
- **失败可定位**：哪个节点失败一目了然
- **可并行**：独立节点并行执行（节省时间）

**出处**：Plan-and-Act (UC Berkeley, 2025)，Data Interpreter (ACL 2025)

### 3.2 Hierarchical Graph Plan (Data Interpreter)

**比线性 plan 更强**：plan 是 DAG 而非 list，节点间有依赖关系。

**关键 prompt** (摘自 MetaGPT 源码思路)：
```
Decompose the task into a DAG of subtasks. Output JSON:
{
  "nodes": [
    {"id": 1, "task": "...", "deps": [], "tool_hints": [...]},
    {"id": 2, "task": "...", "deps": [1], "tool_hints": [...]},
    ...
  ]
}
Allow branching (one node, multiple successors) and merging (multiple deps).
```

### 3.3 Atom of Thoughts (NeurIPS 2025, AoT)

**思想**：把推理过程转化为 Markov 风格的"原子问题"序列，每一步状态自包含。

**优点**：
- 长链推理不会上下文漂移
- 可与 BoN 自然结合（每个 atom 独立 BoN）

**适用**：Extreme 难度的长链推理任务

## 4. Execution Phase（执行阶段）

### 4.1 CodeAct（统一动作空间）

**思想**：Agent 的所有动作都是 Python 代码（不是离散 tool 调用）。

```python
# 工具调用统一长这样
action = """
import pandas as pd
df = pd.read_csv("context/sales.csv")
result = df.groupby("region")["amount"].sum().reset_index()
print(result)
"""
exec(action)  # in sandbox
```

**优点**：
- 表达力最强（能写循环、条件、复合操作）
- 减少多次 round-trip
- LLM 训练数据中代码很丰富

**SOTA 项目**：OpenHands CodeAct 2.1（SWE-Bench 53%）

**注意**：starter-kit 已经有 `execute_python` tool，**等于半个 CodeAct**。可以让 LLM 在 system prompt 里被鼓励"优先用 execute_python，其他 tool 仅用于探索"。

### 4.2 ReAct（Baseline 范式）

```
Thought: 我应该 ...
Action: tool_name(args)
Observation: ...
Thought: 现在我应该 ...
...
Final Answer: ...
```

**何时用**：单个 subtask 内部的 mini-loop。

**注意**：纯 ReAct 在 long-horizon 上会漂移，**不要单独用 ReAct 跑 Hard/Extreme 题**。

### 4.3 Self-Debug

**思想**：执行失败时，把 error trace 喂回 LLM 让其修代码。

```
你的代码：
{code}
执行报错：
{error}
请修正代码后重新输出。
```

**适用**：每次 `execute_python` 报错时都试一次（max retry 2~3）。

## 5. Verification Phase（验证阶段）

### 5.1 ⭐ Step-Level LLM Judge Verifier (DS-STAR 核心)

**做什么**：每个 subtask 执行后，**另一个 LLM** 判断"是否真的解决了 subgoal"。

**关键 prompt**：
```
Subgoal: {subgoal_description}
Plan said: {expected_output_schema}
Tool called: {tool} with args {args}
Observation: {obs}

Did this step actually achieve the subgoal? Output:
- VERDICT: OK | RETRY | REPLAN
- REASON: 1-2 sentences
- HINT: (if not OK) one specific suggestion
```

**为什么有用**：代码不报错 ≠ 结果对。Verifier 强制一次"语义"层面的检查。

**DS-STAR 数据**：DABstep 上 +5pp 来自这个 Verifier。

### 5.2 Final-Answer Pre-Submission Check（必做）

**在 `answer` tool 调用前必须做**：
- 类型检查：column 数量、dtype、行数合理
- 一致性检查：与 question 中数值约束、TopN 等是否吻合
- Sanity 检查：没有 NaN、没有重复行（除非题目要求）

**模板**：
```python
def pre_answer_check(question, predicted_df):
    return llm_call(f"""
Question: {question}
My answer table:
{predicted_df.head().to_string()}
Total rows: {len(predicted_df)}
Columns: {predicted_df.columns.tolist()}

Sanity check:
- Does the column structure match what the question asks?
- Do the row count / value ranges make sense?
- Any NaN/null/error values?

Output: PASS | FAIL with reason.
If FAIL, suggest a fix.
""")
```

### 5.3 Reflexion（错误反思）

**思想**：失败的 trajectory → 文字总结 lesson → 下一轮塞进 prompt。

```python
reflection = llm_call(f"""
Previous attempt failed:
{failed_trace}
Failure reason from verifier: {verifier_reason}

Summarize a 1-sentence lesson for the next attempt.
""")
# 下一轮 system prompt 加上 "Lessons from previous attempts: {reflections}"
```

**出处**：[Reflexion (NeurIPS 2023)](https://arxiv.org/abs/2303.11366)

## 6. Test-Time Compute Scaling（测试时计算扩展）

### 6.1 Best-of-N Sampling（强烈推荐 Phase 1 末尾用）

**做法**：同一题用不同 seed / temperature 跑 N 条 trajectory，选最好的。

**选择策略**（从弱到强）：
1. **Self-consistency**：N 个答案投票（要求答案离散）
2. **Verifier scoring**：用 Verifier 给每条 trajectory 打分
3. **Reward Model scoring**：训一个 PRM（参考 Reward-SQL）

**N 的选择**：
- N=1（baseline）
- N=3（成本可控）
- N=5（一般 sweet spot）
- N=10+（diminishing return）

**出处**：[Scaling LLM Test-time Compute Optimally (DeepMind)](https://arxiv.org/abs/2408.03314)

### 6.2 MCTS Tree Search

**思想**：不是平行采样，而是**树搜索** —— 节点是中间状态，边是动作，UCB 选节点。

**适用**：
- AIDE 用于 ML 工程（greedy → tree）
- SELA 用于 AutoML
- AFlow 用于 workflow 优化
- Alpha-SQL 用于 SQL 生成

**优点**：在 BoN 之上 +5~10pp（SELA 报告）

**缺点**：实现复杂，调试难

**何时用**：Phase 2 末期，BoN 已饱和。

### 6.3 Multi-Agent Critique / Debate

**做法**：N 个 agent 各自给出答案 → 互相 critique → 收敛或投票。

**出处**：[Multi-Agent Verification (NeurIPS 2025)](https://openreview.net/forum?id=LriQ3NY9uL)

**与 BoN 的区别**：BoN 是独立采样，Debate 是有交互的迭代。

## 7. Sandbox & Engineering（工程加固）

### 7.1 Sandbox 隔离

**必做**：
- 每个 task 独立 venv 或 docker
- Python tool 加 timeout（建议单次 30~60s）
- 内存上限（建议 4GB）
- SQL 查询强制 LIMIT
- 输出 cap（防 token 爆炸 + 耗光预算）

**参考**：OpenHands 的 `runtime/` 模块、starter-kit `python_exec.py`

### 7.2 Prompt Cache（Anthropic）

**做什么**：把 system prompt + 数据 profile 标记为 cache，重复调用时只算一次。

**收益**：成本降 50~90%，**对 BoN 至关重要**

**用法**：
```python
client.messages.create(
    model="claude-sonnet-4-5",
    system=[
        {"type": "text", "text": LARGE_PROMPT, "cache_control": {"type": "ephemeral"}},
    ],
    ...
)
```

### 7.3 Token Budget Management

**做什么**：监控每题/每步 token 消耗，超 budget 时早停或降级。

**指标**：
- 每题 input tokens cap：~50k
- 每题 output tokens cap：~10k
- 全 benchmark 预算：根据钱包

### 7.4 Trace 可观测性

**必做**：
- 完整记录 `trace.json`：每步 thought / action / observation
- 离线分析脚本：成功率分布、失败类型、step 长度分布
- diff 工具：对比两个 run，看哪些题被新方法解了/搞坏了

## 8. Schema Linking & RAG（数据子任务专项）

### 8.1 SQL Schema RAG

**问题**：SQLite 表 schema 太多塞不进 prompt
**做法**：
1. 把所有 table schema 做 embedding 索引
2. 根据 question 检索 top-K 相关 table
3. 只把相关 table 喂给 LLM 写 SQL

**出处**：DeepEye-SQL（SIGMOD 2026）, Spider 2.0 baseline

### 8.2 Document Chunk Retrieval

**问题**：长文档（如 Company_Ops_Manual.md）塞不进 prompt
**做法**：
1. Markdown 按 heading 切 chunk
2. embedding + 关键词混合检索
3. 把相关 chunk 注入

**注意**：DataAgent-Bench 的文档不一定特别长，**不一定需要复杂 RAG**，先用 full-context 试

## 9. Multi-Modal Tools（Phase 2 准备）

### 9.1 Chart / Image Reading

**工具设计**：
```python
def read_image(path: str) -> str:
    """Use Claude 4 Opus / GPT-5 Vision to describe the image."""
    return vision_model_call(path, prompt="""
Describe this chart in detail:
- Type (bar/line/pie/...)
- Axes and labels
- Key data points / values
- Trends and patterns
""")
```

**SOTA**：ChartAgent (2025-10), MMAT-1M (ICCV 2025)

### 9.2 Video Reading

**工具设计**：
```python
def read_video(path: str, sample_fps=1) -> str:
    """Sample frames + Vision model describe."""
    frames = extract_frames(path, fps=sample_fps)
    return [vision_model_call(f) for f in frames]
```

## 10. 长视野推理技巧（Hard/Extreme 必备）

### 10.1 Subgoal Decomposition

参考 [A Subgoal-driven Framework (2026)](https://arxiv.org/abs/2603.19685)：把高层 task 拆 3 层：
- Goal → Subgoals → Atomic Actions

### 10.2 Memory Management

**做法**：维护一个 "scratchpad"，记录每步关键中间结果（如某 SQL 的输出），后续步骤可引用。

**避免**：把历史 obs 全塞 prompt（会爆 token + 漂移）

### 10.3 Replan Trigger

**触发条件**：
- 连续 K 步 verifier 给 RETRY
- 某节点 step 数超过预算
- Final-answer check 失败

**Replan 时**：把失败 trace + reflection 喂给 Planner 重新生成 DAG

## 11. 论文级技巧（Phase 2 进阶）

### 11.1 PRM (Process Reward Model) 训练

参考 Reward-SQL（DIAL，SIGMOD 2026）：
- 收集 step-level 数据（step + 是否 helpful）
- SFT 一个 7B verifier
- 用 PRM 替代 LLM Judge → 降本 + 提速

### 11.2 Workflow 自动优化（AFlow）

- 把当前手写 workflow 喂给 AFlow
- AFlow 用 MCTS 搜索 workflow 变体
- Phase 2 用 - 等于让"AI 设计 AI"

### 11.3 Trajectory SFT

- 收集 successful trajectories
- SFT 一个小模型作为 fast Executor
- 大模型只做 Planner+Verifier

## 12. 通用 Agent 编程经验（不踩坑）

| 经验 | 备注 |
|---|---|
| **不要相信 LLM 说"完成了"** | 必须 Verifier 确认 |
| **不要相信 LLM 说"这是答案"** | 必须 final check |
| **temperature 不全是 0** | Planner 0.0，Executor 0.3，BoN 时 0.7 |
| **prompt 越长越乱** | 删减比加 few-shot 更有效 |
| **trajectory 越长越漂** | max_steps 不要无脑调大 |
| **多 agent 不一定更好** | 角色越多 communication overhead 越大；建议 ≤3 |
| **API 错误必须 retry** | 加 exponential backoff |
| **JSON 解析必须 robust** | 用 partial JSON parser，不要相信 LLM 的 JSON 完美 |

下一份 → [`05-our-agent-design.md`](./05-our-agent-design.md)
