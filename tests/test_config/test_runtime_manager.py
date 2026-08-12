"""Tests for thumbelina.config.runtime_manager module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from thumbelina.config.models import AppConfig
from thumbelina.config.runtime_manager import RuntimeConfigManager


def _make_mock_agent():
    """Create a mock ThumbelinaAgent with swap_provider."""
    agent = MagicMock()
    agent.swap_provider = MagicMock()
    return agent


def _make_mock_provider(name="test-provider"):
    """Create a mock LLMProvider."""
    provider = MagicMock()
    provider.chat_model = MagicMock()
    return provider


class TestSwapLLMProvider:
    """Tests for RuntimeConfigManager.swap_llm_provider."""

    @pytest.mark.asyncio
    async def test_swap_success(self, tmp_path):
        """Successful swap updates all subsystem references."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate({"llm": {"provider": "openai", "model": "gpt-4o"}})
        manager = RuntimeConfigManager(config, config_file)

        agent = _make_mock_agent()
        skill_engine = MagicMock()
        subagent_manager = MagicMock()
        user_profiler = MagicMock()
        composition_engine = MagicMock()

        new_provider = _make_mock_provider()

        with patch(
            "thumbelina.config.runtime_manager.create_provider",
            return_value=new_provider,
        ) as mock_create:
            await manager.swap_llm_provider(
                new_provider="anthropic",
                new_model="claude-3",
                new_api_key="sk-new",
                new_base_url=None,
                agent=agent,
                skill_engine=skill_engine,
                composition_engine=composition_engine,
                subagent_manager=subagent_manager,
                user_profiler=user_profiler,
            )

        mock_create.assert_called_once_with("anthropic", model="claude-3", api_key="sk-new")
        agent.swap_provider.assert_called_once_with(new_provider)
        assert skill_engine.llm_provider is new_provider
        assert subagent_manager.llm_provider is new_provider
        assert composition_engine.llm_provider is new_provider
        assert user_profiler.llm_provider is new_provider

        # Config updated
        assert config.llm.provider == "anthropic"
        assert config.llm.model == "claude-3"
        assert config.llm.api_key == "sk-new"

    @pytest.mark.asyncio
    async def test_swap_invalid_provider_raises(self, tmp_path):
        """Unknown provider name raises ValueError without side effects."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate({"llm": {"provider": "openai", "model": "gpt-4o"}})
        manager = RuntimeConfigManager(config, config_file)
        agent = _make_mock_agent()

        with patch(
            "thumbelina.config.runtime_manager.create_provider",
            side_effect=ValueError("Unknown provider: 'bad'"),
        ):
            with pytest.raises(ValueError, match="Unknown provider"):
                await manager.swap_llm_provider(
                    new_provider="bad",
                    new_model="x",
                    new_api_key="",
                    new_base_url=None,
                    agent=agent,
                )

        # Old config unchanged
        assert config.llm.provider == "openai"
        agent.swap_provider.assert_not_called()

    @pytest.mark.asyncio
    async def test_swap_persists_config(self, tmp_path):
        """Successful swap writes config to YAML."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate({"llm": {"provider": "openai", "model": "gpt-4o"}})
        manager = RuntimeConfigManager(config, config_file)
        agent = _make_mock_agent()

        with patch(
            "thumbelina.config.runtime_manager.create_provider",
            return_value=_make_mock_provider(),
        ):
            await manager.swap_llm_provider(
                new_provider="ollama",
                new_model="llama3",
                new_api_key="",
                new_base_url="http://localhost:11434",
                agent=agent,
            )

        raw = yaml.safe_load(open(config_file, encoding="utf-8").read())
        assert raw["llm"]["provider"] == "ollama"
        assert raw["llm"]["model"] == "llama3"
        assert raw["llm"]["base_url"] == "http://localhost:11434"

    @pytest.mark.asyncio
    async def test_swap_uses_existing_key_when_empty(self, tmp_path):
        """Empty api_key falls back to existing config value."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate(
            {"llm": {"provider": "openai", "model": "gpt-4o", "api_key": "sk-existing"}}
        )
        manager = RuntimeConfigManager(config, config_file)
        agent = _make_mock_agent()

        with patch(
            "thumbelina.config.runtime_manager.create_provider",
            return_value=_make_mock_provider(),
        ) as mock_create:
            await manager.swap_llm_provider(
                new_provider="openai",
                new_model="gpt-4-turbo",
                new_api_key="",
                new_base_url=None,
                agent=agent,
            )

        mock_create.assert_called_once_with("openai", model="gpt-4-turbo", api_key="sk-existing")

    @pytest.mark.asyncio
    async def test_swap_with_base_url(self, tmp_path):
        """base_url is passed through to create_provider."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig()
        manager = RuntimeConfigManager(config, config_file)
        agent = _make_mock_agent()

        with patch(
            "thumbelina.config.runtime_manager.create_provider",
            return_value=_make_mock_provider(),
        ) as mock_create:
            await manager.swap_llm_provider(
                new_provider="openai",
                new_model="gpt-4o",
                new_api_key="sk-x",
                new_base_url="https://proxy.example.com/v1",
                agent=agent,
            )

        mock_create.assert_called_once_with(
            "openai",
            model="gpt-4o",
            api_key="sk-x",
            base_url="https://proxy.example.com/v1",
        )

    @pytest.mark.asyncio
    async def test_swap_skips_none_subsystems(self, tmp_path):
        """None subsystem references are skipped without error."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig()
        manager = RuntimeConfigManager(config, config_file)
        agent = _make_mock_agent()

        with patch(
            "thumbelina.config.runtime_manager.create_provider",
            return_value=_make_mock_provider(),
        ):
            # Should not raise
            await manager.swap_llm_provider(
                new_provider="openai",
                new_model="gpt-4o",
                new_api_key="",
                new_base_url=None,
                agent=agent,
                skill_engine=None,
                composition_engine=None,
                subagent_manager=None,
                user_profiler=None,
            )


class TestSwapChannel:
    """Tests for RuntimeConfigManager.swap_channel."""

    @pytest.mark.asyncio
    async def test_swap_channel_invalid_name(self, tmp_path):
        """Unknown channel name raises ValueError."""
        config = AppConfig()
        manager = RuntimeConfigManager(config, str(tmp_path / "c.yaml"))

        with pytest.raises(ValueError, match="Unknown channel"):
            await manager.swap_channel("invalid", MagicMock(), MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_swap_channel_enable_qq(self, tmp_path):
        """Enabling QQ channel creates and starts it."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig()
        manager = RuntimeConfigManager(config, config_file)

        from thumbelina.channels.config import QQChannelConfig

        new_config = QQChannelConfig(enabled=True, app_id="test-id", app_secret="s")

        mock_agent = MagicMock()
        app_state = MagicMock()
        app_state.qq_channel = None  # no existing channel

        new_channel = AsyncMock()
        new_channel.start = AsyncMock()

        with patch("thumbelina.channels.qq_channel.QQChannel", return_value=new_channel):
            connected = await manager.swap_channel("qq", new_config, app_state, mock_agent)

        assert connected is True
        new_channel.start.assert_awaited_once()
        assert app_state.qq_channel is new_channel
        assert config.channels.qq.enabled is True
        assert config.channels.qq.app_id == "test-id"

    @pytest.mark.asyncio
    async def test_swap_channel_disable_qq(self, tmp_path):
        """Disabling QQ channel stops old and sets None."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate({"channels": {"qq": {"enabled": True}}})
        manager = RuntimeConfigManager(config, config_file)

        from thumbelina.channels.config import QQChannelConfig

        new_config = QQChannelConfig(enabled=False)

        old_channel = AsyncMock()
        old_channel.stop = AsyncMock()

        app_state = MagicMock()
        app_state.qq_channel = old_channel

        connected = await manager.swap_channel("qq", new_config, app_state, MagicMock())

        assert connected is False
        old_channel.stop.assert_awaited_once()
        assert app_state.qq_channel is None

    @pytest.mark.asyncio
    async def test_swap_channel_start_failure_raises(self, tmp_path):
        """Channel start failure raises RuntimeError."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig()
        manager = RuntimeConfigManager(config, config_file)

        from thumbelina.channels.config import WeChatChannelConfig

        new_config = WeChatChannelConfig(enabled=True, bot_token="tok")

        app_state = MagicMock()
        app_state.wechat_channel = None

        new_channel = AsyncMock()
        new_channel.start = AsyncMock(side_effect=ConnectionError("refused"))

        with (
            patch("thumbelina.channels.wechat_channel.WeChatChannel", return_value=new_channel),
            pytest.raises(RuntimeError, match="Failed to start wechat"),
        ):
            await manager.swap_channel("wechat", new_config, app_state, MagicMock())

        assert app_state.wechat_channel is None


class TestPersistConfig:
    """Tests for persistence from RuntimeConfigManager."""

    def test_persist_no_path_is_noop(self, tmp_path):
        """When config_path is None, persist does nothing."""
        config = AppConfig()
        manager = RuntimeConfigManager(config, None)
        # Should not raise
        manager._persist()

    def test_persist_writes_yaml(self, tmp_path):
        """persist writes the current config to disk."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate({"llm": {"provider": "ollama"}})
        manager = RuntimeConfigManager(config, config_file)

        manager._persist()

        raw = yaml.safe_load(open(config_file, encoding="utf-8").read())
        assert raw["llm"]["provider"] == "ollama"


class TestLoadFromDatabase:
    """Tests for RuntimeConfigManager.load_from_database auth overrides."""

    @staticmethod
    def _manager_with_db_config(config, db_config):
        repo = MagicMock()
        repo.export_to_dict = AsyncMock(return_value=db_config)
        return RuntimeConfigManager(config, None, config_repo=repo)

    @pytest.mark.asyncio
    async def test_auth_required_roles_applied_in_place(self):
        """required_roles from the DB update the existing list in place."""
        config = AppConfig.model_validate({"auth": {"required_roles": ["user"]}})
        original_list = config.auth.required_roles

        manager = self._manager_with_db_config(
            config, {"auth": {"required_roles": ["admin", "ops"]}}
        )
        await manager.load_from_database()

        assert config.auth.required_roles == ["admin", "ops"]
        # In-place update so a running auth middleware sees the change
        assert config.auth.required_roles is original_list

    @pytest.mark.asyncio
    async def test_auth_secret_key_never_applied_from_db(self):
        """secret_key is a secret and must never be applied from the DB."""
        config = AppConfig()
        manager = self._manager_with_db_config(
            config,
            {"auth": {"secret_key": "injected-from-db", "required_roles": ["admin"]}},
        )
        await manager.load_from_database()

        assert config.auth.secret_key == ""
        assert config.auth.required_roles == ["admin"]

    @pytest.mark.asyncio
    async def test_non_list_required_roles_ignored(self):
        """Malformed required_roles values are ignored without error."""
        config = AppConfig.model_validate({"auth": {"required_roles": ["user"]}})
        manager = self._manager_with_db_config(config, {"auth": {"required_roles": "admin"}})
        await manager.load_from_database()

        assert config.auth.required_roles == ["user"]
