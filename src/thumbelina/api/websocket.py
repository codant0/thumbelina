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


async def _run_generation(
    websocket: WebSocket,
    agent: ThumbelinaAgent,
    message: str,
    cid: str | None,
    active_conv_ref: dict[str, str | None],
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

        # Use streaming for frontend, regardless of WeChat binding
        streaming = websocket.app.state.config.llm.streaming_enabled
        full_response = ""
        if streaming:
            try:
                async for event in agent.stream(message, context_window_tokens=window_tokens):
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
            full_response = await agent.run(message, context_window_tokens=window_tokens)
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

            if not parsed.message.strip():
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

            # 生成在独立任务中运行，主循环立即回到 receive_text()，
            # 使流式进行中也能接收并响应 stop。
            current_task = asyncio.create_task(
                _run_generation(websocket, agent, parsed.message, cid, active_conv_ref)
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
