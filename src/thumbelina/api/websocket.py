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
from thumbelina.tools.workspace_context import set_current_conversation_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# WebSocket message size limit (1MB)
MAX_MESSAGE_SIZE = 1024 * 1024


def _tool_event_frame(event: dict[str, Any]) -> dict[str, Any]:
    """把 agent.stream 的 tool_start/tool_end 事件映射为 WS 下行帧。

    下行帧形如 ``{"tool_event": {"phase": "start"|"end", ...字段原样透传}}``:
    ``type`` 被替换为 ``phase``,其余字段(call_id/name/args/args_truncated/
    duration_ms/is_error/result_preview/result_truncated)保持不变,
    ``conversation_id`` 由调用方补充。
    """
    payload = {k: v for k, v in event.items() if k != "type"}
    payload["phase"] = "start" if event["type"] == "tool_start" else "end"
    return {"tool_event": payload}


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
    非图片 mime 的附件显式跳过(debug 日志)——send_image 只支持图片。
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
            mime = ref.get("mime") or record.get("mime")
            if isinstance(mime, str) and not mime.startswith("image/"):
                logger.debug(
                    "Skipping non-image attachment %s (mime=%s) — "
                    "WeChat forward only supports images",
                    attachment_id,
                    mime,
                )
                continue
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


# ---------------------------------------------------------------------------
# 在途回合注册表与帧广播器:生成任务与 WebSocket 连接解耦。
#
# 生成不再随连接断开(刷新/断线)而取消:任务按会话 id 注册在
# ``_generation_tasks``,断开后继续运行至完整落库。下行的流式帧缓存在
# ``_turn_streams``,新连接通过 ``switch_conversation`` 重新附加 —— 先
# 重放缓存帧,再无缝续流。stop(含跨连接)经注册表取消任务。
# ---------------------------------------------------------------------------

_generation_tasks: dict[str | None, asyncio.Task[None]] = {}
_turn_streams: dict[str | None, _TurnStream] = {}
# task → stream:stop 处理器据此判断请求方是否已订阅该回合的帧流
# (已订阅则取消路径广播的 stopped 帧经泵送达,不再直接补发)。
_task_streams: dict[asyncio.Task[None], _TurnStream] = {}


class _TurnStream:
    """单个在途回合的帧广播器。

    ``frames`` 按发布顺序缓存本回合全部可重放帧(chunk/tool_event/
    subagent_event);订阅者以 ``asyncio.Queue`` 收帧,``subscribe`` 先
    同步播种缓存帧再注册队列 —— 无 await 窗口,保证"重放 + 续流"对每个
    订阅者恰好一次且全局有序。终止帧(done/error/stopped)只投递不缓存:
    回合结束后由 HTTP 历史提供完整内容。
    """

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.queues: dict[WebSocket, asyncio.Queue[dict[str, Any] | None]] = {}

    def publish(self, frame: dict[str, Any], *, replay: bool = True) -> None:
        """发布一帧:可重放帧进缓存,并投递给所有订阅者队列。"""
        if replay:
            self.frames.append(frame)
        for queue in self.queues.values():
            queue.put_nowait(frame)

    def subscribe(self, websocket: WebSocket) -> None:
        """注册订阅者并播种已缓存帧(幂等:重复订阅是 no-op)。"""
        if websocket in self.queues:
            return
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        for frame in self.frames:
            queue.put_nowait(frame)
        self.queues[websocket] = queue

    def unsubscribe(self, websocket: WebSocket) -> None:
        self.queues.pop(websocket, None)

    def finish(self) -> None:
        """回合结束:向所有订阅泵投递哨兵,令其退出。"""
        for queue in self.queues.values():
            queue.put_nowait(None)


# 后台泵任务的强引用集合:asyncio 只持弱引用,不持引用的任务可能在
# 执行中被 GC;完成(含取消/异常)后经回调自动移除。
_background_pumps: set[asyncio.Task[None]] = set()


def _spawn_turn_pump(
    websocket: WebSocket, queue: asyncio.Queue[dict[str, Any] | None]
) -> asyncio.Task[None]:
    """创建并持有引用地启动一个订阅泵任务。"""
    task = asyncio.create_task(_pump_turn_frames(websocket, queue))
    _background_pumps.add(task)
    task.add_done_callback(_background_pumps.discard)
    return task


async def _pump_turn_frames(
    websocket: WebSocket, queue: asyncio.Queue[dict[str, Any] | None]
) -> None:
    """把广播器队列中的帧发往一个订阅连接,直到哨兵或连接失效。

    连接断开(发送抛错)时泵自行退出;回合与缓存帧继续存活,供用户刷新
    后的新连接重新订阅。
    """
    try:
        while True:
            frame = await queue.get()
            if frame is None:
                return
            await websocket.send_json(frame)
    except Exception:
        return


async def _persist_partial_response(
    agent: ThumbelinaAgent,
    cid: str | None,
    content: str,
    reasoning: str = "",
) -> None:
    """取消/停止/流式异常时把已生成的部分响应 best-effort 落库。

    委托 ``agent.persist_interrupted_response``（带中断标记写消息表与
    轨迹）。历史行为是"partial 不落库"，叠加"断开即取消"后，用户刷新
    页面会把整轮已流出的内容全部丢掉 —— 现在至少把用户看到过的部分
    留在历史里。任何失败只记日志：不能让落库问题干扰取消语义。
    """
    if not content and not reasoning:
        return
    try:
        await agent.persist_interrupted_response(content, reasoning or None)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "Failed to persist interrupted partial response (conversation %s)",
            cid,
            exc_info=True,
        )


async def _run_generation(
    websocket: WebSocket,
    agent: ThumbelinaAgent,
    message: str,
    cid: str | None,
    attachments: list[dict[str, object]] | None = None,
) -> None:
    """在独立 asyncio.Task 中执行一轮生成（流式或非流式）。

    生成任务与连接解耦：任务经 ``_generation_tasks`` 按会话注册，连接
    断开（刷新/断线）不取消它 —— 回合继续运行至完整落库。下行帧统一经
    ``_TurnStream`` 分发：origin 连接在回合开始时即订阅，由专用泵发送；
    新连接经 ``switch_conversation`` 附加后先重放缓存帧再续流。只应被
    ``asyncio.create_task`` 包裹调用；函数内部自己获取
    ``per_conversation_lock(cid)``，保持跨入口的会话级串行化。

    两种模式都消费 ``agent.stream()``：流式分支把 content/reasoning 事件
    逐帧转发，工具事件（tool_start/tool_end）映射为 ``tool_event`` 帧
    立即下发（聊天流内实时工具卡，工具可见性特性）；非流式分支只下发
    ``tool_event`` 帧，content 累积后仍按现有 ``{"response": ...}`` 单帧
    发送 —— ``streaming_enabled`` 仅决定 token 是否逐字到达，工具卡行为
    一致。``done`` 帧的 ``streaming_mode`` 字段语义不变。

    ``task.cancel()`` 取消时（stop，含来自新连接的 stop）：流式分支
    ``async for agent.stream(...)`` 抛 ``CancelledError`` 且原样向上传播；
    部分内容带中断标记 best-effort 落库（``_persist_partial_response``），
    并向所有订阅者广播 ``stopped`` 帧供 UI 收尾。注意：部分内容只进
    UI 历史/轨迹，不回写检查点（下一轮 LLM 上下文不含它），检查点自愈
    行为不变。

    Subagent 生命周期事件由本回合注册的 listener 接收，按
    ``event.conversation_id`` 过滤后并入本回合帧流（并发回合互不串话）。

    ``attachments`` 是可选的图像附件引用(``[{id, mime, width, height, alt?}]``,
    已由 ``websocket_chat`` 按设计 §3.2/§4.2 用附件记录补全),透传给
    ``agent.stream``/``agent.run``。微信绑定的会话同样接受附件(设计 §2):
    refs 随用户消息持久化并组装图像块喂给模型;回复完成后逐张经三步流程
    转发给微信对端(见下方 WeChat sync 块)。纯图片轮(文本空白 + 有图)
    照常生成,不再拒绝。
    """
    stream = _TurnStream()
    current = asyncio.current_task()
    if current is not None:
        _task_streams[current] = stream
    if cid:
        _turn_streams[cid] = stream
    # origin 连接在回合开始时即订阅:该连接的泵由本回合持有,回合结束
    # (finish 哨兵)或连接死亡(发送失败)时自行退出。
    stream.subscribe(websocket)
    _spawn_turn_pump(websocket, stream.queues[websocket])

    async def _emit(frame: dict[str, Any], *, replay: bool = True) -> None:
        stream.publish(frame, replay=replay)

    subagent_unsubscribe: Callable[[], None] | None = None

    async def _on_subagent_event(event: SubagentEvent) -> None:
        # 按发起会话过滤(事件缺少会话标注时不转发,避免并发回合串话)。
        if event.conversation_id != cid:
            return
        await _emit(
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
                    "conversation_id": event.conversation_id,
                },
                "conversation_id": cid,
            }
        )

    subagent_manager: SubagentManager | None = getattr(
        websocket.app.state, "subagent_manager", None
    )
    if subagent_manager is not None:
        subagent_unsubscribe = subagent_manager.add_listener(_on_subagent_event)

    try:
        async with per_conversation_lock(cid):
            if cid:
                agent.current_conversation_id = cid
                # 供 CreateSubagentTool 标注子 agent 的发起会话,使事件能
                # 路由回本回合的帧流。
                set_current_conversation_id(cid)
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
            # 消息持久化、图像块喂给模型,回复完成后逐张转发微信对端。纯
            # 图片轮(文本空白 + 有图)照常生成,不再拒绝。

            # Use streaming for frontend, regardless of WeChat binding
            streaming = websocket.app.state.config.llm.streaming_enabled
            full_response = ""
            full_reasoning = ""
            if streaming:
                try:
                    async for event in agent.stream(
                        message, context_window_tokens=window_tokens, attachments=attachments
                    ):
                        etype = event["type"]
                        if etype in ("tool_start", "tool_end"):
                            frame = _tool_event_frame(event)
                            frame["conversation_id"] = cid
                            await _emit(frame)
                        elif etype == "reasoning":
                            full_reasoning += event["text"]
                            await _emit(
                                {
                                    "chunk": event["text"],
                                    "chunk_type": "reasoning",
                                    "conversation_id": cid,
                                }
                            )
                        else:
                            full_response += event["text"]
                            await _emit({"chunk": event["text"], "conversation_id": cid})
                except asyncio.CancelledError:
                    # 取消必须原样传播：被 stop 打断时任务被中断。传播前把
                    # 已生成的部分内容落库（外层统一广播 stopped 帧）。
                    await _persist_partial_response(agent, cid, full_response, full_reasoning)
                    raise
                except Exception as exc:
                    # 流式失败时不再用同一线程重跑：用户消息已在
                    # agent.stream() 开头持久化并写入检查点，重跑会重复写入
                    # 消息与状态。直接向客户端报告错误，已保留的消息让用户可
                    # 重发；失败前已流出的部分内容同样落库留存。
                    logger.warning("Streaming failed for conversation %s: %s", cid, exc)
                    await _persist_partial_response(agent, cid, full_response, full_reasoning)
                    await _emit(
                        {"error": f"Streaming failed: {exc}", "conversation_id": cid},
                        replay=False,
                    )
                    return
            else:
                # 非流式分支统一消费 stream()（工具可见性特性）：工具事件照发,
                # reasoning 事件不下发但 stream() 会照常持久化;content 累积后
                # 仍按单个 ``{"response": ...}`` 帧发送,done 帧语义不变。
                full_response = ""
                try:
                    async for event in agent.stream(
                        message, context_window_tokens=window_tokens, attachments=attachments
                    ):
                        etype = event["type"]
                        if etype in ("tool_start", "tool_end"):
                            frame = _tool_event_frame(event)
                            frame["conversation_id"] = cid
                            await _emit(frame)
                        elif etype == "content":
                            full_response += event["text"]
                except asyncio.CancelledError:
                    await _persist_partial_response(agent, cid, full_response)
                    raise
                except Exception as exc:
                    logger.warning("Generation failed for conversation %s: %s", cid, exc)
                    await _persist_partial_response(agent, cid, full_response)
                    await _emit(
                        {"error": f"Generation failed: {exc}", "conversation_id": cid},
                        replay=False,
                    )
                    return
                await _emit({"response": full_response, "conversation_id": cid}, replay=False)

            await _emit(
                {
                    "done": True,
                    "conversation_id": cid,
                    "streaming_mode": streaming,
                },
                replay=False,
            )

            # Sync to WeChat if this is a WeChat conversation. 转发不依赖
            # full_response：纯图片轮模型回复可能为空，此时文本同步跳过，
            # 但附件图片仍必须逐张转发，否则静默丢失。
            if is_wechat_conversation:
                wechat_channel = getattr(websocket.app.state, "wechat_channel", None)
                if wechat_channel is not None:
                    logger.info("Sending frontend message response to WeChat")
                    try:
                        last_wechat_user = getattr(wechat_channel, "_last_wechat_user_id", None)
                        last_context_token = getattr(wechat_channel, "_last_context_token", "")

                        if last_wechat_user:
                            if full_response:
                                await wechat_channel.send_message(
                                    last_wechat_user,
                                    full_response,
                                    context_token=last_context_token,
                                )
                                logger.info("Sent response to WeChat user %s", last_wechat_user)
                            else:
                                logger.info(
                                    "Empty model response for WeChat conversation %s; "
                                    "skipping text sync (attachment forwarding still applies)",
                                    cid,
                                )

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
    except asyncio.CancelledError:
        # stop(含来自新连接的)取消:向所有订阅者广播 stopped 供 UI 收尾;
        # 部分内容已由内层 handler 落库。取消继续向上传播。
        stream.publish({"stopped": True, "conversation_id": cid}, replay=False)
        raise
    finally:
        if subagent_unsubscribe is not None:
            try:
                subagent_unsubscribe()
            except Exception:
                logger.warning("Failed to unsubscribe subagent listener", exc_info=True)
        stream.finish()
        if current is not None:
            _task_streams.pop(current, None)
        if cid and _turn_streams.get(cid) is stream:
            _turn_streams.pop(cid, None)
        if cid and current is not None and _generation_tasks.get(cid) is current:
            _generation_tasks.pop(cid, None)


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
    消息，用于取消当前正在生成的轮次（跨连接生效：按会话注册表定位任务）。

    生成任务与连接解耦：任务按会话注册（``_generation_tasks``），连接
    断开（刷新/断线）不取消在途回合 —— 它继续运行至完整落库；新连接
    通过 ``switch_conversation`` 重新附加（先重放缓存帧，再无缝续流）。
    同一会话的新回合在旧回合结束后才开始；同连接的跨会话回合保持既有的
    每连接串行语义（两个回合共用同一 agent 克隆，并发会产生状态竞争）。
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
    # 本连接启动过的最近一个生成任务:stop 消息未携带会话 id 时的兜底。
    last_started_task: asyncio.Task[Any] | None = None
    # 本连接经 switch_conversation 附加的在途回合订阅(流, 泵);断开时清理。
    # origin 连接回合开始时的订阅由 _run_generation 自持,不在此列。
    subscription: tuple[_TurnStream, asyncio.Task[None]] | None = None

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
                stop_cid = data.get("conversation_id")
                task: asyncio.Task[Any] | None = None
                if stop_cid:
                    task = _generation_tasks.get(stop_cid)
                if task is None:
                    task = last_started_task
                if task is not None and not task.done():
                    # 请求方已订阅该回合流时,取消路径广播的 stopped 帧经泵
                    # 送达(恰好一次);未订阅则在此直接补发,保证 UI 收尾帧
                    # 不缺失。
                    stop_stream = _task_streams.get(task)
                    requester_subscribed = (
                        stop_stream is not None and websocket in stop_stream.queues
                    )
                    task.cancel()
                    await _wait_task_cleared(task)
                    if not requester_subscribed:
                        await websocket.send_json(
                            {"stopped": True, "conversation_id": stop_cid}
                        )
                else:
                    await websocket.send_json({"stopped": True, "conversation_id": stop_cid})
                continue

            # 心跳保活:前端定期发送 {ping: true},回 {pong: true} 供其判活。
            # 不含 message 字段,与 stop 同理必须在 Pydantic 校验之前特判,
            # 否则会被拒绝成 error 帧(前端会把 error 当作回复异常收尾)。
            if isinstance(data, dict) and data.get("ping") is True:
                await websocket.send_json({"pong": True})
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
                # 重连/切换会话时重新附加该会话的在途回合:订阅广播器后由
                # 泵先重放缓存帧再无缝续流(生成与连接解耦的核心路径)。
                # 已是 origin 订阅者时幂等跳过,避免重复泵导致帧乱序。
                if subscription is not None:
                    old_stream, old_pump = subscription
                    old_stream.unsubscribe(websocket)
                    old_pump.cancel()
                    subscription = None
                active_stream = _turn_streams.get(new_cid)
                if active_stream is not None and websocket not in active_stream.queues:
                    active_stream.subscribe(websocket)
                    pump = _spawn_turn_pump(websocket, active_stream.queues[websocket])
                    subscription = (active_stream, pump)
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

            # 同会话已有在途回合(可能来自刷新前的旧连接)先等它结束,保持
            # 会话串行;同连接上一回合(跨会话)按既有语义串行。生成任务
            # 本身与连接解耦,此等待只影响新回合的启动时机。
            existing_task = _generation_tasks.get(cid)
            if existing_task is not None and not existing_task.done():
                await _wait_task_cleared(existing_task)
            elif last_started_task is not None and not last_started_task.done():
                await _wait_task_cleared(last_started_task)

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
                # 形态为 [{id, mime, width?, height?, alt?}]。用校验阶段取回
                # 的记录把上行原始引用补全为富引用后再进入生成(落库、历史、
                # 轨迹摘要共用以此列表;图像块组装仍由 multimodal 按 id 查表)。
                parsed_attachments_enriched = _enrich_attachment_refs(
                    parsed.attachments, attachment_records
                )

            # 生成在独立任务中运行，主循环立即回到 receive_text()，使流式
            # 进行中也能接收并响应 stop。任务按会话注册:连接断开不取消
            # (刷新后继续生成,新连接重连附加续流)。
            task = asyncio.create_task(
                _run_generation(websocket, agent, parsed.message, cid, parsed_attachments_enriched)
            )
            _generation_tasks[cid] = task
            last_started_task = task

    except WebSocketDisconnect:
        pass
    finally:
        # 生成任务与连接解耦:断开(刷新/断线)不取消在途回合 —— 任务继续
        # 运行至完整落库,用户新连接经 switch_conversation 重新附加续流。
        # 此处仅清理本连接经 switch 建立的订阅;origin 连接的泵由回合
        # 自持(发送失败自动退出)。
        if subscription is not None:
            sub_stream, sub_pump = subscription
            sub_stream.unsubscribe(websocket)
            sub_pump.cancel()
        _chat_ws_clients.discard(websocket)
        logger.debug("WebSocket client disconnected (total: %d)", len(_chat_ws_clients))
