# Thumbelina Docker 部署指南

本文档描述如何使用 Docker 部署 Thumbelina（后端 FastAPI + 前端 React），以及代码修改后如何快速更新服务。

> 适用版本：仓库当前主干。相关文件：`Dockerfile`、`Dockerfile.frontend`、`frontend/nginx.conf`、`docker-compose.yml`、`.dockerignore`。

---

## 1. 部署架构

```
                        ┌─────────────────────────────────────────┐
 浏览器                  │  docker compose 网络                     │
 ────────►  :3000 ────► │  frontend (nginx:alpine)                 │
                        │   ├─ 静态文件 /usr/share/nginx/html       │
                        │   ├─ /api/*  ──反向代理──► backend:8000   │
                        │   └─ /ws/*   ──WebSocket 代理──►          │
                        │                                          │
                        │  backend (python:3.11-slim)              │
                        │   ├─ uvicorn 0.0.0.0:8000                │
  直接调 API ─► :8000 ──►│   ├─ /app/thumbelina.yaml（只读挂载）     │
                        │   └─ /app/data ◄── 命名卷                 │
                        │        ├─ thumbelina.db   (SQLite)       │
                        │        └─ chroma/         (向量库)        │
                        └─────────────────────────────────────────┘
```

| 容器 | 镜像 | 宿主机端口 | 说明 |
|---|---|---|---|
| `backend` | `python:3.11-slim` 自建 | `8000 → 8000` | FastAPI + LangGraph，uvicorn 启动 |
| `frontend` | `node:22-alpine` 构建 + `nginx:alpine` | `3000 → 80` | 静态页面 + 反代 `/api`、`/ws` |

- 浏览器只需访问 **3000 端口**；前端代码统一使用相对路径（`/api/v1/*`、`/ws/chat`），由 nginx 代理到后端。
- 8000 端口保留，供直接调用 REST API / 健康检查。
- 所有运行期数据都在命名卷 `thumbelina-data` 中，重建容器不丢失。

## 2. 文件清单

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 后端镜像：装系统依赖 → 缓存依赖层 → 拷源码安装 → uvicorn 启动 |
| `Dockerfile.frontend` | 前端镜像：node:22 构建 → nginx 托管产物 |
| `frontend/nginx.conf` | nginx 站点配置：SPA fallback + `/api`、`/ws` 反代 |
| `docker-compose.yml` | 编排两个服务、端口、卷、环境变量、健康检查 |
| `.dockerignore` | 排除 `node_modules`、`.git`、`*.db`、日志等，加速构建 |
| `thumbelina.yaml` | 应用配置，运行时以只读方式挂载进后端容器 |

## 3. 前置条件

1. **Docker**：Docker Engine 20.10+（Linux 服务器）或 Docker Desktop（Windows/macOS），Compose v2（`docker compose version` 可用）。
2. **端口**：宿主机 `3000`、`8000` 未被占用（占用时见 [FAQ Q2](#q2-端口被占用怎么办)）。
3. **LLM API Key**：OpenAI / Anthropic / Ollama 等任一可用提供方的密钥。
4. 仓库克隆到部署机，且 `thumbelina.yaml` 已按 [第 4 节](#4配置说明) 准备好。

> Windows 提示：以下命令在 Git Bash / WSL 中可直接执行；PowerShell 下 `export` 换成 `$env:变量名="值"`。

## 4. 配置说明

配置优先级（高 → 低）：**环境变量（`THUMBELINA_*`）＞ `thumbelina.yaml` ＞ 内置默认值**。

### 4.1 thumbelina.yaml（推荐方式）

compose 会把仓库根目录的 `thumbelina.yaml` 以只读方式挂载到容器 `/app/thumbelina.yaml`。最小可用配置：

```yaml
llm:
  provider: openai                 # openai / anthropic / ollama
  model: gpt-4o
  api_key: ''                      # 留空时用环境变量 THUMBELINA_LLM__API_KEY
  base_url: ''                     # 自定义 OpenAI 兼容端点时填写
  streaming_enabled: true

memory:
  database_url: sqlite:///thumbelina.db   # 容器内会被环境变量覆盖，见 4.2

auth:
  secret_key: ''                   # 生产环境务必设置（≥32 字节随机串），启用 JWT 鉴权

rate_limit:
  enabled: false
  max_requests: 60
  window_seconds: 60

channels:
  qq:
    enabled: false
  wechat:
    enabled: false                 # 启用后在容器日志中扫码登录，见 FAQ Q6
```

yaml 中支持 `${VAR}` 环境变量占位，例如 `api_key: ${OPENAI_API_KEY}`。

### 4.2 compose 注入的环境变量

`docker-compose.yml` 中已预置：

| 变量 | 值 | 作用 |
|---|---|---|
| `THUMBELINA_LLM__API_KEY` | 取自宿主机同名变量 | LLM 密钥，避免写死在 yaml 里 |
| `THUMBELINA_MEMORY__DATABASE_URL` | `sqlite:////app/data/thumbelina.db` | **把 SQLite 放进持久卷**（注意是 4 个斜杠，表示绝对路径）；环境变量优先级高于 yaml，无需改 yaml |

命名规则：`THUMBELINA_` 前缀 + 双下划线 `__` 表示嵌套，如 `THUMBELINA_LLM__PROVIDER` 对应 `llm.provider`。

## 5. 首次部署

```bash
cd thumbelina                      # 进入仓库根目录

# 1) 设置 LLM 密钥（若已写入 thumbelina.yaml 可跳过）
export THUMBELINA_LLM__API_KEY="sk-..."

# 2) 构建并后台启动
docker compose up -d --build

# 3) 验证
docker compose ps                  # backend 应为 running → healthy，frontend 为 running
curl -s http://localhost:8000/health
# 期望输出：{"status":"ok"}（或类似 JSON）

# 4) 打开前端
# http://localhost:3000
```

首次构建约 5～15 分钟（取决于网络；后端需安装 langgraph / chromadb / llama-index 等较重的依赖）。

## 6. 数据持久化与迁移

### 6.1 数据在哪里

| 数据 | 容器内路径 | 持久化方式 |
|---|---|---|
| SQLite 数据库 | `/app/data/thumbelina.db` | 命名卷 `thumbelina-data` |
| ChromaDB 向量库 | `/app/data/chroma` | 命名卷 `thumbelina-data` |
| 应用配置 | `/app/thumbelina.yaml` | 宿主机文件只读挂载 |

`docker compose down` 不会删除数据卷；只有 `docker compose down -v` 才会清空数据。

### 6.2 迁移本地已有数据库

容器内是全新数据库。如需把本地开发机的 `thumbelina.db` 带进容器：

```bash
docker compose cp thumbelina.db backend:/app/data/thumbelina.db
docker compose restart backend
```

### 6.3 备份与恢复

```bash
# 查看真实卷名（含项目名前缀）
docker volume ls | grep thumbelina-data

# 备份（在卷里打包到宿主机当前目录）
docker run --rm \
  -v thumbelina_thumbelina-data:/data \
  -v "$PWD":/backup \
  alpine tar czf /backup/thumbelina-data-$(date +%F).tar.gz -C /data .

# 恢复
docker run --rm \
  -v thumbelina_thumbelina-data:/data \
  -v "$PWD":/backup \
  alpine tar xzf /backup/thumbelina-data-2026-08-06.tar.gz -C /data
```

## 7. 代码修改后的快速更新

### 7.1 本机部署（代码与 Docker 同机）

| 改动内容 | 命令 | 耗时参考 |
|---|---|---|
| 仅后端 Python 代码 | `docker compose up -d --build backend` | 1～2 分钟（依赖层命中缓存，仅重装本项目） |
| 仅前端 React 代码 | `docker compose up -d --build frontend` | 1～3 分钟（npm 层命中缓存，仅重新 `vite build`） |
| 前后端都改了 | `docker compose up -d --build` | 两者之和 |
| 仅改 `thumbelina.yaml` | `docker compose restart backend` | 秒级，**无需构建** |
| 改了 `pyproject.toml` 依赖 | `docker compose up -d --build backend` | 较慢（依赖层重建） |
| 改了 `frontend/package*.json` | `docker compose up -d --build frontend` | 较慢（npm 层重建） |

原理：后端 Dockerfile 先用占位包安装依赖并固化为缓存层，再拷贝源码 `--no-deps` 重装；前端先 `npm ci` 固化缓存层再构建。只要依赖清单不变，重建只处理业务代码。

**只改了配置/数据库结构、不想重建镜像** 时，优先用 `docker compose restart backend`。

怀疑缓存有问题时强制全量重建：

```bash
docker compose build --no-cache backend    # 或 frontend
docker compose up -d
```

更新后确认无旧镜像残留（可选，释放磁盘）：

```bash
docker image prune -f
```

### 7.2 远程服务器部署（本地改代码，服务器跑容器）

推荐流程：git 同步 + 服务器上重建。

```bash
# ① 本地：提交并推送
git add . && git commit -m "update" && git push

# ② 服务器：拉取并重建（可保存为 ~/deploy-thumbelina.sh 一键执行）
cd /path/to/thumbelina
git pull --ff-only
docker compose up -d --build     # 只改了一端时可用 backend / frontend 单独重建
docker image prune -f
```

注意事项：

- `git pull` 前确认服务器上没有本地未提交改动（`--ff-only` 会拒绝合并冲突，避免误覆盖）。
- `thumbelina.yaml` 若在服务器上单独维护（含密钥），不要纳入 git 跟踪，或改用 `thumbelina.yaml.example` + 服务器本地副本的方式，避免 `git pull` 冲突。
- 重建期间服务会有秒级中断：旧容器停止、新容器启动，浏览器刷新页面即可（数据卷不受影响）。
- 服务器配置较低（内存不足以构建）时，可在本地或 CI 构建镜像并推送到镜像仓库，服务器端将 compose 的 `build:` 换成 `image:`，然后 `docker compose pull && docker compose up -d`。

## 8. 日常运维命令

```bash
docker compose ps                       # 查看状态（含健康检查）
docker compose logs -f backend          # 跟踪后端日志
docker compose logs -f frontend         # nginx / 前端日志
docker compose logs --tail=200 backend  # 最近 200 行
docker compose restart backend          # 重启（改配置后）
docker compose stop                     # 停止（保留容器）
docker compose start                    # 再次启动
docker compose down                     # 删除容器（数据卷保留）
docker compose down -v                  # ⚠️ 连数据一起删除
docker compose exec backend python -m thumbelina.cli.main --help   # 进入后端执行命令
docker compose top                      # 查看进程
```

## 9. FAQ / 故障排查

### Q1. 前端页面能打开，但聊天没响应 / 请求 404？

确认是通过 **http://localhost:3000** 访问（nginx 会代理 `/api`、`/ws`）。检查代理是否生效：

```bash
docker compose logs frontend | grep -E "api|ws"
docker compose exec frontend wget -qO- http://backend:8000/health
```

### Q2. 端口被占用怎么办？

修改 `docker-compose.yml` 中冒号左侧的宿主机端口，容器内端口不要动：

```yaml
ports:
  - "9000:8000"   # 后端改到 9000
  - "9001:80"     # 前端改到 9001
```

注意：若改了**前端**端口，浏览器访问新端口即可，无需改任何代码（前端用相对路径）。若绕过 nginx 直连后端 8000，则前端仍需经 nginx 访问。

### Q3. 构建很慢 / 拉取依赖超时？

两个 Dockerfile 已默认使用国内镜像源（清华 PyPI / npmmirror），一般无需处理。海外环境或需要官方源时，构建时覆盖：

```bash
docker compose build \
  --build-arg PIP_INDEX_URL=https://pypi.org/simple \
  --build-arg PIP_TRUSTED_HOST=pypi.org backend
docker compose build --build-arg NPM_REGISTRY=https://registry.npmjs.org frontend
```

注意：基础镜像（`python:3.11-slim`、`node:22-alpine`、`nginx:alpine`）仍需从 Docker 仓库拉取，镜像源/代理问题见 Q9。

### Q4. 容器重启后历史对话没了？

确认 `docker-compose.yml` 中 `THUMBELINA_MEMORY__DATABASE_URL=sqlite:////app/data/thumbelina.db` 仍然存在（4 个斜杠）。若曾被删掉，数据库会落在容器内 `/app`，重建即丢。

### Q5. backend 一直 unhealthy？

```bash
docker compose logs backend
```

常见原因：LLM 配置缺失（服务仍可启动，聊天时会提示配置 provider）、`thumbelina.yaml` 语法错误（YAML 解析报错会直接退出）。本地验证配置：`python -c "import yaml; yaml.safe_load(open('thumbelina.yaml'))"`。

### Q6. 微信 / QQ 频道能在容器里用吗？

可以。微信（weixin-bot）是**出站长轮询**，不需要入站端口：在 `thumbelina.yaml` 中设 `channels.wechat.enabled: true`，然后 `docker compose restart backend` 并跟踪日志 `docker compose logs -f backend` 获取二维码/登录状态。QQ 频道同理，填好 `app_id` / `app_secret` 即可。

### Q7. 本地开发是 Python 3.13，镜像是 3.11，会有问题吗？

`pyproject.toml` 要求 `>=3.11`，两者均满足。若依赖了仅 3.13 可用的语法/库，构建或启动会在日志中暴露，届时把基础镜像改为 `python:3.13-slim` 即可。

### Q8. 如何升级依赖版本？

修改 `pyproject.toml`（或 `frontend/package.json`）后执行 `docker compose up -d --build`；对应的依赖缓存层会自动重建。

### Q9. 构建时报 `load metadata ... no route to host` 或代理错误？

典型报错：`failed to resolve source metadata for docker.io/library/nginx:alpine: ... proxyconnect tcp: dial tcp 192.168.x.x:7890: connect: no route to host`。

含义：Docker 守护进程配置了一个**连不通的 HTTP 代理**（常见为 Clash 的 7890 端口），或配置的 registry 加速器不可用。注意：**该代理同样会作用于 Dockerfile 内的 pip/npm 安装**，必须先处理：

1. **继续用代理**：确认代理主机开机、代理软件运行中，并开启「允许局域网连接」、放行防火墙端口；在部署机上验证：
   `curl -x http://<代理IP>:7890 -sI https://registry-1.docker.io/v2/ | head -1`
2. **不用代理**：SSH 登录移除守护进程代理配置（通常在 `/etc/systemd/system/docker.service.d/*.conf` 或 `/etc/default/docker`），然后：
   `systemctl daemon-reload && systemctl restart docker`
3. **基础镜像拉不下来（网络受限）**：在任意可联网机器上 `docker pull` 三个基础镜像后 `docker save -o base-images.tar ...`，传到部署机 `docker load -i base-images.tar`，再执行 compose 构建（BuildKit 会优先使用本地已有镜像）。
4. 查看当前代理 / 镜像加速器配置：`docker info | grep -iE "proxy|mirror" -A2`。不可用的加速器（部分已停止代理 Docker Hub）建议从 `/etc/docker/daemon.json` 的 `registry-mirrors` 中移除。

## 10. 生产部署建议

1. **开启鉴权**：`auth.secret_key` 设为 ≥32 字节随机串（如 `openssl rand -hex 32`），并按需配置 `required_roles`；同时建议开启 `rate_limit`。
2. **HTTPS**：在宿主机再加一层反向代理（nginx / Caddy / Traefik）终结 TLS，并把 WebSocket 一并代理：

   ```nginx
   server {
       listen 443 ssl;
       server_name thumbelina.example.com;
       # ssl_certificate ...;

       location / {
           proxy_pass http://127.0.0.1:3000;
           proxy_set_header Host $host;
       }
       location /ws/ {
           proxy_pass http://127.0.0.1:3000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_read_timeout 3600s;
       }
   }
   ```

   前端代码已根据页面协议自动切换 `ws://` / `wss://`，无需改动。
3. **收敛暴露端口**：仅对外暴露 443，把 compose 中的端口映射改为 `"127.0.0.1:8000:8000"`、`"127.0.0.1:3000:80"`，避免绕过反代直连。
4. **定期备份**：按 [6.3](#63-备份与恢复) 设置 cron 定时打包数据卷；也可使用应用内置的 `/api/v1/data/export` 接口导出对话数据。
5. **日志**：后端日志输出到 stdout，由 `docker compose logs` 收集；如需落盘，可为 compose 增加 `logging` 驱动配置（如 `json-file` 限制大小，或 `fluentd`/`loki`）。
6. **Ollama 场景**：若 LLM 使用宿主机 Ollama，`base_url` 填 `http://host.docker.internal:11434/v1`（Windows/macOS）或 `http://<宿主机内网 IP>:11434/v1`（Linux）。
