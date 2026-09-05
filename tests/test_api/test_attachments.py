"""Tests for image attachment REST endpoints (thumbelina.api.routes.attachments).

Covers upload / download / delete / size limit / unsupported mime / path
traversal protection (design doc §3.1 / §4.3, Task B6). Image bytes are
hand-constructed minimal headers (no binary fixtures committed).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import struct
from pathlib import Path

import pytest

from thumbelina.repository.repository import ConversationRepository

# ----------------------------------------------------------------------
# Minimal image byte builders (header-only, just enough for the
# pure-struct dimension parsers; not decodable by real image libraries).
# ----------------------------------------------------------------------


def _png_bytes(width: int = 3, height: int = 2) -> bytes:
    """PNG signature + IHDR header carrying big-endian width/height."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height)


def _jpeg_bytes(width: int = 4, height: int = 3) -> bytes:
    """JPEG SOI + SOF0 segment (height precedes width, big-endian)."""
    return (
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", height, width)
    )


def _gif_bytes(width: int = 6, height: int = 5) -> bytes:
    """GIF89a header with little-endian width/height."""
    return b"GIF89a" + struct.pack("<HH", width, height)


def _webp_bytes(width: int = 8, height: int = 7) -> bytes:
    """RIFF/WEBP container with a minimal VP8L payload."""
    bits = ((width - 1) & 0x3FFF) | (((height - 1) & 0x3FFF) << 14)
    return (
        b"RIFF"
        + struct.pack("<I", 17)
        + b"WEBP"
        + b"VP8L"
        + struct.pack("<I", 5)
        + b"\x2f"
        + bits.to_bytes(4, "little")
    )


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def attachment_repo() -> ConversationRepository:
    """Real repository backed by in-memory SQLite (StaticPool, cross-thread)."""
    return ConversationRepository("sqlite:///:memory:")


@pytest.fixture
def attachments_root(tmp_path: Path) -> Path:
    return tmp_path / "attachments"


@pytest.fixture
def attachment_client(client, attachment_repo, attachments_root: Path):
    """API client wired to a real attachment repository and a temp root."""
    client.app.state.repository_manager = attachment_repo
    client.app.state.config.repository.attachments_directory = str(attachments_root)
    return client


def _upload(attachment_client, data: bytes, mime: str = "image/png", alt: str | None = None):
    """POST a single image attachment via multipart."""
    form = {"alt": alt} if alt is not None else {}
    return attachment_client.post(
        "/api/v1/attachments",
        files={"file": ("img", data, mime)},
        data=form,
    )


def _get_record(repo: ConversationRepository, attachment_id: str):
    return asyncio.run(repo.get_attachment(attachment_id))


# ----------------------------------------------------------------------
# Upload (POST /api/v1/attachments)
# ----------------------------------------------------------------------


def test_upload_success_returns_metadata_persists_row_and_writes_file(
    attachment_client, attachment_repo, attachments_root
):
    """POST success: exact response shape, yyyy/mm file on disk, DB row readable."""
    data = _png_bytes()
    resp = _upload(attachment_client, data, alt="a screenshot")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"id", "mime", "size", "width", "height", "sha256", "alt"}
    assert body["mime"] == "image/png"
    assert body["size"] == len(data)
    assert body["width"] == 3
    assert body["height"] == 2
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["alt"] == "a screenshot"
    assert isinstance(body["id"], str) and body["id"]

    record = _get_record(attachment_repo, body["id"])
    assert record is not None
    assert record["mime"] == "image/png"
    assert record["size"] == len(data)
    assert record["width"] == 3
    assert record["height"] == 2
    assert record["sha256"] == body["sha256"]
    # 落盘于 attachments/{yyyy}/{mm}/<uuid>.<ext>
    assert re.fullmatch(r"\d{4}/\d{2}/[0-9a-f]{32}\.png", record["relative_path"])
    stored = attachments_root / record["relative_path"]
    assert stored.is_file()
    assert stored.read_bytes() == data


@pytest.mark.parametrize(
    ("mime", "builder", "width", "height"),
    [
        ("image/png", _png_bytes, 3, 2),
        ("image/jpeg", _jpeg_bytes, 4, 3),
        ("image/gif", _gif_bytes, 6, 5),
        ("image/webp", _webp_bytes, 8, 7),
    ],
)
def test_upload_parses_dimensions_for_all_supported_formats(
    attachment_client, mime, builder, width, height
):
    """Hand-built PNG/JPEG/GIF/WebP headers each resolve to real dimensions."""
    resp = _upload(attachment_client, builder(width, height), mime=mime)

    assert resp.status_code == 200
    body = resp.json()
    assert body["mime"] == mime
    assert body["width"] == width
    assert body["height"] == height


def test_upload_truncated_header_yields_null_dimensions(attachment_client):
    """A truncated image header still uploads but reports width/height null."""
    truncated = _png_bytes()[:16]  # signature only, IHDR dimensions cut off

    resp = _upload(attachment_client, truncated, mime="image/png")

    assert resp.status_code == 200
    body = resp.json()
    assert body["width"] is None
    assert body["height"] is None


def test_upload_rejects_unsupported_mime_empty_file_and_oversize(attachment_client):
    """mime 白名单 415 / 空文件 400 / >10MB 413."""
    unsupported = _upload(attachment_client, b"hello", mime="text/plain")
    assert unsupported.status_code == 415
    assert "image/png" in unsupported.json()["detail"]

    empty = _upload(attachment_client, b"", mime="image/png")
    assert empty.status_code == 400

    oversize = _upload(
        attachment_client, b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024 - 8 + 1)
    )
    assert oversize.status_code == 413


# ----------------------------------------------------------------------
# Download (GET /api/v1/attachments/{id})
# ----------------------------------------------------------------------


def test_get_attachment_round_trips_bytes_with_private_cache(attachment_client):
    """GET returns identical bytes, correct content type and private caching."""
    data = _png_bytes(width=10, height=4)
    created = _upload(attachment_client, data).json()

    resp = attachment_client.get(f"/api/v1/attachments/{created['id']}")

    assert resp.status_code == 200
    assert resp.content == data
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "private, max-age=86400"


def test_get_attachment_unknown_id_404(attachment_client):
    resp = attachment_client.get("/api/v1/attachments/does-not-exist")
    assert resp.status_code == 404


def test_get_attachment_missing_file_404(attachment_client, attachment_repo, attachments_root):
    """Row exists but the backing file was removed → 404 instead of a 500."""
    created = _upload(attachment_client, _png_bytes()).json()
    record = _get_record(attachment_repo, created["id"])
    (attachments_root / record["relative_path"]).unlink()

    resp = attachment_client.get(f"/api/v1/attachments/{created['id']}")
    assert resp.status_code == 404


def test_get_attachment_path_traversal_record_404(attachment_client, attachment_repo, tmp_path):
    """手工插入 relative_path='../../x' 的行 → 404 且不抛异常。

    The traversal target is created outside the root to prove the response
    is the traversal guard, not a missing file.
    """
    record = asyncio.run(
        attachment_repo.create_attachment(
            mime="image/png",
            size=3,
            relative_path="../../escape.png",
            width=None,
            height=None,
            sha256=None,
        )
    )
    (tmp_path / "escape.png").write_bytes(b"secret")

    resp = attachment_client.get(f"/api/v1/attachments/{record['id']}")
    assert resp.status_code == 404
    assert (tmp_path / "escape.png").read_bytes() == b"secret"  # untouched


# ----------------------------------------------------------------------
# Delete (DELETE /api/v1/attachments/{id})
# ----------------------------------------------------------------------


def test_delete_attachment_removes_row_and_file(
    attachment_client, attachment_repo, attachments_root
):
    """DELETE removes the DB row and the physical file; later GET is 404."""
    created = _upload(attachment_client, _png_bytes()).json()
    record = _get_record(attachment_repo, created["id"])
    stored = attachments_root / record["relative_path"]
    assert stored.is_file()

    resp = attachment_client.delete(f"/api/v1/attachments/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"id": created["id"], "deleted": True}

    assert _get_record(attachment_repo, created["id"]) is None
    assert not stored.exists()
    assert attachment_client.get(f"/api/v1/attachments/{created['id']}").status_code == 404


def test_delete_attachment_unknown_id_404(attachment_client):
    resp = attachment_client.delete("/api/v1/attachments/does-not-exist")
    assert resp.status_code == 404
