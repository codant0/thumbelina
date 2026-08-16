# syntax=docker/dockerfile:1
############################################################
# Stage 1 — 构建前端（React + Vite，产物 dist/）              #
############################################################
FROM node:22-alpine AS frontend
WORKDIR /app

# npm 国内镜像（默认 npmmirror；海外构建覆盖：
#   docker compose build --build-arg NPM_REGISTRY=https://registry.npmjs.org）
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry ${NPM_REGISTRY}

# 先装依赖并固化为缓存层：只有 package*.json 变化才重建这层
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# 拷贝前端源码并构建
COPY frontend/ ./
RUN npm run build
# → /app/dist 是 Vite 生产构建产物

############################################################
# Stage 2 — 运行时（Python + FastAPI + LangGraph）            #
############################################################
FROM python:3.11-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# PyPI 国内镜像（默认清华；海外覆盖：
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple \
#                        --build-arg PIP_TRUSTED_HOST=pypi.org）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
RUN pip config set global.index-url ${PIP_INDEX_URL} \
    && pip config set install.trusted-host ${PIP_TRUSTED_HOST}

# 编译本地 wheel（chromadb、llama-index 等）需要的系统工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 先用占位包装依赖并固化为缓存层：只要 pyproject.toml 不变，
# 代码修改后的重建会跳过这层（只重装本项目，原理见 docs/docker-deployment.md §7）
# 安装带上 [rag] extras：api 启动时无条件导入 rag 路由（loader.py 等顶部
# 直接 import requests/bs4/markdown_it/simhash/datasketch），缺这些无法启动。
COPY pyproject.toml ./
RUN mkdir -p src/thumbelina \
    && touch src/thumbelina/__init__.py \
    && pip install --no-cache-dir ".[rag]" \
    && rm -rf src

# 拷贝真实源码，快速重装（依赖已满足，只装本项目 wheel）
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .

# 前端构建产物拷贝进镜像，由 uvicorn 托管（main.py 将 /app/static 挂载到 /）
COPY --from=frontend /app/dist /app/static

# 持久数据目录：docker-compose.yml 会把卷 / bind mount 挂载到这里
# （默认命名卷 thumbelina-data，或 THUMBELINA_DATA_DIR 指定的宿主机目录）
RUN mkdir -p /app/data

EXPOSE 8000

# thumbelina-serve 只绑定 127.0.0.1，容器外不可达；
# 这里直接以 0.0.0.0 起 uvicorn，并启用工厂模式以托管前端静态文件
CMD ["python", "-m", "uvicorn", "thumbelina.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
