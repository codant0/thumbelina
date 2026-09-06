# Thumbelina 检视意见复核报告

- **日期**:2026-09-05(同日晚,对上午检视的复核)
- **复核区间**:原检视基线 `664be57`(multimodal 分支,含未提交改动)→ 当前 `da3f7e8`(main),共 **18 个提交,+6115 / −915 行,51 个文件**
- **区间内主要变更**:① 多模态附件链路补全(`5c27105` WS 协议 + agent 图像块、`97a0498` 微信纯图轮拒绝与去重、`d71605a` 附件 UI 样式 + 双语 i18n、`3db3627` final-review 修复、`7e56930`/`8c01507` 共 1288 行测试);② **全新微信图片收发功能**(`305de14` 设计、`cd006a7` iLink 媒体协议、`bd235b1` 接线、`da3f7e8` QR 热登录修复);③ 文档(`bb65662` 存储重构正式回退注记)、`f8ff9a8` ruff 0.16.6 重排版
- **复核方式**:3 个并行子 agent——A 逐条复核附件/多模态相关 17 项意见;B 逐条复核非附件遗留 18 项意见;C 对从未检视过的微信图片渠道新代码做全量检视。所有结论附当前 HEAD 的 `文件:行号` 证据。
- **状态标记**:✅已修复 / ⚠️部分修复 / ❌未修复 / 🗑️不适用

原报告:[2026-09-05-project-review.md](2026-09-05-project-review.md)(以下"原 §x"均指该文档章节)

---

## 0. 复核结论摘要

**修复集中在"多模态链路搭建"上,原检视的结构性结论基本未被触碰。**

- **附件/多模态 17 项意见**:✅ 完全修复 4(后端全链路 P0、T7 样式、附件 i18n、ObjectURL 撤回项确认完好);⚠️ 部分修复 4;❌ 未修复 9。完全修复率 24%,含部分修复 47%。
- **非附件遗留 18 项意见**:除静态检查外**全部原样**(❌ 16、⚠️ 2)。mypy 仍 133 errors / 44 files(零变化);前端 eslint 1 error→0、tsc 1 error→0(多模态批次顺手修掉)。
- **最重要的正向结果**:原 P0"后端附件链路断链"已**全链路打通**——`WebSocketMessage` 支持附件、空文本+图片放行、附件引用落库、`agent/multimodal.py` 构建图像块、历史回放渲染,且实现质量良好、有测试锁定。
- **最需要警惕的负向变化**:鉴权 fail-open(P0)未修的同时,本批提交把**附件上传/落盘/回读、WS 图片帧、微信媒体解密**全部挂到了这个无鉴权面上——风险敞口比检视时**更大**而非持平。
- **新代码(微信图片渠道,从未检视)发现 2 个 P1**:扫码热登录重建渠道缺 `runtime=` 透传(会话端点/上下文窗口静默退化为全局默认,自定义附件目录时入站图片落错盘);媒体下载无大小上限(绕过"单文件 ≤10MB"不变量)。

### 0.1 修复成绩单

| 类别 | 结果 |
|------|------|
| ✅ 已修复并验证 | 后端多模态全链路(原 P0);附件 UI 全部 CSS 走主题 token,Lightbox 改 fixed 定位(原 UI F1);附件文案 i18n 双语成对 + 一致性测试(原 UI F4);附件"重试"可用且整卡可点(原易用性 6 的一半);eslint/tsc 错误清零 |
| ⚠️ 部分修复 | Enter 门禁(补了 pendingActive 守卫,**仍绕过 hasBlockingAttachments**);error 帧带 conv id(仅 "Invalid attachment"/"Streaming failed" 两类,stopped 帧仍回显客户端 id);Lightbox a11y(Esc/方向键/计数有,焦点管理三件套无);mypy 基线(数量未动,前端两个 error 修掉) |
| ❌ 未修复(原样) | docker-compose 附件卷、鉴权 fail-open 全部 7 子项、FK/WAL/5 engine、run/stream 落库漂移、messages 无 seq、SubagentManager 累计上限、WS 重连、IME 守卫、删除会话无确认、错误静默/伪装空状态、tsconfig strict、API_BASE×9、僵尸层、版本三源、上传端点阻塞 IO 与孤儿文件、粘贴/拖入非图片/灯箱兜底/草稿串扰/n÷4 计数 |
| 🆕 新发现 | 微信渠道 2×P1 + 3×P2 + 若干 P3(§3);修复引入的 4 个 P3(§1.3) |

### 0.2 更新后的优先行动清单(合并排序)

1. **【P0】鉴权 fail-safe**——风险敞口已扩大,附件上传写盘、`/fs` 任意目录列举、微信媒体链路都挂在无鉴权 + `cors_origins=["*"]` 之上;修复时把新端点一并纳入设计。
2. **【P0】compose 补 `THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY=/app/data/attachments`**——同批提交把微信凭据/TODO/HF_HOME 都指进了持久卷,唯独漏了附件;一行配置消除"重建即丢"。
3. **【P1】微信热登录 `swap_channel` 补 `runtime=` 透传**(`runtime_manager.py:216-221`)——新功能自身的接线缺口,静默退化 + 落错盘 + Web 回读 404。
4. **【P1】`download_media` 加大小上限 + `mid_size` 预检**(`wechat_qrcode.py:667-669`)——恢复被绕过的 10MB 不变量。
5. **【P1】InputBox `handleSend` 补 `if (hasBlockingAttachments) return`**,并显式决定流式二次排队是"覆盖"还是"拒绝"(当前覆盖丢消息,且测试表明覆盖是有意设计,需要产品层面确认后改 UI 表达)。
6. **【P2】上传链路 I/O 收口**:`attachments.py` 分块读 + `asyncio.to_thread`(哈希/写盘)+ 入库失败回滚;微信入站 `write_bytes_atomic`/`read_bytes` 同样 `to_thread` 化;`_sniff_image_mime` 未识别时不再兜底 JPEG。
7. **【P2】`send_image` errcode≠0 改抛错**(-14 触发会话过期标记),消除"转发失败记为成功"。
8. **【P2】剩余 UX 长尾打包**:非图片拖入反馈、粘贴支持、灯箱 onError + 焦点管理、切会话草稿语义、n/4 计数、IME `isComposing` 守卫(一行代码,建议与 5 同 PR)。
9. **【P2/决策】存储地基显式化**:Alembic 已正式回退,`PRAGMA foreign_keys/WAL` 与 messages `seq` 不再有计划主题兜底——要么升格为独立小修复(各一处机械改动),要么在 CLAUDE.md 显式记为已接受风险。
10. **【P1/规范】tsconfig 开 strict(实测单独开 0 报错)+ mypy 133 错接 CI 冻结基线**。

---

## 1. 附件 / 多模态链路复核(子 agent A)

复核范围:原报告附件相关 17 项 + 修复提交本身的质量。前端测试实测 **55 文件 / 552 测试全部通过**;`ruff check` 全绿;`npm run lint` 0 errors / 7 warnings(均为既有 exhaustive-deps)。

### 1.1 复核结论总表

| # | 原编号 | 原严重度 | 状态 | 证据(HEAD) | 备注 |
|---|--------|---------|------|-------------|------|
| 1 | §2 P1-1(原 P0) | P0 | ✅ | `api/schemas.py:76-112`、`api/websocket.py:469-519`、`agent/graph.py:902-948,1160,1235`、`agent/multimodal.py:27-125`、`repository/models.py:257-264`、`repository/repository.py:232,328`、`agent/compression/base.py:37,65-86` | 全链路打通:WS schema 附件字段、空文本+图片放行、透传、附件引用落库、图像块构建、历史回放;multimodal.py 质量良好 |
| 2 | §2 P1-2 | P1 | ⚠️ | `InputBox.tsx:251-283,294-298`、`useWebSocket.ts:392-401` | 已补非流式 `pendingActive` 守卫(纯图片排队也被挡);**未修**:handleSend 仍不检查 hasBlockingAttachments(Enter 静默丢上传中附件);流式分支二次 Enter 仍覆盖排队消息(useWebSocket.ts:394-400 注释明言"覆盖旧的待发内容",InputBox.test.tsx:109 表明是有意设计) |
| 3 | §2 P2-3 | P2 | ❌ | `api/routes/attachments.py:189-196,201,208-209` | 仍整读后验长;同步 sha256 + fsync 写盘在事件循环内 |
| 4 | §2 P2-4 | P2 | ❌ | `api/routes/attachments.py:209-218` | 写盘成功 → create_attachment 无 try/except 回滚 |
| 5 | §2 P2-6 | P2 | ⚠️ | `api/websocket.py:402-412,421,436,441,490-497` | "Invalid attachment"/"Streaming failed" 帧已带解析后 cid;stopped 帧仍回显客户端传入 id;"Message too large"/"Invalid JSON"/"Conversation not found"/"Invalid message format"/"Empty message" 均无 conv id;stop 无归属校验(注释明示单用户取舍) |
| 6 | §2 P3-3 | P3 | ❌ | `useAttachments.ts:98-107` | 无效文件仍计入配额、整批误拒、提示掩盖类型错误 |
| 7 | §2 P3-4 | P3 | ❌ | `api/attachments.ts:22-25` | fetch 仍无 AbortController/超时 |
| 8 | §4 F1 | P1 | ✅ | `styles/chat.css:1241-1641`、`main.tsx:6`、`InputBox.visual.test.tsx:149-154` | 全部类名有定义且走主题 token,含窄屏与 prefers-reduced-motion 降级;Lightbox fixed+inset:0 定位,文档流问题消除;视觉断言扩展到 attachment 类 |
| 9 | §4 F4 | P2 | ✅ | `InputBox.tsx:360` 等、`locales/en.json`/`zh-CN.json:292-309`、`locales.test.ts:30-53` | t() 全覆盖,16 组键双语成对 + 一致性测试 |
| 10 | §4 F5 | P2 | ⚠️ | `AttachmentLightbox.tsx:35-61` | Esc/方向键/X/aria-modal/计数已有;仍无焦点陷阱、初始焦点、焦点恢复;遮罩点击不关闭 |
| 11 | §5 发现 4 | P2 | ❌ | `InputBox.tsx:400-409` | textarea 仍无 onPaste,全 Chat 目录无 onPaste |
| 12 | §5 发现 5 | P2 | ❌ | `hooks/useDropZone.ts:9-13,54-60` | 非图片仍静默过滤,蒙层承诺后零反馈 |
| 13 | §5 发现 6 | P2 | ⚠️ | `InputBox.tsx:74-104,426-432`、`useAttachments.ts:129-136` | "重试"已可用(整卡可点+回归测试);阻塞原因仍仅按钮 title,无行内/aria-live 提示 |
| 14 | §5 发现 7 | P2 | ❌ | `AttachmentLightbox.tsx:63`、`chat.css:1534-1540` | 仍无缩放;灯箱 img 仍无 onError(消息内缩略图有) |
| 15 | §5 发现 8 | P2 | ❌ | `ChatWindow.tsx:296-302,426` | 切会话仍清附件不清正文,InputBox 无 key,草稿可误发 |
| 16 | §5 发现 13 | P3 | ❌ | `InputBox.tsx:358-373` | 仍无 n/4 常驻计数 |
| 17 | §6.3 撤回项 | — | ✅完好 | `InputBox.tsx:163-170,174-189,233-241` | previewUrlsRef 唯一写入点与三条回收路径均完好 |

### 1.2 修复链路的质量确认(项 1 详情)

多模态修复不是"补字段"式的最小改动,而是完整落地了设计文档 B3/B4/B5:WS schema 新增附件引用模型(含服务端解析与富引用);`_run_generation` 透传;`_persist_message` 落 `{id,mime,width,height,alt}` 引用;新模块 `agent/multimodal.py` 构建图像内容块并管理 token placeholder;`agent/compression` 感知图像块(压缩时保留);历史回放 `parseHistoryAttachments` 渲染。`97a0498` 的附件 id 去重与 `3db3627` 的富引用补全有双向测试。**注意**:97a0498 的"微信纯图片轮拒绝"实现正确但已被后续设计变更(`bd235b1`+`da3f7e8`,设计 v2.1)有意取代——现微信绑定会话接受附件并逐张转发,纯图片轮放行。

### 1.3 修复引入的新问题(4 项,均 P3)

| 严重度 | 位置 | 描述 | 建议 |
|---|---|---|---|
| P3 | `agent/graph.py:909-910` | 纯图片轮且图像块全部解析失败时回退 `HumanMessage(content=user_input)`,而 user_input 为空串 → 空文本消息发给模型(部分 provider 会 400),且该轮已以空文本落库,历史永久残留空消息 | blocks 为空且文本为空时不启动生成,走 WS 错误帧 |
| P3 | `agent/multimodal.py:109-124` | 事件循环内同步 `read_bytes` + base64 编码(最多 4×10MB);同类 `websocket.py:130`(微信转发 read_bytes)、`wechat_channel.py:608`(同步写盘) | 一律 `asyncio.to_thread` 包裹 |
| P3 | `agent/multimodal.py:36`(docstring) | "单文件 ≤10MB 由上传端保证"仅对 REST 成立;微信入站走独立落库路径(wechat_channel.py:597-616,无 10MB 上限),超大声明的入站图整体 base64 进 prompt | build_image_blocks 内复核 `record["size"]`,超限跳过(与 §3 P1-2 同根) |
| P3 | `MessageList.tsx:223` | 富引用设计保留重复 id(协议层"保持原顺序与重复项"),渲染 `key={att.id}` → 重复 id 触发 React duplicate key(UI 管道当前产生不了,协议层可注入) | key 改 `${att.id}-${i}` 或 WS 层去重 |

---

## 2. 非附件遗留意见复核(子 agent B)

复核 18 项非附件类意见:**❌ 未修复 16、⚠️ 部分修复 2,无一项完全修复**。18 个提交未触碰原检视的核心结论。

### 2.1 复核结论总表

| # | 原编号 | 状态 | 证据(HEAD) | 备注 |
|---|--------|------|-------------|------|
| 1 | §2 P0-1 | ❌ | `docker-compose.yml:20-41`、`docker-compose.nas.yml:28-45` 均无 `THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY`;CWD 解析仍在 `attachments.py:150` | 同批提交已把微信凭据/TODO/HF_HOME 指进 `/app/data` 卷,唯独漏附件。局部改善:新增 `resolve_attachments_root()` 统一上传与 WS 读侧(`websocket.py:341`) |
| 2 | §1 P0-1/2/3/4(鉴权) | ❌ | `_AuthMiddleware` 仍 BaseHTTPMiddleware 仅 http scope(`app.py:25,99`);密钥缺失时中间件根本不挂载(`app.py:988`);WS 无条件 accept(`websocket.py:329`);前端 Authorization 0 处;`/fs` 无白名单(`fs.py:43-56`);`/data/all?confirm=true` 仍一参清库(`data.py:86-102`);`/config/export` 不脱敏(`config.py:338-355`,且 `tools.web_search.api_key` 明文入库 `runtime_manager.py:371-372`);`cors_origins` 默认仍 `["*"]`(`config/models.py:347-350`) | **7 个子项全部原样;且附件/微信媒体链路使无鉴权面扩大** |
| 3 | §1 P0-4a(FK/WAL/engine) | ❌ | `repository/db.py:13-29` 无任何 PRAGMA;5 处独立 engine 仍在(config_repo:58、feedback_repo:59、repository:84、skills/repository:27、skills/composition_repo:26) | 计划文档已把存储统一主题标记回退——从"等计划"变成"无主债务" |
| 4 | §1 #13(run/stream 漂移) | ❌ | `graph.py:1204`(run 不带 reasoning)vs `1348-1350`(stream 带);`startswith("Error")` 仍在 `graph.py:775`;`is` 契约仍在 `557-558,736-737`(已在 compression/base.py:172-174 文档化,轻微缓解) | 本批 graph.py 改动全是附件参数穿线 |
| 5 | §1 #5(Provider 重接线) | ❌ | 无 ProviderRegistry;散落 4 处依旧:`graph.py:415`、`runtime_manager.py:57-121`、`routes/config.py:215-244`、`app.py:745-783` | 原样 |
| 6 | §1 #10(messages seq) | ❌ | Message 模型无 seq(`models.py:215-255`);`repository.py:217-221` 仅按 created_at 排序 | `models.py:356` 的 seq 属 TrajectoryEvent,勿混淆 |
| 7 | §2 P1-4(SubagentManager) | ❌ | `_agents` 无终态清理(`manager.py:46,112-117`);create_task 不持引用(:145);_execute 无条件置 COMPLETED(:161-165);cancel 不取消底层任务(:203-212) | 行号漂移,行为原样 |
| 8 | §2 P1-5 / §5-1(WS 重连) | ❌ | `useWebSocket.ts:774-792` 无重连;`ChatWindow.tsx:428` 断线仍整体禁用 | 本批新增 90s 超时与待发队列,重连缺失原样 |
| 9 | §5-2(IME) | ❌ | `InputBox.tsx:278-283` 无 isComposing;frontend/src 内 composition 零匹配 | 一行守卫仍未加 |
| 10 | §5-3/15(删除确认) | ❌ | `Sidebar.tsx:140-148` → `App.tsx:227-236` 直删;ConfirmDialog/window.confirm/两段式三套并存 | 原样 |
| 11 | §5-9(错误静默) | ⚠️ | 全前端 `catch { /* ignore */ }` 计 61 处;Toast 仍是页面级局部实现,无全局总线 | 轻微改善:Coder 页新增 coderError 不再伪装空列表(`App.tsx:159-172`);聊天侧未跟进 |
| 12 | §3 P1-1(tsconfig strict) | ❌ | `tsconfig.app.json`/`tsconfig.node.json` 均无 strict | 原样 |
| 13 | §3 静态检查 | ⚠️ | mypy **133 errors / 44 files(零变化)**;ruff check/format 全过;eslint **0 errors** 7 warnings(原 1E);tsc **0 errors**(原 1E) | 前端两个 error 被多模态批次顺手修掉 |
| 14 | §3 P2-4(API 复制) | ❌ | API_BASE 仍 9 个文件(本批还新增第 9 个 attachments.ts);client.ts 不存在;api 目录外 22 处裸 fetch | 原样 |
| 15 | §1 #11/#16(migrations/notifications) | ⚠️ | migrations/ 目录已删(bb65662);但 tests/test_migrations/ 留下只含 `__pycache__` 的空壳;`notifications.py` 109 行仍在,app.py:60,556,586 实例化并广播,**全库无 subscribe() 调用方**——广播发给 0 个订阅者 | 僵尸层坐实(计划文档 D8 也自注"零接线") |
| 16 | §1 #12(backup/导出) | ❌ | backup/ 死代码仍在;`/data/export` 仍两次顺序读拼 dict、无快照 | 原样 |
| 17 | §1 其他(版本/botpy/mypy 版本) | ❌ | VERSION=v0.0.3 vs pyproject=0.1.0 vs app.py:961,1020 硬编码;botpy 仍未声明;python_version 3.13 vs requires-python >=3.11 | 三处漂移原样 |
| 18 | §5-11(i18n 硬编码非附件类) | ❌ | `useWebSocket.ts:253,313,502` 英文系统消息;任务状态枚举直出(TaskManager.tsx:181,262,321);"gpt-4o" 散布 4 处;main.py:81 端口;Sidebar.tsx:7 与 wechat_channel.py:33 两端硬编码 '微信Clawbot' 靠字符串耦合 | 原样 |

### 2.2 计划文档 / 依赖的实质变化(影响原报告"计划差距对照表")

- **存储重构正式回退**:`bb65662` 在 `docs/plans/2026-08-29-architecture-refactoring-plan.md` 顶部加注记——主题二"存储地基统一"(D1-D12,含全部 Alembic 方案)已于 2026-08-30 回退不再实施;schema 演进长期走 `create_all + ensure_schema()`;配套 751 行设计文档整篇删除;`2026-08-30-event-timer-tasks-design.md` D3 明言"一库多 engine 是既有债务,不再新增"。
- **影响**:原报告对照表中主题二的"⚠️ 回退"状态已被官方确认;代价是 §2.1 第 3、6 条(PRAGMA、messages seq)**不再有计划主题兜底**,需要显式决策(修复或记为已接受风险)。
- **依赖**:pyproject 仅新增 `cryptography>=42`(微信 iLink 媒体解密);botpy 仍未声明。
- **新规格文档**:`docs/specs/2026-09-04-multimodal-chat-design.md`(496 行,binding authority)、`docs/specs/2026-09-05-wechat-image-channel-design.md`(71 行)。

---

## 3. 新增微信图片渠道检视(子 agent C,首次检视)

### 3.1 实现速写

**入站(微信用户 → bot)**:`_poll_loop`(主事件循环内的 asyncio.Task,无独立线程)→ getupdates 长轮询解析 image_item → `_collect_image_attachments` 逐张 `download_media`(CDN GET + AES-128-ECB/PKCS7 解密)→ 魔数嗅探 mime → 原子落盘 `attachments_root/yyyy/mm/<uuid>.<ext>` → 入库 → 组 refs → 复用共享 chat 管线(`per_conversation_lock` + `apply_conversation_runtime` + `resolve_run_window` + `build_image_blocks`)→ 文本回复发回微信 + 5 参回调广播 `channel_message` 帧到 Web。失败单张降级占位文本,不中断轮次。

**出站(Web → 微信对端)**:`_run_generation` 持锁生成 → done 帧后若为微信绑定会话:文本先 `send_message`,再逐张校验(mime image/*、路径穿越、DB 记录)→ `send_image` 三步流(getuploadurl → CDN POST 密文 → sendmessage 引用)。单张失败仅 warning。

### 3.2 发现清单

**W-1【P1】扫码热登录重建渠道缺 `runtime=`,会话运行时接线整体退化** — `config/runtime_manager.py:216-221`
`swap_channel` 构造 `WeChatChannel(...)` 未传 `runtime=`。经 QR 扫码热启用(而非重启)时:① `wechat_channel.py:414` 判空跳过 `apply_conversation_runtime`/`resolve_run_window` → 微信回复用**全局默认端点**而非会话绑定端点,上下文窗口压缩失效(启动路径 `app.py:819-821` 已修,热登录路径漏了);② `wechat_channel.py:122-125` 接线 `attachments_root` 时 `app_state=None` → 回退 `cwd/attachments`,自定义附件目录时入站图片**落错盘**,Web 历史缩略图 404。
**修复**:`swap_channel` 增加 runtime 参数透传(参照 app.py 的 SimpleNamespace 模式);补热登录路径回归测试(现有测试 patch 了渠道类,未覆盖构造参数)。

**W-2【P1】媒体下载无大小上限,绕过"单文件 ≤10MB"不变量** — `wechat_qrcode.py:667-669`
`resp = await client.get(url)` 全量缓冲响应体,无 Content-Length/累计上限、无流式;`multimodal.py:34-36` 明写"≤10MB 由上传端保证,这里不重复限制"——微信入站绕过上传端点,不变量被打破。已解析的 `image_size`(mid_size,`wechat_qrcode.py:495`)从未用于校验。超大媒体依次经历全量缓冲 → AES 解密 → sha256 → 落盘 → base64(≈1.33×)进 prompt,内存/CPU 峰值再被 `per_conversation_lock` 串行化放大。
**修复**:`download_media` 加 `max_bytes`(httpx stream 累计计数超限抛 `ILinkMediaError`),下载前用 mid_size 预检;超限走既有占位降级。

**W-3【P2】`send_image` 第三步 errcode≠0 仅 warning 不抛错,失败静默记为成功** — `wechat_qrcode.py:858-866`
iLink 返回 errcode≠0(含 -14 会话过期)时图片实际未送达,但 `websocket.py:132-137` 记录转发成功、Web 用户无感知;-14 不置 `needs_authentication`,渠道状态不更新。与既有 `send_message` 行为一致且有测试锁定,属沿袭而非疏忽。
**修复**:errcode==-14 抛 `ILinkSessionExpiredError`,其余抛 `ILinkMediaError`——调用方均已 fail-soft,不会破坏文本回复。

**W-4【P2】转发目标与 context_token 跨用户竞态** — `websocket.py:263-271` + `wechat_channel.py:675-676`
生成期间(可数十秒)另一微信用户来消息会改写 `_last_wechat_user_id`/`_last_context_token` → Web 用户的回复文本与图片被转发给**错误的微信用户**(共享"微信Clawbot"会话本就多用户混流,图片转发放大了信息外泄面)。
**修复**:短期在生成前快照 user/token;中期按微信用户拆分会话。待确认:实际部署是否单微信用户。

**W-5【P2】事件循环内同步 IO/CPU** — `wechat_channel.py:597-615`(同步写盘+fsync)、`websocket.py:130`(同步 read_bytes)
微信渠道与 QQ 不同,跑在 FastAPI 主事件循环上(无独立线程),MB 级图片的解密/哈希/fsync/读盘会停顿整个 loop。与 REST 上传路由同模式(§1.1 项 3),建议一并 `asyncio.to_thread` 收口。

**W-6【P2】下载内容类型校验仅魔数嗅探,未识别一律兜底 JPEG 入库** — `wechat_channel.py:45-59`
与 REST 上传的严格白名单(415)不同源:任何无法识别的内容都会按 `image/jpeg` 落盘入库并 base64 进模型。建议未识别时计入 failed 走占位降级。

**P3(摘要)**
- **W-7** 降级占位文案过时:"[image message received -- currently only text is supported]"(wechat_channel.py:42)——图片已支持,该文案进 prompt 且显示在 Web 气泡,自相矛盾。
- **W-8** 入站纯图轮模型空回复时 `channel_message` 实时广播被整体跳过(wechat_channel.py:436 `... and response and ...`),Web 端看不到入站图片(刷新后可见),与 da3f7e8 出站"空回复仍转发"的修正精神不一致。
- **W-9** 跨模块直读私有成员(`_last_wechat_user_id`、`_agent`、`_needs_authentication` 等 5 处),建议暴露只读属性。
- **W-10** `image_size`(mid_size)解析后从未消费(wechat_qrcode.py:428,495)——要么删掉,要么落地为 W-2 的预检。
- **W-11** 出站三步流无重试,步骤 2/3 之间失败留 CDN 孤儿媒体(设计 §2 明确"跳过+warning",符合规格,记录为已知取舍)。
- **W-12** 微信入站落盘与入库非原子,DB 失败留孤儿文件(与 REST 上传同模式,预先存在)。

### 3.3 已排查无问题的可疑点

SSRF 防线完整(https + `.cdn.weixin.qq.com` 后缀 allowlist,lookalike host 有专项测试,签名令牌不进日志,无重定向绕过);路径穿越两侧(入站服务端全控、出站 `is_relative_to` 校验)与 REST 同规则;AES key 三编码兼容且异常信息不含 key 材料,base64(hex) gotcha 有双向断言;**无 QQ 式双事件循环问题**(微信在主 loop,代价即 W-5);入站与 Web 轮持共享 `per_conversation_lock` 不会交错写检查点;5-arg 回调迁移全仓仅两处且均有测试锁定;da3f7e8 空回复判断正确;无裸 except,CancelledError 显式 re-raise;`cryptography>=42` 已入 pyproject + uv.lock。**微信路径是对已合入多模态链路的复用而非复制,架构一致性良好。**

### 3.4 测试覆盖评价

新增约 930 行测试质量较高:协议层(key 三编码、AES 手工向量、allowlist 拒绝、三步流全载荷断言)与集成层(入站全链路、占位降级、纯图轮、空回复转发回归、非图跳过、5-arg 回调)均有锁定。**缺口**:热登录 swap 路径的接线断言、超大媒体、并发转发竞态、非 JPEG 魔数兜底行为。

---

## 4. 复核总结

**一句话**:这一批 18 个提交把上午检视中"最疼的一条"(后端多模态断链)完整修掉且质量过硬,把 UI 侧 T7 也收了尾;但原检视指出的**结构性问题(鉴权、部署持久化、存储地基、异常路径静默)一项都没动**,并且新增的微信图片渠道自带 2 个 P1 接线/边界缺口,同时无鉴权攻击面随新功能扩大。

**值得肯定的**:多模态全链路的实现与 1288 行测试;附件 UI 样式全部走主题 token 并有视觉回归;i18n 键成对 + 一致性测试;微信渠道复用共享 chat 管线与 filestore 原子写,未另起炉灶;存储重构回退以正式注记 + 删除设计文档的方式显式化(决策纪律好)。

**下一步建议**:按 §0.2 的 10 项清单执行——其中第 1、2 项是上午报告的遗留 P0(优先级因攻击面扩大而升高),第 3、4 项是本批新代码的 P1,第 5-8 项多为低成本高收益的收口,第 9 项需要一次显式决策。

*本报告由 3 个并行复核子 agent 的结论整合而成;所有行号对应当前 HEAD `da3f7e8`。原报告结论除本文标注的修复/漂移外均维持有效。*
