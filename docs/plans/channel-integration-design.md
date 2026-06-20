# 频道集成设计文档 — QQ Bot & 微信 (weixin-bot)

> 创建日期：2026-06-03
> 更新日期：2026-06-20
> 状态：QQ Bot 已实施，微信已实施（使用 weixin-bot 协议）

---

## 一、概述

Thumbelina 已有 Web（FastAPI + WebSocket）和 CLI 两个交互频道。本文档设计将交互能力扩展到 **QQ** 和 **微信** 平台，使用户可以通过即时通讯软件与 Thumbelina Agent 对话。

### 技术选型

| 平台 | 方案 | 理由 |
|------|------|------|
| **QQ** | `qq-botpy` 官方 SDK（`tencent-connect/botpy`） | 腾讯官方 Python SDK，WebSocket 长连接，支持频道/群/私聊 |
| **微信** | [weixin-bot](https://github.com/epiral/weixin-bot) 协议 | 直接调用 iLink API，无需 sidecar 进程，协议文档完善 |

---

## 二、架构设计

### 2.1 频道抽象层

```
src/thumbelina/channels/
├── __init__.py          # 导出所有频道
├── base.py              # Channel ABC
├── qq_channel.py        # QQ Bot 频道
├── wechat_channel.py    # 微信频道（weixin-bot 协议）
├── wechat_qrcode.py     # 微信 QR 码登录 + iLink 客户端
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

### 2.3 微信频道（weixin-bot 协议）

**接入方式**: 直接调用 iLink API，使用 [weixin-bot](https://github.com/epiral/weixin-bot) 协议

**协议参考**: https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md

**架构**:
```
用户发微信 → 微信服务器 → iLink API
    → ILinkClient.getupdates() [长轮询 ~35s]
    → WeChatChannel._process_message()
    → ThumbelinaAgent.run(text)
    → ILinkClient.send_message() [需要 context_token]
    → 用户收到回复
```

**关键协议细节**:

1. **X-WECHAT-UIN**: 必须是 base64 编码的随机数字字符串
2. **SKRouteTag**: 必须设置为 `1001`
3. **context_token**: 每条消息都包含 context_token，回复时必须原样传回
4. **get_updates_buf**: 长轮询游标，必须持久化，会话过期时清除
5. **会话过期**: `errcode=-14` 表示会话过期，需要重新扫码认证

**API 端点**:

| 端点 | 方法 | 用途 |
|------|------|------|
| `/ilink/bot/get_bot_qrcode?bot_type=3` | GET | 获取登录二维码 |
| `/ilink/bot/get_qrcode_status?qrcode=...` | GET | 轮询扫码状态 |
| `/ilink/bot/getupdates` | POST | 长轮询接收消息 |
| `/ilink/bot/sendmessage` | POST | 发送回复 |

**请求头**:

```json
{
  "Content-Type": "application/json",
  "AuthorizationType": "ilink_bot_token",
  "Authorization": "Bearer <bot_token>",
  "X-WECHAT-UIN": "<base64_encoded_random_uint32>",
  "SKRouteTag": "1001"
}
```

**凭据管理**:
- 凭据保存在 `~/.weclaw/accounts/{bot_id}.json`
- 包含 `bot_token`, `ilink_bot_id`, `ilink_user_id`, `baseurl`
- 重启时自动加载保存的凭据

**配置**:
```yaml
channels:
  wechat:
    enabled: true
    bot_token: ""              # iLink bot token（扫码后自动填充）
    ilink_bot_id: ""           # iLink bot ID
    ilink_user_id: ""          # iLink user ID
    ilink_base_url: "https://ilinkai.weixin.qq.com"
```

**依赖**: `httpx`（已有）

---

## 三、集成到 Thumbelina

### 3.1 配置模型

在 `channels/config.py` 中定义:

```python
class QQChannelConfig(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    allowed_guilds: list[str] = []
    allowed_groups: list[str] = []

class WeChatChannelConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""           # iLink bot token
    ilink_bot_id: str = ""        # iLink bot ID
    ilink_user_id: str = ""       # iLink user ID
    ilink_base_url: str = "https://ilinkai.weixin.qq.com"
    webhook_secret: str = ""      # 可选 webhook 签名验证

class ChannelsConfig(BaseModel):
    qq: QQChannelConfig = QQChannelConfig()
    wechat: WeChatChannelConfig = WeChatChannelConfig()
```

### 3.2 应用生命周期集成

在 `api/app.py` 的 `lifespan()` 中，**先加载数据库配置，再初始化频道**:

```python
# 1. 初始化配置仓库和运行时管理器
config_repo = ConfigRepository(db_url=config.memory.database_url)
runtime_manager = RuntimeConfigManager(config=config, config_repo=config_repo)

# 2. 从数据库加载配置（覆盖 YAML）
await runtime_manager.load_from_database()

# 3. 初始化频道（使用数据库配置）
if config.channels.wechat.enabled:
    wechat_channel = WeChatChannel(config=config.channels.wechat, agent=agent)
    await wechat_channel.start()

if config.channels.qq.enabled:
    qq_channel = QQChannel(config=config.channels.qq, agent=agent)
    await qq_channel.start()
```

### 3.3 消息流

#### 微信 → 前端

1. 微信用户发送消息
2. `ILinkClient.getupdates()` 接收消息
3. `WeChatChannel._process_message()` 处理消息
4. `handle_incoming()` 调用 agent 并广播到 WebSocket 客户端
5. 响应通过 `send_message()` 发送回微信用户

#### 前端 → 微信

1. 前端通过 WebSocket 发送消息到微信对话
2. WebSocket 处理器识别为微信对话
3. 调用 `handle_incoming()` 获取 agent 响应
4. 响应返回给前端 WebSocket 客户端
5. 调用 `send_message()` 将响应发送到微信（包含 context_token）

---

## 四、消息格式处理

### 4.1 QQ 消息

- 接收: `message.content` 包含 @mention 需要剥离
- 发送: 纯文本，支持 Markdown（QQ 频道支持）
- 群消息: 需要 @Bot 才响应（`on_group_at_message_create`）
- 私聊: 直接响应

### 4.2 微信消息

- 接收: 纯文本（`item_list` 中 `type=1` 的 `text_item.text`）
- 发送: 纯文本，通过 `sendmessage` API
- **context_token**: 必须从接收消息中获取并传回发送消息
- **消息类型**: `message_type=1`（用户消息），`message_state=2`（已完成）

---

## 五、安全设计

1. **QQ Bot**: AppSecret 保密，不提交到代码库
2. **微信**: bot_token 保密，不存储在数据库中，只保存在本地凭据文件
3. **Webhook 验证**: 可选的 HMAC-SHA256 签名验证
4. **消息限流**: 复用现有 `RateLimiter`

---

## 六、错误处理

### 6.1 会话过期（errcode=-14）

当 iLink 返回 `errcode=-14` 时:
1. 停止长轮询循环
2. 清除内存中的 `context_token` 缓存
3. 清除持久化的 `get_updates_buf`
4. 提示用户重新扫码认证

### 6.2 连接错误

- 连接超时: 指数退避重试（最多 60 秒）
- 连续 5 次错误: 记录错误并提示重新认证
- 网络不可用: 持续重试直到恢复

---

## 七、实施计划

| 步骤 | 内容 | 预计工作量 | 状态 |
|------|------|-----------|------|
| 1 | 创建 Channel ABC + 配置模型 | 小 | 已完成 |
| 2 | 实现 QQChannel（qq-botpy） | 中 | 已完成 |
| 3 | 实现 WeChatChannel（weixin-bot 协议） | 中 | 已完成 |
| 4 | 集成到 app.py（数据库配置优先） | 小 | 已完成 |
| 5 | 编写测试 | 中 | 已完成（809 个测试用例） |
| 6 | 更新文档 | 小 | 已完成 |

---

## 八、使用方式

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

### 微信（weixin-bot 协议）

#### 方式 A：扫码登录（推荐）

1. 启动 Thumbelina: `thumbelina-serve`
2. 调用 `POST /api/v1/wechat/qrcode` 获取二维码
3. 微信扫码
4. 轮询 `GET /api/v1/wechat/qrcode/status` 直到状态为 `confirmed`
5. 调用 `POST /api/v1/wechat/qrcode/confirm` 保存凭据并启用频道

#### 方式 B：手动配置

在 `thumbelina.yaml` 中添加：
```yaml
channels:
  wechat:
    enabled: true
    bot_token: "your_bot_token"
    ilink_bot_id: "your_bot_id"
    ilink_user_id: "your_user_id"
    ilink_base_url: "https://ilinkai.weixin.qq.com"
```

---

## 九、参考资料

- [weixin-bot 项目](https://github.com/epiral/weixin-bot)
- [weixin-bot 协议规范](https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md)
- [QQ Bot SDK 文档](https://botpy.qq.com/)
