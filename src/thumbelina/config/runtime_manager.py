"""Runtime configuration manager with hot-swap capabilities."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, cast

from thumbelina.config.models import AppConfig
from thumbelina.config.persistence import save_config
from thumbelina.llm.factory import create_provider

if TYPE_CHECKING:
    from thumbelina.agent.graph import ThumbelinaAgent
    from thumbelina.config.config_repo import ConfigRepository
    from thumbelina.llm.base import LLMProvider
    from thumbelina.skills.application import SkillApplicationEngine
    from thumbelina.skills.composition_engine import CompositionEngine
    from thumbelina.subagents.manager import SubagentManager

from thumbelina.channels.config import QQChannelConfig, WeChatChannelConfig

logger = logging.getLogger(__name__)


class RuntimeConfigManager:
    """Manages runtime configuration with hot-swap capabilities.

    Instantiated once during ``lifespan()`` and stored on
    ``app.state.runtime_config_manager``.
    """

    def __init__(
        self,
        config: AppConfig,
        config_path: str | None,
        config_repo: ConfigRepository | None = None,
    ) -> None:
        self._config = config
        self._config_path = config_path
        self._config_repo = config_repo
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
            await self._persist_to_db("llm", "llm.provider", new_provider)
            await self._persist_to_db("llm", "llm.model", new_model)
            if new_base_url:
                await self._persist_to_db("llm", "llm.base_url", new_base_url)

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
        on_message_callback: Any = None,
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
                    logger.warning("Failed to stop old %s channel", channel_name, exc_info=True)

            # Update in-memory config
            if channel_name == "qq":
                self._config.channels.qq = new_config  # type: ignore[assignment]
            else:
                self._config.channels.wechat = new_config  # type: ignore[assignment]

            # Persist BEFORE attempting to start the channel so that
            # non-secret fields (ilink_bot_id, ilink_user_id, enabled, …)
            # survive even if the channel fails to start (e.g. expired
            # token).  This allows the saved-credentials recovery path in
            # WeChatChannel.start() to kick in on the next restart.
            self._persist()
            await self._persist_to_db(
                "channel", f"channels.{channel_name}.enabled", new_config.enabled
            )
            if channel_name == "qq":
                assert isinstance(new_config, QQChannelConfig)
                await self._persist_to_db("channel", "channels.qq.app_id", new_config.app_id)
                if new_config.allowed_guilds:
                    await self._persist_to_db(
                        "channel", "channels.qq.allowed_guilds", new_config.allowed_guilds
                    )
                if new_config.allowed_groups:
                    await self._persist_to_db(
                        "channel", "channels.qq.allowed_groups", new_config.allowed_groups
                    )
            else:
                assert isinstance(new_config, WeChatChannelConfig)
                if new_config.ilink_bot_id:
                    await self._persist_to_db(
                        "channel", "channels.wechat.ilink_bot_id", new_config.ilink_bot_id
                    )
                if new_config.ilink_user_id:
                    await self._persist_to_db(
                        "channel", "channels.wechat.ilink_user_id", new_config.ilink_user_id
                    )
                if new_config.ilink_base_url:
                    await self._persist_to_db(
                        "channel", "channels.wechat.ilink_base_url", new_config.ilink_base_url
                    )

            # Create and start new channel if enabled
            if new_config.enabled:
                from thumbelina.channels.qq_channel import QQChannel
                from thumbelina.channels.wechat_channel import WeChatChannel

                new_channel: QQChannel | WeChatChannel
                if channel_name == "qq":
                    assert isinstance(new_config, QQChannelConfig)
                    new_channel = QQChannel(config=new_config, agent=agent)
                else:
                    assert isinstance(new_config, WeChatChannelConfig)
                    new_channel = WeChatChannel(
                        config=new_config,
                        agent=agent,
                        on_message_callback=on_message_callback,
                    )

                try:
                    await new_channel.start()
                except Exception as exc:
                    # Channel failed to start — clear reference and raise.
                    # Config is already persisted above, so ilink_bot_id
                    # survives for session recovery on next restart.
                    setattr(app_state, attr, None)
                    raise RuntimeError(f"Failed to start {channel_name} channel: {exc}") from exc

                setattr(app_state, attr, new_channel)
                # Cache WeChat conversation ID for fast lookup in WS handler.
                # If the WeChat channel needs re-authentication, there is no
                # active conversation yet.
                if channel_name == "wechat":
                    wechat_channel = cast("WeChatChannel", new_channel)
                    app_state.wechat_conversation_id = (
                        None
                        if wechat_channel._needs_authentication
                        else wechat_channel._agent.current_conversation_id
                    )
            else:
                setattr(app_state, attr, None)
                if channel_name == "wechat":
                    app_state.wechat_conversation_id = None

            connected = new_config.enabled and getattr(app_state, attr) is not None
            if channel_name == "wechat" and connected:
                connected = not cast("WeChatChannel", new_channel)._needs_authentication
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

    async def _persist_to_db(self, category: str, key: str, value: Any) -> None:
        """Write a single config value to the database."""
        if self._config_repo is None:
            return
        try:
            await self._config_repo.set(key, json.dumps(value), category)
        except Exception:
            logger.warning("Failed to persist config to database: %s", key, exc_info=True)

    async def load_from_database(self) -> None:
        """Load configuration overrides from the database.

        Database values take precedence over YAML/env values for
        hot-swappable fields only (LLM provider/model/base_url,
        channel enabled states, streaming_enabled, rate_limit).
        """
        if self._config_repo is None:
            return

        try:
            db_config = await self._config_repo.export_to_dict()
        except Exception:
            logger.warning("Failed to load config from database", exc_info=True)
            return

        if not db_config:
            return

        # Apply LLM overrides
        llm = db_config.get("llm", {})
        if "provider" in llm:
            self._config.llm.provider = llm["provider"]
        if "model" in llm:
            self._config.llm.model = llm["model"]
        if "base_url" in llm:
            self._config.llm.base_url = llm["base_url"]
        if "streaming_enabled" in llm:
            self._config.llm.streaming_enabled = llm["streaming_enabled"]
        if "request_timeout" in llm:
            self._config.llm.request_timeout = llm["request_timeout"]

        # Apply channel overrides
        channels = db_config.get("channels", {})
        qq = channels.get("qq", {})
        if "enabled" in qq:
            self._config.channels.qq.enabled = qq["enabled"]
        if "app_id" in qq:
            self._config.channels.qq.app_id = qq["app_id"]
        if "allowed_guilds" in qq:
            self._config.channels.qq.allowed_guilds = qq["allowed_guilds"]
        if "allowed_groups" in qq:
            self._config.channels.qq.allowed_groups = qq["allowed_groups"]

        wechat = channels.get("wechat", {})
        if "enabled" in wechat:
            self._config.channels.wechat.enabled = wechat["enabled"]
        if "ilink_bot_id" in wechat:
            self._config.channels.wechat.ilink_bot_id = wechat["ilink_bot_id"]
        if "ilink_user_id" in wechat:
            self._config.channels.wechat.ilink_user_id = wechat["ilink_user_id"]
        if "ilink_base_url" in wechat:
            self._config.channels.wechat.ilink_base_url = wechat["ilink_base_url"]

        # Apply rate_limit overrides
        rate_limit = db_config.get("rate_limit", {})
        if "enabled" in rate_limit:
            self._config.rate_limit.enabled = rate_limit["enabled"]
        if "max_requests" in rate_limit:
            self._config.rate_limit.max_requests = rate_limit["max_requests"]
        if "window_seconds" in rate_limit:
            self._config.rate_limit.window_seconds = rate_limit["window_seconds"]

        logger.info("Loaded config overrides from database")
