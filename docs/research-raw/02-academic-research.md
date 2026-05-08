# 02 · Academic Research · 最近半年 Data Agent SOTA 全景

> 时间窗口：2024-10 ~ 2026-04，重点覆盖 ICLR 2025、ICML 2025、NeurIPS 2025、SIGMOD 2026
> 关注维度：**Benchmark + 方法论 + Survey**

---

## 1. 与本赛题最相关的 Benchmarks（按相关度排序）

### 1.1 ⭐⭐⭐ DABstep (Adyen × HuggingFace, 2025-06)

- **arXiv**: [2506.23719](https://arxiv.org/abs/2506.23719)
- **Leaderboard**: https://huggingface.co/spaces/adyen/DABstep
- **数据**：450+ 题，Adyen 真实金融业务数据，**结构化 + 非结构化混合**
- **任务**：多步 reasoning，要 Agent 自己用工具
- **SOTA**：
 - **学术**：DS-STAR (Google) 44.69%
 - **商用 #1**：**Energent.ai 94.4%**（不开源，闭源商业产品）
 - 早期 baseline（2025-02）：最强的 LLM 也只在 16% 左右
- **与 KDD Cup 关系**：**最相似的开放 benchmark**，思路可直接迁移
- **可借鉴**：Adyen 提供 smolagents 实现做 baseline；HF blog 有完整 [agent 设计指南](https://huggingface.co/blog/dabstep)

### 1.2 ⭐⭐⭐ DA-Code (EMNLP 2024)

- **arXiv**: [2410.07331](https://arxiv.org/abs/2410.07331) | **GitHub**: [yiyihum/da-code](https://github.com/yiyihum/da-code) | **Bench site**: [da-code-bench.github.io](https://da-code-bench.github.io/)
- **数据**：500 题，分 3 类
 - Data Wrangling（数据清洗）
 - Machine Learning（建模）
 - EDA（探索分析）
- **任务**：Agent 在 sandbox 里写代码完成
- **SOTA**：DA-Agent（自家） 30.5%（GPT-4），其他框架更低
- **与 KDD Cup 关系**：CodeAct + Sandbox 范式与 starter-kit 完全一致
- **可借鉴**：
 - 评测脚本（执行结果比对）思路
 - Sandbox 容器化设计（docker-based）
 - Tool 接口规范

### 1.3 ⭐⭐⭐ DSBench (ICLR 2025)

- **arXiv**: [2409.07703](https://arxiv.org/abs/2409.07703) | **GitHub**: [liqiangjing/dsbench](https://github.com/liqiangjing/dsbench) | **Site**: [liqiangjing.github.io/dsbench.github.io](https://liqiangjing.github.io/dsbench.github.io/)
- **数据**：540 题
 - 466 数据分析（来自 ModelOff）
 - 74 数据建模（来自 Kaggle）
- **SOTA**：最佳 agent 在 analysis 仅 **34.12%**，modeling 34.74% RPG
- **结论**："Data Science Agent 远未达到 Data Scientist 水平" → 巨大改进空间

### 1.4 ⭐⭐ Spider 2.0 (ICLR 2025 Oral)

- **arXiv**: [2411.07763](https://arxiv.org/abs/2411.07763) | **Site**: [spider2-sql.github.io](https://spider2-sql.github.io/) | **GitHub**: [xlang-ai/Spider2](https://github.com/xlang-ai/Spider2)
- **数据**：632 题真实企业级 SQL workflow
- **关键观察**：Spider 1.0 上 90%+ 的模型，**Spider 2.0 上掉到 10~20%**
- **与 KDD Cup 关系**：DataAgent-Bench 的 SQLite 子任务难度参考此基准

### 1.5 ⭐⭐ InfiAgent-DABench (ICML 2024)

- **arXiv**: [2401.05507](https://arxiv.org/abs/2401.05507) | **GitHub**: [InfiAgent/InfiAgent](https://github.com/InfiAgent/InfiAgent) | **Site**: [infiagent.github.io](https://infiagent.github.io/)
- **数据**：257 题，单 CSV 上的数据分析
- **SOTA**：GPT-4 ~75%，相对成熟
- **与 KDD Cup 关系**：Easy 难度参考

### 1.6 ⭐⭐ Tapilot-Crossing (NAACL 2024)

- **arXiv**: [2403.05307](https://arxiv.org/abs/2403.05307) | **Site**: [tapilot-crossing.github.io](https://tapilot-crossing.github.io/)
- **数据**：1024 多轮交互式数据分析
- **特色**：交互式（multi-turn）→ Phase 2 Creative 子赛道可借鉴
- **方法**：提出 Adaptive Reasoning（AIR）

### 1.7 ⭐⭐ BIRD-CRITIC (NeurIPS 2025 Main)

- **GitHub**: [bird-bench/BIRD-CRITIC-1](https://github.com/bird-bench/BIRD-CRITIC-1) | **Site**: [bird-bench.github.io](https://bird-bench.github.io/)
- **数据**：600 dev + 200 OOD 测试，PostgreSQL/SQLite SQL 调试任务
- **SOTA**（2026-03）：Claude Opus 4.6 仅 34.0%
- **与 KDD Cup 关系**：SQL 错误恢复能力参考

### 1.8 ⭐⭐ MLE-Bench (OpenAI, 2024-10)

- **OpenReview**: [PDF](https://openreview.net/pdf?id=6s5uXNWGIh)
- **数据**：75 个真实 Kaggle ML 工程比赛
- **SOTA**：AIDE 16.9% medal rate
- **与 KDD Cup 关系**：端到端 ML 任务，Phase 2 modeling 子任务参考

### 1.9 ⭐ AgentDS-Bench (2026-03, ICHI 2026 配套)

- **arXiv**: [2603.19005](https://arxiv.org/abs/2603.19005) | **Site**: [agentds.org](https://agentds.org/)
- **数据**：17 个领域专项数据科学挑战，多模态
- **特色**：考察**人机协作**

### 1.10 ⭐ DS-Bench (2025-05)

- **新版** Realistic Data Science Code Generation
- 与 DSBench 不同（注意区分）

### 1.11 ⭐ DataSciBench (arXiv 2502.13897)

- 又一个 LLM-as-Data-Scientist benchmark

## 2. 方法论 SOTA（核心论文）

### 2.1 ⭐⭐⭐⭐⭐ DS-STAR (Google Research, 2025-11) — 当前公认 SOTA

- **Blog**: [Google Research](https://research.google/blog/ds-star-a-state-of-the-art-versatile-data-science-agent/)
- **OpenReview**: [WJOgneFtVi](https://openreview.net/forum?id=WJOgneFtVi)
- **arXiv**: 2025
- **核心创新**：
 1. **Iterative Planner**：Plan → Execute → Verify → Update Plan，循环直到收敛
 2. **LLM Judge as Verifier**：用另一个 LLM 检查每步是否真的解决了子任务（而非只看代码是否运行成功）
 3. **多文件异构数据自动检索**：原始实验设置（无 oracle）下准确率 **44.69%**，超过 DA-Agent 39.79%；Oracle 设置 **52.55%**
- **DABstep 上的提升**：+5pp 来自 Verifier，+5pp 来自 Iterative Planning
- **可直接借鉴**：Verifier prompt + 迭代收敛逻辑

### 2.2 ⭐⭐⭐⭐ MetaGPT Data Interpreter (ACL 2025 Findings)

- **arXiv**: [2402.18679](https://arxiv.org/abs/2402.18679) | **GitHub**: [examples/di](https://github.com/geekan/MetaGPT/blob/main/examples/di/README.md)
- **作者**：含骆昱宇（**赛题主办方**）
- **核心创新**：
 1. **Hierarchical Graph Modeling**：动态生成任务图（DAG），节点 = 子任务
 2. **Programmable Node Generation**：每个节点用 LLM 写代码
 3. **Verification + Tool Recommendation**：根据节点类型推荐合适的工具
- **效果**：InfiAgent-DABench 上 +25%，超越当时所有开源框架
- **强烈建议**：**直接 fork MetaGPT 的 di 模块作为我们的 Planner 基底**

### 2.3 ⭐⭐⭐⭐ AutoKaggle (ICLR 2025)

- **arXiv**: [2410.20424](https://arxiv.org/abs/2410.20424) | **GitHub**: [multimodal-art-projection/AutoKaggle](https://github.com/multimodal-art-projection/AutoKaggle) | **Site**: [m-a-p.ai/AutoKaggle.github.io](https://m-a-p.ai/AutoKaggle.github.io/)
- **核心创新**：
 1. **6 阶段 workflow**：背景理解 → 初步 EDA → 数据清洗 → 深入 EDA → 特征工程 → 建模/验证/预测
 2. **5 个专家 agent**：Reader / Planner / Developer / Reviewer / Summarizer
 3. **数据科学工具库**：内置 ML 常用算法
- **效果**：8 个 Kaggle 比赛，平均完成率 83.8%，平均排名 42.8%
- **可借鉴**：Phase 阶段化 + Reviewer agent

### 2.4 ⭐⭐⭐⭐ AIDE (Weco AI, 2025-02)

- **arXiv**: [2502.13138](https://arxiv.org/abs/2502.13138) | **GitHub**: [WecoAI/aideml](https://github.com/wecoai/aideml) | **Site**: [aide.ml](https://www.aide.ml/)
- **核心创新**：
 1. **Code as State**：把 ML 工程问题建模为代码空间的优化问题
 2. **Tree Search**：试错被建模为对潜在解的树搜索
- **效果**：MLE-Bench 上 **比 OpenHands 多拿 4× 奖牌**
- **关键**：OpenAI 在 MLE-Bench 论文中**官方采用 AIDE**

### 2.5 ⭐⭐⭐⭐ SELA (NeurIPS 2025)

- **arXiv**: [2410.17238](https://arxiv.org/abs/2410.17238) | **GitHub**: [FoundationAgents/SELA](https://foundationagents.org/projects/sela/)
- **作者**：MetaGPT 团队
- **核心创新**：
 1. **MCTS + LLM Agent**：用 MCTS 优化 AutoML pipeline
 2. **从实验反馈学习**：Selection / Expansion / Simulation / Backpropagation
- **效果**：20 个 ML 数据集 SOTA，**超越 AIDE**

### 2.6 ⭐⭐⭐⭐ AFlow (ICLR 2025 Oral, top 1.8%)

- **arXiv**: [2410.10762](https://arxiv.org/abs/2410.10762) | **GitHub**: [FoundationAgents/AFlow](https://github.com/FoundationAgents/AFlow)
- **作者**：含骆昱宇（**赛题主办方**）
- **核心创新**：
 1. **Workflow as Code**：把 agentic workflow 表示成代码空间
 2. **MCTS 自动优化**：自动生成 + 优化最优 workflow
- **效果**：用 GPT-3.5/4o-mini 达到 GPT-4 水平
- **与 KDD Cup 关系**：**Phase 2 用来自动优化我们的 agent workflow，不需要人工调参**

### 2.7 ⭐⭐⭐⭐ Alpha-SQL (ICML 2025)

- **arXiv**: [2502.17248](https://arxiv.org/abs/2502.17248) | **GitHub**: [HKUSTDial/Alpha-SQL](https://github.com/HKUSTDial/Alpha-SQL) | **Site**: [alpha-sql-hkust.github.io](https://alpha-sql-hkust.github.io/)
- **作者**：DIAL（**赛题主办方**）
- **核心创新**：
 1. **MCTS for Text-to-SQL**：把 SQL 生成建模为结构化搜索
 2. **Schema Constraints + Semantic Rules**：剪枝
 3. **Zero-Shot**：不需要 in-context examples
- **与 KDD Cup 关系**：**直接拿来做 SQLite 子任务的处理器**

### 2.8 ⭐⭐⭐ Atom of Thoughts (NeurIPS 2025)

- **arXiv**: [2502.12018](https://arxiv.org/abs/2502.12018) | **GitHub**: [qixucen/atom](https://github.com/qixucen/atom)
- **作者**：含骆昱宇
- **核心创新**：
 1. **Markov 风格的原子推理**：每一步只依赖当前状态
 2. **Test-time scaling**：随计算预算增加，准确率线性提升
- **与 KDD Cup 关系**：在长链推理任务上做 test-time compute 时可参考

### 2.9 ⭐⭐⭐ DeepEye-SQL (SIGMOD 2026)

- 作者：李伯岩、骆昱宇等（**赛题主办方**）
- 创新：**Software-Engineering-Inspired** Text-to-SQL（即把 SE 实践引入：unit test、refactor、code review）
- BIRD 榜单 Top 5
- **与 KDD Cup 关系**：SQL 子任务的另一选择，与 Alpha-SQL 互补

### 2.10 ⭐⭐⭐ TableGPT2 (2024-11)

- **arXiv**: [2411.02059](https://arxiv.org/abs/2411.02059) | **HuggingFace**: [tablegpt/TableGPT2-7B](https://huggingface.co/tablegpt/TableGPT2-7B)
- 用 593.8K 表格 + 2.36M 高质量 query-table-output 微调
- 7B 小模型在表格任务上接近大模型
- **与 KDD Cup 关系**：可作为**轻量 retriever / table semantic understanding 模块**，省 token

### 2.11 ⭐⭐⭐ Reward-SQL (SIGMOD 2026)

- 作者：DIAL
- 创新：Stepwise Execution-Aware Reasoning + Process Reward Model
- **与 KDD Cup 关系**：如果有时间训 PRM，是好方向

### 2.12 ⭐⭐⭐ AgenticData (2025-08)

- **arXiv**: [2508.05002](https://arxiv.org/pdf/2508.05002)
- **核心**：Data Profiling Agent（理解数据 → 选数据集 → 抽相关数据） + Multi-step Analysis Agent
- **与 KDD Cup 关系**：异构数据 profiling 思路可直接复用

## 3. Surveys（必读，建立全景认知）

### 3.1 ⭐⭐⭐⭐⭐ Data Agents: Levels, State of the Art, and Open Problems (SIGMOD 2026 Tutorial)

- **arXiv**: [2602.04261](https://arxiv.org/abs/2602.04261)
- **作者**：骆昱宇 + 李国良 + 汤南（**全是赛题主办方**）
- **必读理由**：**主办方亲自定义"Data Agent"是什么、有几个等级、SOTA 在哪 → 这就是赛题的"答案模板"**
- 配套：[Awesome Data Agents](https://github.com/) 列表

### 3.2 ⭐⭐⭐⭐ LLM/Agent-as-Data-Analyst: A Survey (2025-09)

- **arXiv**: [2509.23988](https://arxiv.org/abs/2509.23988)
- **核心贡献**：建立 5 个 Data Agent 设计目标
 1. Semantic-aware design（语义感知）
 2. Modality-hybrid integration（多模态融合）
 3. Autonomous pipelines（自主流水线）
 4. Tool-augmented workflows（工具增强）
 5. Open-world tasks support（开放任务支持）
- 把数据按模态分了 4 类：结构化 / 半结构化 / 非结构化 / 异构 → **DataAgent-Bench 是后两类**

### 3.3 ⭐⭐⭐ A Survey of Data Agents: Emerging Paradigm or Overstated Hype? (2025-10)

- **arXiv**: [2510.23587](https://arxiv.org/abs/2510.23587)
- 系统化追踪 data agent autonomy levels

### 3.4 ⭐⭐⭐ A Survey on AI Agents for Data Management (HAL 2025)

- 编排模式 / 自治级别 / 内存设计 / 输入模态四个视角综述

### 3.5 ⭐⭐⭐ A Survey of LLM × DATA (Tsinghua DB Group)

- 来自李国良组（**赛题主办方**），与 RAG / 数据管理交叉

## 4. 一线"通用 Agent SOTA"（虽然不是数据领域，但技巧迁移有用）

### 4.1 OpenHands CodeAct 2.1 (2025)

- [Blog](https://openhands.dev/blog/openhands-codeact-21-an-open-state-of-the-art-software-development-agent)
- SWE-Bench Verified **53% 解决率**（开源 SOTA）
- 核心：**统一 code action 空间**

### 4.2 SWE-Bench 当前 Leaderboard (2026-04)

| 模型 / Agent | SWE-Bench Verified |
|---|---|
| GPT 5.2 Codex | 72.80 |
| Claude 4.5 Sonnet (high reasoning) | 71.40 |
| Kimi K2.5 (high reasoning) | 70.80 |
| DeepSeek V3.2 | ~65 |
| **mini-SWE-agent** (100 行 Python) | 74% |

### 4.3 Plan-and-Act (UC Berkeley, 2025)

- 长视野任务 SOTA，57.58% web navigation
- 启示：**显式 Planner + Executor 双层是长视野任务的标配**

### 4.4 Multi-Agent Verification (NeurIPS 2025)

- 在 best-of-N 之上引入 verifier ensemble
- 启示：**Verifier 也可以"投票"**

### 4.5 Test-time Compute Scaling Survey

- [arXiv 2506.12928](https://arxiv.org/html/2506.12928v1)
- 系统总结 BoN / Beam Search / Tree Search 在 agent 场景的应用

## 5. 模型选型详细数据

### 5.1 SWE-Bench Verified（当前最权威的 agent 能力 benchmark）

| 模型 | 得分 | 备注 |
|---|---|---|
| GPT-5.2 Codex | 72.80% | 闭源 |
| Claude 4.5 Sonnet | 71.40% | 闭源，工具使用最稳 |
| Kimi K2.5 | 70.80% | 月之暗面 |
| DeepSeek V3.2 | ~65% | 开源 SOTA |
| Qwen3-Coder-480B | ~63% | 开源 |

### 5.2 综合编码能力（截至 2025-04）

| 模型 | 上下文 | 输入价 ($/M) | 优势 |
|---|---|---|---|
| Claude Sonnet 4.5 | 200K | 3.0 | 工具使用、长 trajectory 最稳 |
| GPT-5 | 1M | 15.0 | 推理最强 |
| Claude Opus 4 | 200K | 15.0 | 视觉最强 |
| DeepSeek V3.2 | 128K | 0.55 | 性价比之王 |
| Gemini 2.5 Pro | 1M | 5.0 | 长上下文 + 视觉好 |

### 5.3 我们的推荐分工（成本最优）

```
Planner:    Claude Sonnet 4.5（每题 1~2 次调用，但要稳）
Executor:   DeepSeek V3.2 / Qwen3-Coder（10~16 次调用，要便宜）
Verifier:   Claude Sonnet 4.5 or GPT-5-mini（每步 1 次，必须准）
Vision:     Claude Opus 4 / GPT-5（仅 Phase 2）
```

下一份 → [`03-open-source-agents.md`](./03-open-source-agents.md)
