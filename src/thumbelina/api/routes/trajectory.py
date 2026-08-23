"""轨迹(审计)API 路由(设计文档 §4)。

- 有轨迹事件的会话按轮次分页倒序返回。
- 无轨迹事件的会话从 messages 表合成轮次(仅 user/assistant 文本,
  工具调用与上下文数据自然缺失不展示)。
- conversation_id 不存在 → 404;page/page_size 越界 → 422。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from thumbelina.api.deps import get_repository_manager
from thumbelina.repository.manager import RepositoryManager

router = APIRouter(prefix="/trajectory", tags=["trajectory"])

_PAGE_SIZE_MAX = 100


def _synthesize_message_turns(
    messages: list[dict[str, Any]], page: int, page_size: int
) -> dict[str, Any]:
    """把纯文本消息史合成为轮次:user 开轮、后续 assistant 归入。"""
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for msg in messages:
        role = msg.get("role")
        created_at = msg.get("created_at", "")
        if role == "user":
            current = {
                "turn_id": f"msg-{msg['id']}",
                "started_at": created_at,
                "events": [
                    {
                        "seq": 0,
                        "event_type": "user",
                        "payload": {"content": msg.get("content", "")},
                        "created_at": created_at,
                    }
                ],
            }
            turns.append(current)
        elif role == "assistant":
            if current is None:
                current = {
                    "turn_id": f"msg-{msg['id']}",
                    "started_at": created_at,
                    "events": [],
                }
                turns.append(current)
            current["events"].append(
                {
                    "seq": len(current["events"]),
                    "event_type": "assistant",
                    "payload": {"content": msg.get("content", "")},
                    "created_at": created_at,
                }
            )
    turns.reverse()
    total = len(turns)
    start = (page - 1) * page_size
    page_turns = turns[start : start + page_size]
    return {"total_turns": total, "page": page, "page_size": page_size, "turns": page_turns}


@router.get("/cache-stats")
async def get_cache_stats(
    limit: int = Query(100, ge=1, le=1000),
    conversation_id: str | None = Query(None, description="限定统计到单个会话"),
    repository: RepositoryManager = Depends(get_repository_manager),
) -> dict[str, Any]:
    """最近 limit 条 llm_usage 事件的 KV 缓存命中汇总(状态栏展示用,可限定会话)。"""
    return await repository.get_cache_stats(limit, conversation_id)


@router.get("/{conversation_id}")
async def get_trajectory(
    conversation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=_PAGE_SIZE_MAX),
    repository: RepositoryManager = Depends(get_repository_manager),
) -> dict[str, Any]:
    """按轮次分页返回轨迹(最新轮次在前)。"""
    conversation = await repository.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    name = conversation.get("name")
    if await repository.has_trajectory(conversation_id):
        data = await repository.get_trajectory_page(conversation_id, page, page_size)
        return {
            "conversation_id": conversation_id,
            "conversation_name": name,
            **data,
            "page": page,
            "page_size": page_size,
        }
    messages = await repository.get_messages(conversation_id)
    data = _synthesize_message_turns(messages, page, page_size)
    return {
        "conversation_id": conversation_id,
        "conversation_name": name,
        **data,
    }
