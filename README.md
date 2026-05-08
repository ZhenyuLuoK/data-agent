# Docker 打包指南

本文档介绍如何将 `data-agent-baseline` 项目打包成 Docker 镜像，以便在 KDD Cup 2026 DataAgent-Bench 评测平台上运行。

## 📋 前置要求

- Docker 已安装并正常运行
- 项目根目录下已有 `Dockerfile`（如果没有，请参考下方的 Dockerfile 示例）

## 🐳 构建 Docker 镜像

### 基础构建命令

```bash
docker build -t data-agent-baseline:latest .
```

### 带缓存优化的构建

```bash
docker build --cache-from data-agent-baseline:latest -t data-agent-baseline:latest .
```

### 指定平台构建（如需跨平台兼容）

```bash
docker build --platform linux/amd64 -t data-agent-baseline:latest .
```

## 🚀 运行 Docker 容器

### 本地测试运行

```bash
docker run -it \
  -v /path/to/input:/input \
  -v /path/to/output:/output \
  -e MODEL_NAME="your-model-name" \
  -e MODEL_API_URL="https://your-api-url.com" \
  -e MODEL_API_KEY="your-api-key" \
  -e CONFIG_PATH="configs/react_baseline.submit.yaml" \
  data-agent-baseline:latest
```

**参数说明：**
- `-v /path/to/input:/input`: 挂载输入数据集目录
- `-v /path/to/output:/output`: 挂载输出结果目录
- `-e MODEL_NAME`: 模型名称
- `-e MODEL_API_URL`: 模型 API 地址
- `-e MODEL_API_KEY`: 模型 API 密钥
- `-e CONFIG_PATH`: 配置文件路径（可选，默认为 `configs/react_baseline.submit.yaml`）

### 后台运行模式

```bash
docker run -d \
  --name data-agent-run \
  -v /path/to/input:/input \
  -v /path/to/output:/output \
  -e MODEL_NAME="your-model-name" \
  -e MODEL_API_URL="https://your-api-url.com" \
  -e MODEL_API_KEY="your-api-key" \
  data-agent-baseline:latest
```

查看日志：
```bash
docker logs -f data-agent-run
```

停止容器：
```bash
docker stop data-agent-run
```

## 📦 推送镜像到仓库

### 推送到 Docker Hub

```bash
# 登录
docker login

# 打标签
docker tag data-agent-baseline:latest your-username/data-agent-baseline:latest

# 推送
docker push your-username/data-agent-baseline:latest
```

### 推送到阿里云容器镜像服务

```bash
# 登录阿里云镜像仓库
docker login registry.cn-hangzhou.aliyuncs.com

# 打标签
docker tag data-agent-baseline:latest registry.cn-hangzhou.aliyuncs.com/your-namespace/data-agent-baseline:latest

# 推送
docker push registry.cn-hangzhou.aliyuncs.com/your-namespace/data-agent-baseline:latest
```

## 🔧 常见问题

### 1. 构建失败：依赖安装超时

**解决方案：** 使用国内镜像源加速 pip 安装

在 Dockerfile 中添加：
```dockerfile
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt
```

### 2. 运行时找不到输入数据

**检查点：**
- 确认 `/input` 目录已正确挂载
- 确认输入目录包含完整的 task 子目录结构
- 验证权限设置是否正确

```bash
# 验证挂载
docker run -it --rm \
  -v /path/to/input:/input \
  data-agent-baseline:latest ls -la /input
```

### 3. 输出结果未同步

**说明：** `entrypoint.sh` 已内置后台同步进程，每 5 秒自动将结果从 `/output/<run_id>/task_*/` 同步到 `/output/task_*/`。即使容器被强制终止，已完成的任务结果也会被保留。

### 4. 内存不足

**解决方案：** 限制容器内存使用

```bash
docker run -m 8g \
  --memory-swap 16g \
  [其他参数...] \
  data-agent-baseline:latest
```

## 📝 Dockerfile 示例

如果项目中还没有 Dockerfile，可以创建如下内容：

```dockerfile
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY pyproject.toml .

# 安装 Python 依赖
RUN pip install --no-cache-dir .

# 复制项目代码
COPY src/ ./src/
COPY configs/ ./configs/
COPY entrypoint.sh .

# 赋予执行权限
RUN chmod +x entrypoint.sh

# 设置环境变量
ENV PYTHONPATH=/app/src:$PYTHONPATH
ENV CONFIG_PATH=configs/react_baseline.submit.yaml

# 入口脚本
ENTRYPOINT ["./entrypoint.sh"]
```

## 🎯 KDD Cup 评测平台提交

评测平台会自动：
1. 挂载 `/input` 目录（包含完整数据集）
2. 挂载 `/output` 目录（用于输出结果）
3. 注入环境变量：`MODEL_NAME`、`MODEL_API_URL`、`MODEL_API_KEY`

你只需要确保：
- ✅ Docker 镜像已构建并推送到可访问的仓库
- ✅ `entrypoint.sh` 能正确处理环境变量
- ✅ 输出格式符合评测要求（`prediction.csv` 文件）

## 📊 监控与调试

### 查看容器资源使用

```bash
docker stats data-agent-run
```

### 进入运行中的容器调试

```bash
docker exec -it data-agent-run bash
```

### 查看容器日志

```bash
# 实时日志
docker logs -f data-agent-run

# 最近 100 行日志
docker logs --tail 100 data-agent-run
```

## 💡 最佳实践

1. **分层优化**：将依赖安装和代码复制分开，充分利用 Docker 缓存
2. **多阶段构建**：如需减小镜像体积，可使用多阶段构建
3. **.dockerignore**：确保已配置 `.dockerignore` 排除不必要的文件
4. **健康检查**：生产环境建议添加 HEALTHCHECK 指令
5. **日志管理**：合理配置日志轮转，避免磁盘空间耗尽

## 📚 相关文档

- [项目主要代码 src/data_agent_baseline/agents/langgraph_agent.py]
- [相关文献 docs/data-agent/]
- [agent 架构 docs/agengt_architecture.md, docs/agent_architecture_summary.html]
- [工作流程 docs/agent-workflow.svg]
- [case 示例 docs/example]
- [直接运行 需要APIkey config/react_baseline.local.yaml]
---

**注意：** 请根据实际项目结构调整上述配置和命令。
