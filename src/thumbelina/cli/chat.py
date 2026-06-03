"""Interactive chat session implementation for Thumbelina CLI."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.config import load_config
from thumbelina.llm.factory import create_provider
from thumbelina.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

EXIT_COMMANDS = frozenset({"/exit", "/quit"})


class ChatSession:
    """Manages an interactive chat session with the Thumbelina agent.

    The agent handles its own conversation persistence internally, so
    the session only tracks the in-memory history for display purposes.

    Parameters
    ----------
    agent:
        The ThumbelinaAgent instance to use for generating responses.
    """

    def __init__(self, agent: ThumbelinaAgent) -> None:
        self.agent = agent
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

        # Use the full agent pipeline (with graph, tools, memory)
        response = await self.agent.run(user_input)

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
    # 加载配置文件
    config_path = "thumbelina.yaml" if Path("thumbelina.yaml").exists() else None
    config = load_config(config_path)

    kwargs: dict[str, Any] = {}
    if config.llm.api_key:
        kwargs["api_key"] = config.llm.api_key
    if config.llm.base_url:
        kwargs["base_url"] = config.llm.base_url
    # 命令行参数优先，否则使用配置文件中的 model
    kwargs["model"] = model or config.llm.model

    llm_provider = create_provider(provider, **kwargs)

    memory_manager = MemoryManager(db_url=config.memory.database_url)

    # Initialize feedback repository
    feedback_repo = None
    try:
        from thumbelina.memory.feedback_repo import FeedbackRepository
        feedback_repo = FeedbackRepository(db_url=config.memory.database_url)
    except Exception:
        pass

    # Initialize optional subsystems
    skill_engine = None
    skill_repo = None
    try:
        from thumbelina.skills.application import SkillApplicationEngine
        from thumbelina.skills.repository import SkillRepository
        skill_repo = SkillRepository(db_url=config.memory.database_url)
        skill_engine = SkillApplicationEngine(
            repository=skill_repo,
            llm_provider=llm_provider,
            feedback_repo=feedback_repo,
        )
    except Exception:
        pass

    composition_engine = None
    try:
        from thumbelina.skills.composition_engine import CompositionEngine
        from thumbelina.skills.composition_repo import CompositionRepository
        if skill_repo is None:
            from thumbelina.skills.repository import SkillRepository
            skill_repo = SkillRepository(db_url=config.memory.database_url)
        comp_repo = CompositionRepository(db_url=config.memory.database_url)
        composition_engine = CompositionEngine(
            composition_repo=comp_repo,
            skill_repo=skill_repo,
            llm_provider=llm_provider,
        )
    except Exception:
        pass

    subagent_manager = None
    try:
        from thumbelina.subagents.manager import SubagentManager
        subagent_manager = SubagentManager(llm_provider=llm_provider)
    except Exception:
        pass

    scheduler = None
    try:
        from thumbelina.scheduler.scheduler import TaskScheduler
        scheduler = TaskScheduler()
    except Exception:
        pass

    from thumbelina.tools import get_all_tools

    agent = ThumbelinaAgent(
        llm_provider=llm_provider,
        tools=get_all_tools(),
        memory_manager=memory_manager,
        request_timeout=config.llm.request_timeout,
        skill_engine=skill_engine,
        subagent_manager=subagent_manager,
        scheduler=scheduler,
        composition_engine=composition_engine,
    )

    session = ChatSession(agent=agent)

    try:
        asyncio.run(session.run())
    finally:
        memory_manager.close()
