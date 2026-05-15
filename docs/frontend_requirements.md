# Data-Agent Web 前端需求文档

> 目标：为 `data-agent-baseline` 提供一个单页 Web 控制台，支持选择/上传任务 → 配置模型 → 触发执行 → **实时**观察推理日志和 DAG 演化 → 查看产物 → 跳转到现有的架构与论文文档。
> 后端契约见 `docs/backend_requirements.md`，本文档不重复字段定义，只描述前端的视觉与交互。
>
> **本文档已根据后端实现（`src/data_agent_baseline/web/`）逐字段对齐**。如发现冲突，以后端 OpenAPI（启动后 `GET http://localhost:8000/openapi.json` 或 `/docs` Swagger UI）为准。

---

## 1. 技术选型（建议）

| 项 | 选择 | 理由 |
| --- | --- | --- |
| 框架 | **React 18 + TypeScript** | 生态最成熟、与可视化库兼容性好 |
| 构建 | **Vite** | 启动快，开发体验好 |
| UI 库 | **Ant Design 5** 或 **shadcn/ui + Tailwind** | 自选，能快速搭出表单/表格/抽屉即可 |
| 状态管理 | **Zustand**（或 React Context） | 轻量；run 状态、WS 连接、配置都放一个 store |
| 路由 | **React Router v6** | SPA 多页 |
| HTTP | `fetch` + 简单封装；或 `axios` | 都行 |
| WebSocket | 原生 `WebSocket`，封装一个带自动重连 + `?from_seq` 续传的 hook | — |
| DAG 可视化 | **React Flow**（首选） / Cytoscape.js / D3 | React Flow 自带拖拽/缩放/小地图，开发成本最低 |
| 日志查看器 | **xterm.js** 或自实现 `<pre>` + 虚拟滚动（`react-window`） | 必须支持长日志（10w+ 行）不卡 |
| 代码/CSV 预览 | **Monaco Editor** + `papaparse` | 预览上传的 csv / json |
| 包管理 | `pnpm` | — |

> 后端是 FastAPI，监听 `http://localhost:8000`（可被 `DABENCH_WEB_PORT` 覆盖）。前端开发期通过 Vite `server.proxy` 把 `/api`、`/static` **以及 WebSocket** 都反代过去：
>
> ```ts
> // vite.config.ts
> server: {
>   proxy: {
>     '/api':    { target: 'http://localhost:8000', changeOrigin: true, ws: true }, // ws: true 关键
>     '/static': { target: 'http://localhost:8000', changeOrigin: true },
>   },
> }
> ```
>
> 生产期前后端同源部署，由前端构建产物 `dist/` 由后端 `StaticFiles` 直接托管，或前置 nginx 同时代理 `/api` + `/static` + 前端静态资源。

---

## 2. 信息架构与路由

```
/                     首页：欢迎 + 入口卡片（开始新任务 / 历史 run / 文档）
/tasks                内置任务库：表格 + 搜索 + 详情侧栏
/upload               上传任务：表单 + 拖拽区
/runs                 历史 run 列表：表格 + 状态筛选
/runs/:runId          Run 详情：左侧日志，右侧 DAG，底部产物面板（核心页）
/settings             API 配置：默认 model / api_base / api_key 持久化到 localStorage
/docs/architecture    iframe 嵌入 /static/docs/agent_architecture_summary.html
/docs/papers          iframe 嵌入 /static/docs/data-agent/html/index.html
```

顶部导航（始终可见）：`Tasks | Upload | Runs | Docs ▾ | Settings`，右上角显示当前选中的 model 与 base_url（缩略 + tooltip）。

---

## 3. 核心页面详细设计

### 3.1 `/tasks` — 内置任务库

- **左侧主区**：任务表格，列：`task_id | difficulty | question(前 80 字截断) | context_files 数 | 操作(查看 / 运行)`
- **顶部筛选**：`difficulty` 下拉（all / easy / medium / hard） + 关键词搜索框（前端本地过滤足够，后端也支持）
- **右侧抽屉**（点击行打开）：完整 question、context 文件树（可点击预览 csv/json/db schema）、按钮 `Run with current settings`
- **数据源**：`GET /api/tasks` / `GET /api/tasks/{task_id}` / `GET /api/tasks/{task_id}/context/{path}`

### 3.2 `/upload` — 用户自定义任务

- 表单字段（必须用 `multipart/form-data`，字段名要与后端一致）：

  | UI 标签 | form 字段名 | 必填 | 约束 |
  | --- | --- | --- | --- |
  | Task ID | `task_id` | 否 | 留空则后端生成 `task_upload_<UTC时间戳>`；非空时必须匹配 `[A-Za-z0-9_]{1,64}`，不以 `task_` 开头时后端会自动加前缀 |
  | Difficulty | `difficulty` | 否 | 默认 `custom`，下拉选项：easy/medium/hard/custom |
  | Question / Task description | `question` | 是 | 至少 1 字符；多行文本框；支持 Markdown 预览 |
  | Context files | `files` | 是 | 至少 1 个；可多文件；**拖拽上传区**支持文件夹拖拽，浏览器需保留相对路径（用 `webkitdirectory` 或 `File.webkitRelativePath`）|

- 提交：`POST /api/uploads` → **201 Created**，body 形如 `{upload_id, task: TaskBrief}` → 跳到任务详情抽屉，支持立即点 `Run`
- 校验（必须**前端先校验**再提交，避免 415/413 才发现）：
  - 扩展名白名单：`csv, tsv, json, jsonl, xlsx, xls, parquet, db, sqlite, sqlite3, txt, md`（后端可配；前端硬编码该 7 个 + 5 个变体即可）
  - 单文件 ≤ **200 MB**（后端 `max_upload_file_bytes`）
  - 单次上传总量 ≤ **1 GB**（后端 `max_upload_total_bytes`）
  - 文件名禁止 `..` 和绝对路径前缀，浏览器拖拽保留 `webkitRelativePath` 时也要剔除前导 `/`
- 错误处理（后端响应体统一 `{"detail": {"code": "...", "message": "..."}}`）：
  - 415 `unsupported_file_type` → 红字标在该文件行
  - 413 `file_too_large` → 红字标 message
  - 400 `invalid_payload` → 表单字段级红字
- 删除上传：`DELETE /api/uploads/{upload_id}` → **204 No Content**。**注意**：后端当前不会校验该 upload 是否被某个 active run 引用，前端在删除前需自行二次确认。

### 3.3 「Run 配置弹层」 — 任意 `Run` 按钮触发

弹一个 Modal，预填 `GET /api/config/defaults`（响应字段见下表）+ `localStorage` 中保存的覆盖值：

**`GET /api/config/defaults` 响应**（后端真实字段）：

```json
{
  "model": "qwen3.5-35b-a3b",
  "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key_set": true,            // ← 后端是否已配置默认 key；绝不返回 key 本身
  "max_steps": 500,
  "temperature": 0.0,
  "task_timeout_seconds": 0,
  "vote_rounds": 1,
  "max_concurrent_runs": 2
}
```

**Modal 字段**：

| 字段 | 控件 | 约束 / 备注 |
| --- | --- | --- |
| `model` | Input | 默认值取 `defaults.model` |
| `api_base` | Input | 默认值取 `defaults.api_base` |
| `api_key` | Input.Password（带眼睛切换） | 当 `api_key_set === true` 时显示灰色 placeholder "使用服务端默认 key（可覆盖）"；用户输入则覆盖。**`localStorage` 加密前提示用户**（见 §6 安全） |
| `max_steps` | InputNumber，1-1000 | 默认 `defaults.max_steps` |
| `temperature` | Slider 0.0-2.0 | 默认 `defaults.temperature` |
| `task_timeout_seconds` | InputNumber，0=不超时 | 默认 `defaults.task_timeout_seconds` |
| `vote_rounds` | Radio 1/2/3 | 默认 `defaults.vote_rounds`（后端校验 [1, 3]） |
| `Save as default` | Checkbox | 勾选则写回 `localStorage` |

提交：`POST /api/runs` → **202 Accepted**，body 即 `RunSummary`（`status` 多半为 `queued` 或已经 `running`），拿到 `run_id` → 跳到 `/runs/:runId`。

**请求体**：

```json
{
  "source": "builtin",      // builtin | upload
  "task_id": "task_180",
  "upload_id": null,        // source=upload 时必填
  "agent_overrides": {      // 任何字段未设置（或 null）则用服务端默认
    "model": "...",
    "api_base": "...",
    "api_key": "...",       // 用户没填且 api_key_set=false 时，会被后端 400 拒绝
    "max_steps": 500,
    "temperature": 0.0,
    "task_timeout_seconds": 0,
    "vote_rounds": 1
  }
}
```

**常见错误响应**（统一 `{"detail": {"code", "message"}}`）：

| HTTP | code | 触发条件 | UI 处理 |
| --- | --- | --- | --- |
| 400 | `invalid_payload` | `api_key` 既没传也没在服务端配置；或字段越界 | 弹错误条 + 高亮 api_key 输入框 |
| 404 | `task_not_found` | builtin task 不存在 | toast |
| 404 | `upload_not_found` | upload_id 不存在 | toast |

### 3.4 `/runs/:runId` — Run 详情（**核心**）

布局（桌面优先，宽度 < 1280px 改为上下布局）：

```
+----------------------------------------------------------------------+
| Header: task_id · difficulty · question (折叠) · status badge ·       |
|         elapsed timer · [Cancel] [Re-run] [Open dag.svg] [Download…] |
+-------------------------------+--------------------------------------+
| 左：Reasoning Log (40% 宽)    | 右：DAG Live View (60% 宽)           |
|                               |                                      |
|  - 顶部工具条：                | - React Flow 画布                    |
|    [Auto-scroll] [Pause]      |   - 节点：圆角矩形，显示 node_id +    |
|    [Filter level ▾]           |     goal(截断) + status 颜色          |
|    [Search box]               |     · pending  灰                    |
|    [Download .log]            |     · running  蓝（呼吸动画）        |
|                               |     · done     绿                    |
|  - 虚拟滚动列表，每行：        |     · failed   红                    |
|    [HH:MM:SS] [LEVEL] [src]   |   - 节点点击 → 右侧弹出 detail panel |
|    full message (无截断)       |     展示 goal / output_summary /     |
|    若是 step 事件，行尾出现   |     suggested_tools / 关联 step      |
|    可展开按钮 → 弹出 step      | - 工具条：[Fit] [Reset zoom]         |
|    详情（thought/action/      |     [Layout: TB | LR] [小地图开关]    |
|    observation 完整 JSON）     | - 多轮投票时顶部出现 round tabs:     |
|                               |     [Round 1 ✓ | Round 2 ▶ | …]      |
+-------------------------------+--------------------------------------+
| 底部产物面板（可折叠）：                                              |
|   Tabs: [Prediction CSV] [Trace JSON] [DAG SVG] [Raw agent.log]      |
|     - Prediction：表格预览（papaparse） + Download                    |
|     - Trace：Monaco JSON 视图 + 折叠                                  |
|     - DAG SVG：直接 <object data=".../dag.svg">                       |
|     - Raw log：iframe 或外部窗口打开 /api/runs/{id}/files/agent.log    |
+----------------------------------------------------------------------+
```

#### 实时数据流（详见后端 §6）

页面进入即建立 WS。同源部署时用相对路径 + 自动协议升级：

```ts
const wsScheme = location.protocol === 'https:' ? 'wss' : 'ws';
// 注意：续传必须传 lastSeq + 1，因为后端按 seq >= from_seq 回放，
// 直接传 lastSeq 会导致客户端再次收到最后一条事件。
const fromSeqParam = lastSeq > 0 ? `?from_seq=${lastSeq + 1}` : '';
const ws = new WebSocket(
  `${wsScheme}://${location.host}/api/runs/${runId}/stream${fromSeqParam}`,
);
```

**WS 关闭码**：

| code | 含义 | 前端动作 |
| --- | --- | --- |
| `1000` | 正常关闭（run 已 final） | 不重连，保留页面状态 |
| `1011` | 服务端内部错误 | toast + 5 次指数退避重连 |
| `4404` | run_id 不存在（连接前被拒） | 跳回 `/runs` 列表 + toast |

**事件协议**（每条消息 JSON 对象，含 `type` + `seq`）：

| event.type | seq 规则 | 前端动作 |
| --- | --- | --- |
| `snapshot` | **固定 `seq = 0`**，每个 client 连接后立即收到一次（不参与 `from_seq` 续传） | 用 `log_tail`（已切片重组好的字符串数组）一次性灌满日志列表；用 `dag` 初始化 React Flow 节点/边；用 `run` 更新 header 状态 |
| `log` | seq ≥ 1 单调递增 | 长行已被后端按 64 KiB 切片，**必须**按 `line_id` 重组后再追加；若 `Auto-scroll` 开启则滚到底 |
| `step` | seq ≥ 1 单调递增 | 在对应日志行旁出现「展开 step」标记；step 详情同步推送给 DAG 节点的 detail panel |
| `dag_update` | seq ≥ 1 单调递增 | **全量替换** React Flow 节点/边（后端总是发完整快照）；用 `updated_node_ids` 给这些节点加一个 1s 高亮动画 |
| `final` | seq ≥ 1 单调递增 | 状态 badge 更新为终态；停止本地状态机（不要主动 close，等服务端 close 1000）；自动刷新底部产物面板 |
| `error` | seq ≥ 1 单调递增 | toast 红色提示，badge 变 failed |
| ~~`vote_round`~~ | — | **后端当前未实现**。多轮投票（`vote_rounds > 1`）的 round 切换目前只能从日志行中间接观察。前端 round tabs 可以按 `defaults.vote_rounds` + `dag_update` 中节点 id 复用情况推断；后端如需也实现，请追加到 backend §6.2。 |

**WS 消息形状（关键字段，后端真实输出）**：

```ts
type Snapshot = {
  type: 'snapshot'; seq: 0;
  run: RunSummary;
  dag: DagSnapshot;            // 见 §3.4 末尾 DAG 字段
  log_tail: string[];          // 已重组好的完整行；> 1 MiB 时仅取最后 1 MiB，
                               // 首行加 sentinel "[snapshot truncated to last 1 MiB; ...]"
                               // 前端检测到该首行时应给个 "Load full log" 按钮拉
                               // /api/runs/{id}/files/agent.log 拿全量
};

type LogChunk = {
  type: 'log'; seq: number; ts: string;
  line_id: number;             // 同一行的所有 chunk 共享同一个 line_id
  chunk_index: number;         // 0-based
  chunk_total: number;         // chunk_total === 1 即短行无需重组
  line: string;                // 注意是按 byte 切片后再 utf-8 decode 的，
                               // 跨多字节字符可能用 U+FFFD 占位符替代——重组
                               // 后再做一次 normalize 即可还原
};

type StepEvent = {
  type: 'step'; seq: number;
  step_index: number | null;   // 任一字段都可能为 null（trace.json 字段缺省）
  thought: string | null;
  action: string | null;       // 例如 "__plan__" / "mark_node_done" / 其他工具名
  action_input: unknown;       // 任意 JSON
  observation: unknown;        // 任意 JSON
  raw_response: string | null;
  elapsed_ms: number | null;
};

type DagUpdate = {
  type: 'dag_update'; seq: number;
  nodes: DagNode[];
  edges: { from: string; to: string }[];   // 注意字段名 from / to（后端用 alias）
  final_node_id: string | null;
  updated_node_ids: string[];               // 仅用于动画高亮
};

type FinalEvent = {
  type: 'final'; seq: number;
  run: RunSummary;             // status 必为 succeeded/failed/cancelled/timeout
};
```

**关键非功能要求**：

1. **日志无截断**：
   - 单行可能 > 1 MiB（被后端切片成 64 KiB chunk），前端必须按 `line_id + chunk_index/chunk_total` 重组后再渲染；
   - 渲染层用虚拟列表（`react-window` 的 `VariableSizeList`），保证 10w+ 行不掉帧；
   - 严禁在 UI 上对超长行加 `...`；要么折叠（默认收起，点击展开），要么允许横向滚动；
   - snapshot 的 `log_tail` 已被服务端重组为完整行字符串数组（不需要再做 chunk 重组）。
2. **断线自动重连**：5 次指数退避；恢复时带上 `?from_seq=<lastSeq+1>`（**不是** `lastSeq`，避免重复最后一条）。后端 ring buffer 容量约 50000 条事件——若客户端断线时间过长，**首条收到的 `seq` 可能 > `lastSeq+1`**，前端检测到 gap 应当主动 `ws.close()` 并重新进入页面以触发新一轮 snapshot 灌满。
3. **Auto-scroll 智能停**：用户手动滚动离开底部时自动暂停 auto-scroll，回到底部时自动恢复。
4. **取消按钮**：点击 → 二次确认 → `POST /api/runs/{id}/cancel` 返回 **200 + 当前 RunSummary**；后端会立刻通过 WS 广播 `final{status: cancelled}`；按钮 loading 直到收到该 final 事件。

### 3.5 `/runs` — 历史 run

数据源：`GET /api/runs?limit=50&status=running`（`limit` 范围 [1, 500]，`status` 可选 `queued/running/succeeded/failed/cancelled/timeout`）。

表格列：`run_id | task_id | source | status | started_at | duration_ms | actions`，状态用彩色 Tag。
注意 RunSummary 中**没有** `model` 字段（model 信息在 `run_meta.json` 里，目前不被任何 GET 接口返回）。如需在列表里显示 model，请补一个 `GET /api/runs/{run_id}/meta` 接口或在前端 Settings 页统一显示当前默认 model。

`prediction_csv_url` / `trace_url` / `dag_svg_url` / `log_url` 这四个字段**只有在文件落盘后才非 null**（后端在 `as_summary()` 里对每个文件都做了 `.exists()` 判断），所以前端展示"下载"按钮时按 URL 是否为 null 来判断 disable。

点击行进入 `/runs/:runId`。

### 3.6 `/settings` — 默认配置

把 §3.3 的字段做成持久表单，保存到 `localStorage` 的 `dabench.web.defaults` 键。
顶部红色 Banner 提醒：**API Key 仅存于本浏览器；如使用公共电脑请勿勾选 Save as default**。

### 3.7 `/docs/architecture` 与 `/docs/papers`

两条独立路由，每条页面：

```tsx
<iframe
  src="/static/docs/agent_architecture_summary.html"
  className="w-full h-[calc(100vh-56px)] border-0"
  title="Agent Architecture"
  referrerPolicy="no-referrer"
/>
```

第二条同理指向 `/static/docs/data-agent/html/index.html`（注意是子目录 `data-agent/html/`，由后端 `StaticFiles(directory="docs", html=True)` 自动解析索引）。

顶部导航 `Docs ▾` 下拉两项：
- `Agent Architecture` → `/docs/architecture`
- `Research Papers`    → `/docs/papers`
- 额外提供 `Open in new tab` 图标，直接 `window.open(staticUrl, '_blank')`。

**额外可用的静态资源**（后端已挂载，可按需直接 `<img>` 或链接）：
- `/static/docs/agent-workflow.svg` —— 整体工作流图
- `/static/docs/agengt_architecture.md`、`/static/docs/rule.md` 等 markdown 源文件（`html=True` 模式下浏览器会按文本下载，可用第三方 markdown 渲染或仅作下载链接）

---

## 4. 组件清单

| 组件 | 职责 |
| --- | --- |
| `<AppShell>` | 顶部导航 + 路由出口 + 全局 toast |
| `<TaskTable>` | 任务列表（内置 + 搜索 + 详情抽屉） |
| `<TaskDetailDrawer>` | 任务详情：question / context tree / Run 按钮 |
| `<UploadForm>` | 拖拽上传 + 字段表单 |
| `<RunConfigModal>` | Run 触发弹窗（model/api_base/api_key/...） |
| `<RunHeader>` | run 元信息 + 计时器 + 操作按钮 |
| `<LogPanel>` | 虚拟滚动日志 + 工具条 + 长行 chunk 重组 |
| `<DagFlow>` | React Flow 画布 + 节点状态着色 + 高亮动画 |
| `<DagNodeDetail>` | 节点详情 side panel |
| `<ArtifactsPanel>` | 底部产物 tabs（CSV / JSON / SVG / log） |
| `<DocsIframePage>` | 通用文档 iframe 容器 |
| `useRunStream(runId)` | WS 连接 + 自动重连 + 事件分发 hook |
| `useDagSnapshot()` | DAG 状态归一化 + diff（避免每次 dag_update 全量重渲染抖动） |

---

## 5. 状态管理（Zustand 草案）

```ts
type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timeout';

type DefaultsStore = {
  // 完整 AgentOverrides；空字符串表示沿用后端默认（不要发送到后端）
  defaults: Partial<AgentOverrides>;
  setDefaults: (next: Partial<AgentOverrides>) => void;
  rememberApiKey: boolean;       // 仅 true 时把 api_key 写入 localStorage
};

type RunStreamStore = {
  runId: string | null;
  status: RunStatus;
  logLines: LogLine[];           // 长行已按 line_id 重组完毕
  pendingChunks: Map<number, LogChunk[]>;   // line_id → 尚未集齐的 chunk
  dag: DagSnapshot | null;
  steps: StepEvent[];
  lastSeq: number;               // 已成功处理的最大 seq；snapshot=0 不计
  paused: boolean;
  // 注意：voteRound 字段后端目前不发送，移除避免误导。
  // 若未来后端补 vote_round 事件，再加回 { current, total }。
};
```

**长行重组器关键逻辑（必须独立单测）**：

```ts
function ingestLogChunk(store: RunStreamStore, chunk: LogChunk): LogLine | null {
  if (chunk.chunk_total === 1) {
    return { line_id: chunk.line_id, ts: chunk.ts, text: chunk.line };
  }
  const buf = store.pendingChunks.get(chunk.line_id) ?? [];
  buf[chunk.chunk_index] = chunk;
  store.pendingChunks.set(chunk.line_id, buf);
  // 集齐所有 chunk 后才输出整行
  if (buf.filter(Boolean).length === chunk.chunk_total) {
    const text = buf.map((c) => c.line).join('');
    store.pendingChunks.delete(chunk.line_id);
    return { line_id: chunk.line_id, ts: chunk.ts, text };
  }
  return null;
}
```

---

## 6. 安全 & 隐私

1. **API Key 存储**：默认仅放在内存（页面刷新丢失）；只有用户显式勾选 `Save as default` 才写 `localStorage`，并在 Settings 页可一键清除。
2. **传输**：生产环境必须 HTTPS + WSS；前端代码里**严禁** `console.log(apiKey)`。
3. **iframe 跳转**：嵌入的两个文档来自同源 `/static/`，无需 sandbox，但要给 `referrerpolicy="no-referrer"`。
4. **CORS**：开发期靠 Vite proxy；生产期前后端同源部署。

---

## 7. 视觉与交互细节

- 颜色与后端 `dag_visualizer.py` 的 `_FILL_BY_STATUS` **保持一致**，让 SVG 与动态 DAG 视觉对齐：
  - pending `#e0e0e0`、in_progress `#64b5f6`、done `#81c784`、failed `#e57373`
- 字体：日志区强制等宽（`ui-monospace, SFMono-Regular, "JetBrains Mono", monospace`），字号 12-13px。
- 暗色模式：日志查看器和 Monaco 默认暗色；DAG 画布跟随系统。
- 国际化：MVP 仅中文 + 英文双语 placeholder，文案集中到 `src/locales/{zh,en}.ts`。
- 无障碍：所有按钮带 `aria-label`；状态颜色额外配图标，避免色盲不可识别。

---

## 8. 性能预算

| 项 | 预算 |
| --- | --- |
| 首屏 JS（gzip） | ≤ 350 KB |
| `/runs/:runId` 进入到首条日志可见 | ≤ 800 ms（不含 LLM 耗时） |
| 日志列表 100k 行滚动 | 60 fps |
| DAG 50 节点重排 | < 100 ms |

---

## 9. 测试

- **单元（Vitest）**：长行 chunk 重组器、WS 续传 hook、DAG diff
- **E2E（Playwright）**：
  1. 选择内置 task → 触发 run → 看到日志流 + DAG 节点由 pending → done → 出现 prediction.csv 预览
  2. 上传一个最小 csv + question → 触发 run → 同上
  3. 点击导航 `Docs → Agent Architecture` 能正确加载 iframe
  4. WS 断开后自动重连且 `from_seq` 生效（用 mock 后端）

---

## 10. 交付物

- [ ] `web/`（前端工程根目录，与 `src/` 同级），Vite + React + TS 模板
- [ ] 上述 7 类页面 + 12 类组件
- [ ] `web/README.md`：开发 / 构建 / 与后端联调指南
- [ ] 构建产物 `web/dist/` 由后端 `StaticFiles` 挂到 `/`（生产）
- [ ] Playwright E2E 4 条用例

---

## 11. 实施阶段建议

> 后端已经把 WebSocket 全套（snapshot + log + step + dag_update + final）实现并测试通过，所以前端 MVP 可以**直接上 WS**，不再走"先轮询 agent.log"的过渡方案。

**MVP（先打通主流程）**

1. `/tasks` 列表 + Run 配置弹窗
2. `/upload` 基本上传
3. `/runs/:runId` 核心页：**WS snapshot + log/step/final**（DAG 部分先用占位，仅显示节点列表也行）
4. `/docs/*` iframe 跳转

**Iter 2（DAG 可视化与体验）**

5. React Flow 动态 DAG（`dag_update` 全量替换 + `updated_node_ids` 高亮动画）
6. 长行 chunk 重组器 + 虚拟列表
7. 历史 run 列表 + 取消 / 重跑
8. 断线 `from_seq+1` 续传 + ring buffer 跌出处理（重新 snapshot）

**Iter 3（打磨）**

9. 暗色模式、i18n、无障碍
10. E2E 全量
11. 性能调优至 §8 预算
12. （可选）`vote_round` round tabs —— **依赖后端先补该事件**

---

## 12. 后端联调 Quick Start（前端开发者必读）

```bash
# 1. 在后端目录启动 FastAPI（默认 8000 端口）
cd /path/to/data-agent
uv pip install --python .venv/bin/python -e ".[web]"
DABENCH_WEB_PORT=8000 .venv/bin/python -m data_agent_baseline.web.app
# 或 .venv/bin/dabench-web

# 2. 验证关键接口
curl http://localhost:8000/api/health                  # → {"ok":true,"version":"..."}
curl http://localhost:8000/api/config/defaults         # → 默认 model/api_base/api_key_set
curl 'http://localhost:8000/api/tasks?keyword=patient' # → TaskBrief[]
open http://localhost:8000/docs                        # FastAPI Swagger UI（强烈建议联调时常开）
open http://localhost:8000/openapi.json                # 可直接喂给 openapi-typescript 生成 TS 类型

# 3. 前端项目里跑 Vite，确认 proxy 工作
pnpm dev
# 浏览器 DevTools Network 应当能看到 /api/* 走 proxy；
# WS 选 ws://localhost:5173/api/runs/<id>/stream，开发者工具 → 网络 → WS 抓帧确认
```

**强烈建议**用 `openapi-typescript` 直接从 `http://localhost:8000/openapi.json` 生成所有 DTO 类型（`TaskBrief / AgentOverrides / RunSummary / DefaultsResponse / CreateRunRequest`），避免手抄字段名带来的 typo。WS 事件类型由于不在 OpenAPI 里，需要按本文档 §3.4 末尾的 `Snapshot/LogChunk/StepEvent/DagUpdate/FinalEvent` 手写。
