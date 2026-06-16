"""Runtime configuration manager with hot-swap capabilities."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from thumbelina.config.models import AppConfig
from thumbelina.config.persistence import save_config
from thumbelina.llm.factory import create_provider

if TYPE_CHECKING:
    from thumbelina.agent.graph import ThumbelinaAgent
    from thumbelina.channels.config import QQChannelConfig, WeChatChannelConfig
    from thumbelina.llm.base import LLMProvider
    from thumbelina.skills.application import SkillApplicationEngine
    from thumbelina.skills.composition_engine import CompositionEngine
    from thumbelina.subagents.manager import SubagentManager

logger = logging.getLogger(__name__)


class RuntimeConfigManager:
    """Manages runtime configuration with hot-swap capabilities.

    Instantiated once during ``lifespan()`` and stored on
    ``app.state.runtime_config_manager``.
    """

    def __init__(self, config: AppConfig, config_path: str | None) -> None:
        self._config = config
        self._config_path = config_path
        self._swap_lock = asyncio.Lock()

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def config_path(self) -> str | None:
        return self._config_path

    # ------------------------------------------------------------------
    # LLM hot-swap
    # ------------------------------------------------------------------

    async def swap_llm_provider(
        self,
        new_provider: str,
        new_model: str,
        new_api_key: str,
        new_base_url: str | None,
        agent: ThumbelinaAgent,
        skill_engine: SkillApplicationEngine | None = None,
        composition_engine: CompositionEngine | None = None,
        subagent_manager: SubagentManager | None = None,
        user_profiler: Any = None,
    ) -> None:
        """Create a new LLM provider and atomically swap all references.

        Raises
        ------
        ValueError
            If the provider name is unknown or the provider fails to
            initialise (bad key, unreachable host, etc.).
        """
        async with self._swap_lock:
            # Resolve api_key: use provided value, fall back to existing
            effective_key = new_api_key or self._config.llm.api_key

            kwargs: dict[str, Any] = {
                "model": new_model,
                "api_key": effective_key,
            }
            if new_base_url:
                kwargs["base_url"] = new_base_url

            # Create provider — may raise ValueError
            new_llm: LLMProvider = create_provider(new_provider, **kwargs)

            # Swap references
            agent.swap_provider(new_llm)
            if skill_engine is not None:
                skill_engine.llm_provider = new_llm
            if composition_engine is not None:
                composition_engine.llm_provider = new_llm
            if subagent_manager is not None:
                subagent_manager.llm_provider = new_llm
            if user_profiler is not None:
                user_profiler.llm_provider = new_llm

            # Update in-memory config
            self._config.llm.provider = new_provider
            self._config.llm.model = new_model
            self._config.llm.api_key = effective_key
            self._config.llm.base_url = new_base_url

            # Persist
            self._persist()

            logger.info(
                "LLM provider swapped → %s/%s",
                new_provider,
                new_model,
            )

    # ------------------------------------------------------------------
    # Channel hot-swap
    # ------------------------------------------------------------------

    async def swap_channel(
        self,
        channel_name: str,
        new_config: QQChannelConfig | WeChatChannelConfig,
        app_state: Any,
        agent: ThumbelinaAgent,
    ) -> bool:
        """Stop the old channel, create/start a new one, update *app_state*.

        Returns ``True`` if the channel is connected after the swap.

        Raises
        ------
        ValueError
            If *channel_name* is not ``"qq"`` or ``"wechat"``.
        RuntimeError
            If the new channel fails to start.
        """
        if channel_name not in ("qq", "wechat"):
            raise ValueError(f"Unknown channel: {channel_name}")

        async with self._swap_lock:
            attr = f"{channel_name}_channel"

            # Stop old channel if present
            old_channel = getattr(app_state, attr, None)
            if old_channel is not None:
                try:
                    await old_channel.stop()
                except Exception:
                    logger.warning(
                        "Failed to stop old %s channel", channel_name, exc_info=True
                    )

            # Create and start new channel if enabled
            if new_config.enabled:
                if channel_name == "qq":
                    from thumbelina.channels.qq_channel import QQChannel

                    new_channel = QQChannel(config=new_config, agent=agent)  # type: ignore[arg-type]
                else:
                    from thumbelina.channels.wechat_channel import WeChatChannel

                    new_channel = WeChatChannel(config=new_config, agent=agent)  # type: ignore[arg-type]

                try:
                    await new_channel.start()
                except Exception as exc:
                    # Channel failed to start — clear reference and raise
                    setattr(app_state, attr, None)
                    raise RuntimeError(
                        f"Failed to start {channel_name} channel: {exc}"
                    ) from exc

                setattr(app_state, attr, new_channel)
            else:
                setattr(app_state, attr, None)

            # Update in-memory config
            if channel_name == "qq":
                self._config.channels.qq = new_config  # type: ignore[assignment]
            else:
                self._config.channels.wechat = new_config  # type: ignore[assignment]

            # Persist
            self._persist()

            connected = new_config.enabled and getattr(app_state, attr) is not None
            logger.info(
                "Channel %s swapped → enabled=%s connected=%s",
                channel_name,
                new_config.enabled,
                connected,
            )
            return connected

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Write current config to YAML if a path is known."""
        if self._config_path is None:
            logger.debug("No config path — skipping persistence")
            return
        try:
            save_config(self._config, self._config_path)
        except Exception:
            logger.warning("Failed to persist config", exc_info=True)
