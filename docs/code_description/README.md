# KDD Cup 2026 · Data Agents · 冲 SOTA 调研报告

> 调研对象：[KDD Cup 2026 — Data Agents for Complex Data Analysis](https://dataagent.top/)
> 调研时间：2026-04-23
> 调研周期覆盖：2024-10 ~ 2026-04（最近半年重点）
> 仓库：`HKUSTDial/kddcup2026-data-agents-starter-kit`

---

## 0. 一句话结论（TL;DR）

**这是一场考验"端到端 Data Agent"工程能力的比赛，而不是单点 LLM benchmark。** 评测平台 `DataAgent-Bench` 给出的是**包含 SQLite/CSV/JSON/Markdown 多源异构数据的真实业务问题**，要求 Agent 在 **16 步以内**完成"理解 → 规划 → SQL/Python 调用 → 跨源融合 → 最终输出表格"的完整闭环。Baseline 是一个最朴素的 ReAct + 8 个 tool 的 Agent；**冲 SOTA 的核心抓手不在"换模型"，而在"工作流设计 + 测试时计算 + 自验证机制"**。

报告中给出的最终建议方案（详见 [`05-our-agent-design.md`](./05-our-agent-design.md)）是一套 **PER-Loop 架构**：
**P**lanner（DAG 计划器，借鉴 Data Interpreter / DS-STAR）+
**E**xecutor（CodeAct 单一动作空间）+
**R**eflector/**V**erifier（LLM-as-Judge + Self-Consistency 双重验证），并在外层套 **Best-of-N + MCTS（受 AFlow / SELA / Alpha-SQL 启发）** 进行测试时搜索。

---

## 1. 报告导航

| # | 文档 | 内容速览 | 推荐阅读对象 |
|---|---|---|---|
| 00 | [Executive Summary & 冲分路线图](./00-executive-summary.md) | 比赛核心 + 5 阶段冲分路线 + 风险点 | **必读** |
| 01 | [Competition Analysis](./01-competition-analysis.md) | DataAgent-Bench 任务剖析 / 数据形态 / 评测指标 / Phase1+2 赛制 / 时间线 / 奖金 / 提交方式 | 必读 |
| 02 | [Academic Research（最近半年 SOTA）](./02-academic-research.md) | 11 个核心 benchmark + 8 篇 SOTA 方法论文，2024H2~2026Q1 | 必读 |
| 03 | [Open-Source Data Agents](./03-open-source-agents.md) | OpenManus / Data Interpreter / DS-STAR / AutoKaggle / AIDE / SELA / OpenHands / smolagents / DA-Agent 横评 | 必读 |
| 04 | [SOTA 技巧手册](./04-sota-techniques.md) | CodeAct / ReAct / Reflexion / MCTS / Best-of-N / Multi-Agent Verify / Schema RAG / Long-Horizon Planning | 必读 |
| 05 | [我们的 Agent 设计方案 PER-Loop](./05-our-agent-design.md) | 完整架构图 + 模块设计 + 提示词骨架 + 5 周迭代路线 | **重点必读** |
| 06 | [References](./06-references.md) | 全部论文/项目/链接清单 | 备查 |

---

## 2. 关键事实速查

### 比赛
- **承办方**：港科大（广州）DIAL 实验室 + 清华大学数据库组（**首次由中国高校完全主导的 KDD Cup 重磅赛道**）
- **总监**：李国良（清华，ACM Fellow）+ 骆昱宇（HKUST-GZ，OpenManus 主要作者，DeepEye 负责人）
- **奖池**：120,000 RMB + 大厂 Offer + KDD 2026 Workshop 演讲
- **关键时间**（AoE）：
 - **2026-04-24 ~ 2026-05-23** Phase 1（公榜单赛道）
 - **2026-05-28 ~ 2026-06-30** Phase 2（双子赛道：Leaderboard / Creative）
 - **2026-08-09** KDD 2026 现场颁奖（济州岛）
- **Starter-kit**：[HKUSTDial/kddcup2026-data-agents-starter-kit](https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit)，已含 ReAct baseline + 8 个工具

### 任务（DataAgent-Bench）
- 每条 task 是一个目录：`task.json`（题目 + 难度）+ `context/`（异构数据：CSV / JSON / SQLite / 文本）
- **难度 4 级**：Easy / Medium / Hard / Extreme，区分维度是 **模态数量 × 干扰项规模**
- **Phase 2 Leaderboard 子赛道会引入新模态**：图像、视频
- 推理范式：顺序链 / 分支合并 / 迭代循环
- 输出：`prediction.csv`（最终答案表格）+ `trace.json`（执行轨迹）

### 学术界 SOTA（最近半年关键里程碑）
- **DS-STAR (Google Research, 2025-11)** — 当前公认 SOTA Data Science Agent；DABstep 总分 44.69%（超过 DA-Agent 39.79%）；核心是 **"迭代 Planner + LLM Judge 验证器"**
- **Energent.ai (2026-Q1)** — DABstep 排行榜第 1，**94.4% 准确率**（外部商用，闭源，但可参考其架构思路）
- **DABstep (Adyen × HuggingFace, 2025-06)** — 与本赛题最相似的开放 benchmark；含 450+ 条真实金融多源数据任务
- **DA-Code (EMNLP 2024)** — 当前最强基线 DA-Agent 准确率仅 30.5%，留下巨大空间
- **AutoKaggle (ICLR 2025)** — 6 阶段 5 智能体 Kaggle 自动化，平均完成率 83.8%
- **AIDE (Weco AI, 2025-02)** — 树搜索 ML 工程；MLE-Bench 上比 OpenHands 多拿 4× 奖牌
- **SELA (MetaGPT, 2024-10)** — MCTS 增强 LLM Agent，超越 AIDE
- **AFlow (ICLR 2025 Oral)** — 用 MCTS 自动生成 Agent 工作流（DIAL 团队作品，**与赛题主办方同源**）
- **Alpha-SQL (ICML 2025)** — Zero-Shot Text-to-SQL + MCTS（DIAL 团队作品）
- **Data Interpreter (ACL 2025 Findings)** — Hierarchical Graph 动态规划，InfiAgent +25%

### 模型选型基准（2025 主流）
| 模型 | 适用场景 | 备注 |
|---|---|---|
| **Claude Sonnet 4 / 4.5** | Agent 主控 + 代码生成 | SWE-Bench Verified ~71%，工具使用最稳 |
| **GPT-5 / o3** | 复杂推理 + Verifier | SWE-Bench 72.8%，但贵 |
| **DeepSeek-V3.2 / R1** | 性价比 Executor | 开源 + 低成本 |
| **Qwen3-Coder-480B** | 自托管代码生成 | 开源 SOTA 编码模型 |
| **TableGPT2-7B** | 表格语义理解（小模型补充） | 表格预训练，可做轻量 retriever |

---

## 3. 报告核心结论（5 条）

1. **比赛形态 ≈ DABstep × DA-Code × Spider 2.0** —— 当前学术界最相关的三个 benchmark；冲分思路可直接迁移。
2. **不要在 Phase 1 死磕单步精度，而要把"计划-执行-验证"循环跑稳** —— DS-STAR 的 +5pp 提升，核心来自 LLM Judge 验证器。
3. **MCTS / Best-of-N / Multi-Agent Critique 三选一是必做项** —— 在 16 步预算内，用更多"测试时计算"换 +10~20pp 准确率，是 SOTA agent 的共性。
4. **DIAL 团队（主办方）有 4 个高度相关开源项目**：OpenManus / AFlow / Alpha-SQL / Data Interpreter（DIAL 是 ACL 2025 Findings 共同作者）—— **直接复用其代码框架，可拿到"对赛题理解最深的工程基底"**。
5. **Phase 2 会加图像/视频** —— Phase 1 设计时就要预留多模态 tool 接口，否则 Phase 2 来不及。

---

## 4. 强烈推荐先读这 3 份

1. [Executive Summary & 冲分路线图](./00-executive-summary.md) — 给你 2 周内的具体动作清单
2. [Competition Analysis](./01-competition-analysis.md) — 题目本身没读懂，一切都白费
3. [我们的 Agent 设计方案 PER-Loop](./05-our-agent-design.md) — 直接落地的工程蓝图

祝冲分顺利 🚀
