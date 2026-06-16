"""Tests for thumbelina.channels.wechat_qrcode module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from thumbelina.channels.wechat_qrcode import (
    WeChatCredentials,
    WeChatQRCodeManager,
    _accounts_dir,
    _normalize_id,
)


class TestNormalizeID:
    def test_replaces_at(self):
        assert _normalize_id("bot@wechat") == "bot-wechat"

    def test_replaces_dot(self):
        assert _normalize_id("bot.name") == "bot-name"

    def test_replaces_colon(self):
        assert _normalize_id("bot:name") == "bot-name"

    def test_no_change(self):
        assert _normalize_id("normal-id") == "normal-id"


class TestAccountsDir:
    def test_returns_weclaw_accounts(self):
        d = _accounts_dir()
        assert ".weclaw" in str(d)
        assert "accounts" in str(d)


class TestFetchQRCode:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "qrcode": "test-qr-id-123",
            "qrcode_img_content": "https://ilinkai.weixin.qq.com/qr/xxx",
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        manager = WeChatQRCodeManager(http_client=mock_client)
        result = await manager.fetch_qrcode()

        assert result.qrcode == "test-qr-id-123"
        assert result.qrcode_img_content == "https://ilinkai.weixin.qq.com/qr/xxx"
        mock_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_qrcode_raises(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"qrcode": "", "qrcode_img_content": ""}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        manager = WeChatQRCodeManager(http_client=mock_client)
        with pytest.raises(ValueError, match="empty qrcode"):
            await manager.fetch_qrcode()

    @pytest.mark.asyncio
    async def test_http_error_propagates(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_resp
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        manager = WeChatQRCodeManager(http_client=mock_client)
        with pytest.raises(httpx.HTTPStatusError):
            await manager.fetch_qrcode()


class TestPollStatus:
    @pytest.mark.asyncio
    async def test_wait_status(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "wait"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        manager = WeChatQRCodeManager(http_client=mock_client)
        result = await manager.poll_status("qr-id")

        assert result.status == "wait"
        assert result.credentials is None

    @pytest.mark.asyncio
    async def test_scanned_status(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "scaned"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        manager = WeChatQRCodeManager(http_client=mock_client)
        result = await manager.poll_status("qr-id")

        assert result.status == "scaned"
        assert result.credentials is None

    @pytest.mark.asyncio
    async def test_confirmed_status_with_credentials(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "confirmed",
            "bot_token": "tok-123",
            "ilink_bot_id": "bot@wechat",
            "baseurl": "https://ilinkai.weixin.qq.com",
            "ilink_user_id": "user-456",
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        manager = WeChatQRCodeManager(http_client=mock_client)
        result = await manager.poll_status("qr-id")

        assert result.status == "confirmed"
        assert result.credentials is not None
        assert result.credentials.bot_token == "tok-123"
        assert result.credentials.ilink_bot_id == "bot@wechat"
        assert result.credentials.base_url == "https://ilinkai.weixin.qq.com"
        assert result.credentials.ilink_user_id == "user-456"

    @pytest.mark.asyncio
    async def test_expired_status(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "expired"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        manager = WeChatQRCodeManager(http_client=mock_client)
        result = await manager.poll_status("qr-id")

        assert result.status == "expired"
        assert result.credentials is None


class TestSaveCredentials:
    def test_saves_to_weclaw_accounts(self, tmp_path):
        creds = WeChatCredentials(
            bot_token="tok-abc",
            ilink_bot_id="bot@id",
            base_url="https://example.com",
            ilink_user_id="user-123",
        )

        accounts_dir = tmp_path / ".weclaw" / "accounts"
        with patch(
            "thumbelina.channels.wechat_qrcode._accounts_dir",
            return_value=accounts_dir,
        ):
            saved = WeChatQRCodeManager.save_credentials(creds)

        assert accounts_dir.exists()
        assert saved.endswith("bot-id.json")

        data = json.loads((accounts_dir / "bot-id.json").read_text())
        assert data["bot_token"] == "tok-abc"
        assert data["ilink_bot_id"] == "bot@id"
        assert data["baseurl"] == "https://example.com"
        assert data["ilink_user_id"] == "user-123"

    def test_creates_directory(self, tmp_path):
        creds = WeChatCredentials(
            bot_token="t",
            ilink_bot_id="b",
            base_url="u",
            ilink_user_id="i",
        )
        accounts_dir = tmp_path / "nested" / "deep" / "accounts"
        with patch(
            "thumbelina.channels.wechat_qrcode._accounts_dir",
            return_value=accounts_dir,
        ):
            WeChatQRCodeManager.save_credentials(creds)

        assert accounts_dir.exists()


class TestClose:
    @pytest.mark.asyncio
    async def test_close_without_client(self):
        manager = WeChatQRCodeManager()
        await manager.close()  # should not raise

    @pytest.mark.asyncio
    async def test_close_with_client(self):
        mock_client = AsyncMock()
        manager = WeChatQRCodeManager(http_client=mock_client)
        await manager.close()
        mock_client.aclose.assert_awaited_once()
