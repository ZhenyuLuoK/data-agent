#!/usr/bin/env bash
set -euo pipefail

# KDD Cup 2026 DataAgent-Bench 评测入口
#
# 评测平台保证：
#   - /input 已挂载完整数据集（包含所有 task_<id>/）
#   - /output 已挂载结果输出目录
#   - 已注入环境变量 MODEL_NAME / MODEL_API_URL / MODEL_API_KEY
#
# 关键设计：
#   - 启动 dabench 之前先起一个后台同步进程，每 5 秒把
#     /output/<run_id>/task_<id>/prediction.csv 同步到
#     /output/task_<id>/prediction.csv（评测系统读后者）。
#   - 这样即使 12h 上限被 SIGKILL 强杀，已完成的 task 也已经落到
#     评测系统能找到的位置，最坏只丢 5 秒内刚写完的那一个。
#   - dabench 退出时通过 trap 再做一次最终全量同步并杀掉后台进程。

cd /app

CONFIG_PATH="${CONFIG_PATH:-configs/react_baseline.submit.yaml}"

# ---- 环境变量校验日志（不打印 key 本身）----
echo "[entrypoint] python: $(python --version 2>&1)"
echo "[entrypoint] config: ${CONFIG_PATH}"
echo "[entrypoint] MODEL_NAME=${MODEL_NAME:-<unset>}"
if [ -n "${MODEL_API_URL:-}" ]; then echo "[entrypoint] MODEL_API_URL=<set>"; else echo "[entrypoint] MODEL_API_URL=<unset>"; fi
if [ -n "${MODEL_API_KEY:-}" ]; then echo "[entrypoint] MODEL_API_KEY=<set>"; else echo "[entrypoint] MODEL_API_KEY=<unset>"; fi
echo "[entrypoint] /input contents:" && ls -1 /input | head -20 || true

# ---- 同步函数：把 /output/<run_id>/task_*/prediction.csv 拍平到 /output/task_*/prediction.csv ----
# 三轮投票语义下，必须改为「总是覆盖」：
#   - 第 1 轮先把保底 prediction.csv 拍平到 /output/task_*/，评测系统能立刻读到结果
#   - 三轮跑完后 runner 会在 /output/<run_id>/task_*/prediction.csv 覆盖写胜者，
#     下一个 5s 周期会把胜者拍平到顶层
# 注意：绝对只同步 prediction.csv 这一个文件名，r2.csv / r3.csv 留在 run 子目录里
# 仅作为 trace 证据，禁止泄露到 /output/task_*/（评测系统只读 prediction.csv）。
# 写入用 .tmp + mv 做原子替换，避免后台进程把"半个文件"拍上去。
sync_predictions() {
  shopt -s nullglob
  for src in /output/*/task_*/prediction.csv; do
    task_id="$(basename "$(dirname "${src}")")"
    case "${task_id}" in task_*) ;; *) continue ;; esac
    dst_dir="/output/${task_id}"
    dst="${dst_dir}/prediction.csv"
    mkdir -p "${dst_dir}"
    cp "${src}" "${dst}.tmp" && mv "${dst}.tmp" "${dst}"
  done
}

# ---- 后台同步进程：每 5 秒扫一次 ----
(
  while true; do
    sync_predictions || true
    sleep 5
  done
) &
SYNC_PID=$!

# 无论正常/异常退出，都做一次最终同步并清理后台进程。
# 注意：SIGKILL 无法被 trap，但 5 秒轮询已经把损失下限到 5 秒内未同步的那一个。
cleanup() {
  sync_predictions || true
  if kill -0 "${SYNC_PID}" 2>/dev/null; then
    kill "${SYNC_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ---- 跑 benchmark ----
RC=0
dabench run-benchmark --config "${CONFIG_PATH}" || RC=$?

echo "[entrypoint] dabench exit code: ${RC}"
exit "${RC}"
