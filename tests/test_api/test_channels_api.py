"""Tests for channel-related API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig


@pytest.fixture
def config_with_channels():
    """Create config with both channels enabled."""
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )
    config.channels.qq.enabled = True
    config.channels.qq.app_id = "test-qq-id"
    config.channels.qq.allowed_guilds = ["guild-1"]
    config.channels.wechat.enabled = True
    config.channels.wechat.ilink_bot_id = "test-bot-id"
    return config


class TestConfigIncludesChannels:
    """GET /api/v1/config includes channel configuration."""

    def test_config_has_channels_field(self, client: TestClient) -> None:
        """Response includes channels with qq and wechat sub-objects."""
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "channels" in data
        assert "qq" in data["channels"]
        assert "wechat" in data["channels"]

    def test_channel_fields_are_correct(self, client: TestClient) -> None:
        """Channel fields reflect config values (excluding secrets)."""
        resp = client.get("/api/v1/config")
        channels = resp.json()["channels"]
        # Default config has both disabled
        assert channels["qq"]["enabled"] is False
        assert channels["wechat"]["enabled"] is False
        assert "app_secret" not in channels["qq"]
        assert "bot_token" not in channels["wechat"]
        assert "webhook_secret" not in channels["wechat"]


class TestQQStatusEndpoint:
    """GET /api/v1/qq/status behavior."""

    def test_qq_status_not_initialized(self, client: TestClient) -> None:
        """Returns 404 when QQ channel is not in app.state."""
        resp = client.get("/api/v1/qq/status")
        assert resp.status_code == 404

    def test_qq_status_connected(self) -> None:
        """Returns connected status when QQ channel is mocked."""
        mock_channel = MagicMock()
        mock_channel.check_status = AsyncMock(
            return_value={"connected": True}
        )

        config = AppConfig(
            llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
            memory=MemoryConfig(database_url="sqlite:///:memory:"),
        )

        with (
            patch("thumbelina.api.app.MemoryManager"),
            patch("thumbelina.api.app.create_provider"),
            patch("thumbelina.api.app.ThumbelinaAgent"),
        ):
            from thumbelina.api.app import create_app

            app = create_app(config)
            app.state.qq_channel = mock_channel
            with TestClient(app) as test_client:
                resp = test_client.get("/api/v1/qq/status")
                assert resp.status_code == 200
                assert resp.json() == {"connected": True}
