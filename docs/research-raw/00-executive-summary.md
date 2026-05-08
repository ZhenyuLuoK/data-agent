# 00 · Executive Summary & 冲分路线图

> 给你 2 周可立即落地的 SOTA 攻坚方案

---

## 1. 比赛一句话定位

> **DataAgent-Bench = "DABstep（异构源 + 多步推理）+ DA-Code（可执行代码 agent）+ Spider 2.0（企业级真实数据）" 的合体，并在 Phase 2 加入图像/视频模态。**

它不是单点 LLM benchmark（不是问答），而是一个**多步、跨模态、需要 Sandbox 执行的端到端 Agent 任务**。Baseline 是最朴素的 ReAct (8 工具，max 16 step)，留下了**巨大的优化空间**。

## 2. SOTA 的 4 个公认抓手

参考最近半年所有 SOTA 工作（DS-STAR、AIDE、SELA、AFlow、Data Interpreter、AutoKaggle、OpenManus、Energent.ai #1 DABstep 94.4%）的共性，**冲 SOTA 的方案几乎都包含以下 4 个核心元素**：

| 抓手 | 出处代表作 | 预期增益 | 工程成本 |
|---|---|---|---|
| **A. 显式规划层（Planner）** —— 把"题目 → 子任务 DAG"显式化，避免 ReAct 一步步漂移 | Data Interpreter, DS-STAR, AutoKaggle | +10~20pp | 低 |
| **B. 自验证层（Verifier / LLM-Judge）** —— 每步执行后用另一个 LLM 检查"这一步是否真的解决了子任务" | DS-STAR (核心创新), Reflexion | +5~15pp | 中 |
| **C. 测试时搜索（TTC）** —— Best-of-N 或 MCTS，在 16 步预算内并行多解 | AIDE, SELA, AFlow, Alpha-SQL | +5~15pp | 中-高 |
| **D. 强 Schema/Context 准备** —— 进入推理前先做 dataset profiling + schema linking | DS-STAR, DA-Agent | +5~10pp | 低 |

**关键判断**：在 baseline 仅 30~45% 准确率的当下，**不要追求"精巧的单点优化"，要先把 A+B+D 跑通，单这三项叠加就能从 baseline 推到 60%+**；C 在最后 1 周做。

## 3. 模型选型建议

```
Phase 1（成本敏感，需大量并行实验）
  - Planner / Verifier:  Claude Sonnet 4 / 4.5  ← 工具使用 + 长上下文最稳
  - Executor (CodeAct):  DeepSeek-V3.2 / Qwen3-Coder-480B  ← 性价比 + 代码强
  - 可选 Reasoner:        DeepSeek-R1            ← 复杂规划时切换

Phase 2（追求极致，加多模态）
  - Vision tool:         Claude 4 Opus / GPT-5  ← 图像/视频理解
  - 主控不变，仅在需要时调用 Vision
```

> 主办方 starter-kit 的 `agent.api_base` 字段是 OpenAI-Compatible，**任何上述模型都可直接接入**。

## 4. 5 周冲分路线图（与官方时间线对齐）

> 注：Phase 1 = 04-24 ~ 05-23（30 天），Phase 2 = 05-28 ~ 06-30（34 天）

### **Week 0（本周，4-23 ~ 4-30）— 地基**

**目标**：跑通 baseline + 建立可观测的迭代闭环

- [ ] Fork & 跑通 [`HKUSTDial/kddcup2026-data-agents-starter-kit`](https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit)，复现官方 ReAct baseline 在公开 demo 数据上的得分作为**基线分数 X₀**
- [ ] 把 Demo 数据集 (Easy / Medium / Hard / Extreme) 全跑一遍，**人工分析每个 Hard / Extreme 失败 case**，归类失败原因（建议归 6 类：①规划错误 ②工具调用错误 ③SQL/Python 语法 ④数据理解错 ⑤跨源融合错 ⑥幻觉答案）
- [ ] 搭建 **trace.json 离线分析脚本**，自动统计：平均步数、工具使用频次、失败步占比、错误类型分布
- [ ] 写一份 **5~10 条"标准问题"的硬测试集**，每次改动都跑，避免过拟合公开 demo

### **Week 1（4-30 ~ 5-7）— Planner + Schema RAG**

**目标**：A + D 抓手落地，把 baseline 推到 +10~15pp

- [ ] 实现 **Planner-Executor 双 Agent 架构**：
 - Planner: 收到 task 后，先用专用 prompt 让 LLM 输出 "**JSON 格式的子任务 DAG**"（节点 = 子目标 + 推荐工具 + 输入输出）
 - Executor: 按拓扑序执行 DAG 节点，每个节点是一个独立 ReAct mini-loop（max 4 step）
 - 失败回退：节点失败时，Planner 重新规划该节点（不重做整个任务）
 - 参考 Data Interpreter 的 Hierarchical Graph 设计
- [ ] 实现 **Schema/Dataset Profiling 工具**：进入 Executor 前自动跑一次：
 - 列出 context/ 全部文件 + 文件大小
 - SQLite: 自动 dump schema + 每表 sample 5 行
 - CSV: 列名 + dtype + 5 行样本
 - JSON / Markdown: 读取前 N 字符 + 关键词索引
 - **将 profiling 结果作为 system prompt 的一部分注入**（这是 DA-Agent 的关键技巧）
- [ ] 跑硬测试集 → 得到 **X₁**

### **Week 2（5-7 ~ 5-14）— Verifier + Reflexion**

**目标**：B 抓手落地，DS-STAR 同款迭代验证

- [ ] 实现 **Step-Level Verifier**：每个 Executor mini-loop 结束时，用另一个 LLM call 评估
 - "这一步执行结果是否真的解决了规划好的子目标？" → {OK, RETRY, REPLAN}
 - 输入：子目标描述 + 工具调用 + 执行 observation
 - 输出：判断 + 失败原因（用于下一轮 Reflexion）
- [ ] 实现 **Final-Answer Verifier**：在 `answer` tool 调用前，强制做一次自检
 - 类型检查：列名 / 行数 / 数值范围是否合理
 - 一致性检查：与原始 question 中的关键约束（"前 5 名"、"金额超过 X"）是否对得上
- [ ] 引入 **Reflexion buffer**：失败 trace 转化为 "lesson"，下一轮规划时作为 few-shot
- [ ] 跑硬测试集 → 得到 **X₂**

### **Week 3（5-14 ~ 5-21）— TTC: Best-of-N + Sandbox 加固**

**目标**：C 抓手 + 工程鲁棒性

- [ ] 实现 **Trajectory-Level Best-of-N**：
 - 同一 task 用不同 temperature / 不同 seed 跑 N 条 trajectory（推荐 N=3 或 5）
 - 用 LLM Judge 投票或基于 verifier 分数选最优
 - 与 Energent.ai / AIDE 同思路
- [ ] **Sandbox 加固**：
 - 每个 task 起独立 docker / venv，避免污染
 - Python tool 加 timeout (60s) + memory cap
 - SQL tool 强制 `LIMIT` 防 OOM
 - 文件读取 cap 防止 token 爆炸
- [ ] 实现 **prompt cache + KV cache 复用**（Anthropic prompt caching），降低 Best-of-N 成本
- [ ] 跑硬测试集 → 得到 **X₃**

### **Week 4（5-21 ~ 5-23）— Phase 1 冲刺提交**

- [ ] 在公开 demo + 自建硬测试集上做 ablation，确认每个组件都有正贡献
- [ ] 调 `max_steps`（baseline 16，建议升 24~32）+ `max_workers`（看预算）
- [ ] 准备 **3 套配置**（保守 / 激进 / 多模型 ensemble），看哪套在隐藏测试集上分数最高
- [ ] **Phase 1 截止：5-23**

### **Week 5+（5-28 ~ 6-30）— Phase 2 多模态 + Creative**

> 选择 Leaderboard 子赛道还是 Creative 子赛道？建议**根据 Phase 1 排名决定**：
> - 排名靠前（Top 10）→ 继续 Leaderboard，加 Vision tool 即可
> - 排名中游 → Creative，比拼"系统设计 + 决策透明度"，主办方亲自背书 OpenManus，**做一个高质量交互式 UI 是奇兵**

**Leaderboard 子赛道（追准确率）**：
- [ ] 加 **Vision tool**：`read_image(path)` → Claude 4 Opus 描述 + chart QA
- [ ] 加 **Video tool**：抽帧 + Vision 分析（Phase 2 数据公布后再细化）
- [ ] 引入 **MCTS（参考 SELA / Alpha-SQL / AFlow）**：在 Best-of-N 之上做 tree-search
- [ ] 再做一次 Reflexion buffer 的离线训练数据收集，下一版可考虑微调小模型做 Verifier

**Creative 子赛道（拼系统美感）**：
- [ ] 用 OpenManus / Streamlit / Gradio 做交互式 UI
- [ ] 可视化 trace.json：DAG 计划 + 每步代码 + 中间结果，**展示决策透明度**
- [ ] 加 human-in-the-loop 接口：允许中途纠正
- [ ] 写一份 6~8 页的 system paper，瞄准 Workshop 演讲

## 5. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| **隐藏测试集与公开 demo 分布漂移** | 公开数据过拟合，线上崩盘 | 自建 Hard/Extreme 风格题；不要为公开 demo 做特殊化 prompt |
| **API 成本爆炸**（Best-of-N × max_steps × tasks） | 钱包破产 | 必做 prompt cache；用便宜模型做 Executor，贵模型只做 Planner+Verifier；超时熔断 |
| **超时被判 0 分** | 大量 task 失败 | 单 task 严格设 timeout（baseline 600s 已合理）；Verifier 早停而不是死循环 |
| **Sandbox 安全/资源问题** | Python tool 卡死 | resource limit + signal-based timeout；隔离工作目录 |
| **Phase 2 多模态准备不足** | 临时抱佛脚 | Phase 1 阶段就把 vision tool 接口预留好（即使只是占位） |
| **过度 over-engineering** | 框架太复杂改不动 | 每个抓手做完都要做 ablation；不能让组件多到自己也调不动 |
| **追新模型疲劳** | 每周新模型，不断重测 | 锁定 1 主模型 + 2 备选，超过 2 周无明显增益不切换 |

## 6. 我们要不要"自己训模型"？

**结论：Phase 1 不要，Phase 2 视情况而定。**

- **不要做的事**：从头训 7B 模型（来不及，价值低）
- **可考虑做的事**：
 - 收集 Phase 1 的成功 trace（自家 + 开源数据），**SFT 一个小 Verifier 模型**（Qwen2.5-7B or InternLM3-8B），代替 Verifier 的 LLM call → 可大幅降本提速
 - Reward Model 思路：参考 DIAL 团队的 [Reward-SQL (SIGMOD 2026)](https://luoyuyu.vip/) — Stepwise Execution-Aware Reasoning + PRM
 - 微调 InfiAgent 风格的小型 DA-Agent（如果 Phase 2 数据足够）

## 7. 一个不能忽视的"内部消息"

**主办方 DIAL 实验室自己有 4 个高度相关的开源项目**，都是 SIGMOD/ICLR/ICML 顶会工作：

1. [**OpenManus**](https://github.com/FoundationAgents/OpenManus) — 通用 Agent 框架（5w+ Stars），骆昱宇 PI，**架构思路即主办方期望**
2. [**AFlow**](https://github.com/FoundationAgents/AFlow) (ICLR 2025 Oral) — MCTS 自动 workflow 优化
3. [**Alpha-SQL**](https://github.com/HKUSTDial/Alpha-SQL) (ICML 2025) — Zero-Shot Text-to-SQL + MCTS
4. [**DeepEye-SQL**](https://luoyuyu.vip/) (SIGMOD 2026) — Software-Engineering-Inspired Text-to-SQL，BIRD Top 5

**强烈建议**：
- 用 OpenManus 作为基础脚手架（而不是从零写）
- 在 SQL 子任务上直接调用 Alpha-SQL / DeepEye-SQL 的算法
- AFlow 的 MCTS workflow 优化思路可以借鉴到 Phase 2 的 TTC 模块

> 这是**赛题设计者的"思想偏好"**——他们认为优秀的 Data Agent 长这样。沿着这条路走，至少不会南辕北辙。

---

**下一步行动**：现在立刻 `git clone` starter-kit，配好 API key 跑 baseline，今晚就拿到 X₀。

下一份必读文档 → [`01-competition-analysis.md`](./01-competition-analysis.md)
