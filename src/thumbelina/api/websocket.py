"""WebSocket handler for real-time chat."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.routes.attachments import resolve_attachments_root
from thumbelina.api.routes.chat import (
    _apply_conversation_endpoint,
    apply_conversation_runtime,
    resolve_run_window,
)
from thumbelina.api.schemas import WebSocketMessage
from thumbelina.concurrency import per_conversation_lock
from thumbelina.subagents.base import SubagentEvent
from thumbelina.subagents.manager import SubagentManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# WebSocket message size limit (1MB)
MAX_MESSAGE_SIZE = 1024 * 1024

# Connected chat WebSocket clients (used for cross-channel message broadcast)
_chat_ws_clients: set[WebSocket] = set()


async def broadcast_chat_message(message: dict[str, Any]) -> None:
    """Broadcast a message to all connected chat WebSocket clients.

    Used by channel integrations (e.g. WeChat) to push incoming messages
    to the frontend in real-time.
    """
    failed: list[WebSocket] = []
    for ws in _chat_ws_clients:
        try:
            await ws.send_json(message)
        except Exception:
            failed.append(ws)
    for ws in failed:
        _chat_ws_clients.discard(ws)
    if _chat_ws_clients:
        logger.debug("Broadcast to %d client(s): %s", len(_chat_ws_clients), list(message.keys()))


def _enrich_attachment_refs(
    refs: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """把上行原始附件引用 ``[{id, alt?}]`` 补全为持久化形态(设计 §3.2/§4.2)。

    ``mime``/``width``/``height`` 取自附件记录(存在性校验时已批量取回),
    ``alt`` 保留上行值;保持原顺序与重复项。``width``/``height`` 为空的记录
    省略对应键;id 无法解析或记录缺失的引用原样保留(交由下游容错)。
    """
    enriched: list[dict[str, Any]] = []
    for ref in refs:
        attachment_id = ref.get("id")
        record = records.get(attachment_id) if isinstance(attachment_id, str) else None
        if record is None:
            enriched.append(dict(ref))
            continue
        item: dict[str, Any] = {"id": attachment_id, "mime": record.get("mime")}
        if record.get("width") is not None:
            item["width"] = record["width"]
        if record.get("height") is not None:
            item["height"] = record["height"]
        if ref.get("alt") is not None:
            item["alt"] = ref["alt"]
        enriched.append(item)
    return enriched


async def _forward_attachments_to_wechat(
    websocket: WebSocket,
    agent: ThumbelinaAgent,
    wechat_channel: Any,
    wechat_user_id: str,
    context_token: str,
    attachments: list[dict[str, Any]],
) -> None:
    """把本轮 Web 侧附件逐张转发给微信对端(设计 §2)。

    调用时机:回复文本已经 :meth:`WeChatChannel.send_message` 同步之后
    (协议要求文字说明先于图片发送,见 ``ILinkClient.send_image``)。
    每张独立 fail-soft:记录缺失、文件缺失、路径穿越或发送失败只
    ``logger.warning`` 并继续下一张,不影响文本回复与后续图片。
    """
    from thumbelina.api.routes.attachments import resolve_attachments_root

    root = resolve_attachments_root(getattr(websocket.app.state, "config", None))
    resolved_root = root.resolve()
    repository = agent.repository_manager
    for ref in attachments:
        attachment_id = ref.get("id") if isinstance(ref, dict) else None
        if not isinstance(attachment_id, str) or not attachment_id:
            continue
        try:
            if repository is None:
                raise ValueError("no repository manager")
            record = await repository.get_attachment(attachment_id)
            if record is None:
                raise ValueError("attachment record not found")
            relative_path = record.get("relative_path")
            if not isinstance(relative_path, str) or not relative_path:
                raise ValueError("attachment record has no relative_path")
            # 路径穿越防护:与上传/回读路由同规则,逃逸附件根目录即拒绝。
            full = (root / relative_path).resolve()
            if not full.is_relative_to(resolved_root):
                raise ValueError(f"path escapes attachments root: {relative_path}")
            data = full.read_bytes()
            await wechat_channel.send_image(wechat_user_id, data, context_token=context_token)
            logger.info(
                "Forwarded attachment %s (mime=%s) to WeChat user %s",
                attachment_id,
                ref.get("mime") or record.get("mime"),
                wechat_user_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to forward attachment %s to WeChat (skipped): %s",
                attachment_id,
                exc,
            )


async def _run_generation(
    websocket: WebSocket,
    agent: ThumbelinaAgent,
    message: str,
    cid: str | None,
    active_conv_ref: dict[str, str | None],
    attachments: list[dict[str, object]] | None = None,
) -> None:
    """在独立 asyncio.Task 中执行一轮生成（流式或非流式）。

    只应被 ``asyncio.create_task`` 包裹调用；函数内部自己获取
    ``per_conversation_lock(cid)``，保持跨入口的会话级串行化。

    ``task.cancel()`` 取消时：流式分支 ``async for agent.stream(...)`` 会
    抛 ``CancelledError`` 且被原样向上传播（不吞），因此取消生效。部分
    响应已通过前面的 ``yield`` 发给前端，但 assistant 消息不会落库
    （``stream`` 只在完整结束时才 ``_persist_message``）—— 这是可接受的：
    partial 不落库。非流式分支（``agent.run``）同样被 cancel 中断。

    ``active_conv_ref`` 是 ``websocket_chat`` 持有的可变容器,被
    subagent listener 用来读取"本轮正在生成的会话 ID",以决定把事件推给
    哪个连接、避免跨会话串话。

    ``attachments`` 是可选的图像附件引用(``[{id, mime, width, height, alt?}]``,
    已由 ``websocket_chat`` 按设计 §3.2/§4.2 用附件记录补全),透传给
    ``agent.stream``/``agent.run``。微信绑定的会话同样接受附件(设计 §2):
    refs 随用户消息持久化并组装图像块喂给模型;回复完成后逐张经三步流程
    转发给微信对端(见下方 WeChat sync 块)。纯图片轮(文本空白 + 有图)
    照常生成,不再拒绝。
    """
    # 在本轮范围内,subagent listener 能从 active_conv_ref 读到本次 cid,
    # 因此即便 listener 注册在 connect 时,它仍能正确路由。
    if cid:
        active_conv_ref["value"] = cid
    async with per_conversation_lock(cid):
        if cid:
            agent.current_conversation_id = cid
            # 应用会话的端点与角色（与 HTTP / 通道共用同一套逻辑）
            await apply_conversation_runtime(websocket, agent, cid)

        # 解析会话的上下文窗口（会话端点 → 全局活跃端点 →
        # llm.context_window），供压缩阶段使用。
        window_tokens = await resolve_run_window(websocket, agent, cid)

        # Check if this is the WeChat conversation using the cached ID
        wechat_cid = getattr(websocket.app.state, "wechat_conversation_id", None)
        is_wechat_conversation = cid and wechat_cid and cid == wechat_cid

        if is_wechat_conversation:
            wechat_channel = getattr(websocket.app.state, "wechat_channel", None)
            if wechat_channel is not None:
                try:
                    # Apply the conversation's endpoint to the WeChat channel agent
                    await _apply_conversation_endpoint(websocket, wechat_channel._agent, cid)
                except Exception as exc:
                    logger.warning("Failed to apply WeChat endpoint: %s", exc)

        # 微信绑定的会话不再丢弃附件(设计 §2 废弃旧行为):refs 随用户
        # 消息持久化、图像块喂给模型,回复完成后逐张转发微信对端。纯图片
        # 轮(文本空白 + 有图)照常生成。

        # Use streaming for frontend, regardless of WeChat binding
        streaming = websocket.app.state.config.llm.streaming_enabled
        full_response = ""
        if streaming:
            try:
                async for event in agent.stream(
                    message, context_window_tokens=window_tokens, attachments=attachments
                ):
                    text = event["text"]
                    if event["type"] == "reasoning":
                        await websocket.send_json(
                            {
                                "chunk": text,
                                "chunk_type": "reasoning",
                                "conversation_id": cid,
                            }
                        )
                    else:
                        full_response += text
                        await websocket.send_json({"chunk": text, "conversation_id": cid})
            except asyncio.CancelledError:
                # 取消必须原样传播：被 stop 打断时任务被中断，部分响应
                # 已发出但不会落库。不要让普通的异常处理吞掉它。
                raise
            except Exception as exc:
                # 流式失败时不再用同一线程重跑：用户消息已在
                # agent.stream() 开头持久化并写入检查点，重跑会重复写入
                # 消息与状态。直接向客户端报告错误，已保留的消息让用户可
                # 重发。
                logger.warning("Streaming failed for conversation %s: %s", cid, exc)
                await websocket.send_json(
                    {"error": f"Streaming failed: {exc}", "conversation_id": cid}
                )
                return
        else:
            full_response = await agent.run(
                message, context_window_tokens=window_tokens, attachments=attachments
            )
            await websocket.send_json({"response": full_response, "conversation_id": cid})

        await websocket.send_json(
            {
                "done": True,
                "conversation_id": cid,
                "streaming_mode": streaming,
            }
        )

        # Sync to WeChat if this is a WeChat conversation
        if is_wechat_conversation and full_response:
            wechat_channel = getattr(websocket.app.state, "wechat_channel", None)
            if wechat_channel is not None:
                logger.info("Sending frontend message response to WeChat")
                try:
                    last_wechat_user = getattr(wechat_channel, "_last_wechat_user_id", None)
                    last_context_token = getattr(wechat_channel, "_last_context_token", "")

                    if last_wechat_user:
                        await wechat_channel.send_message(
                            last_wechat_user,
                            full_response,
                            context_token=last_context_token,
                        )
                        logger.info("Sent response to WeChat user %s", last_wechat_user)

                        # 设计 §2:回复文本先发,本轮 Web 侧附件图片随后逐张
                        # 经三步流程转发;单张失败仅 warning,不影响文本回复。
                        if attachments:
                            await _forward_attachments_to_wechat(
                                websocket,
                                agent,
                                wechat_channel,
                                last_wechat_user,
                                last_context_token,
                                attachments,
                            )
                    else:
                        logger.warning("No WeChat user ID available to send response to")
                except Exception as send_exc:
                    logger.warning("Failed to send response to WeChat: %s", send_exc)


async def _wait_task_cleared(task: asyncio.Task[Any] | None) -> None:
    """等待 *task* 结束并清理引用，吞掉取消/异常。

    连接关闭或被 stop 打断后，以及下一轮普通消息开始前，都通过它回收
    前一个进行中的生成任务。任务可能因正常完成、被取消或出错而结束，
    三种情况都视为"清理"，绝不向上传播。
    """
    if task is None:
        return
    if not task.done():
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Generation task finished with an error", exc_info=True)


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat.

    Accepts JSON messages with a ``message`` field and responds with a JSON
    object containing a ``response`` field. 还支持 ``{"stop": true}``
    消息，用于取消当前正在生成的轮次。

    生成在独立的 :class:`asyncio.Task` 中运行，主循环持续 ``receive_text()``
    以接收 stop —— 因此流式进行中也能收到并响应中断。每连接保持串行：
    下一轮普通消息启动前先等待当前轮结束；跨连接仍由
    ``per_conversation_lock`` 串行化同一会话。
    """
    await websocket.accept()
    _chat_ws_clients.add(websocket)
    logger.debug("WebSocket client connected (total: %d)", len(_chat_ws_clients))

    shared_agent: ThumbelinaAgent = websocket.app.state.agent

    # Clone the agent per connection to isolate conversation state
    agent = shared_agent.clone()

    # 附件根目录接线(Task B3):与上传路由同源解析(绝对路径直接用,
    # 相对路径基于工作目录,config 缺失回退默认目录),克隆实例据此在
    # _build_initial_messages 中读取附件字节构建图像块。
    agent.attachments_root = resolve_attachments_root(getattr(websocket.app.state, "config", None))

    # Conversation is created lazily on first message, not on connect.
    default_conversation_id: str | None = None
    # 当前进行中的生成任务（可为 None）。每个连接至多一个在跑。
    current_task: asyncio.Task[Any] | None = None

    # Subagent 事件桥接:在 connect 时一次性注册 listener,把 Subagent
    # 生命周期事件推给当前连接。listener 用 active_conv_ref 拿到本轮
    # 正在跑的 conversation id,只有匹配 cid 才发送,避免跨会话串话。
    active_conv_ref: dict[str, str | None] = {"value": None}
    subagent_manager: SubagentManager | None = getattr(
        websocket.app.state, "subagent_manager", None
    )
    unsubscribe_subagent: Callable[[], None] | None = None

    async def _on_subagent_event(event: SubagentEvent) -> None:
        target_cid = active_conv_ref["value"]
        if not target_cid:
            return
        try:
            await websocket.send_json(
                {
                    "subagent_event": {
                        "type": event.type,
                        "id": event.id,
                        "task": event.task,
                        "status": event.status.value,
                        "result": event.result,
                        "error": event.error,
                        "started_at": event.started_at,
                        "finished_at": event.finished_at,
                    },
                    "conversation_id": target_cid,
                }
            )
        except Exception:
            # 连接已断开 / 写入失败 — listener 会在 finally 中被取消,
            # 这里吞掉避免打断 manager 循环。
            logger.debug("subagent_event push failed; will be unsubscribed")

    if subagent_manager is not None:
        unsubscribe_subagent = subagent_manager.add_listener(_on_subagent_event)

    try:
        while True:
            raw_text = await websocket.receive_text()

            if len(raw_text.encode("utf-8")) > MAX_MESSAGE_SIZE:
                await websocket.send_json({"error": "Message too large"})
                continue

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            # 停止当前生成。stop 消息不含 message 字段，因此必须在
            # switch_conversation / Pydantic 校验之前单独判断，避免被
            # WebSocketMessage.model_validate 拒绝或触发 Empty message。
            if isinstance(data, dict) and data.get("stop") is True:
                if current_task is not None and not current_task.done():
                    current_task.cancel()
                    await _wait_task_cleared(current_task)
                current_task = None
                await websocket.send_json(
                    {
                        "stopped": True,
                        "conversation_id": data.get("conversation_id"),
                    }
                )
                continue

            # Handle conversation switch (no message payload)
            if "switch_conversation" in data:
                new_cid = data["switch_conversation"]
                if new_cid and agent.repository_manager:
                    existing = await agent.repository_manager.get_conversation(new_cid)
                    if existing is None:
                        await websocket.send_json({"error": f"Conversation not found: {new_cid}"})
                        continue
                default_conversation_id = new_cid
                await websocket.send_json(
                    {
                        "conversation_switched": True,
                        "conversation_id": new_cid,
                    }
                )
                continue

            # Validate incoming message via Pydantic schema
            try:
                parsed = WebSocketMessage.model_validate(data)
            except ValidationError:
                await websocket.send_json({"error": "Invalid message format"})
                continue

            # 纯文本或纯图片至少其一;守卫放宽以放行纯图片消息(Task B3)。
            if not parsed.message.strip() and not parsed.attachments:
                await websocket.send_json({"error": "Empty message"})
                continue

            # 每连接串行：启动下一轮前先等当前轮结束（若仍在进行）。
            # 主循环此刻已拿到这条消息，等待不会再阻塞 receive_text，
            # 因此下一帧仍能收到 stop。
            if current_task is not None:
                await _wait_task_cleared(current_task)
                current_task = None

            # Use client-supplied conversation_id, or fall back to default.
            cid = parsed.conversation_id or default_conversation_id
            if not cid and agent.repository_manager:
                cid = await agent.repository_manager.create_conversation()
                default_conversation_id = cid
                await websocket.send_json({"conversation_created": cid})
            if cid and agent.repository_manager:
                existing = await agent.repository_manager.get_conversation(cid)
                if existing is None:
                    await websocket.send_json({"error": f"Conversation not found: {cid}"})
                    continue

            # 附件存在性校验(Task B3,无用户体系不做归属校验):任何 id
            # 在 attachments 表中缺失 → 错误帧且不开新一轮。仓储异常按
            # 校验失败处理(全部视为缺失),不中断连接。
            # 错误帧携带解析后的 cid(而非 parsed.conversation_id):首条
            # 消息在服务端新建会话时 parsed 值为 None,前端拿不到会话 id
            # 就无法清除等待态,会白等到 90s 超时。
            attachment_records: dict[str, dict[str, Any]] = {}
            parsed_attachments_enriched = parsed.attachments
            if parsed.attachments and agent.repository_manager:
                attachment_ids: list[str] = []
                for ref in parsed.attachments:
                    attachment_id = ref.get("id")
                    if isinstance(attachment_id, str) and attachment_id:
                        attachment_ids.append(attachment_id)
                missing: list[str] = list(attachment_ids)
                try:
                    attachment_records = await agent.repository_manager.get_attachments(
                        attachment_ids
                    )
                except Exception:
                    logger.warning(
                        "Attachment existence check failed (conversation %s)",
                        cid,
                        exc_info=True,
                    )
                else:
                    missing = [aid for aid in attachment_ids if aid not in attachment_records]
                if missing:
                    await websocket.send_json(
                        {
                            "error": "Invalid attachment",
                            "missing_attachment_ids": missing,
                            "conversation_id": cid,
                        }
                    )
                    continue

                # 设计 §3.2/§4.2:messages.attachments 持久化与历史回放的
                # 形态为 [{id, mime, width, height, alt?}]。用校验阶段取回
                # 的记录把上行原始引用补全为富引用后再进入生成(落库、历史、
                # 轨迹摘要共用以此列表;图像块组装仍由 multimodal 按 id 查表)。
                parsed_attachments_enriched = _enrich_attachment_refs(
                    parsed.attachments, attachment_records
                )

            # 生成在独立任务中运行，主循环立即回到 receive_text()，
            # 使流式进行中也能接收并响应 stop。
            current_task = asyncio.create_task(
                _run_generation(
                    websocket,
                    agent,
                    parsed.message,
                    cid,
                    active_conv_ref,
                    parsed_attachments_enriched,
                )
            )

    except WebSocketDisconnect:
        pass
    finally:
        # 连接关闭：取消并进行中的生成任务，清理集合。
        if current_task is not None and not current_task.done():
            current_task.cancel()
        await _wait_task_cleared(current_task)
        _chat_ws_clients.discard(websocket)
        if unsubscribe_subagent is not None:
            try:
                unsubscribe_subagent()
            except Exception:
                logger.warning("Failed to unsubscribe subagent listener", exc_info=True)
        logger.debug("WebSocket client disconnected (total: %d)", len(_chat_ws_clients))
