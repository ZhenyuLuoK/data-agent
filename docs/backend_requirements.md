# Data-Agent Web 后端需求文档

> 目标：在不破坏现有 `dabench` CLI / Docker 评测路径的前提下，提供一个轻量的 HTTP + WebSocket 服务，封装 `data_agent_baseline` 内部的 agent 执行能力，给前端使用。

---

## 1. 背景与定位

当前项目 `data-agent-baseline` 是 KDD Cup 2026 DataAgent-Bench 的参赛 baseline：

- 任务定义：`data/public/input/task_<id>/{task.json, context/...}`
- 入口：`dabench run-task <task_id> --config <yaml>` / `dabench run-benchmark --config <yaml>`
- Python 入口：`data_agent_baseline.run.runner.run_single_task(task_id, config, run_output_dir)`
- 产物：`artifacts/runs/<run_id>/task_<id>/{prediction.csv, trace.json, dag.svg, agent.log}`
- 配置：`configs/react_baseline.local.yaml`（`agent.model / agent.api_base / agent.api_key / agent.max_steps / agent.temperature / dataset.root_path / run.output_dir / run.task_timeout_seconds / run.vote_rounds`）

后端的职责，是把上述能力包装成 **可以被浏览器消费的 HTTP/WebSocket 接口**，并且：

1. 既能选择已有的 `task_<id>`（来自 `data/public/input/`），也能由用户**自行上传 task description + context 文件**临时构造一个 ad-hoc task；
2. **实时**把 agent 推理过程（`agent.log` 的每一行 + `trace.json` 的每一个 step）推给前端，**不允许截断**；
3. **实时**把 DAG 的演化过程（plan 节点 / 节点状态变更）推给前端，供前端做动态图渲染；
4. 允许前端**临时覆盖** `model / api_base / api_key`，无需修改 YAML 配置；
5. 提供静态资源代理，使前端能直接跳转到 `docs/agent_architecture_summary.html` 与 `docs/data-agent/html/index.html`。

---

## 2. 技术选型（建议，非强制）

- 语言/框架：**Python 3.10+ + FastAPI + Uvicorn**（与项目同语言，可直接 `import data_agent_baseline.*`，避免再起一层进程间协议）
- 实时通道：**WebSocket**（一个 run 对应一条连接，承载日志流 + DAG 增量事件）；备选 SSE
- 任务调度：**asyncio + ThreadPoolExecutor**（单机；agent 本身是 CPU/IO 混合阻塞型，必须放线程池跑，不能阻塞事件循环）
- 进程隔离：复用 `runner._run_single_task_with_timeout` 已有的 `multiprocessing` 超时机制，不重复造轮子
- 文件存储：直接落到 `artifacts/runs/<run_id>/task_<id>/`，与 CLI 完全一致；**ad-hoc 任务**落到 `artifacts/uploads/<upload_id>/task_<id>/` 作为输入根目录
- 项目布局：在 `src/data_agent_baseline/web/` 下新增一个子包，`pyproject.toml` 增加 `[project.scripts] dabench-web = "data_agent_baseline.web.app:main"`，**不污染** CLI / Docker 入口

---

## 3. 目录与产物约定

```
artifacts/
  runs/
    <run_id>/
      task_<id>/
        prediction.csv      # 已有：最终预测
        trace.json          # 已有：完整推理轨迹（含 DAG 快照、每个 step 的 action/observation）
        dag.svg             # 已有：dag_visualizer 渲染的静态 SVG
        agent.log           # 已有：行式结构化日志（必须无截断地实时透传到前端）
        run_meta.json       # 【新增】后端写入：run_id / task_id / source(builtin|upload) /
                            # agent_overrides / status(queued|running|succeeded|failed|cancelled|timeout) /
                            # started_at / finished_at / duration_ms / failure_reason
  uploads/
    <upload_id>/
      task_<id>/
        task.json           # {task_id, difficulty, question}，由后端根据用户输入生成
        context/            # 用户上传的 csv/db/json/... 原样落盘
```

**run_id 生成规则**：复用 `runner.create_run_id()`（UTC 时间戳 `YYYYMMDDTHHMMSSZ`）。后端必须保证同一时刻发起的多个 run 不会撞 id（必要时追加 `-<rand4>`）。

---

## 4. 数据模型（DTO）

> JSON 字段命名统一 `snake_case`，时间戳统一 ISO 8601 UTC（`2026-05-08T14:19:17Z`）。

### 4.1 TaskBrief（任务摘要）

```json
{
  "task_id": "task_180",
  "difficulty": "easy",
  "question": "For patients with severe degree of thrombosis, ...",
  "source": "builtin",                // builtin | upload
  "context_files": [
    {"path": "db/transactions_1k.db", "kind": "sqlite", "size": 102400},
    {"path": "csv/yearmonth.csv",     "kind": "csv",    "size": 8732012}
  ]
}
```

### 4.2 AgentOverrides（前端可选覆盖）

```json
{
  "model":   "qwen3.5-35b-a3b",                                    // 必填（可由后端默认值兜底）
  "api_base":"https://dashscope.aliyuncs.com/compatible-mode/v1",  // 必填
  "api_key": "sk-xxxx",                                            // 必填，后端**禁止**记入日志/落盘
  "max_steps":   500,                                              // 选填
  "temperature": 0.0,                                              // 选填
  "task_timeout_seconds": 0,                                       // 选填，0 表示不超时
  "vote_rounds": 1                                                 // 选填，[1,3]
}
```

### 4.3 RunSummary

```json
{
  "run_id": "20260508T141917Z",
  "task_id": "task_180",
  "source": "builtin",
  "status": "running",                  // queued | running | succeeded | failed | cancelled | timeout
  "started_at": "2026-05-08T14:19:17Z",
  "finished_at": null,
  "duration_ms": null,
  "prediction_csv_url": null,           // /api/runs/{run_id}/files/prediction.csv，结束时才有
  "trace_url":          "/api/runs/20260508T141917Z/files/trace.json",
  "dag_svg_url":        "/api/runs/20260508T141917Z/files/dag.svg",
  "log_url":            "/api/runs/20260508T141917Z/files/agent.log",
  "failure_reason": null
}
```

---

## 5. REST 接口

> 统一前缀 `/api`。错误返回 `{"error": {"code": "...", "message": "..."}}`，HTTP 状态码遵循 RFC 7807 风格。

### 5.1 元信息

| Method | Path | 描述 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查，返回 `{"ok": true, "version": "..."}` |
| GET | `/api/config/defaults` | 返回当前后端默认 `AgentOverrides`（**绝不**返回 `api_key` 明文，仅返回 `api_key_set: bool`） |

### 5.2 内置任务

| Method | Path | 描述 |
| --- | --- | --- |
| GET | `/api/tasks` | 列出 `data/public/input/` 下所有 `task_<id>`，支持 `?difficulty=easy|medium|hard&keyword=xxx` 过滤；返回 `TaskBrief[]` |
| GET | `/api/tasks/{task_id}` | 单个任务详情（含 `context_files` 树，复用 `tools.filesystem.list_context_tree`） |
| GET | `/api/tasks/{task_id}/context/{path:path}` | 下载 / 预览 context 内的某个文件（仅允许在 `context/` 子树内，必须做路径穿越校验） |

### 5.3 用户上传任务

| Method | Path | 描述 |
| --- | --- | --- |
| POST | `/api/uploads` | `multipart/form-data`：`question`（str，必填）、`difficulty`（str，可选，默认 `custom`）、`task_id`（str，可选，默认 `task_upload_<ts>`）、`files[]`（多文件，原样落到 `context/<原相对路径>`，必须保留目录结构）。返回 `{upload_id, task: TaskBrief}` |
| GET | `/api/uploads/{upload_id}` | 同 `TaskBrief`，`source=upload` |
| DELETE | `/api/uploads/{upload_id}` | 删除上传目录（仅未被 active run 引用时允许） |

**安全约束**：
- 单文件 ≤ 200 MB，单次上传总量 ≤ 1 GB（可配置）
- 文件名做 `werkzeug.secure_filename` 风格清洗，**绝对禁止** 路径中出现 `..`
- 仅允许扩展名白名单：`csv, tsv, json, jsonl, xlsx, xls, parquet, db, sqlite, sqlite3, txt, md`（可配置）

### 5.4 触发执行

| Method | Path | 描述 |
| --- | --- | --- |
| POST | `/api/runs` | 创建一个 run，请求体见下；返回 `RunSummary`（`status=queued`） |
| GET | `/api/runs` | 列出最近 N 个 run（`?limit=50&status=running`），按 `started_at` 倒序 |
| GET | `/api/runs/{run_id}` | 单个 run 详情 |
| POST | `/api/runs/{run_id}/cancel` | 取消正在执行的 run（向 worker 发送终止信号；底层走 `multiprocessing.Process.terminate`） |
| GET | `/api/runs/{run_id}/files/{name}` | 下载产物文件（`prediction.csv` / `trace.json` / `dag.svg` / `agent.log`） |

**POST `/api/runs` 请求体**：

```json
{
  "source": "builtin",          // builtin | upload
  "task_id": "task_180",        // builtin 时来自 /api/tasks，upload 时来自 /api/uploads/{upload_id}.task.task_id
  "upload_id": null,            // upload 时必填
  "agent_overrides": { ... }    // 见 4.2，未传字段使用后端默认
}
```

**实现要点**：
1. 依据 `source` 决定 `dataset.root_path`：builtin → `data/public/input`；upload → `artifacts/uploads/<upload_id>`。
2. 内存里构造一个 `AppConfig`（不要写临时 yaml 文件，直接 `dataclasses.replace(load_app_config(default), agent=..., dataset=..., run=...)`）。
3. 调 `runner.create_run_output_dir(...)` 拿到 `run_output_dir`，写 `run_meta.json`。
4. 把 `runner.run_single_task(task_id, config, run_output_dir)` 丢线程池执行。

---

## 6. 实时通道（WebSocket）

### 6.1 路径

```
WS  /api/runs/{run_id}/stream
```

握手成功后服务端立即推送一条 `snapshot` 事件（包含截至当前的所有日志行 + 当前 DAG 快照），随后持续推送增量事件，直到 run 进入终态再推送一条 `final` 事件并由服务端主动关闭连接。

### 6.2 事件协议

每条消息一个 JSON 对象，必含 `type` 与 `seq`（全局单调递增 int，便于前端断线重连后用 `?from_seq=N` 续传）。

| type | 触发 | payload 关键字段 |
| --- | --- | --- |
| `snapshot` | 连接建立 | `{run: RunSummary, dag: DagSnapshot, log_tail: string[]}`，`log_tail` 必须是**完整未截断**的全部历史行 |
| `log` | `agent.log` 新增一行 | `{line: string, ts: string}`；**严禁**截断；多行合一行下发也允许，但每行原文必须完整 |
| `step` | `trace.json` 新增一个 step | `{step_index, thought, action, action_input, observation, raw_response, elapsed_ms}`，字段直接透传 |
| `dag_update` | DAG 节点新增 / 状态变更 | `{nodes: DagNode[], edges: DagEdge[], updated_node_ids: string[]}`，发增量也发完整快照（前端按完整快照覆盖即可） |
| `vote_round` | 多轮投票（`vote_rounds > 1`）切换 round | `{round: int, total_rounds: int}` |
| `final` | run 结束 | `{run: RunSummary}`，之后服务端关闭连接 |
| `error` | 不可恢复错误 | `{code, message}` |

**`DagSnapshot` 结构**（前端动态图直接渲染，无需再读 SVG）：

```json
{
  "nodes": [
    {"id": "n1", "goal": "...", "depends_on": [],     "suggested_tools": ["execute_context_sql"],
     "expected_output": "...", "status": "done",      "started_at": "...", "finished_at": "...",
     "output_summary": "Found 153 unique CustomerIDs ..."}
  ],
  "edges": [{"from": "n1", "to": "n2"}],
  "final_node_id": "n2"
}
```

> `nodes/edges/status` 全部可以从现有 `trace.json` 的 `steps[].observation.content.dag` + `mark_node_done` 工具调用中推导出来，无需改动 agent 内核。

### 6.3 数据来源（实现方案）

后端有 **两条数据源**，二选一或并行：

1. **文件 tail（推荐，零侵入）**
   - 用 `watchdog` / 自实现 `aiofiles` 轮询 `agent.log`，逐行推 `log` 事件；
   - 用同样方式监听 `trace.json` 的写入（`runner` 在每个 step 后 flush），diff 出新增 step → 推 `step` + `dag_update`；
   - 优点：完全不动 agent 代码；缺点：trace.json 每次全量重写时要做差分。

2. **In-process callback（可选，未来优化）**
   - 在 `LangGraphAgent` 内增加 `on_step` / `on_dag_change` 回调钩子，由 web 层注入；
   - 优点：零延迟、零差分；缺点：需要改 `langgraph_agent.py`，与 CLI 路径分叉。

> **MVP 必须实现方案 1**，方案 2 视性能再做。

### 6.4 日志无截断保证（硬性要求）

- WebSocket 消息体不得超过 **1 MiB**：单行日志超过该阈值时，按 64 KiB 切片发送，每片携带 `chunk_index/chunk_total/line_id`，前端按 `line_id` 重组；**绝对不允许**用 `…` / `truncated` 之类的省略；
- 服务端必须设置 `WS_MAX_MESSAGE_SIZE >= 16 MiB`，并禁用任何中间代理（nginx）的 buffering（文档中给出 nginx `proxy_buffering off; proxy_read_timeout 1d;` 配置示例）；
- 对 `GET /api/runs/{run_id}/files/agent.log` 必须支持 `Range` 请求和 `text/plain; charset=utf-8`，前端兜底拉取完整日志。

---

## 7. 静态资源跳转

后端必须挂载以下静态路径，让前端直接 `<a target="_blank" href="...">` 打开即可：

| URL | 实际文件 |
| --- | --- |
| `/static/docs/agent_architecture_summary.html` | `docs/agent_architecture_summary.html` |
| `/static/docs/data-agent/html/index.html` 及其同目录下所有相对资源 | `docs/data-agent/html/*` |
| `/static/docs/agent-workflow.svg` | `docs/agent-workflow.svg`（可选，方便前端引用） |

实现：FastAPI `StaticFiles(directory="docs", html=True)` 挂到 `/static/docs/`，`html=True` 让 `index.html` 自动解析。

---

## 8. 配置与启动

### 8.1 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DABENCH_WEB_HOST` | `0.0.0.0` | 监听地址 |
| `DABENCH_WEB_PORT` | `8000` | 监听端口 |
| `DABENCH_WEB_BASE_CONFIG` | `configs/react_baseline.local.yaml` | 默认 `AppConfig` 来源 |
| `DABENCH_WEB_DATASET_ROOT` | `data/public/input` | 内置任务根目录 |
| `DABENCH_WEB_RUN_ROOT` | `artifacts/runs` | run 产物根目录 |
| `DABENCH_WEB_UPLOAD_ROOT` | `artifacts/uploads` | 上传目录 |
| `DABENCH_WEB_MAX_CONCURRENT_RUNS` | `2` | 同时运行的 agent 数上限（与 `run.max_workers` 解耦） |
| `DABENCH_WEB_CORS_ORIGINS` | `*` | 逗号分隔，前端独立部署时收紧 |
| `MODEL_NAME` / `MODEL_API_URL` / `MODEL_API_KEY` | — | 与 CLI 一致，作为 `AgentOverrides` 的兜底默认 |

### 8.2 启动方式

```bash
# 开发
uv run dabench-web --reload

# 生产
uv run uvicorn data_agent_baseline.web.app:app --host 0.0.0.0 --port 8000 --workers 1
```

> 必须 `--workers 1`：内部用线程池 + 内存中的 run 注册表，多 worker 会出现 run 跨进程不可见的问题。横向扩展走前置网关 + 多实例 + 独立 run_id 命名空间，超出 MVP。

---

## 9. 安全

1. **API Key 不落盘、不入日志**：
   - `agent_overrides.api_key` 仅在内存里塞进 `AgentConfig`，run_meta.json 中只存 `api_key_fingerprint = sha256(api_key)[:8]`；
   - 全局 logging filter，过滤掉任何包含 `sk-` 前缀的字符串；
2. **路径穿越**：所有用户传入的路径（task_id / context path / upload filename）必须 `Path.resolve()` 后校验是否在允许根目录之内；
3. **上传限速**：单 IP 每分钟 ≤ 10 次 `POST /api/uploads`；
4. **CORS**：默认 `*` 仅用于本地联调，文档里强制写明生产环境必须收紧；
5. **认证**：MVP 不做；预留 `Authorization: Bearer <token>` 中间件接口（可被未来的简单 token 校验插上）。

---

## 10. 错误码与异常

| code | HTTP | 含义 |
| --- | --- | --- |
| `task_not_found` | 404 | builtin task_id 不存在 |
| `upload_not_found` | 404 | upload_id 不存在 |
| `run_not_found` | 404 | run_id 不存在 |
| `invalid_payload` | 400 | 请求体校验失败（pydantic 详情透传到 `message`） |
| `file_too_large` | 413 | 上传超限 |
| `unsupported_file_type` | 415 | 上传文件扩展名不在白名单 |
| `concurrency_exceeded` | 429 | 并发 run 数已达上限 |
| `agent_failed` | 500 | agent 运行抛异常（透传 `failure_reason`） |
| `agent_timeout` | 504 | 触发 `task_timeout_seconds` |

---

## 11. 测试

最低单元测试覆盖（放在 `tests/web/`）：

1. `tests/web/test_tasks_api.py`：列任务 / 详情 / context 文件下载 / 路径穿越拒绝
2. `tests/web/test_uploads_api.py`：合法上传 / 超大上传被拒 / 非法扩展名被拒 / 删除上传
3. `tests/web/test_runs_api.py`：用 `monkeypatch` 把 `run_single_task` 替换成一个写假 `agent.log` / `trace.json` 的 stub，验证：
   - run 状态机：`queued → running → succeeded`
   - 取消能进入 `cancelled`
   - 默认配置 + overrides 能正确合并到 `AppConfig`
4. `tests/web/test_ws_stream.py`：连接 WS → 收到 `snapshot` → stub 写入新行 → 收到对应 `log` / `step` / `dag_update` → 收到 `final` → 服务端主动关闭

---

## 12. 交付物清单

- [ ] `src/data_agent_baseline/web/`：`app.py`、`api/{tasks,uploads,runs,stream}.py`、`services/{run_manager,log_tailer,trace_watcher,dag_builder}.py`、`schemas.py`
- [ ] `pyproject.toml`：新增依赖 `fastapi`、`uvicorn[standard]`、`python-multipart`、`watchfiles`（或 `watchdog`）；新增脚本 `dabench-web`
- [ ] `tests/web/`：上述 4 类测试
- [ ] `docs/backend_requirements.md`（本文）+ `docs/openapi.json`（FastAPI 自动导出，启动后 `GET /openapi.json` 落盘即可）
- [ ] `README` 增补一节 "Web Server 启动方式"

---

## 13. 与现有路径的兼容性约束（不允许破坏的红线）

1. **不得修改** `entrypoint.sh`、`Dockerfile`、`configs/*.submit.yaml`、`runner.run_benchmark` 的对外签名 —— Docker 评测路径必须保持原样可跑；
2. **不得修改** `LangGraphAgent` 与 `dag_visualizer` 的对外行为 —— 即便方案 2（in-process callback）落地，回调注入也必须是可选的，缺省行为与现状逐字节一致；
3. **不得**让 web 层成为 `dabench` CLI 的依赖：CLI 在没有装 `fastapi` 的环境里仍然可用。
