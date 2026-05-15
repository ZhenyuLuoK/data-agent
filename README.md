# Data-Agent Baseline

KDD Cup 2026 **DataAgent-Bench** 的 ReAct 风格 baseline，基于 LangGraph + LangChain，
对单个数据分析任务（含 CSV / Excel / SQLite / Parquet 等多模态数据）自动完成
「读数据 → 规划 → 多步推理 → 写代码 → 输出 prediction.csv」全流程。

仓库同时提供两种使用形态：

| 形态 | 入口 | 适用场景 |
|---|---|---|
| **CLI Agent** (`dabench`) | `dabench run-benchmark` / `run-task` | 批量评测、提交镜像、CI |
| **Web Console** (`dabench-web`) | `http://localhost:8000` | 交互式调试、单任务跑、上传自有数据 |

---

## 📂 项目结构

```
data-agent/
├── src/data_agent_baseline/   # Python 主代码（agents / tools / run / web）
├── web/                       # React + Vite 前端（Web Console UI）
├── configs/                   # YAML 配置（local / docker / submit / example）
├── docs/                      # 设计文档 / 架构图 / 论文摘要
├── data/                      # 本地数据集（已 gitignore）
├── artifacts/                 # 运行产物（已 gitignore）
├── Dockerfile                 # data-agent-web 一体化镜像（前后端）
├── Dockerfile.submit.bak      # KDD Cup 评测提交用镜像（仅 CLI）
├── entrypoint.web.sh          # Web 镜像入口
└── pyproject.toml             # 依赖声明（含可选 [web] / [dev] 组）
```

> **API Key 安全约定**：`configs/react_baseline.local.yaml` 是本地配置，**包含真实 key**，已被
> `.gitignore` + `.dockerignore` 双重排除，永远不会进入 git 提交或 Docker 镜像。

---

## 1. 本地 Agent 运行（CLI）

### 1.1 环境准备

```bash
# Python 3.10+；推荐使用 uv
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'        # 仅 CLI
# 或者
uv pip install -e '.[dev,web]'    # 同时装 Web Console 依赖
```

也可以用 pip：
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,web]'
```

### 1.2 准备数据集

把 KDD Cup 公开数据集解压到：
```
data/public/input/task_<id>/...
```

### 1.3 配置 API Key

复制示例配置并填入你的 key：
```bash
cp configs/react_baseline.example.yaml configs/react_baseline.local.yaml
# 编辑 configs/react_baseline.local.yaml，填 model / api_base / api_key
```

### 1.4 运行

```bash
# 跑全量 benchmark
dabench run-benchmark --config configs/react_baseline.local.yaml

# 跑单个 task
dabench run-task <task_id> --config configs/react_baseline.local.yaml

# 评分
dabench score --runs-dir artifacts/runs/<run_id>
```

产物：`artifacts/runs/<run_id>/task_<id>/`
- `prediction.csv` —— 评测答案
- `agent.log` —— 完整 ReAct 轨迹
- `trace.json` —— 结构化执行日志
- `dag.svg` —— 任务 DAG 可视化

---

## 2. Agent 评测镜像构建（KDD Cup 提交用）

KDD Cup 评测平台需要一个**仅含 CLI、不含 Web** 的最小镜像，平台运行时挂载 `/input`、
`/output`，并通过 `MODEL_NAME / MODEL_API_URL / MODEL_API_KEY` 环境变量注入 key。

对应 Dockerfile：`Dockerfile.submit.bak`（如需启用，重命名为 `Dockerfile`）。

### 2.1 构建

```bash
# 评测机为 x86_64，必须强制 amd64
docker build --platform linux/amd64 \
  -t team1408:v2 \
  -f Dockerfile.submit.bak .
```

### 2.2 本地试跑

```bash
docker run --rm --platform linux/amd64 \
  --name team1408 \
  --cpus=10 --memory=5g \
  -v "$(pwd)/data/public/input:/input:ro" \
  -v "$(pwd)/artifacts/docker-out:/output" \
  -e MODEL_NAME="qwen3.5-35b-a3b" \
  -e MODEL_API_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e MODEL_API_KEY="${DEV_MODEL_API_KEY}" \
  team1408:v2 \
  2>&1 | tee artifacts/docker-out/run.log
```

### 2.3 提交

```bash
docker save team1408:v2 | gzip > submission.tar.gz
# 把 submission.tar.gz 上传到评测平台
```

> 详细约定参见 `Dockerfile.submit.bak` 顶部注释和 `entrypoint.sh`（含 5 秒同步
> `/output/<run_id>/task_*/prediction.csv → /output/task_*/prediction.csv` 的兜底机制）。

---

## 3. Data-Agent Web 本地运行

Web Console 提供：任务浏览 / 数据上传 / 单任务运行 / 实时 ReAct 流 / DAG 可视化 / 历史对比。

### 3.1 后端

```bash
# 装 web 可选依赖
uv pip install -e '.[web]'

# 启动 FastAPI（默认 :8000）
dabench-web
# 或开启热重载
DABENCH_WEB_RELOAD=1 dabench-web
```

后端关键环境变量：
| 变量 | 默认 | 说明 |
|---|---|---|
| `DABENCH_WEB_HOST` | `0.0.0.0` | 监听地址 |
| `DABENCH_WEB_PORT` | `8000` | 监听端口 |
| `DABENCH_WEB_BASE_CONFIG` | `configs/react_baseline.local.yaml` | 默认 AppConfig |
| `DABENCH_WEB_DATASET_ROOT` | `data/public/input` | builtin task 数据根 |
| `DABENCH_WEB_DIST_ROOT` | `web/dist` | 前端构建产物（生产模式用） |

### 3.2 前端（开发模式）

```bash
cd web
pnpm install
pnpm dev          # 开 vite dev server，:5173，自动代理 /api → :8000
```

浏览器打开 `http://localhost:5173`。

### 3.3 前端（生产模式 / 单服务一体化）

```bash
cd web && pnpm build   # 生成 web/dist
# 回到根目录启动后端，会自动托管 web/dist
dabench-web
```

浏览器打开 `http://localhost:8000`，前后端由同一进程提供。

---

## 4. Data-Agent Web Docker 构建与运行

一体化镜像（Node 构建前端 + Python 跑后端，**镜像内不含任何 API key**），用户在浏览器
Settings 页填入 key 即可使用。

### 4.1 构建

```bash
docker build -t data-agent-web:latest -f Dockerfile .
```

镜像组成：
- **Stage 1 (frontend)**：`node:22-bookworm-slim` + `pnpm@9.15.0` → `pnpm build` 出 `web/dist`
- **Stage 2 (backend)** ：`python:3.11-slim` + `pip install '.[web]'`
- 产出体积：~1.9 GB（解压）/ ~460 MB（压缩）

安全保证（双保险）：
1. **构建时**：`.dockerignore` 显式排除 `configs/react_baseline.local.yaml`、`*.local.yaml`、`.env*`
2. **运行时**：默认 base config 是 `react_baseline.docker.yaml`（key 留空），后端 `runs.py` 强制
   校验「overrides 或 base 至少一个非空 api_key」，前端不填则 `400` 拒绝创建 run

### 4.2 运行

```bash
docker run --rm -p 8000:8000 --name data-agent-web data-agent-web:latest
```

浏览器打开 `http://localhost:8000`：
1. 点 **Settings** → 填 `model` / `api_base` / `api_key`（勾选「记住」存到 localStorage）→ Save
2. 回 **Tasks** 或 **Upload** 页 → 选任务 → 点 **Run**
3. 实时观察 ReAct 步骤 + DAG 演化 + 日志流

### 4.3 持久化产物 / 自带数据集（可选）

```bash
docker run --rm -p 8000:8000 \
  -v $(pwd)/artifacts:/app/artifacts \
  -v $(pwd)/data/public/input:/app/data/public/input:ro \
  --name data-agent-web \
  data-agent-web:latest
```

### 4.4 导出与分发

```bash
# 导出为 tar
docker save data-agent-web:latest | gzip > data-agent-web.tar.gz

# 对方加载并启动
gunzip -c data-agent-web.tar.gz | docker load
docker run --rm -p 8000:8000 data-agent-web:latest
```

跨平台构建（给 x86 机器跑 arm 上构建的镜像）：
```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t data-agent-web:latest --load .
```

---

## 📚 进一步阅读

- 架构总览：`docs/agengt_architecture.md` / `docs/agent_architecture_summary.html`
- 工作流图：`docs/agent-workflow.svg`
- 后端 API 契约：`docs/backend_requirements.md`
- 前端设计：`docs/frontend_requirements.md`
- 评测规则：`docs/rule.md`
- Case 示例：`docs/example/`

---

## 🛠 常见问题

**Q: 运行 `dabench-web` 报 `ModuleNotFoundError: No module named 'fastapi'`？**
→ Web 依赖是可选组，需 `pip install -e '.[web]'`。

**Q: Docker 镜像构建时前端 `pnpm install` 失败 (`ERR_UNKNOWN_BUILTIN_MODULE`)？**
→ Dockerfile 已 pin `pnpm@9.15.0`，对应 `pnpm-lock.yaml` v9.0；如自行改 Node 版本需同步调整。

**Q: 浏览器创建 run 提示 `api_key is required`？**
→ 这是预期行为：镜像不含 key，请去 Settings 页填入后再 Run。

**Q: 怎么确认镜像里没有真实 key？**
```bash
docker run --rm --entrypoint sh data-agent-web:latest \
  -c "grep -RnE 'sk-[A-Za-z0-9]{20,}' /app/configs /app/src 2>/dev/null \
       || echo 'OK: no real key found'"
```
## 📚 相关文档

- [项目主要代码 src/data_agent_baseline/agents/langgraph_agent.py]
- [相关文献 docs/data-agent/]
- [agent 架构 docs/agengt_architecture.md, docs/agent_architecture_summary.html]
- [工作流程 docs/agent-workflow.svg]
- [case 示例 docs/example]
- [直接运行 需要APIkey config/react_baseline.local.yaml]
---

**注意：** 请根据实际项目结构调整上述配置和命令。