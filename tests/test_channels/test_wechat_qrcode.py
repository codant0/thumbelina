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
    load_credentials,
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
    def test_default_is_channel_dir(self):
        d = _accounts_dir()
        assert d.parts[:1] == ("CHANNEL",)
        assert ".weclaw" in str(d)
        assert "accounts" in str(d)
        assert not d.is_absolute()

    def test_override_takes_precedence(self, tmp_path):
        custom = tmp_path / "data" / "weclaw" / "accounts"
        assert _accounts_dir(str(custom)) == custom

    def test_empty_override_falls_back_to_default(self):
        assert _accounts_dir("") == _accounts_dir()


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

    def test_saves_to_override_dir(self, tmp_path):
        creds = WeChatCredentials(
            bot_token="tok",
            ilink_bot_id="bot-1",
            base_url="https://example.com",
            ilink_user_id="user-1",
        )
        custom_dir = tmp_path / "data" / "weclaw" / "accounts"

        saved = WeChatQRCodeManager.save_credentials(creds, str(custom_dir))

        assert custom_dir.exists()
        assert saved == str(custom_dir / "bot-1.json")
        data = json.loads((custom_dir / "bot-1.json").read_text())
        assert data["bot_token"] == "tok"


class TestLoadCredentials:
    def test_loads_by_bot_id(self, tmp_path):
        accounts_dir = tmp_path / "accounts"
        accounts_dir.mkdir()
        (accounts_dir / "bot-id.json").write_text(
            json.dumps(
                {
                    "bot_token": "tok-1",
                    "ilink_bot_id": "bot@id",
                    "baseurl": "https://example.com",
                    "ilink_user_id": "user-1",
                }
            ),
            encoding="utf-8",
        )

        creds = load_credentials(str(accounts_dir), bot_id="bot@id")

        assert creds is not None
        assert creds.bot_token == "tok-1"
        assert creds.ilink_bot_id == "bot@id"
        assert creds.base_url == "https://example.com"
        assert creds.ilink_user_id == "user-1"

    def test_missing_file_returns_none(self, tmp_path):
        assert load_credentials(str(tmp_path), bot_id="nobody") is None

    def test_auto_discovers_newest_file(self, tmp_path):
        accounts_dir = tmp_path / "accounts"
        accounts_dir.mkdir()
        old = accounts_dir / "old-bot.json"
        old.write_text(
            json.dumps(
                {
                    "bot_token": "old-token",
                    "ilink_bot_id": "old@bot",
                    "baseurl": "",
                    "ilink_user_id": "old@user",
                }
            ),
            encoding="utf-8",
        )
        new = accounts_dir / "new-bot.json"
        new.write_text(
            json.dumps(
                {
                    "bot_token": "new-token",
                    "ilink_bot_id": "new@bot",
                    "baseurl": "",
                    "ilink_user_id": "new@user",
                }
            ),
            encoding="utf-8",
        )
        # make 'new' strictly newer
        import os
        import time

        old_time = time.time() - 100
        os.utime(old, (old_time, old_time))

        creds = load_credentials(str(accounts_dir), bot_id="")

        assert creds is not None
        assert creds.bot_token == "new-token"
        assert creds.ilink_bot_id == "new@bot"

    def test_auto_discover_empty_dir_returns_none(self, tmp_path):
        assert load_credentials(str(tmp_path), bot_id="") is None

    def test_auto_discover_missing_dir_returns_none(self, tmp_path):
        assert load_credentials(str(tmp_path / "nope"), bot_id="") is None

    def test_parse_invalid_json_returns_none(self, tmp_path):
        accounts_dir = tmp_path / "accounts"
        accounts_dir.mkdir()
        (accounts_dir / "bad.json").write_text("{not json", encoding="utf-8")
        assert load_credentials(str(accounts_dir), bot_id="bad") is None


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
