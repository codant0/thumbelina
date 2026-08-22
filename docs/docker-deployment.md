# Thumbelina Docker 部署指南

本文档描述如何使用 Docker 部署 Thumbelina（后端 FastAPI + 前端 React），以及代码修改后如何快速更新服务。

> 适用版本：仓库当前主干。相关文件：`Dockerfile`、`docker-compose.yml`、`.dockerignore`、`deploy/online/*.sh`、`deploy/offline/*.sh`。
>
> 自 v0.2 起部署改为**单容器**：前端构建产物由后端 uvicorn 直接托管（FastAPI `StaticFiles`），不再使用 nginx。

> **⚠️ 升级提醒（存储配置节重命名）**：近期存储配置节已由 `memory` 更名为 `repository`（见 `src/thumbelina/config/models.py`），对应的环境变量从 `THUMBELINA_MEMORY__DATABASE_URL` 改为 **`THUMBELINA_REPOSITORY__DATABASE_URL`**（见 [4.2](#42-compose-注入的环境变量)）。旧变量名会被**静默忽略**，若沿用会导致数据库写入容器内 `/app`（不在持久卷里），**重建容器即丢数据**。从旧版本升级时务必同步修改 compose。
>
> 同时新增了「可配置数据文件存放路径」能力（见 [4.3](#43-指定数据文件存放路径)）：默认命名卷，也可用 `THUMBELINA_DATA_DIR` 指定宿主机目录。

---

## 1. 部署架构

```
                        ┌────────────────────────────────────────────┐
 浏览器                  │  docker compose 网络                      │
 ────────►  :8000 ────► │  thumbelina (python:3.11-slim)             │
                        │   ├─ uvicorn 0.0.0.0:8000                  │
                        │   │    ├─ /api/v1/*、/ws/chat  (FastAPI)   │
                        │   │    └─ / (静态文件，前端 dist)          │
                        │   ├─ /app/thumbelina.yaml（只读挂载）      │
                        │   └─ /app/data ◄── 卷/bind mount           │
                        │        ├─ thumbelina.db  (SQLite+ckpt)     │
                        │        ├─ chroma/        (向量库)          │
                        │        └─ TODO/          (待办/随手记)     │
                        └────────────────────────────────────────────┘
```

| 容器 | 镜像 | 宿主机端口 | 说明 |
|---|---|---|---|
| `thumbelina` | `node:22-alpine` 构建前端 + `python:3.11-slim` 自建 | `8000 → 8000` | FastAPI + LangGraph，同时托管前端静态文件 |

- 浏览器只需访问 **8000 端口**；前端代码统一使用相对路径（`/api/v1/*`、`/ws/chat`），由同一进程内的 uvicorn 处理，无需反向代理。
- 所有运行期数据都在持久数据目录中（默认命名卷 `thumbelina-data`，也可用 `THUMBELINA_DATA_DIR` 指定宿主机目录，见 [4.3](#43-指定数据文件存放路径)），重建容器不丢失。

## 2. 文件清单

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 多阶段镜像：node 阶段 `vite build` 前端 → python 阶段装后端依赖、拷贝 `dist` 到 `/app/static` |
| `docker-compose.yml` | 编排单服务、端口、卷、环境变量、健康检查 |
| `.dockerignore` | 排除 `node_modules`、`.git`、`*.db`、日志等，加速构建 |
| `thumbelina.yaml` | 应用配置，运行时以只读方式挂载进容器 |

## 3. 前置条件

1. **Docker**：Docker Engine 20.10+（Linux 服务器）或 Docker Desktop（Windows/macOS），Compose v2（`docker compose version` 可用）。
2. **端口**：宿主机 `8000` 未被占用（占用时见 [FAQ Q2](#q2-端口被占用怎么办)）。
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

repository:
  database_url: sqlite:///thumbelina.db   # 容器内会被环境变量覆盖，见 4.2（旧节名 memory 已废弃）

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
| `THUMBELINA_REPOSITORY__DATABASE_URL` | `sqlite:////app/data/thumbelina.db` | **把 SQLite 放进持久数据目录**（注意是 4 个斜杠，表示绝对路径）。存储配置节已由 `memory` 更名为 `repository`；**旧变量名 `THUMBELINA_MEMORY__DATABASE_URL` 已失效且被静默忽略**（数据会落容器内 `/app`，重建即丢）。SQLite 与 LangGraph checkpoint 上下文表**共用此文件**，持久化它即同时保住全部会话上下文 |
| `THUMBELINA_TODO__DIRECTORY` | `/app/data/TODO` | 待办/随手记（本地 Markdown）默认目录相对工作目录（`/app/TODO`，不在卷里）；改到持久数据目录内，随数据一起备份 |
| `THUMBELINA_CHANNELS__WECHAT__ACCOUNTS_DIR` | `/app/data/CHANNEL/.weclaw/accounts` | 微信扫码登录凭据（`{bot_id}.json`）默认在工作目录下 `CHANNEL/.weclaw/accounts`（容器内即 `/app/CHANNEL`，不在卷里，重建即丢）；改到持久数据目录后重建容器无需重新扫码 |
| `HF_ENDPOINT` | 默认 `https://hf-mirror.com` | RAG 嵌入模型下载走国内镜像（huggingface.co 不可达）；海外环境可 `export HF_ENDPOINT=https://huggingface.co` 覆盖 |
| `HF_HOME` | `/app/data/huggingface` | 模型缓存放进持久数据目录，重建容器无需重新下载 |

命名规则：`THUMBELINA_` 前缀 + 双下划线 `__` 表示嵌套，如 `THUMBELINA_LLM__PROVIDER` 对应 `llm.provider`。

### 4.3 指定数据文件存放路径

容器内数据挂载点固定为 `/app/data`；**宿主机一侧的存放位置通过 `THUMBELINA_DATA_DIR` 配置**，两种方式二选一：

| 方式 | 配置 | 数据落在哪 |
|---|---|---|
| **命名卷（默认，零配置）** | 不设置 `THUMBELINA_DATA_DIR` | Docker 卷目录内（`docker volume ls` 可查到 `thumbelina-data`） |
| **宿主机目录（bind mount）** | `THUMBELINA_DATA_DIR=<宿主机/路径>` | 直接落到你指定的目录，方便查看、备份、迁移 |

使用宿主机目录时，推荐在项目根目录建 `.env` 文件长期生效（`.env` 会被 `docker compose` 自动读取）：

```bash
# .env
THUMBELINA_DATA_DIR=/volume1/thumbelina/data   # NAS 存储盘（如绿联 /volume1）
# THUMBELINA_DATA_DIR=./data                    # 或项目内的相对目录
```

也可命令行临时指定：

```bash
THUMBELINA_DATA_DIR=/data/thumbelina docker compose up -d --build
```

**落在该数据目录里的内容**：SQLite 数据库（`thumbelina.db`，含 LangGraph checkpoint）、ChromaDB 向量库（`chroma/`）、HF 嵌入模型缓存（`huggingface/`）、待办/随手记 Markdown（`TODO/`）、微信扫码登录凭据（`CHANNEL/.weclaw/accounts/`）。

> 从命名卷切换到宿主机目录后，旧数据不会自动搬过去 —— 迁移方法见 [6.3](#63-备份与恢复)。

## 5. 首次部署

```bash
cd thumbelina                      # 进入仓库根目录

# 1) 设置 LLM 密钥（若已写入 thumbelina.yaml 可跳过）
export THUMBELINA_LLM__API_KEY="sk-..."

# 2) 构建并后台启动
docker compose up -d --build

# 3) 验证
docker compose ps                  # thumbelina 应为 running → healthy
curl -s http://localhost:8000/health
# 期望输出：{"status":"ok"}（或类似 JSON）

# 4) 打开前端
# http://localhost:8000
```

首次构建约 5～15 分钟（取决于网络；需安装后端依赖——**含 `[rag]` 可选组**（llama-index 嵌入/LLM、pymupdf、sqlite-vec、beautifulsoup4 等；应用启动时无条件导入 rag 路由，缺了会直接崩）——并完成一次前端 `vite build`）。

## 6. 数据持久化与迁移

### 6.1 数据在哪里

| 数据 | 容器内路径 | 持久化方式 |
|---|---|---|
| SQLite 数据库（**含 LangGraph checkpoint 上下文**） | `/app/data/thumbelina.db` | 命名卷 `thumbelina-data` 或 `THUMBELINA_DATA_DIR` 指定的宿主机目录 |
| ChromaDB 向量库 | `/app/data/chroma` | 同上 |
| HF 嵌入模型缓存 | `/app/data/huggingface` | 同上 |
| 待办/随手记（Markdown） | `/app/data/TODO` | 同上 |
| 微信扫码登录凭据 | `/app/data/CHANNEL/.weclaw/accounts` | 同上 |
| 应用配置 | `/app/thumbelina.yaml` | 宿主机文件只读挂载 |

`docker compose down` 不会删除数据；命名卷只有 `docker compose down -v` 才会清空，`THUMBELINA_DATA_DIR` 指向的宿主机目录则不受 `-v` 影响。

### 6.2 迁移本地已有数据库

容器内是全新数据库。如需把本地开发机的 `thumbelina.db` 带进容器：

```bash
docker compose cp thumbelina.db thumbelina:/app/data/thumbelina.db
docker compose restart thumbelina
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

如果数据放在 `THUMBELINA_DATA_DIR` 指定的宿主机目录（bind mount），备份/恢复更直接，无需进卷：

```bash
# 备份（直接打包宿主机目录）
tar czf thumbelina-data-$(date +%F).tar.gz -C /volume1/thumbelina/data .

# 恢复
mkdir -p /volume1/thumbelina/data
tar xzf /backup/thumbelina-data-2026-08-16.tar.gz -C /volume1/thumbelina/data
docker compose restart thumbelina
```

## 7. 代码修改后的快速更新

### 7.1 本机部署（代码与 Docker 同机）

| 改动内容 | 命令 | 耗时参考 |
|---|---|---|
| 仅后端 Python 代码 | `docker compose up -d --build` | 1～2 分钟（依赖层命中缓存，仅重装本项目） |
| 仅前端 React 代码 | `docker compose up -d --build` | 1～3 分钟（npm 层命中缓存，仅重新 `vite build` + 拷贝 dist） |
| 前后端都改了 | `docker compose up -d --build` | 两者之和 |
| 仅改 `thumbelina.yaml` | `docker compose restart thumbelina` | 秒级，**无需构建** |
| 改了 `pyproject.toml` 依赖 | `docker compose up -d --build` | 较慢（依赖层重建） |
| 改了 `frontend/package*.json` | `docker compose up -d --build` | 较慢（npm 层重建） |

原理：后端 Dockerfile 先用占位包安装依赖并固化为缓存层，再拷贝源码 `--no-deps` 重装；前端阶段先 `npm ci` 固化缓存层再构建，`COPY --from=frontend` 只在前端产物变化时重建。只要依赖清单不变，重建只处理业务代码。

**只改了配置/数据库结构、不想重建镜像** 时，优先用 `docker compose restart thumbelina`。

怀疑缓存有问题时强制全量重建：

```bash
docker compose build --no-cache
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
docker compose up -d --build
docker image prune -f
```

注意事项：

- `git pull` 前确认服务器上没有本地未提交改动（`--ff-only` 会拒绝合并冲突，避免误覆盖）。
- `thumbelina.yaml` 若在服务器上单独维护（含密钥），不要纳入 git 跟踪，或改用 `thumbelina.yaml.example` + 服务器本地副本的方式，避免 `git pull` 冲突。
- 重建期间服务会有秒级中断：旧容器停止、新容器启动，浏览器刷新页面即可（数据卷不受影响）。
- 服务器配置较低（内存不足以构建）时，使用第 7.3 节的私有 registry 方案，或构建镜像推送后 NAS 端 `docker compose pull && docker compose up -d`。

### 7.3 私有 registry 部署（PC 构建镜像，NAS 拉取）

NAS（尤其 ARM 的绿联 DH 系列）现场构建后端依赖较重；推荐在 PC/CI 上构建**多架构镜像**推送到私有 registry，NAS 端直接拉取，只执行 `pull`、不构建。

**1) 准备 registry（可选，已有公网仓库可跳过）**

```bash
docker run -d --name registry --restart=unless-stopped -p 5000:5000 registry:2
```

> 内网 HTTP registry 需要给 **PC 和 NAS** 的 Docker 守护进程配置 `insecure-registries`（`/etc/docker/daemon.json`，或绿联 Docker 设置中的镜像源）。公网服务（阿里云 ACR / 腾讯云 TCR / GHCR 等）走 HTTPS，无需该配置。

**2) PC 端构建并推送**

```bash
docker login <REGISTRY>          # 一次即可
REGISTRY=192.168.1.100:5000 ./deploy/online/build-and-push.sh   # tag 默认取 git 短 commit
# REGISTRY=... TAG=v1.2 ./deploy/online/build-and-push.sh       # 手动指定 tag
```

脚本用 `buildx` 同时构建 `linux/amd64` 和 `linux/arm64` 镜像并推送，NAS 拉取时自动匹配自身架构。首次在 x86 上构建 arm64 需先启用 QEMU：

```bash
docker run --privileged --rm tonistiigi/binfmt --install all
```

**3) NAS 端拉取并启动**

```bash
docker login <REGISTRY>
cd /path/to/thumbelina
REGISTRY=192.168.1.100:5000 TAG=<上一步的 tag> ./deploy/online/pull-and-run.sh
```

`pull-and-run.sh` 会设置 `THUMBELINA_IMAGE` 并执行 `docker compose pull thumbelina`（只拉镜像、不构建）后 `up -d`。之后更新版本：PC 重新构建推送新 tag，NAS 换 tag 再执行一遍即可。

> 说明：`docker-compose.yml` 同时声明了 `build` 和 `image`。本地 `docker compose up -d --build` 走构建流程不受影响；NAS 端不构建，依赖 `pull` 拉取的镜像运行。

### 7.4 离线传输（导出镜像文件，NAS 上导入）

NAS 无法直连 registry 或不想搭私有仓库时，把镜像导出为 tar 文件拷贝过去。

**1) PC 端构建并导出**

```bash
sh ./deploy/offline/export-image.sh                 # 默认 amd64，tag=latest
# ARCH=arm64 ./deploy/offline/export-image.sh    # 绿联 DH 系列（ARM）
# ARCH=arm64 TAG=v1.2 ./deploy/offline/export-image.sh
```

生成 `thumbelina-<arch>-<tag>.tar`。首次在 x86 上构建 arm64 需先启用 QEMU（同 7.3）。

**2) 拷贝到 NAS**

U 盘 / SMB 共享 / SCP 均可，无需联网。

**3) NAS 上导入并启动**

```bash
cd /path/to/thumbelina
./deploy/offline/load-and-run.sh thumbelina-arm64-latest.tar
```

> NAS 上建议把数据放到存储盘而非 Docker 卷目录：启动前 `export THUMBELINA_DATA_DIR=/volume1/thumbelina/data`（或写入项目根 `.env`），再执行 `load-and-run.sh` / `docker compose up -d`，见 [4.3](#43-指定数据文件存放路径)。

> 先确认 NAS 架构：绿联 DXP 系列是 x86（amd64），DH 系列是 ARM（arm64）。导出的架构必须与 NAS 一致（多平台镜像无法离线 `docker save`）。

## 8. 日常运维命令

```bash
docker compose ps                       # 查看状态（含健康检查）
docker compose logs -f thumbelina       # 跟踪后端日志
docker compose logs --tail=200 thumbelina  # 最近 200 行
docker compose restart thumbelina       # 重启（改配置后）
docker compose stop                     # 停止（保留容器）
docker compose start                    # 再次启动
docker compose down                     # 删除容器（数据卷保留）
docker compose down -v                  # ⚠️ 连数据一起删除
docker compose exec thumbelina python -m thumbelina.cli.main --help   # 进入容器执行命令
docker compose top                      # 查看进程
```

## 9. FAQ / 故障排查

### Q1. 前端页面能打开，但聊天没响应 / 请求 404？

确认是通过 **http://localhost:8000** 访问。前端和 API/WebSocket 在同一进程内，无需代理。检查后端是否正常：

```bash
docker compose logs -f thumbelina
curl -s http://localhost:8000/health
```

### Q2. 端口被占用怎么办？

修改 `docker-compose.yml` 中冒号左侧的宿主机端口，容器内端口不要动：

```yaml
ports:
  - "9000:8000"   # 宿主机改用 9000
```

注意：改了宿主机端口后，浏览器访问新端口即可，无需改任何代码（前端用相对路径）。

### Q3. 构建很慢 / 拉取依赖超时？

Dockerfile 已默认使用国内镜像源（清华 PyPI / npmmirror），一般无需处理。海外环境或需要官方源时，构建时覆盖：

```bash
docker compose build \
  --build-arg PIP_INDEX_URL=https://pypi.org/simple \
  --build-arg PIP_TRUSTED_HOST=pypi.org
docker compose build --build-arg NPM_REGISTRY=https://registry.npmjs.org
```

注意：基础镜像（`python:3.11-slim`、`node:22-alpine`）仍需从 Docker 仓库拉取，镜像源/代理问题见 Q9。

### Q4. 容器重启后历史对话没了？

确认 `docker-compose.yml` 中 `THUMBELINA_REPOSITORY__DATABASE_URL=sqlite:////app/data/thumbelina.db` 仍然存在（4 个斜杠）。若它被删掉、或被误用已失效的旧变量名 `THUMBELINA_MEMORY__DATABASE_URL`（会被静默忽略），数据库会落在容器内 `/app`，重建即丢。注意 SQLite 与 LangGraph checkpoint 共用此文件：它既存对话记录，也存会话上下文，一并丢失时表现为"历史对话和上下文全没了"。

### Q5. 容器一直 unhealthy？

```bash
docker compose logs thumbelina
```

常见原因：LLM 配置缺失（服务仍可启动，聊天时会提示配置 provider）、`thumbelina.yaml` 语法错误（YAML 解析报错会直接退出）。本地验证配置：`python -c "import yaml; yaml.safe_load(open('thumbelina.yaml'))"`。

### Q6. 微信 / QQ 频道能在容器里用吗？

可以。微信（weixin-bot）是**出站长轮询**，不需要入站端口：在 `thumbelina.yaml` 中设 `channels.wechat.enabled: true`，然后 `docker compose restart thumbelina` 并跟踪日志 `docker compose logs -f thumbelina` 获取二维码/登录状态。QQ 频道同理，填好 `app_id` / `app_secret` 即可。

### Q7. 本地开发是 Python 3.13，镜像是 3.11，会有问题吗？

`pyproject.toml` 要求 `>=3.11`，两者均满足。若依赖了仅 3.13 可用的语法/库，构建或启动会在日志中暴露，届时把基础镜像改为 `python:3.13-slim` 即可。

### Q8. 如何升级依赖版本？

修改 `pyproject.toml`（或 `frontend/package.json`）后执行 `docker compose up -d --build`；对应的依赖缓存层会自动重建。

### Q9. 构建时报 `load metadata ... no route to host` 或代理错误？

典型报错：`failed to resolve source metadata for docker.io/library/python:3.11-slim: ... proxyconnect tcp: dial tcp 192.168.x.x:7890: connect: no route to host`。

含义：Docker 守护进程配置了一个**连不通的 HTTP 代理**（常见为 Clash 的 7890 端口），或配置的 registry 加速器不可用。注意：**该代理同样会作用于 Dockerfile 内的 pip/npm 安装**，必须先处理：

1. **继续用代理**：确认代理主机开机、代理软件运行中，并开启「允许局域网连接」、放行防火墙端口；在部署机上验证：
   `curl -x http://<代理IP>:7890 -sI https://registry-1.docker.io/v2/ | head -1`
2. **不用代理**：SSH 登录移除守护进程代理配置（通常在 `/etc/systemd/system/docker.service.d/*.conf` 或 `/etc/default/docker`），然后：
   `systemctl daemon-reload && systemctl restart docker`
3. **基础镜像拉不下来（网络受限）**：在任意可联网机器上 `docker pull` 基础镜像后 `docker save -o base-images.tar ...`，传到部署机 `docker load -i base-images.tar`，再执行 compose 构建（BuildKit 会优先使用本地已有镜像）。
4. 查看当前代理 / 镜像加速器配置：`docker info | grep -iE "proxy|mirror" -A2`。不可用的加速器（部分已停止代理 Docker Hub）建议从 `/etc/docker/daemon.json` 的 `registry-mirrors` 中移除。

## 10. 生产部署建议

1. **开启鉴权**：`auth.secret_key` 设为 ≥32 字节随机串（如 `openssl rand -hex 32`），并按需配置 `required_roles`；同时建议开启 `rate_limit`。
2. **HTTPS**：在宿主机再加一层反向代理（nginx / Caddy / Traefik / NAS 自带反代）终结 TLS，并把 WebSocket 一并代理：

   ```nginx
   server {
       listen 443 ssl;
       server_name thumbelina.example.com;
       # ssl_certificate ...;
   
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
       }
       location /ws/ {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_read_timeout 3600s;
       }
   }
   ```

   前端代码已根据页面协议自动切换 `ws://` / `wss://`，无需改动。
3. **收敛暴露端口**：仅对外暴露 443，把 compose 中的端口映射改为 `"127.0.0.1:8000:8000"`，避免绕过反代直连。
4. **定期备份**：按 [6.3](#63-备份与恢复) 设置 cron 定时打包数据卷；也可使用应用内置的 `/api/v1/data/export` 接口导出对话数据。
5. **日志**：后端日志输出到 stdout，由 `docker compose logs` 收集；如需落盘，可为 compose 增加 `logging` 驱动配置（如 `json-file` 限制大小，或 `fluentd`/`loki`）。
6. **Ollama 场景**：若 LLM 使用宿主机 Ollama，`base_url` 填 `http://host.docker.internal:11434/v1`（Windows/macOS）或 `http://<宿主机内网 IP>:11434/v1`（Linux）。
