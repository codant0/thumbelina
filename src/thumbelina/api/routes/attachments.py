"""图片附件 REST 路由(设计文档 §3.1 / §4.3 / Task B2)。

- ``POST /attachments``:multipart 上传单张图片(mime 白名单 + 10MB 上限),
  纯 ``struct`` 解析文件头取尺寸(不引入 Pillow,失败返回 (None, None)),
  落盘 ``{attachments_directory}/{yyyy}/{mm}/{uuid}.{ext}`` 后记录元数据。
- ``GET /attachments/{id}``:回读字节流,``Cache-Control: private, max-age=86400``。
- ``DELETE /attachments/{id}``:物理删除(行 + 磁盘文件,无软删/无 GC)。

个人单用户部署:无鉴权、无归属校验。任何从 ``relative_path`` 拼出的
路径必须 resolve 后仍在附件根目录内(路径穿越防护),否则 404。
"""

from __future__ import annotations

import hashlib
import struct
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from thumbelina.api.deps import get_repository_manager
from thumbelina.filestore import ensure_dir, safe_unlink, write_bytes_atomic
from thumbelina.repository.manager import RepositoryManager

router = APIRouter(tags=["attachments"])

# mime 白名单 → 落盘扩展名(设计 §4.3)
SUPPORTED_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_DEFAULT_ATTACHMENTS_DIRECTORY = "attachments"


# ----------------------------------------------------------------------
# 尺寸解析(纯 struct 解析文件头;解析不出一律返回 None,不抛错)
# ----------------------------------------------------------------------


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    """PNG:IHDR 块固定在文件头,16..24 为大端 width/height。"""
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _gif_dimensions(data: bytes) -> tuple[int, int] | None:
    """GIF:头 6..10 为小端 width/height。"""
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return width, height


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """JPEG:扫描 SOF0-CF 段(跳过 C4/C8/CC)解析尺寸。

    SOF 段内 i+5..i+9 依次是大端 height/width(先高后宽)。碰到 SOS/EOI
    即止——SOF 必在扫描数据之前,再往后扫只会误读。
    """
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    n = len(data)
    while i + 2 <= n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # 填充字节
            i += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # TEM/RST:无长度的独立标记
            i += 2
            continue
        if marker in (0xD9, 0xDA):  # EOI / SOS:扫描数据开始
            return None
        if i + 4 > n:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                return None
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if seg_len < 2:
            return None
        i += 2 + seg_len
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    """WebP:RIFF/WEBP 头后按 VP8 / VP8L / VP8X 三种子块分别解析。"""
    # VP8L 至少要 25 字节(头 20 + 签名 1 + 宽高 4),VP8/VP8X 要 30。
    if len(data) < 25 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    fourcc = data[12:16]
    if fourcc == b"VP8 ":  # 有损:帧头 3 字节 + 同步码后为小端 14bit 宽高
        if len(data) < 30 or data[23:26] != b"\x9d\x01\x2a":
            return None
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if fourcc == b"VP8L":  # 无损:签名 0x2F 后 4 字节打包 width-1 / height-1(各 14bit)
        if data[20] != 0x2F:
            return None
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if fourcc == b"VP8X":  # 扩展:画布宽高 -1 各占 3 字节小端
        if len(data) < 30:
            return None
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None


_DIMENSION_PARSERS = {
    "image/png": _png_dimensions,
    "image/gif": _gif_dimensions,
    "image/jpeg": _jpeg_dimensions,
    "image/webp": _webp_dimensions,
}


# ----------------------------------------------------------------------
# 路径与目录
# ----------------------------------------------------------------------


def _attachments_root(request: Request) -> Path:
    """解析附件根目录(绝对路径直接用,相对路径基于工作目录)。

    config 经 ``getattr`` 读取,测试 fixture 缺失时回退默认目录。
    """
    directory = _DEFAULT_ATTACHMENTS_DIRECTORY
    config = getattr(request.app.state, "config", None)
    repository_config = getattr(config, "repository", None) if config is not None else None
    if repository_config is not None:
        directory = getattr(repository_config, "attachments_directory", None) or directory
    root = Path(directory)
    return root if root.is_absolute() else Path.cwd() / root


def _attachment_file(root: Path, relative_path: str) -> Path:
    """从 ``relative_path`` 拼出绝对路径;逃逸附件根目录(路径穿越)则 404。"""
    full = (root / relative_path).resolve()
    try:
        full.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Attachment not found") from exc
    return full


# ----------------------------------------------------------------------
# 端点
# ----------------------------------------------------------------------


@router.post("/attachments")
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    alt: str | None = Form(default=None),
    repository: RepositoryManager = Depends(get_repository_manager),
) -> dict[str, Any]:
    """上传单张图片附件,返回 ``{id, mime, size, width, height, sha256, alt}``。"""
    mime = (file.content_type or "").lower()
    if mime not in SUPPORTED_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_TYPES))
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type {mime!r}; allowed: {allowed}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data)} bytes); max {MAX_ATTACHMENT_BYTES} bytes",
        )

    # 文件头只有几十字节,同步解析即可。
    dimensions = _DIMENSION_PARSERS[mime](data)
    width, height = dimensions if dimensions is not None else (None, None)
    sha256 = hashlib.sha256(data).hexdigest()

    now = datetime.now()
    file_id = uuid.uuid4().hex
    ext = SUPPORTED_TYPES[mime]
    relative_path = f"{now:%Y/%m}/{file_id}.{ext}"
    full = _attachments_root(request) / f"{now:%Y}" / f"{now:%m}" / f"{file_id}.{ext}"
    ensure_dir(full.parent)
    write_bytes_atomic(full, data)

    record = await repository.create_attachment(
        mime=mime,
        size=len(data),
        relative_path=relative_path,
        width=width,
        height=height,
        sha256=sha256,
    )
    return {
        "id": record["id"],
        "mime": mime,
        "size": len(data),
        "width": width,
        "height": height,
        "sha256": sha256,
        "alt": alt,
    }


@router.get("/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: str,
    request: Request,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> FileResponse:
    """按 id 回读附件字节流(私有缓存一天;行或文件缺失均 404)。"""
    record = await repository.get_attachment(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    root = _attachments_root(request)
    full = _attachment_file(root, record["relative_path"])
    if not full.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        full,
        media_type=record["mime"],
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    request: Request,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> dict[str, Any]:
    """物理删除附件(行 + 磁盘文件,无软删);id 不存在返回 404。"""
    record = await repository.get_attachment(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    root = _attachments_root(request)
    # 先做穿越防护再删行,防止伪造 relative_path 借 DELETE 删除任意文件。
    full = _attachment_file(root, record["relative_path"])
    if not await repository.delete_attachment(attachment_id):
        raise HTTPException(status_code=404, detail="Attachment not found")
    # 文件缺失视为已删除;OSError 由 safe_unlink 记 warning 不抛。
    safe_unlink(full)
    return {"id": attachment_id, "deleted": True}
