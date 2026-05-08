# KDD Cup 2026 DataAgent-Bench 提交规则解读 & 当前项目打包指南

> 规则原文：<https://dataagent.top/rules>
> 适用项目：本仓库（`boost-agent` / `data-agent-baseline`）
> 文档目标：把当前仓库打包成一个**可以直接 `docker run` 跑通官方评测**的镜像，并按官方流程提交。
>
> ⚠️ 来源声明：官方页面是 SPA，本文规则部分通过 `r.jina.ai` 代理拉取的 Markdown 渲染版本得到，原文可见以下章节：
> `1 / 2.2 / 2.3 / 3.1 / 3.2 / 3.3 / 3.5 / 4.1 / 5.1 / 5.2 / 5.3 / 5.5 / 6.5 / 6.6 / 7 / 8 / 9`。
> 原文中 **2.1 / 3.4 / 5.4 / 6.1–6.4** 这几节在我能拿到的渲染版里跳号缺失，本文不复述未拿到的内容。
> 提交前请以 `dataagent.top/rules` 当时的最新版本为准（官方明确说明：本文档与官网其他描述冲突时以本文档最新版为准）。

---

## 一、官方对提交的硬性限制（违反 = 评测失败 / 0 分）

### 1. 提交形式（§3）
- **唯一形式**：Docker 镜像导出的 `tar.gz` 压缩包，通过 Google Drive 共享后，邮件提交到 `kddcup@hkust-gz.edu.cn`。
- 不接受源码 / notebook / 远程 endpoint / 其它任何形式。

### 2. 命名规范（§3.1，强制）
| 项目 | 格式 | 示例（team_id = team0042，第 3 次提交） |
| --- | --- | --- |
| 镜像 tag | `<team_id>:v<N>` | `team0042:v3` |
| 压缩包文件名 | `<team_id>_v<N>.tar.gz` | `team0042_v3.tar.gz` |
| 邮件主题 | `[KDDCup2026 Data Agents] Submission - <team_id> - v<N>` | `[KDDCup2026 Data Agents] Submission - team0042 - v3` |

- `team_id` 必须与组委会分配的完全一致（团队报名后由组委会发邮件分配，时间窗口：2026-04-21 ~ 2026-04-23 AoE）。
- `<N>` 从 1 开始，**不能复用**之前的版本号，每次提交必须递增。

### 3. 镜像内容（§3.2）
| 项 | 官方要求 |
| --- | --- |
| 基础镜像 | 不限 |
| 镜像架构 | 评测机为 **x86-64**（§4.1），镜像必须能在 amd64 上运行 |
| 压缩包大小 | `tar.gz` **≤ 10 GB** |
| 启动方式 | 必须设置 `ENTRYPOINT` 或 `CMD`，`docker run <image>` 能直接跑，**不允许追加任何参数** |
| 用户权限 | 允许 root，但**禁止修改 `/input`** |

### 4. I/O 约定（§2、§9 Q1）
- 输入：评测系统将数据集挂到 **`/input`**，结构 `/input/task_<id>/{task.json, context/}`。
- 输出：每个 task 的预测必须写到 **`/output/task_<id>/prediction.csv`**。
- **Agent 必须自己遍历 `/input` 下的所有 `task_<id>/`**（不会有人喂任务）。
- `context/` 子目录是**动态**的（可能有 `csv/`、`db/`、`json/`、`doc/`、`knowledge.md`），不要假设固定结构（§2.3、§9 Q6）。
- **缺少 `prediction.csv` 直接 0 分**（§6.6）。

### 5. 模型调用（§5，最容易违规）
评测时**只能**使用组委会统一部署的 Qwen3.5-35B-A3B（OpenAI Chat Completions 兼容）。注入的环境变量：

| 环境变量 | 含义 |
| --- | --- |
| `MODEL_API_URL` | 模型服务地址（注意官方用的字段名是 `MODEL_API_URL`，**不是 `MODEL_API_BASE`**） |
| `MODEL_API_KEY` | API key（运行时注入，事前拿不到） |
| `MODEL_NAME` | 固定值字符串 `qwen3.5-35b-a3b` |

硬性约束：
- **严禁在镜像 / 代码 / 配置里硬编码** 任何 API URL、API Key（§5.2、§8.1）。
- 容器内**不允许**跑非 Qwen3.5-35B-A3B 的 LLM 当主求解器（包括 CPU 本地推理）；embedding 等小型辅助模型在硬件预算内允许（§5.1、§8.2）。
- 服务端 vLLM 参数（§5.3）：`--max-model-len 262144`（256K context）、`--enable-auto-tool-choice`、`--tool-call-parser qwen3_coder`、`--reasoning-parser qwen3`。可以走标准 OpenAI tool calling。

### 6. 资源 & 网络（§4.1、§5.5）
| 项 | 限制 |
| --- | --- |
| CPU | 16 vCPU，x86-64 |
| 内存 | 64 GB（OOM → 整次评测作废） |
| GPU | **无** |
| 总运行时长 | 所有任务合计 ≤ **12 小时**，超时强杀；A 榜单次 ≤ **2 小时**（§7） |
| 外网 | **完全禁止**，只能访问 `MODEL_API_URL` |
| 内部其它服务 | 禁止 |
| 跨容器通信 | 禁止 |
| 对外端口 | 全部屏蔽 |

### 7. 提交频率（§7）
- 每天最多 1 次；Phase 1 总计 ≤ 30 次。
- 必须等上次评测出结果才能交下一次；每次都要**完整镜像**（不支持增量）。
- 题量参考：A 榜约 60 题，B 榜约 320 题。
- 关键日期：2026-04-30 ~ 2026-05-02（AoE，含）期间提交通道关闭做工作流迁移；最终提交截止 2026-05-20 EoD AoE；Phase 1 终榜 2026-05-25 EoD AoE。

### 8. 评分要点（§6.5、§6.6、§9 Q3-Q4）
- **列名不参与评分**，只比较各列的"值向量签名"，列名可以随便起。
- 多余列会扣分；缺列扣分更严重。
- 数值会用 `Decimal` 规范化到 **2 位小数**（`ROUND_HALF_UP`）。例：`4200000` → `"4200000.00"`，`0.005` → `"0.01"`。
- 字符串**区分大小写**，仅去首尾空白和 `\r\n`。
- `null/none/nan/nat/<NA>`（不区分大小写）统一当作空串。
- 日期统一 `YYYY-MM-DD`；带时区 datetime 转 UTC（`Z` 结尾）；不带时区保留原 ISO 格式。
- 姓名既可拆成两列也可合成一列。
- 注：原文 §6.1–§6.4（评分主体公式 / column_values 签名构造细节）我未拿到，建议提交前再去官网核对。

### 9. 禁止行为（§8 摘录，违者取消资格）
1. 试图访问外网，或绕过 `MODEL_API_URL` 调其它 LLM。
2. 在容器里跑非 Qwen3.5-35B-A3B 当主求解器（含 CPU 本地推理）。
3. 探测 / 攻击 / 容器逃逸。
4. 修改 `/input` 或破坏注入的环境变量。
5. 多团队共用同一 Docker 镜像，或换不同 team 名提交相同解法。
6. 通过非法手段获取测试集答案。
7. 人为干预评测过程。

---

## 二、当前项目对照检查（基于已读源码的事实，非猜测）

仓库相关文件：

```
Dockerfile                                  ✅ 存在
entrypoint.sh                               ✅ 存在
.dockerignore                               ✅ 已排除 .venv/.git/data/artifacts
configs/react_baseline.submit.yaml          ✅ 提交专用配置
src/data_agent_baseline/config.py           ← 配置加载 + 环境变量替换
src/data_agent_baseline/run/runner.py       ← 跑 benchmark + 落盘
src/data_agent_baseline/agents/model.py     ← OpenAI client 封装
docker-build.txt                            📝 已有本地构建/运行命令
```

### 已经满足官方要求的部分（事实）

1. **`Dockerfile`** 设了 `ENTRYPOINT ["/app/entrypoint.sh"]`，满足 §3.2「`docker run` 可直接跑」。
2. **`docker-build.txt`** 已用 `--platform linux/amd64`，满足 §4.1 架构要求（在 Apple Silicon 上构建必须保留这个 flag）。
3. **`.dockerignore`** 实际排除了：`.venv`、`.git`、`docs`、`data`、`artifacts`、`assets`、`__pycache__`、`*.pyc/.pyo`、`.DS_Store`、`.idea`、`.vscode`，并通过 `*.md` + `!README.md` 把所有 Markdown 文件（包括本 `rule.md`、`README.zh.md`）排除在 build context 之外，只保留 `README.md`。这从源头规避了"`rule.md`/`README.zh.md` 这类内部讨论被打进镜像"的合规风险。最终镜像是否 ≤ 10 GB 仍需以 `docker save | gzip | wc -c` 实测为准（见"清理项"）。
4. **`configs/react_baseline.submit.yaml`** 中 `dataset.root_path: /input`、`run.output_dir: /output`，**没有硬编码任何 API key 或 URL 字面量**，三个模型字段都使用 `${VAR:-default}` 形式从环境变量读取——形式上符合 §5.2 的硬性要求；但其中 `api_base` 用的是错误的变量名 `MODEL_API_BASE`，详见下面"风险 1"。
5. **`src/data_agent_baseline/config.py`** 第 12 行的 `_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")` 实现了 `${VAR}` 与 `${VAR:-default}` 替换；`load_app_config` 会对 `agent.model / api_base / api_key` 三个字段做替换。
6. **`src/data_agent_baseline/run/runner.py`** 中 `run_single_task` 在每个 task 跑完时立即调用 `_write_task_outputs`，把 `prediction.csv` 与 `trace.json` 写到 `run_output_dir/<task_id>/`。多 worker 模式下走 `ThreadPoolExecutor + as_completed`，**也是逐 task 落盘**，不是跑完才一次性写。
7. **`runner.py` 的 `_run_single_task_with_timeout`** 已经实现 task 级超时（用子进程 + `Process.terminate/kill`），对应 §4 提示「为每个 task 加超时保护」。

### ⚠️ 与官方规则冲突 / 风险点（基于源码事实定位）

下面每条都对应可定位的代码行，不是猜测。

#### 风险 1（**必修**）：环境变量名对不上 → 评测时 100% 调用失败
- **官方注入的是 `MODEL_API_URL`**（§3.5 / §5.2）。
- **当前 `configs/react_baseline.submit.yaml` 写的是** `${MODEL_API_BASE:-http://localhost:8000/v1}`。
- `config.py` 的 `_ENV_PATTERN` 只会查 `os.environ["MODEL_API_BASE"]`，评测机里这个变量根本不存在 → 回退到默认值 `http://localhost:8000/v1`。
- `OpenAIModelAdapter.complete` 会拿这个假地址去发请求；评测网络只放行 `MODEL_API_URL`，所以 100% 失败。
- 同时正则**只匹配大写字母 + 数字 + 下划线**；不支持嵌套已经实测确认：`${A:-${B:-x}}` 会被替换成字面量 `${B:-x}`（外层贪婪匹配吃到第一个 `}` 停止，内层不会递归展开）。这意味着任何"双层兜底"写法都会让 OpenAI client 拿到一个非法 URL。

**修法（推荐 A，确定性最高）：**

A. 直接把 yaml 字段改成读 `MODEL_API_URL`，并把所有默认值都改为**显眼的占位字符串**——这样如果评测机意外没注入对应变量，错误会立刻暴露而不是被吞掉（评测时官方明确会注入这三个变量，§3.5 / §5.2）：
```yaml
agent:
  model:    ${MODEL_NAME:-MODEL_NAME_NOT_SET}
  api_base: ${MODEL_API_URL:-http://MODEL_API_URL_NOT_SET.invalid}
  api_key:  ${MODEL_API_KEY:-}
```
本地调试时用 `-e MODEL_NAME=... -e MODEL_API_URL=... -e MODEL_API_KEY=...` 三个一起注入。注意**不要**把默认值写成评测时的真实模型名 `qwen3.5-35b-a3b`：那样一旦评测机没注入 `MODEL_NAME`，OpenAI client 会拿这个名字去请求一个根本不存在或权限不对的端点，错误难定位。

B. 如果你坚持本地脚本仍想用 `MODEL_API_BASE` 这个名字调试，则在 `entrypoint.sh` 顶部加映射 + fail-fast：
```bash
# 把官方注入的 MODEL_API_URL 映射成代码用的 MODEL_API_BASE
if [ -z "${MODEL_API_BASE:-}" ] && [ -n "${MODEL_API_URL:-}" ]; then
  export MODEL_API_BASE="${MODEL_API_URL}"
fi
# 两个都没设就直接退出，避免静默回退到 localhost:8000 浪费评测额度
if [ -z "${MODEL_API_BASE:-}" ]; then
  echo "[entrypoint] FATAL: neither MODEL_API_URL nor MODEL_API_BASE is set" >&2
  exit 64
fi
```
**注意不要写成** `${MODEL_API_BASE:-${MODEL_API_URL:-}}` 形式的嵌套兜底——这是 shell 语法没问题，但如果你想在 yaml 里这么写（指望 `_resolve_env` 处理），上面已经实测会失效。

#### 风险 2（**必修**）：超时被强杀 → 已完成的 prediction.csv 也丢
事实链：
- `runner.py:54` `create_run_output_dir(...)` → `run_output_dir = output_root / effective_run_id`，`effective_run_id` 在 `run_id` 留空时是 UTC 时间戳。
- 提交配置里 `output_dir: /output`、`run_id:` 留空 → 实际写到 **`/output/<UTC时间戳>/task_<id>/prediction.csv`**，**不是** 官方要的 `/output/task_<id>/prediction.csv`。
- `entrypoint.sh` 在 `dabench run-benchmark` **整体返回后**才执行 cp 把它们拍平到 `/output/task_<id>/`。
- §4.1 明确：12h 总时长到点容器**强杀**（`SIGKILL`）。一旦超时，`dabench run-benchmark` 不会正常返回，**entrypoint 后半段的 cp 循环不会被执行** → 即使前面已经落盘了一堆 `prediction.csv`，评测系统在 `/output/task_<id>/` 一个都看不到。

**修法（这是唯一推荐方案，已给完整可落地代码）：**

让 dabench 跑完一个 task 就立刻把 `prediction.csv` **同步到** `/output/task_<id>/prediction.csv`，不依赖 `dabench run-benchmark` 整体返回。具体实现：在 `entrypoint.sh` 启动 dabench **之前**起一个后台同步进程，每隔 5 秒扫一次最新 run 目录，发现新 `prediction.csv` 就用 `cp -n`（不覆盖已写入的）写到目标位置；dabench 退出后再做一次最终全量同步并杀掉后台进程。

完整 `entrypoint.sh` 替换为：

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /app

CONFIG_PATH="${CONFIG_PATH:-configs/react_baseline.submit.yaml}"

# ---- 环境变量校验（不打印 key 本身）----
echo "[entrypoint] python: $(python --version 2>&1)"
echo "[entrypoint] config: ${CONFIG_PATH}"
echo "[entrypoint] MODEL_NAME=${MODEL_NAME:-<unset>}"
if [ -n "${MODEL_API_URL:-}" ]; then echo "[entrypoint] MODEL_API_URL=<set>"; else echo "[entrypoint] MODEL_API_URL=<unset>"; fi
if [ -n "${MODEL_API_KEY:-}" ]; then echo "[entrypoint] MODEL_API_KEY=<set>"; else echo "[entrypoint] MODEL_API_KEY=<unset>"; fi
echo "[entrypoint] /input contents:" && ls -1 /input | head -20 || true

# ---- 后台同步：每 5s 把 /output/<run_id>/task_*/prediction.csv 拍平到 /output/task_*/prediction.csv ----
sync_predictions() {
  shopt -s nullglob
  for src in /output/*/task_*/prediction.csv; do
    task_id="$(basename "$(dirname "${src}")")"
    case "${task_id}" in task_*) ;; *) continue ;; esac
    dst_dir="/output/${task_id}"
    dst="${dst_dir}/prediction.csv"
    if [ ! -f "${dst}" ]; then
      mkdir -p "${dst_dir}"
      cp "${src}" "${dst}"
    fi
  done
}

(
  while true; do
    sync_predictions || true
    sleep 5
  done
) &
SYNC_PID=$!

# 无论正常/异常退出，都做一次最终同步并清理后台进程
cleanup() {
  sync_predictions || true
  if kill -0 "${SYNC_PID}" 2>/dev/null; then
    kill "${SYNC_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ---- 跑 benchmark ----
dabench run-benchmark --config "${CONFIG_PATH}" || RC=$?
RC="${RC:-0}"

# 兜底：脚本退出前 trap 会再做一次 sync_predictions
echo "[entrypoint] dabench exit code: ${RC}"
exit "${RC}"
```

为什么这个方案是"完整可落地"的：
- **不改 `runner.py` 源码**，避免引入新 bug。
- **每 5 秒扫一次**，即使评测系统在 12h 上限 `SIGKILL` 容器（`SIGKILL` 无法被 trap），最坏只丢 5 秒内刚写完但还没同步的那个 task，所有更早完成的 task 都已落到 `/output/task_<id>/`。
- 用 `cp` + `[ ! -f "${dst}" ]` 守卫，**不会覆盖**已经同步过去的文件，符合"先到先得，不丢已完成结果"。
- `trap cleanup EXIT INT TERM` 处理正常退出 / `Ctrl-C` / `SIGTERM`（评测系统在硬超时前若先发 `SIGTERM`，可以再多抢救一次同步；若直接 `SIGKILL` 则无法 trap，但因为有 5 秒轮询，影响可控）。

注意：本方案**不会**修改 `runner.py` 写出的原始时间戳目录结构（`/output/<UTC时间戳>/...`），只是**额外**在 `/output/task_<id>/` 下放一份。评测系统读 `/output/task_<id>/prediction.csv` 即可，时间戳目录的存在不会干扰评分（§3.2 也没禁止 `/output` 下有额外文件）。

#### 风险 3（**建议修**）：Dockerfile 在 build 期把 PyPI 镜像源固化到了运行期 ENV
`Dockerfile` 中：
```dockerfile
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
```
评测期容器无外网，不会真的去 pip install，所以**不会直接违规**；但万一镜像里有任何代码在 import 时触发 pip 子进程（极少见），会暴露"试图访问外网"的行为，违反 §5.5 / §8.1。建议安装完依赖后清掉：
```dockerfile
ENV PIP_INDEX_URL= \
    PIP_TRUSTED_HOST=
```

#### 风险 4（**已并入风险 2 的 entrypoint.sh**）：可观测性
上面给出的完整 `entrypoint.sh` 已经包含环境变量注入校验日志（不打印 key 本身），不再需要单独修。

#### 风险 5（**需自行验证**）：A 榜 2 小时 / B 榜 12 小时内能否跑完
当前 submit 配置：`max_workers: 4`、`task_timeout_seconds: 600`、`max_steps: 16`。
- 单 task 实际耗时取决于 LLM RTT、ReAct 步数、context 大小、`execute_python` 工具内部的 30s 超时（见 `src/data_agent_baseline/tools/registry.py:17` `EXECUTE_PYTHON_TIMEOUT_SECONDS = 30`），**这些都不能从静态代码估算**，必须实跑测量。
- 操作步骤（必须在本地真跑）：
  1. 用 demo 数据跑 `dabench run-benchmark --config configs/react_baseline.example.yaml`；
  2. 看 `artifacts/runs/<run_id>/summary.json` 里每个 task 的 `e2e_elapsed_seconds`（由 `runner.py:run_single_task` 写入），统计 P50/P95/Max；
  3. 按 `60题 × P95 / max_workers ≤ 7200s` 反推 `max_workers` 与 `task_timeout_seconds`。
- 内存方面真正的风险是 `_run_single_task_with_timeout` 给每个 task 起一个 `multiprocessing.Process` 子进程，子进程里用户代码 `execute_python` 工具会用 pandas/polars 加载 context 数据。worker 数 × 单题数据驻留内存才是 64 GB 上限的主要消耗源，需要自测；`ToolRegistry` / `OpenAIModelAdapter` 本身只是少量字典+函数引用，可忽略。

#### 不属于"必修"但提交前需要处理的清理项
- `Dockerfile.patch`：当前内容是 `FROM dabench-submit:latest` + 复制一份 yaml，**仅用于"在已有镜像之上贴新 config"的场景**，正式提交时**不要**用它构建（构建命令用 `Dockerfile`，不是 `Dockerfile.patch`）。
- `submission.tar.gz`（仓库根目录的 20 字节占位文件）和 `docker-build.txt`：会进入 build context（`.dockerignore` 当前没排除它们），但 `Dockerfile` 只显式 `COPY pyproject.toml uv.lock README.md ./`、`COPY src ./src`、`COPY configs/react_baseline.submit.yaml ...`、`COPY entrypoint.sh ...`，**不会**把这两个文件复制进最终镜像，对合规没有影响；如果想让 build context 更小，可以在 `.dockerignore` 里追加：
  ```
  submission.tar.gz
  docker-build.txt
  Dockerfile.patch
  ```
- 镜像体积：取决于具体依赖，**必须以本地 `docker save team_xxx_v1:vN | gzip | wc -c` 的实际输出为准**，不要凭感觉。规则上限是 10 GB（§3.2）。

---

## 三、把当前项目打包并提交的标准流程

> 假设组委会给你的 `team_id = team0042`，本次是第 1 次提交（`v1`）。
> 下面流程**默认你已经按"二、风险 1 / 风险 2"的修法改过 yaml 和 entrypoint**。

### Step 1：本地构建镜像（必须 amd64）
```bash
docker build --platform linux/amd64 \
  -t team0042:v1 \
  -f Dockerfile .
```

### Step 2：用"模拟评测机"的方式本地跑通
评测机不会给你 GPU，所以这里只限制 CPU 和内存。`MODEL_API_KEY` 必须是你**自己开发期**用的 key（dashscope / openai / 任何 OpenAI 兼容服务都行），评测机会用它自己的 key 覆盖。

先在当前 shell 里 export 你自己的 key（不要写进任何文件）：
```bash
export DEV_MODEL_API_KEY="sk-your-own-development-key"   # 仅本地调试用，绝不进镜像
```

再跑：
```bash
mkdir -p artifacts/docker-out
docker run --rm --platform linux/amd64 \
  --cpus=16 --memory=64g \
  -v "$(pwd)/data/public/input:/input:ro" \
  -v "$(pwd)/artifacts/docker-out:/output" \
  -e MODEL_NAME="qwen-max" \
  -e MODEL_API_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e MODEL_API_KEY="${DEV_MODEL_API_KEY}" \
  team0042:v1
```

如果你忘了 export，`OpenAIModelAdapter.complete` 会立即抛 `RuntimeError: Missing model API key in config.agent.api_key.`（见 `src/data_agent_baseline/agents/model.py:42`），属于预期行为。

验收标准（缺一不可）：
- 退出码 0；
- `artifacts/docker-out/task_*/prediction.csv` **直接位于顶层**（除此之外还会有一个 `artifacts/docker-out/<UTC时间戳>/...` 的原始 run 目录，这是 `runner.py` 的固有结构，不影响合规）；
- 日志开头能看到 `MODEL_API_URL=<set>`、`MODEL_API_KEY=<set>`；
- 验证 fail-fast：把 `-e MODEL_API_URL=...` 这一行从命令里去掉再跑一次，**预期**：
  - 如果你按"风险 1 修法 A" 改了 yaml（`api_base: ${MODEL_API_URL:-http://localhost:8000/v1}`），dabench 会拿默认的 `http://localhost:8000/v1` 去发请求，失败但不会 fail-fast——所以**还需要核对 dabench 日志里能看到对 `localhost:8000` 的失败请求**，这就是"环境变量没注入"的特征。
  - 如果你按"风险 1 修法 B" 在 entrypoint 里加了 fail-fast 分支，则容器会直接以 exit code 64 退出，更明显。
  - 推荐至少跑一次"故意不注入"的实验，确认本地行为符合预期，再做正式提交。

### Step 3：导出并压缩镜像
```bash
docker save team0042:v1 | gzip > team0042_v1.tar.gz
ls -lh team0042_v1.tar.gz   # 必须 ≤ 10 GB（§3.2）
```

### Step 4：上传 Google Drive
- 把 `team0042_v1.tar.gz` 上传到你 Google Drive 的任意位置。
- 在文件上右键 → **Share / 共享** → 把 "General access" 从 "Restricted" 改为 **"Anyone with the link"**，权限选 **"Viewer"** → 点 **"Copy link"** 拿到形如 `https://drive.google.com/file/d/<FILE_ID>/view?usp=sharing` 的链接（`<FILE_ID>` 是 Drive 自动生成的字符串，直接整条复制即可，不需要你手动抠）。
- 在评测期间不要删除 / 改名 / 移动这个文件，否则链接失效，整次提交作废（§3.3）。

### Step 5：发邮件提交（§3.3）
- 收件人：`kddcup@hkust-gz.edu.cn`
- 主题：`[KDDCup2026 Data Agents] Submission - team0042 - v1`
- 正文（把 `<...>` 全部替换为真实值）：
  ```
  Team ID: team0042
  Version: v1
  Sharing link: <把 Step 4 复制到的整条 Drive 链接粘到这里>
  ```
- 发送前自己用浏览器无痕模式打开一次 Sharing link，确认能看到下载按钮，再发邮件。

### Step 6：等评测结果
- 每天最多 1 次提交；必须等上次结果出来才能交下一次（§7）。
- Phase 1 总计 30 次额度，谨慎使用。

---

## 四、提交前自检清单

- [ ] `docker build --platform linux/amd64` 构建成功
- [ ] 镜像 tag = `<team_id>:v<N>`，`<N>` 与历史不重复
- [ ] yaml 中 `api_base` 读的是 `MODEL_API_URL`（或 entrypoint 已映射）
- [ ] 故意"不注入 `MODEL_API_URL`" 跑一次，确认日志里能定位到失败原因（修法 A 是请求 `localhost:8000` 失败；修法 B 是 entrypoint exit code 64）
- [ ] 仓库里 grep 不到任何真实 key / 外部 LLM URL：
  ```bash
  grep -RInE "sk-[A-Za-z0-9]{20,}|dashscope|api[_-]?key" \
       --exclude-dir=.git --exclude-dir=.venv --exclude-dir=artifacts .
  ```
- [ ] 用 demo 数据本地跑通后，`/output/task_*/prediction.csv` **直接在顶层**（不在时间戳子目录）
- [ ] 已在本地用 demo 数据 profile 过单 task 平均耗时，并据此设置 `max_workers` / `task_timeout_seconds`
- [ ] `docker save | gzip` 后 ≤ 10 GB
- [ ] 压缩包文件名 = `<team_id>_v<N>.tar.gz`
- [ ] Google Drive 链接 = "Anyone with the link, Viewer"
- [ ] 邮件主题 / Team ID / 版本号三处一致

---

## 五、本仓库需要立刻完成的最小改动（精确到文件）

按重要性排序，全部基于上面已核实的源码事实，每条都对应"二、风险点"小节里的完整代码：

1. **`configs/react_baseline.submit.yaml`** — 把 `api_base` 行改成 `${MODEL_API_URL:-http://localhost:8000/v1}`。  
   对应"风险 1 修法 A"。**必修**，否则评测时 100% 调用失败，浪费一次 30 中之 1 的提交额度。
2. **`entrypoint.sh`** — 整体替换为"风险 2 修法"中给出的完整脚本（带后台同步 + trap 兜底 + 环境变量校验日志）。  
   对应"风险 2 + 风险 4"。**必修**，否则一旦评测超时被强杀，所有已完成的 `prediction.csv` 都不会出现在 `/output/task_<id>/`。
3. **`Dockerfile`** — 在 `RUN pip install ...` 之后追加一行：
   ```dockerfile
   ENV PIP_INDEX_URL= \
       PIP_TRUSTED_HOST=
   ```
   对应"风险 3"。**建议修**，避免运行期任何隐式联网行为。
4. **本地 profile**（不是改文件，是必须做的实验）：用 demo 数据集跑一次 `dabench run-benchmark --config configs/react_baseline.example.yaml`，从 `artifacts/runs/<run_id>/summary.json` 读出每个 task 的 `e2e_elapsed_seconds`，按 `task_count × P95 ≤ workers × 总时长上限` 反推 `max_workers` 与 `task_timeout_seconds`。  
   对应"风险 5"。**必须自测**，否则 A 榜 2h / B 榜 12h 上限是否够无法判断。

完成上述 4 项后，按"第三节" Step 1–6 即可正式提交。提交前请逐条勾选"第四节"的自检清单。
