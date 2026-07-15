"""Chat API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.deps import get_agent, get_memory_manager
from thumbelina.api.schemas import ChatRequest, ChatResponse
from thumbelina.llm.factory import create_provider
from thumbelina.memory.manager import MemoryManager

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    agent: ThumbelinaAgent = Depends(get_agent),
    memory: MemoryManager = Depends(get_memory_manager),
) -> ChatResponse:
    """Send a message and get a response.

    Creates a new conversation if no conversation_id is provided.
    """
    # Create or reuse conversation
    conversation_id = request.conversation_id
    if conversation_id is None:
        conversation_id = await memory.create_conversation()
    else:
        existing = await memory.get_conversation(conversation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Clone the agent per request to isolate conversation state
    isolated_agent = agent.clone()
    isolated_agent.current_conversation_id = conversation_id

    # Apply per-conversation model selection when configured
    await _apply_conversation_endpoint(http_request, isolated_agent, conversation_id)

    response_text = await isolated_agent.run(request.message)

    return ChatResponse(response=response_text, conversation_id=conversation_id)


async def _apply_conversation_endpoint(
    http_request: Any, agent: ThumbelinaAgent, conversation_id: str
) -> None:
    """Swap the agent's provider to the conversation's configured endpoint.

    ``http_request`` may be a FastAPI ``Request`` or ``WebSocket`` — only
    ``app.state.endpoint_manager`` is accessed.
    """
    memory = agent.memory_manager
    endpoint_manager = getattr(http_request.app.state, "endpoint_manager", None)
    if memory is None or endpoint_manager is None:
        return
    try:
        conv = await memory.get_conversation(conversation_id)
    except Exception:
        return
    if conv is None:
        return
    endpoint_id = conv.get("endpoint_id")
    if not endpoint_id:
        # No per-conversation endpoint → revert to the shared default provider.
        agent.llm = None
        return
    endpoint = await endpoint_manager.get_endpoint(endpoint_id)
    if endpoint is None or not endpoint.api_key:
        return
    kwargs: dict[str, Any] = {
        "api_key": endpoint.api_key,
        "model": endpoint.model or "gpt-4o",
    }
    if endpoint.base_url:
        kwargs["base_url"] = endpoint.base_url
    try:
        provider = create_provider(endpoint.provider, **kwargs)
        # Swap only the underlying chat model so the shared default
        # ``llm_provider`` is preserved for conversations without an endpoint.
        agent.llm = provider.chat_model
    except Exception:
        # Fall back to the default provider if the endpoint is unusable.
        agent.llm = None
