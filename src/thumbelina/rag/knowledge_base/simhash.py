"""SimHash 工具函数。

提供 SimHash 值的类型转换、汉明距离计算和 sqlite-vec 序列化，
供 Repository 层和 API 层使用。
"""

from __future__ import annotations


def hamming_distance(h1: bytes, h2: bytes) -> int:
    """计算两个 8 字节 SimHash blob 的汉明距离。

    Parameters
    ----------
    h1, h2:
        长度为 8 的 bytes 对象，表示 64-bit SimHash（大端序）。

    Returns
    -------
    int
        汉明距离，范围 [0, 64]。
    """
    return sum(bin(a ^ b).count("1") for a, b in zip(h1, h2))


def bytes_to_hex(b: bytes) -> str:
    """将 bytes 转为十六进制字符串（用于 API 响应展示）。"""
    return b.hex()


def hex_to_simhash_bytes(h: str) -> bytes:
    """将十六进制字符串转回 8 字节 simhash blob（用于 API 请求入参）。

    Parameters
    ----------
    h:
        16 位十六进制字符串，表示 64-bit SimHash。

    Returns
    -------
    bytes
        8 字节大端序 blob。

    Raises
    ------
    ValueError
        如果输入不是合法的 16 位十六进制字符串。
    """
    raw = bytes.fromhex(h)
    if len(raw) != 8:
        raise ValueError(f"SimHash 十六进制字符串应为 16 字符（8 字节），实际为 {len(raw)} 字节")
    return raw


def serialize_for_vec(sim_hash_bytes: bytes) -> bytes:
    """将 8 字节 SimHash 序列化为 sqlite-vec float[64] 列期望的格式。

    sqlite-vec 的 float 类型列使用 ``serialize_float32()`` 序列化。
    将每个 bit 展开为一个 float32（0.0 或 1.0），然后打包。

    对于 0/1 二进制向量，L2 距离的平方等于汉明距离。

    Parameters
    ----------
    sim_hash_bytes:
        8 字节 SimHash blob（大端序）。

    Returns
    -------
    bytes
        sqlite-vec 可接受的 float32 序列化数据。
    """
    import struct

    floats: list[float] = []
    for byte in sim_hash_bytes:
        for i in range(7, -1, -1):
            floats.append(float((byte >> i) & 1))
    return struct.pack(f"{len(floats)}f", *floats)
