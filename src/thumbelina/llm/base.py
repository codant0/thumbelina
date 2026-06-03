"""Abstract base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Concrete subclasses must implement :attr:`model`, :attr:`chat_model`,
    and ``__init__`` (which should store the underlying LangChain model
    as ``self._model``).

    The default :meth:`chat` and :meth:`stream` implementations delegate
    to ``self.chat_model``, so subclasses rarely need to override them.
    """

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_langchain_messages(
        messages: list[dict[str, str]],
    ) -> list[BaseMessage]:
        """Convert role/content dicts to LangChain message objects.

        Parameters
        ----------
        messages:
            Each dict must have ``role`` (``"user"``, ``"assistant"``,
            or ``"system"``) and ``content`` keys.

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

    # ------------------------------------------------------------------
    # Abstract properties every provider must supply
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the model identifier for this provider."""
        ...

    @property
    @abstractmethod
    def chat_model(self) -> BaseChatModel:
        """Return the underlying LangChain chat model."""
        ...

    # ------------------------------------------------------------------
    # Default chat / stream (override only when custom logic is needed)
    # ------------------------------------------------------------------

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
        lc_messages = self._to_langchain_messages(messages)
        response = await self.chat_model.ainvoke(lc_messages)
        return str(response.content)

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
        lc_messages = self._to_langchain_messages(messages)
        async for chunk in self.chat_model.astream(lc_messages):
            yield str(chunk.content)

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

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running — safe to call asyncio.run()
            return asyncio.run(self.chat(messages))
        else:
            raise RuntimeError(
                "chat_sync() cannot be called from within an async context. "
                "Use 'await provider.chat(messages)' instead."
            )
