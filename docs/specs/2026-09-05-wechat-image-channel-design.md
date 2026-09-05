# 微信频道图片收发 — 设计交付（v2.1 增补）

- 日期：2026-09-05
- 前置：`2026-09-04-multimodal-chat-design.md`（已合入 main，PR #22）——附件管道（POST/GET /attachments、messages.attachments 列、`build_image_blocks`）全部复用
- 状态：v1，待实现
- 协议调研结论：iLink bot API（`ilinkai.weixin.qq.com`）**官方支持图片收发**，已由腾讯 `Tencent/openclaw-weixin` 源码、`epiral/weixin-bot` 协议文档、hermes-agent vendored 测试（本地 `hermes-agent/tests/gateway/test_weixin.py:329,371,456`）三方印证

## 1. 协议事实（实现依据）

### 1.1 入站图片
- `getupdates` 的 `msgs[].item_list[]` 中 `type: 2` = IMAGE（1=text, 2=image, 3=voice, 4=file, 5=video）
- 图片项结构：`image_item = {media: {encrypt_query_param, aes_key, encrypt_type: 1}, thumb_media?, aeskey?: <32-hex>, url?, mid_size, thumb_size, thumb_height, thumb_width, hd_size}`
- 下载：`GET {CDN}/download?encrypted_query_param=<urlencode>`，**不带任何鉴权头**（encrypt_query_param 即服务端签名令牌）；优先用服务器给的 `full_url`（若有）
- 解密：**AES-128-ECB + PKCS7**，key 16 字节；key 有两种编码并存（base64(原始16字节) / base64(hex字符串)），解码需兼容；`image_item.aeskey`（裸 hex）优先于 `media.aes_key`

### 1.2 出站图片（无 uploadmedia 端点，三步流程）
1. `POST /ilink/bot/getuploadurl`（bot_token 鉴权）：`{filekey: <16字节hex>, media_type: 1, to_user_id, rawsize, rawfilemd5: <明文md5 hex>, filesize: <PKCS7填充后>, no_need_thumb: true, aeskey: <裸hex>}` → `upload_param`
2. `POST {CDN}/upload?encrypted_query_param=<upload_param>&filekey=<filekey>`（**必须 POST**），body=AES 密文，`Content-Type: application/octet-stream` → 响应头 **`x-encrypted-param`** 即回引令牌
3. `POST /ilink/bot/sendmessage`：`item_list=[{type: 2, image_item: {media: {encrypt_query_param, aes_key: base64(aeskey_hex.encode("ascii")), encrypt_type: 1}, mid_size: <密文字节数>}}]` + 常规 `context_token`
- ⚠️ 出站 `aes_key` 必须是 **base64(hex字符串)** 而非 base64(原始字节)——编码错则对方看到灰框（hermes 测试锁定的断言）
- 文字说明（caption）作为**独立文本消息先发**

### 1.3 平台约束
- 回复须在用户最后一条消息的 **24 小时窗口**内；仅 1v1 私聊；不能主动发起
- 会话超时（errcode -14）只能重新扫码——现有 `ILinkSessionExpiredError` 处理保持
- CDN 域固定 `https://novac2c.cdn.weixin.qq.com/c2c`；payload 里的 `full_url` 需**域allowlist**（`*.cdn.weixin.qq.com`）防 SSRF
- `channel_version` 升至 2.4.3 可能恢复微信客户端被隐藏的「+」发图按钮（上游 issue 未合入，无害可试，可选项）

## 2. 行为定义（本设计新增）

| 场景 | 行为 |
|---|---|
| 微信用户发图片给 bot | 下载解密 → 走附件管道入库 → ref 随用户消息持久化 → `build_image_blocks` 喂给模型 → 文本回复照常同步回微信；纯图片无文字也可触发 |
| 微信用户发的图片在 Web 端回放 | 历史接口天然带 attachments（已支持）；实时 `channel_message` 广播帧新增 `attachments` 字段，前端并入乐观消息 |
| Web 用户在微信绑定会话发附件 | **不再丢弃**：ref 持久化 + 喂给模型（多模态理解）；同时逐张经三步流程**转发**给微信对端（先文本回复同步、图片随转）；纯图片 Web→微信也允许 |
| 下载/上传失败 | 入站：降级为现有占位文本（不中断轮次）；出站：该图跳过 + 日志 warning，文本回复不受影响 |
| 发送顺序 | 出站：caption/回复文本先发，图片随后逐张发（保持与现有文本 sync 的兼容） |

**废弃的旧行为**（由本设计取代）：微信会话丢弃附件、纯图微信轮错误帧拒绝、`test_wechat_conversation_*` 两测试锁定的"不持久化"行为。

## 3. 实现拆解

### W1 协议层（`channels/wechat_qrcode.py`）
- `ILMessageItem` 模型扩展：`image_media_eqp`（encrypt_query_param）、`image_aes_key_b64`、`image_aeskey_hex`、`image_full_url`、`image_size`、`image_width/height`；`getupdates` 解析器从 `image_item` 填充（key 优先级：`aeskey` hex > `media.aes_key`）
- 新增模块级 AES 工具：`aes_ecb_decrypt(data, key) / aes_ecb_encrypt(data, key)`（PKCS7；key 兼容两种编码——`_parse_aes_key(b64_or_hex)`）
- `ILinkClient.download_media(encrypt_query_param, aes_key, full_url=None) -> bytes`：URL 构造/allowlist → GET → 解密；CDN base 常量 `NOVA_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"`
- `ILinkClient.send_image(user_id, data: bytes, context_token, file_ext="jpg") -> None`：getuploadurl → CDN POST（取 `x-encrypted-param`）→ sendmessage（`aes_key=base64(hex)`）
- 依赖：`pyproject.toml` 新增 `cryptography>=42`（AES-ECB 的 C 实现；本设计解禁多模态期的"无新依赖"约束，理由：纯 Python AES 对 MB 级图片不可接受）

### W2 通道接线（`channels/wechat_channel.py` + `api/websocket.py` + `api/app.py`）
- `wechat_channel.start()`：`self._agent.attachments_root = resolve_attachments_root(config)`（共享 agent 从未接线，微信路径需要；`resolve_attachments_root` 已在 routes/attachments.py）
- `_process_message`：提取图片 item 列表 → 逐张 `download_media` → 写盘（attachments root，yyyy/mm/<uuid>.<ext>）→ `repo.create_attachment` → 组 refs；`text` 为空且无图则跳过；有图走 `handle_incoming(..., attachments=refs)`，下载失败的单张降级占位
- `handle_incoming`：删除非 text stub；签名加 `attachments: list[dict] | None`；空文本 + 有图 → `agent.run("", attachments=refs)`（纯图轮）；微信用户消息的 ref **持久化**（agent.run 已做）
- 出站转发：`websocket.py` `_run_generation` 微信 sync 块——删除附件丢弃逻辑；Web 侧 refs（含 mime/尺寸）非空时，逐张读盘字节 → `wechat_channel.send_image(...)`（try/except 单张失败仅 warning）；文本回复 sync 照旧
- `channel_message` 广播帧新增 `attachments` 字段（入站图片），前端 `useWebSocket.ts` 的 `WsIncoming.channel_message` 映射进乐观消息（小改）
- 删除 T3 的 `WeChat channel does not support image-only messages` 逻辑与对应测试断言，行为改为放行

### W3 测试
- 协议层单测：image_item 解析（含双 key 编码优先级）、AES 加解密往返（手工向量）、download_media（mock httpx + allowlist 拒绝外域）、send_image 三步流（mock httpx，断言 base64(hex) 编码与各字段）
- 集成：微信入站图片全链路（mock download_media → 持久化 ref → LLM 收到图像块）；Web→微信转发（mock send_image）；纯图 Web→微信放行；channel_message 帧带 attachments
- 更新被本设计废弃的两个 T4 测试
- CI 教训：格式化必须用 `uvx ruff@0.16.6` 复核

## 4. 验收
- [ ] 微信用户发图 → bot 文本回复体现图片内容（mock 验证图像块）
- [ ] 入站图片在 Web 端历史与实时广播中可见
- [ ] Web 端微信绑定会话发图 → 图片转发到微信对端 + 模型多模态理解
- [ ] 纯图轮（双向）不再被拒绝
- [ ] 下载/上传失败不中断对话轮次
- [ ] 24h 窗口/1v1 约束写入 send_image 的 docstring 与失败日志
- [ ] 后端全量 pytest 绿；ruff 0.16.6 双检通过；前端测试绿
