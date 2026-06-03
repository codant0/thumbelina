# 频道集成设计文档 — QQ Bot & 微信 ClawBot

> 创建日期：2026-06-03
> 状态：QQ Bot 已实施，微信 ClawBot 已实施

---

## 一、概述

Thumbelina 已有 Web（FastAPI + WebSocket）和 CLI 两个交互频道。本文档设计将交互能力扩展到 **QQ** 和 **微信** 平台，使用户可以通过即时通讯软件与 Thumbelina Agent 对话。

### 技术选型

| 平台 | 方案 | 理由 |
|------|------|------|
| **QQ** | `qq-botpy` 官方 SDK（`tencent-connect/botpy`） | 腾讯官方 Python SDK，WebSocket 长连接，支持频道/群/私聊 |
| **微信** | WeClaw HTTP 桥接（`fastclaw-ai/weclaw`） | 个人号接入，HTTP API 简单可靠，无需维护微信协议 |

---

## 二、架构设计

### 2.1 频道抽象层

```
src/thumbelina/channels/
├── __init__.py          # 导出所有频道
├── base.py              # Channel ABC
├── qq_channel.py        # QQ Bot 频道
├── wechat_channel.py    # 微信 ClawBot 频道
└── config.py            # 频道配置模型
```

**Channel ABC** (`base.py`):

```python
from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable

MessageHandler = Callable[[str, str], Awaitable[str]]  # (user_id, text) -> response

class Channel(ABC):
    """频道基类 — 所有 IM 频道实现此接口。"""

    @abstractmethod
    async def start(self) -> None:
        """启动频道连接。"""

    @abstractmethod
    async def stop(self) -> None:
        """停止频道连接。"""

    @abstractmethod
    async def send_message(self, user_id: str, text: str) -> None:
        """主动发送消息给用户。"""

    def set_handler(self, handler: MessageHandler) -> None:
        """设置消息处理回调。"""
        self._handler = handler
```

### 2.2 QQ Bot 频道

**接入方式**: QQ 开放平台（q.qq.com），使用 `qq-botpy` SDK

**消息类型**:
- 频道 @消息（`on_at_message_create`）
- 群消息（`on_group_at_message_create`）
- C2C 私聊（`on_c2c_message_create`）

**流程**:
```
用户 @Bot → QQ 服务器 → botpy WebSocket → on_at_message_create
    → ThumbelinaAgent.run(text)
    → message.reply(content=response)
```

**配置**:
```yaml
channels:
  qq:
    enabled: true
    app_id: "your_app_id"
    app_secret: "your_app_secret"
    # 可选：限制响应的频道/群
    allowed_guilds: []
    allowed_groups: []
```

**依赖**: `qq-botpy`（pip install qq-botpy）

### 2.3 微信 ClawBot 频道

**接入方式**: WeClaw 桥接器（fastclaw-ai/weclaw），通过 HTTP API 通信

**架构**:
```
用户发微信 → 微信服务器 → WeClaw 进程
    → HTTP POST 到 Thumbelina webhook (/api/v1/wechat/incoming)
    → ThumbelinaAgent.run(text)
    → HTTP POST 到 WeClaw API (127.0.0.1:18011/api/send)
    → 用户收到回复
```

**WeClaw 配置** (`~/.weclaw/config.json`):
```json
{
  "default_agent": "thumbelina",
  "agents": {
    "thumbelina": {
      "type": "http",
      "endpoint": "http://127.0.0.1:8000/api/v1/wechat/incoming",
      "model": "thumbelina:main"
    }
  }
}
```

**Thumbelina 端**:
- `POST /api/v1/wechat/incoming` — 接收 WeClaw 转发的消息
- `POST /api/v1/wechat/send` — 主动发送消息（调用 WeClaw API）

**配置**:
```yaml
channels:
  wechat:
    enabled: true
    weclaw_api_url: "http://127.0.0.1:18011"
    weclaw_token: ""  # 可选认证
    webhook_secret: ""  # 可选 webhook 签名验证
```

**依赖**: `httpx`（已有）

---

## 三、集成到 Thumbelina

### 3.1 配置模型扩展

在 `config/models.py` 添加:

```python
class QQChannelConfig(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    allowed_guilds: list[str] = []
    allowed_groups: list[str] = []

class WeChatChannelConfig(BaseModel):
    enabled: bool = False
    weclaw_api_url: str = "http://127.0.0.1:18011"
    weclaw_token: str = ""
    webhook_secret: str = ""

class ChannelsConfig(BaseModel):
    qq: QQChannelConfig = QQChannelConfig()
    wechat: WeChatChannelConfig = WeChatChannelConfig()
```

### 3.2 应用生命周期集成

在 `api/app.py` 的 `lifespan()` 中:

```python
# 初始化频道
channels = []
if config.channels.qq.enabled:
    from thumbelina.channels.qq_channel import QQChannel
    qq = QQChannel(config=config.channels.qq, agent=agent)
    channels.append(qq)
    await qq.start()

if config.channels.wechat.enabled:
    from thumbelina.channels.wechat_channel import WeChatChannel
    wx = WeChatChannel(config=config.channels.wechat, agent=agent)
    channels.append(wx)
    # WeClaw webhook 路由在 create_app() 中注册

yield

for ch in channels:
    await ch.stop()
```

### 3.3 CLI 集成

在 `cli/chat.py` 中，频道作为可选的并行输入源:

```python
if config.channels.qq.enabled:
    qq_channel = QQChannel(config=config.channels.qq, agent=agent)
    await qq_channel.start()
```

---

## 四、消息格式处理

### 4.1 QQ 消息

- 接收: `message.content` 包含 @mention 需要剥离
- 发送: 纯文本，支持 Markdown（QQ 频道支持）
- 群消息: 需要 @Bot 才响应（`on_group_at_message_create`）
- 私聊: 直接响应

### 4.2 微信消息

- 接收: WeClaw 已处理语音转文字、图片等
- 发送: 纯文本（WeClaw 自动处理 Markdown → 纯文本转换）
- 媒体: WeClaw 支持图片/视频/文件，Thumbelina 可发送媒体 URL

---

## 五、安全设计

1. **QQ Bot**: AppSecret 保密，不提交到代码库
2. **微信**: WeClaw 运行在本地，HTTP API 仅监听 127.0.0.1
3. **Webhook 验证**: 可选的签名验证机制
4. **消息限流**: 复用现有 `RateLimiter`

---

## 六、实施计划

| 步骤 | 内容 | 预计工作量 | 状态 |
|------|------|-----------|------|
| 1 | 创建 Channel ABC + 配置模型 | 小 | 已完成 |
| 2 | 实现 QQChannel（qq-botpy） | 中 | 已完成 |
| 3 | 实现 WeChatChannel（WeClaw HTTP） | 中 | 已完成 |
| 4 | 集成到 app.py / chat.py | 小 | 已完成 |
| 5 | 编写测试 | 中 | 已完成（52 个测试用例：29 QQ + 23 WeChat） |
| 6 | 更新文档 | 小 | 已完成 |

---

## 七、使用方式

### QQ Bot

1. 访问 [q.qq.com](https://q.qq.com) 注册开发者
2. 创建机器人应用，获取 AppID 和 AppSecret
3. 在 `thumbelina.yaml` 中配置:
   ```yaml
   channels:
     qq:
       enabled: true
       app_id: "your_app_id"
       app_secret: "your_app_secret"
   ```
4. 启动 Thumbelina: `thumbelina-serve`

### 微信 ClawBot

1. 安装 WeClaw: `curl -sSL https://raw.githubusercontent.com/fastclaw-ai/weclaw/main/install.sh | sh`
2. 配置 WeClaw 指向 Thumbelina:
   ```bash
   weclaw config set agents.thumbelina.type http
   weclaw config set agents.thumbelina.endpoint http://127.0.0.1:8000/api/v1/wechat/incoming
   ```
3. 在 `thumbelina.yaml` 中配置:
   ```yaml
   channels:
     wechat:
       enabled: true
       weclaw_api_url: "http://127.0.0.1:18011"
   ```
4. 启动 WeClaw: `weclaw start`
5. 启动 Thumbelina: `thumbelina-serve`
6. 微信扫码登录，开始对话
