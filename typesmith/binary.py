"""大端字节流读取器。

TrueType 的每一个表都是大端序，Python 的 ``struct`` 默认是小端，所以这里
统一包一层，免得每处都写 ``">"`` 前缀，也方便做边界检查。
"""

from __future__ import annotations

import struct
from typing import Tuple


class FontError(ValueError):
    """字体文件损坏或不支持时抛出。"""


class Reader:
    """在 ``bytes`` 上的大端游标。"""

    __slots__ = ("data", "pos", "end")

    def __init__(self, data: bytes, pos: int = 0, end: int | None = None):
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else end

    # ---------------------------------------------------------------- 基本
    def seek(self, pos: int) -> "Reader":
        if pos < 0 or pos > self.end:
            raise FontError(f"偏移 {pos} 越界（0..{self.end}）")
        self.pos = pos
        return self

    def skip(self, n: int) -> "Reader":
        return self.seek(self.pos + n)

    def remaining(self) -> int:
        return self.end - self.pos

    def _take(self, n: int, fmt: str) -> Tuple:
        if self.pos + n > self.end:
            raise FontError(f"读取 {n} 字节越界：pos={self.pos} end={self.end}")
        out = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += n
        return out

    def u8(self) -> int:
        return self._take(1, ">B")[0]

    def i8(self) -> int:
        return self._take(1, ">b")[0]

    def u16(self) -> int:
        return self._take(2, ">H")[0]

    def i16(self) -> int:
        return self._take(2, ">h")[0]

    def u32(self) -> int:
        return self._take(4, ">I")[0]

    def i32(self) -> int:
        return self._take(4, ">i")[0]

    def tag(self) -> str:
        out = self.data[self.pos:self.pos + 4].decode("latin-1")
        self.pos += 4
        return out

    def advance(self, n: int) -> Reader:
        return self.seek(self.pos + n)

    def take(self, n: int) -> bytes:
        if self.pos + n > self.end:
            raise FontError(f"读取 {n} 字节越界")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def f2dot14(self) -> float:
        return self.i16() / 16384.0

    def fixed(self) -> float:
        return self.i32() / 65536.0

    # ---------------------------------------------------------------- 批量
    def array_u16(self, n: int) -> list:
        if self.pos + 2 * n > self.end:
            raise FontError("数组越界")
        out = list(struct.unpack_from(f">{n}H", self.data, self.pos))
        self.pos += 2 * n
        return out

    def array_i16(self, n: int) -> list:
        if self.pos + 2 * n > self.end:
            raise FontError("数组越界")
        out = list(struct.unpack_from(f">{n}h", self.data, self.pos))
        self.pos += 2 * n
        return out

    def array_u32(self, n: int) -> list:
        if self.pos + 4 * n > self.end:
            raise FontError("数组越界")
        out = list(struct.unpack_from(f">{n}I", self.data, self.pos))
        self.pos += 4 * n
        return out
