# 01 · Competition Analysis · KDD Cup 2026 Data Agents 全维度解读

> 数据来源：[官网 dataagent.top](https://dataagent.top/)、[Starter-kit GitHub](https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit)、官方推文

---

## 1. 主办方与背景

| 维度 | 内容 |
|---|---|
| 比赛名称 | **KDD Cup 2026 — Data Agents for Complex Data Analysis** |
| 主办方 | **港科大（广州）数据智能与分析实验室 DIAL** + **清华大学数据库组** |
| 历史地位 | **首次由中国高校完全主导的 KDD Cup 重磅赛道** |
| 配套会议 | KDD 2026（济州岛，2026-08-09 ~ 13） |
| 官网 | https://dataagent.top/ |
| Discord | https://discord.com/invite/7eFwJQN3Fx |
| Starter-kit | https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit |
| 微信公众号 | 数据智能与分析实验室 DIAL |

### 1.1 组委会（关键人物）

- **General Chair · 李国良**（清华，ACM Fellow / IEEE Fellow / 国家杰青）—— Text-to-SQL、AI for DB 领域奠基级学者
- **General Chair · 骆昱宇**（HKUST-GZ）—— OpenManus / DeepEye / Alpha-SQL / AFlow 主要负责人，Forbes 30U30，World AI Conf Yunfan Award 2025
- **General Chair · 汤南**（HKUST-GZ）—— ACM Distinguished Member，VLDB Best Paper, SIGMOD 2024 Research Highlight
- **General Chair · 李伯岩**（HKUST-GZ 博士）—— DeepEye 项目负责人，DeepEye-SQL（SIGMOD 2026）一作

> **关键启示**：组委会全员深耕 Text-to-SQL / Data Agent / AI4DB，他们对优秀方案的"审美"已经写在了他们自家的开源项目里。详见 `[03-open-source-agents.md]`。

## 2. 赛题：DataAgent-Bench

### 2.1 任务核心定义

每个 task 是一个**自包含的数据分析挑战**，Agent 收到：

1. **一份高层级业务问题**（如"找出本季度销售额超预算 20% 的地区，并分析驱动因素"）
2. **一个异构数据包**（context/ 目录下的多源数据）

需要 Agent **自主完成**：
- 任务理解 → 子任务分解 → 工具选择 → 跨源推理 → 结果综合 → 输出最终答案

### 2.2 数据形态（Phase 1）

每条 task 目录结构（见 starter-kit）：

```
data/public/input/task_<id>/
├── task.json          # {task_id, difficulty, question}
└── context/
    ├── *.csv          # 结构化表格
    ├── *.json         # 半结构化数据 / 配置文件
    ├── *.sqlite/.db   # 关系数据库
    └── *.md / *.txt   # 非结构化文档（手册、报告）
```

> **Phase 1 模态**：CSV + JSON + SQLite + Markdown/Text
> **Phase 2 Leaderboard 子赛道追加**：图像（chart）+ 视频

### 2.3 任务难度（4 级）

> 难度区分维度：**模态数量 × 干扰项规模**

| 难度 | 特征 | 应对策略 |
|---|---|---|
| **Easy** | 单一/双模态，少量干扰文件 | Baseline ReAct 即可 |
| **Medium** | 3 模态以上，需要跨源 join | 需要良好的 schema linking |
| **Hard** | 多模态 + 多干扰 + 嵌套约束 | 需要显式 Planner + Verifier |
| **Extreme** | 全模态 + 长链条推理 + 隐含规则需从文档抽取 | 需要 Planner + Verifier + TTC + Reflexion |

### 2.4 推理模式（官方明确提到）

**非线性多步推理**，包含：
- **顺序链（Sequential）** — A → B → C
- **分支与合并（Branch & Merge）** — 多源并行计算后合并
- **迭代循环（Iterative）** — 看到中间结果后调整下一步

> **关键 Insight**：这意味着**单一线性 ReAct 不够**，必须要有 DAG 级别的规划能力（参考 Data Interpreter / DS-STAR）。

### 2.5 一个具体 Extreme 难度题示例（官方公开示例）

> **背景**：复盘 Q3 业绩，找出销售额超预算 20% 的地区，并分析驱动因素

**数据迷宫**：
- `sales_transactions.sqlite` —— 数百万原始交易，无业务逻辑
- `region_mapping.json` —— 地区代码 ↔ 业务区域映射
- `Company_Ops_Manual.md` —— 含 **预算目标计算公式**（必须读出来）
- `Market_Report_Q3.md` —— 各地区**宏观政策定性描述**（驱动因素分析的关键线索）

**Agent 必须做的"侦探式"推理**：
1. 知识对齐：从 Manual 学公式，从 mapping 学 ID
2. 多源整合：执行复杂 SQL，按公式过滤地区
3. 深度归因：结合 Market Report 做自动化归因

**这一题完美展示了 4 个能力要求**：
- 文档语义理解（Manual + Report）
- Schema linking（SQLite ↔ JSON mapping）
- 复杂 SQL 执行
- 跨模态推理 + 结果综合

## 3. Baseline & 工具集

Starter-kit 提供的 ReAct Baseline 配置：

```yaml
agent:
  model: <你的模型>
  api_base: <OpenAI-Compatible URL>
  max_steps: 16          # 关键参数
  temperature: 0.0
run:
  max_workers: 4         # 并行度
  task_timeout_seconds: 600  # 单题 10 分钟
```

**官方 8 个内置工具**：

| 工具 | 用途 | 输入 |
|---|---|---|
| `list_context` | 列 context/ 文件 | max_depth |
| `read_csv` | CSV 预览 | path, max_rows |
| `read_json` | JSON 预览 | path, max_chars |
| `read_doc` | 文本预览 | path, max_chars |
| `inspect_sqlite_schema` | 看 SQLite 表结构 | path |
| `execute_context_sql` | 执行只读 SQL | path, sql, limit |
| `execute_python` | 执行 Python | code |
| `answer` | 终止并提交答案 | columns, rows |

> **观察**：
> 1. 工具粒度合理，**已经有 `execute_python`，等于给了 CodeAct 能力**
> 2. SQL 是只读，不用担心副作用
> 3. **`answer` 是终止信号**，意味着进入 `answer` 后再无机会修正 → **必须在 answer 前加自验证**
> 4. **没有 vision tool** → Phase 2 需要自己加

## 4. 输出与评测

### 4.1 单 task 输出

```
artifacts/runs/<run_id>/<task_id>/
├── trace.json       # 完整执行轨迹（用于复现 + 离线分析）
└── prediction.csv   # 最终答案表格
```

### 4.2 评测指标（官方未完全公开，根据 starter-kit 与同类基准推断）

- **公开 demo 数据集** ground truth 在 `data/public/output/task_<id>/gold.csv`
- **隐藏测试集**仅有 `input/`，提交后服务端比对 `prediction.csv` vs `gold.csv`
- 比对方式（推断，参考 DABstep / DA-Code 惯例）：
 - **Exact Match on cells**：列名 + 行集合一致
 - 数值 tolerance（小数点）
 - 可能有 partial credit（部分列对）

> ⚠️ **强烈建议**：早期写好**自己的 evaluator**（参考 starter-kit 的 `summary.json` 字段），不要等官方榜单。

### 4.3 提交方式（基于 starter-kit）

入口命令：`uv run dabench run-benchmark --config <yaml>`

提交物推断：
- 整个项目代码 + config（含 baseline agent + 自定义 tools）
- Docker 镜像或 uv lock，使评测端可复现
- 隐藏测试集只跑 input/

## 5. 赛制：双阶段 + 双子赛道

### Phase 1（公榜单赛道）2026-04-24 ~ 05-23

- 全球队伍统一公榜竞技
- 自动化评估排名
- 考察基础能力 + 算法效率

### Phase 2（晋级队伍）2026-05-28 ~ 06-30

**Leaderboard 子赛道**（追准确率）
- 引入新模态：**图像、视频**
- 任务难度大幅提升
- 继续刷榜

**Creative 子赛道**（系统设计美学）
- 强调**系统成熟度 + 用户体验 + 决策透明度**
- 鼓励**交互友好的 Data Agent 系统**
- 评审更主观，但**主办方亲自背书 OpenManus 风格**

> 我们的策略：Phase 1 全力刷榜；Phase 2 视排名决定主攻方向。

## 6. 时间线（AoE 时区）

```
03-22 ~ 04-23   报名（截止前完成）
04-24 ~ 05-23   Phase 1 公榜（30 天，主战场）
05-28 ~ 06-30   Phase 2（双子赛道，34 天）
08-09           KDD 2026 现场颁奖（济州岛）
```

> **当前时间 2026-04-23**：明天 Phase 1 开始，**今晚必须跑通 baseline**。

## 7. 奖励

| 项目 | 内容 |
|---|---|
| 奖金池 | **120,000 RMB** |
| 大厂 Offer | 表现优异团队可获 |
| KDD Workshop 演讲 | Top 队伍受邀 |
| 官方获奖证书 | 全员 |

## 8. 与历史 Data Agent 比赛/Benchmark 的对比

| 比赛/Benchmark | 数据规模 | 模态 | 难度 | 当前 SOTA |
|---|---|---|---|---|
| **InfiAgent-DABench** (ICML 2024) | 257 题 | 单 CSV | 中 | GPT-4 ~75% |
| **DA-Code** (EMNLP 2024) | 500 题 | CSV + Code | 难 | DA-Agent 30.5% |
| **DSBench** (ICLR 2025) | 540 题 (analysis 466 + modeling 74) | Excel + ML | 中-难 | best agent 34% |
| **Tapilot-Crossing** (NAACL 2024) | 1024 交互 | CSV + 多轮对话 | 中 | — |
| **DABstep** (Adyen+HF, 2025-06) | 450+ 题 | 异构金融数据 | 难 | DS-STAR 44.69%（学术）/ Energent.ai 94.4%（商用） |
| **Spider 2.0** (ICLR 2025 Oral) | 632 题 | 企业级 SQL workflow | 极难 | 大幅低于 Spider 1.0 |
| **MLE-Bench** (OpenAI, 2024-10) | 75 Kaggle 比赛 | 全栈 ML | 极难 | AIDE 16.9% medal |
| **🆕 DataAgent-Bench (KDD Cup 2026)** | 未公开 | CSV+JSON+SQLite+MD（+ Phase2 图像/视频） | 4 级 | **待你定义** |

**结论**：DataAgent-Bench 与 **DABstep 最接近**（异构 + 多步 + 真实业务），同时融合了 DA-Code 的代码生成 + Spider 2.0 的复杂 schema。

## 9. 我们能从主办方哪些工作里"窥视设计意图"？

| 主办方工作 | 启示 |
|---|---|
| [**Data Agents Survey** (SIGMOD 2026)](https://arxiv.org/abs/2602.04261) | 骆昱宇 + 李国良 + 汤南合著，定义了"Data Agent 的等级分类"——比赛是这个分类法的实证 |
| [**Data Interpreter** (ACL 2025 Findings)](https://arxiv.org/html/2402.18679v1) | 骆昱宇是合著者；Hierarchical Graph Plan 是其核心创新；**赛题任务的"非线性推理"几乎就是为这个设计而设的** |
| [**OpenManus**](https://github.com/FoundationAgents/OpenManus) | 骆昱宇是合著者；Phase 2 Creative 子赛道几乎"鼓励"用 OpenManus 风格 |
| [**AFlow** (ICLR 2025 Oral)](https://github.com/FoundationAgents/AFlow) | 骆昱宇是合著者；MCTS workflow 优化，Phase 2 想冲分必看 |
| [**Alpha-SQL** (ICML 2025)](https://github.com/HKUSTDial/Alpha-SQL) | DIAL 自家；Zero-Shot Text-to-SQL + MCTS，**SQLite 子任务的最优解** |
| [**DeepEye-SQL** (SIGMOD 2026)](https://luoyuyu.vip/) | DIAL 自家；BIRD 榜单 Top 5；Software-Engineering-Inspired |

> 总结：**主办方期望的 SOTA 解 = OpenManus 框架 + Data Interpreter 规划 + Alpha-SQL/DeepEye-SQL 的 SQL 模块 + AFlow 的 workflow 优化**。

下一份 → [`02-academic-research.md`](./02-academic-research.md)
