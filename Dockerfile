# =============================================================================
# data-agent web 一体化镜像
#   - Stage 1 (frontend): Node 20 编译 React/Vite 前端，产出 web/dist
#   - Stage 2 (backend) : Python 3.11 安装项目本身 + [web] 依赖，托管前端 + API
# 镜像内不包含任何 API key；用户在浏览器 Settings 页面手动填入即可。
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: 编译前端
# -----------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend

WORKDIR /web

# 启用 corepack 并固定 pnpm 版本：lockfileVersion: '9.0' 对应 pnpm 9.x
# pnpm 11 在 Node 20/22 上会触发 ERR_UNKNOWN_BUILTIN_MODULE，必须显式 pin。
RUN corepack enable \
    && corepack prepare pnpm@9.15.0 --activate

# 利用层缓存：先拷依赖清单，再装依赖
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# 拷贝前端源码并构建
COPY web/ ./
RUN pnpm build

# -----------------------------------------------------------------------------
# Stage 2: Python 后端 + 静态资源
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS backend

# ---- 系统依赖 ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libgomp1 \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- pip 配置（仅 build 阶段加速）----
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---- 安装项目本体（含 web 可选依赖）----
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --upgrade pip \
    && pip install '.[web]'

# ---- 拷运行期最小集 ----
# 注意：configs/react_baseline.local.yaml 已在 .dockerignore 排除，绝不进镜像
COPY configs/react_baseline.docker.yaml /app/configs/react_baseline.docker.yaml
COPY configs/react_baseline.example.yaml /app/configs/react_baseline.example.yaml
COPY configs/react_baseline.submit.yaml /app/configs/react_baseline.submit.yaml
COPY docs /app/docs
COPY entrypoint.web.sh /app/entrypoint.web.sh
RUN chmod +x /app/entrypoint.web.sh

# ---- 拷贝前端构建产物 ----
COPY --from=frontend /web/dist /app/web/dist

# ---- 清空 pip 镜像源，避免运行期任何隐式联网 ----
ENV PIP_INDEX_URL= \
    PIP_TRUSTED_HOST=

# ---- 运行期默认环境变量 ----
ENV DABENCH_WEB_HOST=0.0.0.0 \
    DABENCH_WEB_PORT=8000 \
    DABENCH_WEB_BASE_CONFIG=/app/configs/react_baseline.docker.yaml \
    DABENCH_WEB_DATASET_ROOT=/app/data/public/input \
    DABENCH_WEB_RUN_ROOT=/app/artifacts/runs \
    DABENCH_WEB_UPLOAD_ROOT=/app/artifacts/uploads \
    DABENCH_WEB_DOCS_ROOT=/app/docs \
    DABENCH_WEB_DIST_ROOT=/app/web/dist \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# tini 处理 PID 1 信号转发，避免 SIGTERM 丢失
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.web.sh"]
