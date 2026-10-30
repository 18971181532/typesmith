"""最小 PNG 编码器（真彩色 8 位，无交错）。

只用 ``zlib`` 和 ``struct``：IHDR / IDAT / IEND 三个块，每行前面加一个
滤波字节 0（None）。对文字页面来说，用 Up 滤波压缩率会更好，但这里更看重
"一眼能看懂"。
"""

from __future__ import annotations

import struct
import zlib
from typing import List, Tuple

__all__ = ["encode_png", "write_png"]

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def encode_png(width: int, height: int, pixels: bytes, level: int = 6) -> bytes:
    stride = width * 3
    if len(pixels) != stride * height:
        raise ValueError(f"像素数据长度不符：{len(pixels)} != {width}×{height}×3")
    raw = bytearray()
    prev = bytes(stride)
    for row in range(height):
        line = pixels[row * stride:(row + 1) * stride]
        if level > 0 and bytes(line) == prev:
            raw += b"\x02" + bytes(stride)          # Up 滤波：整行与上一行相同
        else:
            raw += b"\x00" + line
        prev = bytes(line)
    out = bytearray(_SIGNATURE)
    out += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    out += _chunk(b"IDAT", zlib.compress(bytes(raw), level))
    out += _chunk(b"IEND", b"")
    return bytes(out)


def write_png(path: str, width: int, height: int, pixels: bytes, level: int = 6) -> None:
    with open(path, "wb") as fh:
        fh.write(encode_png(width, height, pixels, level))


def read_png_size(path: str) -> Tuple[int, int]:
    """读回一张 PNG 的宽高，测试和调试用。"""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != _SIGNATURE:
        raise ValueError("不是 PNG")
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def png_chunks(data: bytes) -> List[bytes]:
    """列出 PNG 里的块标签，用来验证结构。"""
    if data[:8] != _SIGNATURE:
        raise ValueError("不是 PNG")
    pos = 8
    tags = []
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        tags.append(tag)
        pos += 12 + length
    return tags
