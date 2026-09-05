"""Tests for thumbelina.channels.wechat_qrcode module."""

from __future__ import annotations

import base64
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from thumbelina.channels.wechat_qrcode import (
    NOVA_CDN_BASE,
    ILinkClient,
    ILinkMediaError,
    ILMessage,
    WeChatCredentials,
    WeChatQRCodeManager,
    _accounts_dir,
    _message_item_from_raw,
    _normalize_id,
    _parse_aes_key,
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    load_credentials,
)

# 手工构造的 AES-128-ECB 测试向量（key = bytes(range(16))，见 FIPS-197 C.1 家族）
_KEY = bytes(range(16))
_KEY_HEX = _KEY.hex()
_KEY_B64_RAW = base64.b64encode(_KEY).decode()
_KEY_B64_HEX = base64.b64encode(_KEY.hex().encode("ascii")).decode()
# PKCS7(padded) 加密 b"thumbelina-img-01"（17 字节 → 补 15 字节 0x0f）的密文
_PTA = b"thumbelina-img-01"
_CTA = bytes.fromhex("1bb538f370187e80d4ba57683a6bdfcdb0d91211dc6936cab48ef33f50869690")
# 加密 16 字节全 0 的密文——解密后末字节 0x00，PKCS7 填充必非法
_CT_BAD_PAD = bytes.fromhex("c6a13b37878f5b826f4f8162a1c8d879")


def _make_client() -> ILinkClient:
    """构建注入了 mock httpx 客户端的 ILinkClient。"""
    client = ILinkClient(bot_token="tok", ilink_bot_id="bot@id", ilink_user_id="user-1")
    client._client = AsyncMock()
    return client


def _json_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


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


class TestParseAesKey:
    """_parse_aes_key 兼容三种在野编码：裸 hex / base64(原始16字节) / base64(hex字符串)。"""

    def test_bare_hex(self):
        assert _parse_aes_key(_KEY_HEX) == _KEY

    def test_b64_of_raw_bytes(self):
        assert _parse_aes_key(_KEY_B64_RAW) == _KEY

    def test_b64_of_hex_string(self):
        assert _parse_aes_key(_KEY_B64_HEX) == _KEY

    def test_surrounding_whitespace_stripped(self):
        assert _parse_aes_key(f"  {_KEY_HEX}\n") == _KEY

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="为空"):
            _parse_aes_key("")

    def test_garbage_raises(self):
        with pytest.raises(ValueError, match="编码无法识别"):
            _parse_aes_key("not-a-key!!!")

    def test_wrong_decoded_length_raises(self):
        with pytest.raises(ValueError, match="长度异常"):
            _parse_aes_key(base64.b64encode(b"0123456789").decode())


class TestAesEcb:
    """AES-128-ECB + PKCS7 加解密；手工向量与往返一致性。"""

    def test_known_vector_round_trip(self):
        # 手工向量：ECB(key=bytes(range(16))) 加密 PKCS7(b"thumbelina-img-01")
        assert aes_ecb_encrypt(_PTA, _KEY) == _CTA
        assert aes_ecb_decrypt(_CTA, _KEY) == _PTA

    @pytest.mark.parametrize("length", [0, 1, 15, 16, 17, 100])
    def test_round_trip_various_lengths(self, length):
        plaintext = b"z" * length
        ciphertext = aes_ecb_encrypt(plaintext, _KEY)
        assert len(ciphertext) == (length // 16 + 1) * 16  # PKCS7 填充后大小
        assert aes_ecb_decrypt(ciphertext, _KEY) == plaintext

    def test_key_encodings_equivalent(self):
        """同一 key 的三种编码解密结果一致。"""
        for key in (_KEY, _KEY_HEX, _KEY_B64_RAW, _KEY_B64_HEX):
            assert aes_ecb_decrypt(_CTA, key) == _PTA

    def test_invalid_padding_raises(self):
        # 解密后为全 0 块，末字节 0x00 → PKCS7 非法
        with pytest.raises(ValueError):
            aes_ecb_decrypt(_CT_BAD_PAD, _KEY)

    def test_ciphertext_length_not_multiple_of_16_raises(self):
        with pytest.raises(ValueError, match="16 的倍数"):
            aes_ecb_decrypt(b"short", _KEY)

    def test_wrong_length_bytes_key_raises(self):
        with pytest.raises(ValueError, match="16 字节"):
            aes_ecb_encrypt(_PTA, b"0" * 15)


class TestMessageItemImageFields:
    """ILMessageItem 图片字段解析 + key 优先级（aeskey hex > media.aes_key）。"""

    def test_text_item_has_no_image_fields(self):
        item = _message_item_from_raw({"type": 1, "text_item": {"text": "hi"}})
        assert item.type == 1
        assert item.text == "hi"
        assert item.image_media_eqp == ""
        assert item.image_aeskey_hex == ""
        assert item.image_aes_key_b64 == ""
        assert item.resolved_aes_key() is None

    def test_full_image_item(self):
        raw = {
            "type": 2,
            "image_item": {
                "media": {"encrypt_query_param": "eqp-1", "aes_key": _KEY_B64_RAW},
                "aeskey": "ab" * 16,
                "url": "https://novac2c.cdn.weixin.qq.com/c2c/download?encrypted_query_param=x",
                "mid_size": 12345,
                "thumb_width": 1024,
                "thumb_height": 768,
            },
        }
        item = _message_item_from_raw(raw)
        assert item.image_media_eqp == "eqp-1"
        assert item.image_aes_key_b64 == _KEY_B64_RAW
        assert item.image_aeskey_hex == "ab" * 16
        assert item.image_full_url.endswith("encrypted_query_param=x")
        assert item.image_size == 12345
        assert item.image_width == 1024
        assert item.image_height == 768

    def test_key_priority_item_level_hex_wins(self):
        """item 级 aeskey（裸 hex）优先于 media.aes_key。"""
        item = _message_item_from_raw(
            {
                "type": 2,
                "image_item": {
                    "media": {"encrypt_query_param": "e", "aes_key": _KEY_B64_RAW},
                    "aeskey": "cd" * 16,
                },
            }
        )
        assert item.resolved_aes_key() == "cd" * 16

    def test_key_fallback_media_aes_key_b64_raw(self):
        item = _message_item_from_raw(
            {"type": 2, "image_item": {"media": {"aes_key": _KEY_B64_RAW}}}
        )
        assert item.resolved_aes_key() == _KEY_HEX

    def test_key_fallback_media_aes_key_b64_hex_string(self):
        item = _message_item_from_raw(
            {"type": 2, "image_item": {"media": {"aes_key": _KEY_B64_HEX}}}
        )
        assert item.resolved_aes_key() == _KEY_HEX

    def test_unparseable_media_aes_key_returns_none(self):
        item = _message_item_from_raw(
            {"type": 2, "image_item": {"media": {"aes_key": "!!not-b64!!"}}}
        )
        assert item.resolved_aes_key() is None

    def test_full_url_falls_back_to_media_level(self):
        item = _message_item_from_raw(
            {
                "type": 2,
                "image_item": {
                    "media": {
                        "encrypt_query_param": "q",
                        "full_url": "https://x.cdn.weixin.qq.com/a",
                    }
                },
            }
        )
        assert item.image_full_url == "https://x.cdn.weixin.qq.com/a"


class TestGetUpdatesImageParsing:
    """getupdates 端到端：image_item 字段进入 ILMessageItem。"""

    @pytest.mark.asyncio
    async def test_getupdates_parses_image_item(self):
        client = _make_client()
        raw_msg = {
            "message_id": 7,
            "from_user_id": "wx-user-1",
            "to_user_id": "bot-1",
            "message_type": 1,
            "message_state": 0,
            "context_token": "ctx-7",
            "item_list": [
                {"type": 1, "text_item": {"text": "看图"}},
                {
                    "type": 2,
                    "image_item": {
                        "media": {"encrypt_query_param": "eqp-7", "aes_key": _KEY_B64_RAW},
                        "aeskey": _KEY_HEX,
                        "mid_size": 2048,
                    },
                },
            ],
        }
        client._client.post = AsyncMock(
            return_value=_json_response({"ret": 0, "get_updates_buf": "buf-2", "msgs": [raw_msg]})
        )

        messages, sync = await client.getupdates("buf-1")
        assert sync == "buf-2"
        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, ILMessage)
        assert msg.context_token == "ctx-7"
        assert len(msg.items) == 2
        assert msg.items[0].text == "看图"
        img = msg.items[1]
        assert img.type == 2
        assert img.image_media_eqp == "eqp-7"
        assert img.image_aeskey_hex == _KEY_HEX
        assert img.image_aes_key_b64 == _KEY_B64_RAW
        assert img.image_size == 2048
        # key 优先级：item 级 hex 胜出
        assert img.resolved_aes_key() == _KEY_HEX


class TestDownloadMedia:
    """download_media：CDN URL 构造、无鉴权头、full_url allowlist、解密。"""

    @pytest.mark.asyncio
    async def test_builds_cdn_url_without_auth_headers_and_decrypts(self):
        client = _make_client()
        resp = MagicMock()
        resp.content = aes_ecb_encrypt(b"secret-image-bytes", _KEY)
        resp.raise_for_status = MagicMock()
        client._client.get = AsyncMock(return_value=resp)

        out = await client.download_media("eqp token/x", _KEY_HEX)

        assert out == b"secret-image-bytes"
        # encrypt_query_param 需 urlencode；且不带任何鉴权头（仅位置参数 URL）
        client._client.get.assert_awaited_once_with(
            f"{NOVA_CDN_BASE}/download?encrypted_query_param=eqp%20token%2Fx"
        )

    @pytest.mark.asyncio
    async def test_prefers_allowed_full_url(self):
        client = _make_client()
        resp = MagicMock()
        resp.content = aes_ecb_encrypt(b"data", _KEY)
        resp.raise_for_status = MagicMock()
        client._client.get = AsyncMock(return_value=resp)

        full_url = "https://abc123.cdn.weixin.qq.com/c2c/download?encrypted_query_param=zz"
        await client.download_media("eqp", _KEY, full_url=full_url)
        client._client.get.assert_awaited_once_with(full_url)

    @pytest.mark.asyncio
    async def test_refuses_non_wechat_cdn_full_url(self):
        client = _make_client()
        with pytest.raises(ValueError, match="SSRF"):
            await client.download_media("eqp", _KEY, full_url="https://evil.example.com/payload")
        client._client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refuses_http_scheme_even_on_wechat_cdn(self):
        client = _make_client()
        with pytest.raises(ValueError, match="SSRF"):
            await client.download_media(
                "eqp", _KEY, full_url="http://novac2c.cdn.weixin.qq.com/c2c/download"
            )

    @pytest.mark.asyncio
    async def test_refuses_lookalike_host(self):
        client = _make_client()
        with pytest.raises(ValueError, match="SSRF"):
            await client.download_media(
                "eqp", _KEY, full_url="https://cdn.weixin.qq.com.evil.com/x"
            )

    @pytest.mark.asyncio
    async def test_bad_padding_raises_value_error(self):
        client = _make_client()
        resp = MagicMock()
        resp.content = _CT_BAD_PAD  # 解密后全 0，PKCS7 非法
        resp.raise_for_status = MagicMock()
        client._client.get = AsyncMock(return_value=resp)

        with pytest.raises(ValueError):
            await client.download_media("eqp", _KEY)


class TestSendImage:
    """send_image 三步流：getuploadurl → CDN POST（x-encrypted-param）→ sendmessage。"""

    @pytest.mark.asyncio
    async def test_three_step_flow_payloads_and_headers(self):
        client = _make_client()
        client._client.post = AsyncMock(
            side_effect=[
                _json_response({"upload_param": "up-param"}),
                MagicMock(status_code=200, headers={"x-encrypted-param": "enc-param"}),
                _json_response({"ret": 0}),
            ]
        )

        plaintext = b"hello"  # 5 字节 → PKCS7 填充到 16
        await client.send_image("wx-user-1", plaintext, context_token="ctx-1")

        assert client._client.post.await_count == 3

        # ── 第 1 步：getuploadurl ──
        call1 = client._client.post.await_args_list[0]
        assert call1.args[0] == "https://ilinkai.weixin.qq.com/ilink/bot/getuploadurl"
        payload1 = call1.kwargs["json"]
        assert len(payload1["filekey"]) == 32
        aes_key_hex = payload1["aeskey"]
        assert len(aes_key_hex) == 32 and int(aes_key_hex, 16) >= 0  # 裸 32-hex
        assert payload1["media_type"] == 1
        assert payload1["to_user_id"] == "wx-user-1"
        assert payload1["rawsize"] == 5
        assert payload1["rawfilemd5"] == hashlib.md5(b"hello").hexdigest()
        assert payload1["filesize"] == 16  # PKCS7 填充后大小
        assert payload1["no_need_thumb"] is True
        assert call1.kwargs["headers"]["Authorization"] == "Bearer tok"

        # ── 第 2 步：CDN POST（必须 POST，body=AES 密文）──
        call2 = client._client.post.await_args_list[1]
        assert call2.args[0] == (
            f"{NOVA_CDN_BASE}/upload?encrypted_query_param=up-param&filekey={payload1['filekey']}"
        )
        ciphertext = call2.kwargs["content"]
        assert len(ciphertext) == 16
        # 密文可用第 1 步上报的 aeskey 解回明文
        assert aes_ecb_decrypt(ciphertext, aes_key_hex) == plaintext
        assert call2.kwargs["headers"] == {"Content-Type": "application/octet-stream"}

        # ── 第 3 步：sendmessage，aes_key=base64(hex字符串) gotcha ──
        call3 = client._client.post.await_args_list[2]
        assert call3.args[0] == "https://ilinkai.weixin.qq.com/ilink/bot/sendmessage"
        msg = call3.kwargs["json"]["msg"]
        assert msg["to_user_id"] == "wx-user-1"
        assert msg["context_token"] == "ctx-1"
        item = msg["item_list"][0]
        assert item["type"] == 2
        media = item["image_item"]["media"]
        assert media["encrypt_query_param"] == "enc-param"
        # 关键断言（hermes 锁定的 gotcha）：base64(hex字符串)，而非 base64(原始字节)
        assert media["aes_key"] == base64.b64encode(aes_key_hex.encode("ascii")).decode("ascii")
        assert media["aes_key"] != base64.b64encode(bytes.fromhex(aes_key_hex)).decode()
        assert media["encrypt_type"] == 1
        assert item["image_item"]["mid_size"] == 16
        assert call3.kwargs["headers"]["Authorization"] == "Bearer tok"

    @pytest.mark.asyncio
    async def test_missing_upload_param_raises_media_error(self):
        client = _make_client()
        client._client.post = AsyncMock(side_effect=[_json_response({"ret": 0})])

        with pytest.raises(ILinkMediaError, match="upload_param"):
            await client.send_image("u", b"data", context_token="c")
        assert client._client.post.await_count == 1  # 后续两步未执行

    @pytest.mark.asyncio
    async def test_cdn_http_failure_raises_media_error(self):
        client = _make_client()
        client._client.post = AsyncMock(
            side_effect=[
                _json_response({"upload_param": "up-param"}),
                MagicMock(status_code=500, headers={}),
            ]
        )

        with pytest.raises(ILinkMediaError, match="CDN 上传失败"):
            await client.send_image("u", b"data", context_token="c")
        assert client._client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_missing_x_encrypted_param_raises_media_error(self):
        client = _make_client()
        client._client.post = AsyncMock(
            side_effect=[
                _json_response({"upload_param": "up-param"}),
                MagicMock(status_code=200, headers={}),
            ]
        )

        with pytest.raises(ILinkMediaError, match="x-encrypted-param"):
            await client.send_image("u", b"data", context_token="c")

    @pytest.mark.asyncio
    async def test_sendmessage_errcode_nonzero_does_not_raise(self):
        """与 send_message 文本路径一致：errcode!=0 仅告警，不抛异常。"""
        client = _make_client()
        client._client.post = AsyncMock(
            side_effect=[
                _json_response({"upload_param": "up-param"}),
                MagicMock(status_code=200, headers={"x-encrypted-param": "enc-param"}),
                _json_response({"errcode": -1, "errmsg": "freq limit"}),
            ]
        )

        await client.send_image("u", b"data", context_token="c")  # should not raise
        assert client._client.post.await_count == 3
