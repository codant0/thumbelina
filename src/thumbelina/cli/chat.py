"""Interactive chat session implementation for Thumbelina CLI."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from thumbelina.config import load_config
from thumbelina.llm.factory import create_provider
from thumbelina.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

EXIT_COMMANDS = frozenset({"/exit", "/quit"})


class ChatSession:
    """Manages an interactive chat session with the Thumbelina agent.

    Parameters
    ----------
    provider:
        The LLM provider instance to use for generating responses.
    memory_manager:
        Optional memory manager for conversation persistence.
    """

    def __init__(
        self,
        provider: Any,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.provider = provider
        self.memory_manager = memory_manager
        self.history: list[dict[str, str]] = []
        self.running = False

    def is_exit_command(self, text: str) -> bool:
        """Check if the input is an exit command.

        Parameters
        ----------
        text:
            User input text.

        Returns
        -------
        bool
            True if the text is an exit command.
        """
        return text.strip().lower() in EXIT_COMMANDS

    def format_response(self, response: str) -> str:
        """Format the assistant response for display.

        Parameters
        ----------
        response:
            Raw response text from the agent.

        Returns
        -------
        str
            Formatted response string.
        """
        return f"\n[Thumbelina]: {response}\n"

    def get_history(self) -> list[dict[str, str]]:
        """Return a copy of the conversation history.

        Returns
        -------
        list[dict[str, str]]
            Copy of the conversation history.
        """
        return self.history.copy()

    async def process_input(self, user_input: str) -> str:
        """Process user input and get agent response.

        Parameters
        ----------
        user_input:
            The user's message.

        Returns
        -------
        str
            The agent's response.
        """
        self.history.append({"role": "user", "content": user_input})

        messages = self.history.copy()
        response = await self.provider.chat(messages)

        self.history.append({"role": "assistant", "content": response})
        return response

    async def run(self) -> None:
        """Run the interactive chat loop."""
        self.running = True
        prompt_session: PromptSession[str] = PromptSession(history=InMemoryHistory())

        print("Welcome to Thumbelina! Type '/exit' or '/quit' to exit.")
        print("Press Ctrl+C to interrupt.\n")

        while self.running:
            try:
                user_input = await prompt_session.prompt_async("You: ")
                user_input = user_input.strip()

                if not user_input:
                    continue

                if self.is_exit_command(user_input):
                    print("\nGoodbye!")
                    self.running = False
                    break

                response = await self.process_input(user_input)
                print(self.format_response(response))

            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                self.running = False
                break
            except EOFError:
                print("\n\nGoodbye!")
                self.running = False
                break
            except Exception as e:
                logger.error("Error during chat: %s", e)
                print(f"\n[Error]: {e}\n")


def run_chat(provider: str, model: str | None = None) -> None:
    """Run the interactive chat session.

    Parameters
    ----------
    provider:
        Name of the LLM provider to use.
    model:
        Optional model name to use.
    """
    config = load_config()

    kwargs: dict[str, Any] = {}
    if provider == "openai" and config.llm.api_key:
        kwargs["api_key"] = config.llm.api_key
    elif provider == "anthropic" and config.llm.api_key:
        kwargs["api_key"] = config.llm.api_key
    if model:
        kwargs["model"] = model

    llm_provider = create_provider(provider, **kwargs)

    memory_manager = MemoryManager(db_url=config.memory.database_url)

    session = ChatSession(provider=llm_provider, memory_manager=memory_manager)

    try:
        asyncio.run(session.run())
    finally:
        memory_manager.close()
