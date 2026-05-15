#!/usr/bin/env bash
set -euo pipefail

# Web 镜像入口：启动 FastAPI（同时托管 /api 与前端 SPA）。
# 镜像不内置任何 API key，用户在浏览器 Settings 页面手动填入后即可使用。

cd /app

# 默认值；通过 docker run -e 可覆盖。
export DABENCH_WEB_HOST="${DABENCH_WEB_HOST:-0.0.0.0}"
export DABENCH_WEB_PORT="${DABENCH_WEB_PORT:-8000}"
export DABENCH_WEB_BASE_CONFIG="${DABENCH_WEB_BASE_CONFIG:-/app/configs/react_baseline.docker.yaml}"
export DABENCH_WEB_DATASET_ROOT="${DABENCH_WEB_DATASET_ROOT:-/app/data/public/input}"
export DABENCH_WEB_RUN_ROOT="${DABENCH_WEB_RUN_ROOT:-/app/artifacts/runs}"
export DABENCH_WEB_UPLOAD_ROOT="${DABENCH_WEB_UPLOAD_ROOT:-/app/artifacts/uploads}"
export DABENCH_WEB_DOCS_ROOT="${DABENCH_WEB_DOCS_ROOT:-/app/docs}"
export DABENCH_WEB_DIST_ROOT="${DABENCH_WEB_DIST_ROOT:-/app/web/dist}"

# 确保运行期目录存在（即使没挂载卷）
mkdir -p "${DABENCH_WEB_DATASET_ROOT}" \
         "${DABENCH_WEB_RUN_ROOT}" \
         "${DABENCH_WEB_UPLOAD_ROOT}"

echo "[entrypoint.web] python: $(python --version 2>&1)"
echo "[entrypoint.web] listen: ${DABENCH_WEB_HOST}:${DABENCH_WEB_PORT}"
echo "[entrypoint.web] base_config: ${DABENCH_WEB_BASE_CONFIG}"
echo "[entrypoint.web] dataset_root: ${DABENCH_WEB_DATASET_ROOT}"
echo "[entrypoint.web] dist_root: ${DABENCH_WEB_DIST_ROOT}"
echo "[entrypoint.web] (API key 不在镜像中，必须由前端 Settings 页面填入)"

exec dabench-web
