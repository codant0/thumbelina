"""Tests for the WeChat QR code login API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.channels.wechat_qrcode import (
    QRCodeResult,
    QRStatusResult,
    WeChatCredentials,
)


@pytest.fixture()
def client():
    """Create a TestClient for the wechat QR code endpoints."""
    from thumbelina.api.app import create_app
    from thumbelina.config.models import AppConfig

    config = AppConfig.model_validate(
        {"channels": {"wechat": {"enabled": False}}}
    )
    app = create_app(config)
    return TestClient(app)


class TestGetQRCode:
    def test_success(self, client):
        """POST /wechat/qrcode returns QR code data."""
        mock_result = QRCodeResult(
            qrcode="qr-123",
            qrcode_img_content="https://ilinkai.weixin.qq.com/qr/xxx",
        )
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = AsyncMock()
            mock_manager.fetch_qrcode.return_value = mock_result
            mock_get.return_value = mock_manager

            resp = client.post("/api/v1/wechat/qrcode")

        assert resp.status_code == 200
        data = resp.json()
        assert data["qrcode"] == "qr-123"
        assert data["qrcode_img_content"] == "https://ilinkai.weixin.qq.com/qr/xxx"

    def test_failure_returns_502(self, client):
        """POST /wechat/qrcode returns 502 on iLink API failure."""
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = AsyncMock()
            mock_manager.fetch_qrcode.side_effect = ConnectionError("unreachable")
            mock_get.return_value = mock_manager

            resp = client.post("/api/v1/wechat/qrcode")

        assert resp.status_code == 502
        assert "unreachable" in resp.json()["detail"]


class TestQRCodeStatus:
    def test_wait_status(self, client):
        """GET /wechat/qrcode/status returns wait status."""
        mock_result = QRStatusResult(status="wait", credentials=None)
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = AsyncMock()
            mock_manager.poll_status.return_value = mock_result
            mock_get.return_value = mock_manager

            resp = client.get("/api/v1/wechat/qrcode/status?qrcode=qr-123")

        assert resp.status_code == 200
        assert resp.json()["status"] == "wait"
        assert "credentials" not in resp.json()

    def test_scanned_status(self, client):
        """GET /wechat/qrcode/status returns scaned status."""
        mock_result = QRStatusResult(status="scaned", credentials=None)
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = AsyncMock()
            mock_manager.poll_status.return_value = mock_result
            mock_get.return_value = mock_manager

            resp = client.get("/api/v1/wechat/qrcode/status?qrcode=qr-123")

        assert resp.status_code == 200
        assert resp.json()["status"] == "scaned"

    def test_confirmed_status_with_credentials(self, client):
        """GET /wechat/qrcode/status returns confirmed with credentials."""
        creds = WeChatCredentials(
            bot_token="tok",
            ilink_bot_id="bot@id",
            base_url="https://example.com",
            ilink_user_id="user",
        )
        mock_result = QRStatusResult(status="confirmed", credentials=creds)
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = AsyncMock()
            mock_manager.poll_status.return_value = mock_result
            mock_get.return_value = mock_manager

            resp = client.get("/api/v1/wechat/qrcode/status?qrcode=qr-123")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["credentials"]["bot_token"] == "tok"
        assert data["credentials"]["ilink_bot_id"] == "bot@id"

    def test_expired_status(self, client):
        """GET /wechat/qrcode/status returns expired status."""
        mock_result = QRStatusResult(status="expired", credentials=None)
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = AsyncMock()
            mock_manager.poll_status.return_value = mock_result
            mock_get.return_value = mock_manager

            resp = client.get("/api/v1/wechat/qrcode/status?qrcode=qr-123")

        assert resp.status_code == 200
        assert resp.json()["status"] == "expired"

    def test_missing_qrcode_param(self, client):
        """GET /wechat/qrcode/status without qrcode returns 422."""
        resp = client.get("/api/v1/wechat/qrcode/status")
        assert resp.status_code == 422

    def test_failure_returns_502(self, client):
        """GET /wechat/qrcode/status returns 502 on failure."""
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = AsyncMock()
            mock_manager.poll_status.side_effect = Exception("timeout")
            mock_get.return_value = mock_manager

            resp = client.get("/api/v1/wechat/qrcode/status?qrcode=qr-123")

        assert resp.status_code == 502


class TestConfirmLogin:
    def test_success(self, client):
        """POST /wechat/qrcode/confirm saves credentials and enables channel."""
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = MagicMock()
            mock_manager.save_credentials.return_value = "/home/user/.weclaw/accounts/bot-id.json"
            mock_get.return_value = mock_manager

            # Mock runtime config manager on app.state
            mock_runtime = AsyncMock()

            async def fake_swap(channel_name, new_config, app_state, agent):
                app_state.config.channels.wechat.enabled = True
                app_state.config.channels.wechat.bot_token = new_config.bot_token
                app_state.config.channels.wechat.ilink_bot_id = new_config.ilink_bot_id
                return True

            mock_runtime.swap_channel.side_effect = fake_swap
            client.app.state.runtime_config_manager = mock_runtime
            client.app.state.agent = MagicMock()

            resp = client.post(
                "/api/v1/wechat/qrcode/confirm",
                json={
                    "bot_token": "tok-abc",
                    "ilink_bot_id": "bot@id",
                    "base_url": "https://example.com",
                    "ilink_user_id": "user-123",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["bot_id"] == "bot@id"
        assert "credentials_path" in data
        assert data["connected"] is True

        # Verify channel was auto-enabled
        assert client.app.state.config.channels.wechat.enabled is True
        # Verify swap_channel was called
        mock_runtime.swap_channel.assert_awaited_once()

    def test_missing_fields_returns_422(self, client):
        """POST /wechat/qrcode/confirm with missing fields returns 422."""
        resp = client.post(
            "/api/v1/wechat/qrcode/confirm",
            json={"bot_token": "tok"},
        )
        assert resp.status_code == 422

    def test_save_failure_returns_500(self, client):
        """POST /wechat/qrcode/confirm returns 500 if save fails."""
        with patch(
            "thumbelina.api.routes.wechat._get_qrcode_manager"
        ) as mock_get:
            mock_manager = MagicMock()
            mock_manager.save_credentials.side_effect = OSError("disk full")
            mock_get.return_value = mock_manager

            resp = client.post(
                "/api/v1/wechat/qrcode/confirm",
                json={
                    "bot_token": "tok",
                    "ilink_bot_id": "bot",
                    "base_url": "url",
                    "ilink_user_id": "uid",
                },
            )

        assert resp.status_code == 500
        assert "disk full" in resp.json()["detail"]
