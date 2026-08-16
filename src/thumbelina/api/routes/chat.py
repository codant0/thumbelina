"""Chat API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.deps import get_agent, get_repository_manager
from thumbelina.api.schemas import ChatRequest, ChatResponse
from thumbelina.concurrency import per_conversation_lock
from thumbelina.llm.endpoint_manager import EndpointManager
from thumbelina.llm.factory import create_provider
from thumbelina.prompts.roles import get_role_prompt
from thumbelina.repository.manager import RepositoryManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Extended-thinking token budgets mapped from the UI intensity levels.
_THINKING_BUDGETS = {"low": 2048, "medium": 8192, "high": 16384}


def _thinking_kwargs(provider: str, enabled: bool, effort: str) -> dict[str, Any]:
    """Build provider kwargs that enable thinking mode at the given intensity."""
    if not enabled:
        return {}
    if provider == "openai":
        return {"reasoning_effort": effort}
    if provider == "anthropic":
        budget = _THINKING_BUDGETS.get(effort, _THINKING_BUDGETS["medium"])
        return {
            "thinking": {"type": "enabled", "budget_tokens": budget},
            "max_tokens": budget + 1024,
        }
    return {}


async def resolve_context_window_tokens(
    repository: RepositoryManager | None,
    endpoint_manager: EndpointManager | None,
    conversation_id: str | None,
    default_tokens: int,
) -> int:
    """解析会话的有效上下文窗口（单位为 token）。

    端点选择与 :func:`_apply_conversation_endpoint` 保持一致：会话绑定
    的端点已设置且可用时由它服务，否则使用全局活跃端点。服务端点的
    ``context_window`` 配置后优先采用；否则链路回退到
    ``default_tokens``（``llm.context_window``）。

    解析绝不能破坏聊天请求，因此任何查询失败都回退到
    ``default_tokens``。
    """
    if repository is None or endpoint_manager is None or not conversation_id:
        return default_tokens
    try:
        conv = await repository.get_conversation(conversation_id)
        endpoint = None
        if conv is not None:
            endpoint_id = conv.get("endpoint_id")
            if endpoint_id:
                candidate = await endpoint_manager.get_endpoint(endpoint_id)
                # 与 _apply_conversation_endpoint 保持一致：没有 api key 的
                # 端点不可用，因此由默认 provider 服务该会话，
                # 并采用默认窗口。
                if candidate is not None and candidate.api_key:
                    endpoint = candidate
            else:
                active = await endpoint_manager.get_active_endpoint_model()
                if active is not None and active[0].api_key:
                    endpoint = active[0]
        if endpoint is not None and endpoint.context_window_tokens is not None:
            return endpoint.context_window_tokens
    except Exception:
        logger.warning("Context window resolution failed", exc_info=True)
    return default_tokens


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    agent: ThumbelinaAgent = Depends(get_agent),
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ChatResponse:
    """Send a message and get a response.

    Creates a new conversation if no conversation_id is provided.
    """
    # Create or reuse conversation
    conversation_id = request.conversation_id
    if conversation_id is None:
        conversation_id = await repository.create_conversation()
    else:
        existing = await repository.get_conversation(conversation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Clone the agent per request to isolate conversation state
    isolated_agent = agent.clone()
    isolated_agent.current_conversation_id = conversation_id

    # 应用会话的端点与角色（HTTP / WebSocket / 通道共用）
    await apply_conversation_runtime(http_request, isolated_agent, conversation_id)

    # 解析会话的上下文窗口（会话端点 → 全局活跃端点 →
    # llm.context_window），供压缩阶段使用。
    window_tokens = await resolve_run_window(http_request, isolated_agent, conversation_id)

    # 与 WebSocket/通道入口共享 per-conversation 锁：同一会话的并发轮次
    # 会交错读改写同一检查点线程，必须串行化。
    async with per_conversation_lock(conversation_id):
        response_text = await isolated_agent.run(
            request.message, context_window_tokens=window_tokens
        )

    return ChatResponse(response=response_text, conversation_id=conversation_id)


async def _apply_default_provider_thinking(
    http_request: Any, agent: ThumbelinaAgent, effort: str
) -> None:
    """Rebuild the config-file default provider with thinking kwargs.

    Used when thinking mode is enabled on a conversation but no endpoint
    (per-conversation or globally active) is configured — otherwise the
    shared default provider would be used without any thinking parameters.
    """
    config = getattr(http_request.app.state, "config", None)
    if config is None:
        agent.apply_conversation_provider(None)
        return
    kwargs: dict[str, Any] = {"model": config.llm.model}
    if config.llm.api_key:
        kwargs["api_key"] = config.llm.api_key
    if config.llm.base_url:
        kwargs["base_url"] = config.llm.base_url
    kwargs.update(_thinking_kwargs(config.llm.provider, True, effort))
    try:
        provider = create_provider(config.llm.provider, **kwargs)
        agent.apply_conversation_provider(provider)
    except Exception:
        agent.apply_conversation_provider(None)


async def _apply_conversation_endpoint(
    http_request: Any, agent: ThumbelinaAgent, conversation_id: str
) -> None:
    """Swap the agent's provider to the conversation's configured endpoint.

    ``http_request`` may be a FastAPI ``Request`` or ``WebSocket`` — only
    ``app.state.endpoint_manager`` is accessed.
    """
    repository = agent.repository_manager
    endpoint_manager = getattr(http_request.app.state, "endpoint_manager", None)
    if repository is None or endpoint_manager is None:
        return
    try:
        conv = await repository.get_conversation(conversation_id)
    except Exception:
        return
    if conv is None:
        return
    thinking_enabled = bool(conv.get("thinking_enabled"))
    effort = conv.get("thinking_effort") or "medium"
    endpoint_id = conv.get("endpoint_id")
    conv_model = conv.get("model")
    if not endpoint_id:
        # No per-conversation endpoint → fall back to the globally active
        # (endpoint, model) pair if one is set, else the shared default provider.
        active = await endpoint_manager.get_active_endpoint_model()
        if active is None or not active[0].api_key:
            if thinking_enabled:
                await _apply_default_provider_thinking(http_request, agent, effort)
            else:
                agent.apply_conversation_provider(None)
            return
        endpoint, active_model = active
        model = active_model
    else:
        endpoint = await endpoint_manager.get_endpoint(endpoint_id)
        if endpoint is None or not endpoint.api_key:
            return
        model = (
            conv_model
            or endpoint.active_model
            or (endpoint.models[0] if endpoint.models else None)
            or "gpt-4o"
        )
    kwargs: dict[str, Any] = {
        "api_key": endpoint.api_key,
        "model": model,
    }
    if endpoint.base_url:
        kwargs["base_url"] = endpoint.base_url
    kwargs.update(_thinking_kwargs(endpoint.provider, thinking_enabled, effort))
    try:
        provider = create_provider(endpoint.provider, **kwargs)
        # Swap the conversation provider（chat model + 摘要压缩器），
        # 共享默认 ``llm_provider`` 仍为无端点的会话保留。
        agent.apply_conversation_provider(provider)
    except Exception:
        # Fall back to the default provider if the endpoint is unusable.
        agent.apply_conversation_provider(None)


async def _apply_conversation_role(agent: ThumbelinaAgent, conversation_id: str) -> None:
    """Override the agent's role with the conversation's configured role.

    When the conversation has a ``role`` set, its prompt is resolved via
    ``get_role_prompt`` and installed on the cloned agent. Unknown role
    names are logged and the agent keeps its current (global default) role.
    """
    repository = agent.repository_manager
    if repository is None:
        return
    try:
        conv = await repository.get_conversation(conversation_id)
    except Exception:
        return
    if conv is None:
        return
    role = conv.get("role")
    if not role:
        return
    try:
        role_prompt = get_role_prompt(role)
    except ValueError:
        logger.warning(
            "Conversation %s has unknown role %r; keeping default role",
            conversation_id,
            role,
        )
        return
    agent.role = role
    agent.role_prompt = role_prompt


async def apply_conversation_runtime(
    context: Any, agent: ThumbelinaAgent, conversation_id: str
) -> None:
    """应用会话的端点与角色（HTTP / WebSocket / 通道共用）。

    ``context`` 只需暴露 ``app.state``（``Request``、``WebSocket`` 或
    指向 ``app.state`` 的轻量 shim 均可）。
    """
    await _apply_conversation_endpoint(context, agent, conversation_id)
    await _apply_conversation_role(agent, conversation_id)


async def resolve_run_window(
    context: Any, agent: ThumbelinaAgent, conversation_id: str | None
) -> int:
    """解析会话的有效上下文窗口（HTTP / WebSocket / 通道共用）。"""
    return await resolve_context_window_tokens(
        agent.repository_manager,
        getattr(context.app.state, "endpoint_manager", None),
        conversation_id,
        context.app.state.config.llm.context_window_tokens,
    )
