# 03 · Open-Source Data Agents · 全景横评

> 维度：架构 / 适用场景 / 成熟度 / 与 KDD Cup 的契合度

---

## 1. 速查表（一图看完）

| 项目 | 出处 | 核心范式 | 适合 | KDD Cup 借鉴度 |
|---|---|---|---|---|
| **OpenManus** ⭐⭐⭐⭐⭐ | DIAL + MetaGPT | Plan + ReAct + Tool | 通用 / 数据 | **直接当脚手架** |
| **MetaGPT Data Interpreter** ⭐⭐⭐⭐⭐ | MetaGPT (含骆昱宇) | Hierarchical Graph + Code | 数据科学 | **直接 fork** |
| **AFlow** ⭐⭐⭐⭐ | DIAL + MetaGPT | MCTS Workflow Optimization | 工作流自调优 | Phase 2 必用 |
| **Alpha-SQL** ⭐⭐⭐⭐ | DIAL | MCTS for SQL | Text-to-SQL | SQL 子任务直接套 |
| **DeepEye-SQL** ⭐⭐⭐⭐ | DIAL | SE-Inspired Text-to-SQL | SQL 子任务 | 与 Alpha-SQL 互补 |
| **AutoKaggle** ⭐⭐⭐⭐ | M-A-P + ByteDance | 6-Stage 5-Agent Pipeline | Kaggle 风格 | Pipeline 思路借鉴 |
| **AIDE** ⭐⭐⭐⭐ | Weco AI | Tree Search of Code | ML 工程 | OpenAI 官方采用 |
| **SELA** ⭐⭐⭐⭐ | MetaGPT | MCTS for AutoML | AutoML | 与 AIDE 互补 |
| **OpenHands** ⭐⭐⭐⭐ | All Hands AI | CodeAct 2.1 | 软件工程 | CodeAct 范式参考 |
| **SWE-Agent** ⭐⭐⭐ | Princeton | Agent-Computer Interface | Bug fix | 工具接口参考 |
| **smolagents** ⭐⭐⭐ | HuggingFace | Code agent (轻量) | DABstep 已用 | 看 HF 怎么打 DABstep |
| **DA-Agent** ⭐⭐⭐ | DA-Code 团队 | DA-Code baseline | DA-Code | 是 DA-Code SOTA baseline |
| **TableGPT2** ⭐⭐⭐ | 浙大+港大 | Table-pretrained 7B | 表格理解 | 轻量子模块 |
| **AutoGen** ⭐⭐ | Microsoft | Multi-agent conversation | 通用 | 通用框架 |
| **ChatDev** ⭐⭐ | 清华 | 软件公司隐喻 | 软件 | 通用 |

---

## 2. 重点项目深度剖析

### 2.1 ⭐⭐⭐⭐⭐ OpenManus

- **GitHub**: [FoundationAgents/OpenManus](https://github.com/FoundationAgents/OpenManus)（GitHub 50k+ stars）
- **作者**：MetaGPT + DIAL（**骆昱宇是合著者**）
- **架构**：
 ```
 OpenManus
 ├── ReAct Agent (基础)
 ├── PlanningFlow (复杂任务)
 ├── DataAnalysis Agent (数据分析专用) ← 直接相关
 ├── MCP Tool Server
 ├── Sandbox (Docker-based)
 └── Multi-agent flow (run_flow.py)
 ```
- **关键文件**：`app/agent/manus.py`（主 agent）, `app/flow/planning.py`（规划）, `config/config.toml`（LLM 配置）
- **能力**：
 - ✅ 已支持 OpenAI-Compatible API（与 starter-kit 一致）
 - ✅ 已有 DataAnalysis Agent（含 chart 可视化工具）
 - ✅ 已支持 Sandbox 隔离
 - ✅ 已支持 browser-use（Phase 2 可能用）
- **改造方向**（用 OpenManus 改造成 DataAgent-Bench 解题器）：
 1. 把 starter-kit 的 8 个 tool 注册到 OpenManus tool registry
 2. 把 OpenManus 的 PlanningFlow 接到 DataAgent-Bench 的 task loader
 3. 复用 sandbox + browser tool

### 2.2 ⭐⭐⭐⭐⭐ MetaGPT Data Interpreter

- **arXiv**: [2402.18679](https://arxiv.org/abs/2402.18679) | **Repo**: [MetaGPT/examples/di](https://github.com/geekan/MetaGPT/blob/main/examples/di/README.md)
- **核心**：
 ```
 用户 query
   ↓
 Hierarchical Graph Plan (DAG)
   ↓ for each node
 Programmable Node Generation (写代码)
   ↓
 Execute (sandbox)
   ↓
 Verify (节点完成 / 失败重试)
   ↓
 Tool Recommendation (动态推荐工具)
 ```
- **效果**：InfiAgent +25%，MATH SOTA
- **关键 prompt**：在 `metagpt/strategy/planner.py`，**直接抄**

### 2.3 ⭐⭐⭐⭐ DS-STAR (Google Research, 2025-11)

- 公开了 paper / blog，**未公开代码**（Google internal）
- 但有详细的伪代码 + 提示词描述
- **核心可复现的 3 个 prompt**：
 1. Planner prompt：让 LLM 输出 plan-as-code
 2. Verifier prompt：让 LLM 判断"这一步真的解决了 sub-goal 吗"（不只是看代码 success）
 3. Update Plan prompt：根据 verifier 反馈修订 plan
- **应在我们 PER-Loop 中直接复现这 3 个 prompt**

### 2.4 ⭐⭐⭐⭐ AutoKaggle

- **GitHub**: [multimodal-art-projection/AutoKaggle](https://github.com/multimodal-art-projection/AutoKaggle)
- **架构**：5 个角色 agent
 ```
 Reader (理解任务背景)
 ↓
 Planner (制定执行计划)
 ↓
 Developer (写代码 + 执行)
 ↓
 Reviewer (代码审查)  ← 与 DS-STAR Verifier 同思路
 ↓
 Summarizer (总结)
 ```
- **6 阶段固定 pipeline**：
 1. 背景理解 → 2. 初步 EDA → 3. 数据清洗 → 4. 深入 EDA → 5. 特征工程 → 6. 建模
- **关键优势**：稳定、可复现
- **关键劣势**：固定 pipeline，对非 Kaggle 风格任务不灵活

### 2.5 ⭐⭐⭐⭐ AIDE (Weco AI)

- **GitHub**: [WecoAI/aideml](https://github.com/wecoai/aideml)
- **核心思想**：把 ML 工程问题视作"代码空间的优化"
- **算法**：
 1. **Greedy Tree Search**：从初始解出发，每次试 K 个改动，选最好的
 2. **Improvement Operator**：用 LLM 提出改进
 3. **Bug Fix Operator**：失败时修 bug
- **OpenAI MLE-Bench 论文中是 baseline 的最强者**
- **代码非常简洁**（~2000 行），易于理解和迁移

### 2.6 ⭐⭐⭐⭐ SELA (MetaGPT)

- **GitHub/site**: [foundationagents.org/projects/sela](https://foundationagents.org/projects/sela/)
- **核心**：在 AIDE 的 greedy 之上换成 **MCTS**
- 4 步：Selection → Expansion → Simulation → Backpropagation
- **超越 AIDE**

### 2.7 ⭐⭐⭐⭐ OpenHands (All Hands AI)

- **GitHub**: [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) (50k+ stars)
- **核心范式**：**CodeAct 2.1**（unified action space = Python）
- **SWE-Bench Verified 53%**（开源 SOTA）
- **Repo 结构**：
 - `openhands/agenthub/codeact_agent/` ← 主 agent
 - `openhands/runtime/` ← sandbox + tool 执行
 - `openhands/llm/` ← 模型抽象
- **可学习**：
 1. Sandbox 设计（容器隔离）
 2. CodeAct 提示词
 3. tool function 与 Python 命名空间的统一抽象

### 2.8 ⭐⭐⭐ smolagents (Hugging Face)

- **GitHub**: [huggingface/smolagents](https://github.com/huggingface/smolagents)
- **特色**：极简实现的 code agent
- **DABstep 官方 baseline 用的就是 smolagents**
- **与 KDD Cup 关系**：可对比 starter-kit 的 baseline 与 smolagents 谁更强

### 2.9 ⭐⭐⭐ DA-Agent (DA-Code 配套)

- 与 DA-Code benchmark 一起发布
- 是 EMNLP 2024 论文 baseline
- **GitHub**: [yiyihum/da-code](https://github.com/yiyihum/da-code)

### 2.10 ⭐⭐⭐ AFlow

- **GitHub**: [FoundationAgents/AFlow](https://github.com/FoundationAgents/AFlow)
- **DIAL 出品**
- **用法**：把我们手写好的 agent workflow 喂给 AFlow，让它 MCTS 搜索更好的 workflow
- Phase 2 用来"自动调参"

### 2.11 ⭐⭐⭐ Alpha-SQL & DeepEye-SQL

- **DIAL 出品**
- 当 task 涉及 SQLite 时，可以拆出 SQL 子任务，喂给 Alpha-SQL 处理

## 3. 工程脚手架对比（如果你要从 0 搭）

| 选择 | 优点 | 缺点 | 何时选 |
|---|---|---|---|
| **直接改 starter-kit** | 与官方接口完全一致，零迁移成本 | 框架朴素，从 0 写 Planner 等 | Week 0~1，跑通 baseline |
| **OpenManus + 适配 starter-kit** | 主办方背书，已有 DataAnalysis Agent + Sandbox | 需要做接口适配 | Week 1+，正式工程 |
| **MetaGPT 全家桶** | Data Interpreter + AFlow + SELA 都在 | 偏重；学习曲线 | Phase 2 想冲极致 |
| **OpenHands CodeAct** | 工程最成熟，sandbox 最稳 | 偏向 SWE 而非 DS | 想要极强代码能力时 |
| **从 smolagents 起步** | 最轻量，DABstep 同款 | 功能少，要自己加 | 资源紧张时 |

**我们的推荐**：
- **Week 0**：跑 starter-kit 原汁原味
- **Week 1+**：基于 OpenManus 改造（**因为这是主办方亲自参与的项目**），把 Data Interpreter 的 Hierarchical Graph 思想集成进 PlanningFlow

## 4. 商用闭源参考（仅看思路，不能直接用）

### 4.1 Energent.ai（DABstep #1, 94.4%）

- **核心**：商用产品，对外宣传"#1 on DABstep"
- 只有 marketing 页面，无技术细节
- **可推断的架构**：
 - 多 LLM ensemble + verifier
 - 强 schema linking 模块
 - 大量 prompt engineering

### 4.2 Manus（OpenManus 的"原型"）

- 闭源，对外是 SaaS
- **OpenManus 已经复现其大部分能力**

## 5. 核心可借鉴代码段（直接抄）

### 5.1 Data Interpreter 的 Plan Generation Prompt（伪代码）

```python
plan_prompt = """
You are a planning expert. Decompose the user task into a directed acyclic graph (DAG) of subtasks.
Each node should have:
  - id: int
  - description: str
  - depends_on: list[int]
  - required_tools: list[str]
  - expected_output: str

Output JSON only.

User task: {task}
Available tools: {tools_with_descriptions}
"""
```

### 5.2 DS-STAR 的 Verifier Prompt（伪代码）

```python
verifier_prompt = """
You are a verifier. Decide whether the executed step truly solves the subgoal.

Subgoal: {subgoal_description}
Tool called: {tool_name}({args})
Observation: {observation}

Output one of:
  - OK: the step solved the subgoal correctly.
  - RETRY: the same approach should be retried (transient error).
  - REPLAN: the approach is wrong and the planner should re-plan this node.

If not OK, explain why in 1-2 sentences.
"""
```

### 5.3 AIDE 的 Improvement Operator（伪代码）

```python
improve_prompt = """
Current best solution (score={score}):
```python
{current_code}
```
Generate an improved version. Possible improvements:
- Better feature engineering
- Better model
- Bug fix in {known_bug}
"""
```

## 6. 项目"亲缘关系图"（理解人脉）

```
DIAL @ HKUST(GZ)  (骆昱宇 PI)
  ├── OpenManus       ── 共建 with MetaGPT
  ├── AFlow           ── 共建 with MetaGPT
  ├── Alpha-SQL       ── 自家
  ├── DeepEye-SQL     ── 自家
  ├── Data Interpreter ── 共建 with MetaGPT
  ├── Atom of Thoughts ── 共建 with MetaGPT
  └── KDD Cup 2026    ── 主办

MetaGPT (deepwisdom)
  ├── MetaGPT (主项目)
  ├── Data Interpreter (data agent)
  ├── SELA (AutoML)
  ├── AFlow (workflow optim)
  └── 与 DIAL 深度合作

清华 DB Group (李国良)
  ├── A Survey of LLM × DATA
  ├── 多个 SIGMOD/VLDB 论文
  └── KDD Cup 2026 共同主办
```

> **强烈建议**：你的方案 = OpenManus 脚手架 + Data Interpreter 规划 + Alpha-SQL/DeepEye-SQL SQL 模块 + 自己的 Verifier + 自己的 BoN/MCTS。

下一份 → [`04-sota-techniques.md`](./04-sota-techniques.md)
