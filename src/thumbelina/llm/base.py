"""Abstract base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


def _to_langchain_messages(messages: list[dict[str, str]]) -> list[BaseMessage]:
    """Convert a list of role/content dicts to LangChain message objects.

    Parameters
    ----------
    messages:
        Each dict must have ``role`` (``"user"``, ``"assistant"``, or ``"system"``)
        and ``content`` keys.

    Returns
    -------
    list[BaseMessage]
        Corresponding LangChain message instances.

    Raises
    ------
    ValueError
        If a message has an unrecognised ``role``.
    """
    role_map: dict[str, type[BaseMessage]] = {
        "user": HumanMessage,
        "assistant": AIMessage,
        "system": SystemMessage,
    }
    result: list[BaseMessage] = []
    for msg in messages:
        role = msg["role"]
        cls = role_map.get(role)
        if cls is None:
            raise ValueError(
                f"Unknown role: {role!r}. Expected one of: {list(role_map.keys())}"
            )
        result.append(cls(content=msg["content"]))
    return result


class LLMProvider(ABC):
    """Abstract base class that every LLM provider must implement.

    Concrete providers wrap a LangChain chat model and expose a uniform
    async interface for ``chat`` and ``stream`` operations.  A synchronous
    convenience method ``chat_sync`` is also provided.
    """

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a list of messages and return the complete response text.

        Parameters
        ----------
        messages:
            Conversation messages as role/content dicts.

        Returns
        -------
        str
            The assistant's reply.
        """
        ...

    @abstractmethod
    async def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
        """Send a list of messages and yield response chunks as they arrive.

        Parameters
        ----------
        messages:
            Conversation messages as role/content dicts.

        Yields
        ------
        str
            Incremental text chunks of the response.
        """
        # Make this an async generator by having at least one yield
        # (the abstract method uses ... but subclasses override)
        yield ""  # pragma: no cover

    def chat_sync(self, messages: list[dict[str, str]]) -> str:
        """Synchronous wrapper around :meth:`chat`.

        Parameters
        ----------
        messages:
            Conversation messages as role/content dicts.

        Returns
        -------
        str
            The assistant's reply.
        """
        import asyncio

        return asyncio.run(self.chat(messages))

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the model identifier for this provider."""
        ...
