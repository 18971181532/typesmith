"""控制台输出的小工具。

Windows 的 cp936 管道会在遇到"→""×"这类符号时抛 UnicodeEncodeError，
直接把一段漂亮的报告变成 traceback。这里在入口处把三个标准流重新包成
UTF-8，并且提供几个不会崩的绘制函数（不支持的颜色就退化成纯文本）。
"""

from __future__ import annotations

import io
import os
import sys

__all__ = ["force_utf8", "supports_color", "c", "rule", "table", "human"]


def force_utf8() -> None:
    """把 stdout / stderr 换成 UTF-8，失败就算了。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc.replace("-", "") in ("utf8", "utf8mb4"):
            continue
        try:
            buf = getattr(stream, "buffer", None)
            if buf is None:
                continue
            wrapper = io.TextIOWrapper(buf, encoding="utf-8", errors="replace",
                                       newline="\n", line_buffering=True)
            setattr(sys, name, wrapper)
        except Exception:
            pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")
                    or os.environ.get("ANSICON") or "256color" in os.environ.get("TERM", ""))
    return True


_CODES = {
    "dim": "2", "bold": "1", "italic": "3",
    "red": "31", "green": "32", "yellow": "33", "blue": "34",
    "magenta": "35", "cyan": "36", "grey": "90",
}


def c(text: str, *styles: str) -> str:
    """给文本套 ANSI 样式；终端不支持时原样返回。"""
    if not styles or not supports_color():
        return text
    codes = [_CODES[s] for s in styles if s in _CODES]
    if not codes:
        return text
    return "\x1b[" + ";".join(codes) + "m" + text + "\x1b[0m"


def rule(width: int = 68, ch: str = "─") -> str:
    return c(ch * width, "grey")


def human(n: float, unit: str = "") -> str:
    """把字节数 / 计数变成好读的形式。"""
    value = float(n)
    for prefix in ("", "k", "M", "G"):
        if abs(value) < 1000 or prefix == "G":
            if prefix == "":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{prefix}{unit}"
        value /= 1000.0
    return f"{value:.1f}G{unit}"


def _visible_len(s: str) -> int:
    """算可见宽度：忽略 ANSI 转义，东亚宽字符算 2。"""
    out = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\x1b":
            j = s.find("m", i)
            i = (j + 1) if j != -1 else i + 1
            continue
        out += 2 if _wide(ch) else 1
        i += 1
    return out


def _wide(ch: str) -> bool:
    o = ord(ch)
    return (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF
            or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF
            or 0xFE30 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60
            or 0xFFE0 <= o <= 0xFFE6 or 0x20000 <= o <= 0x3FFFD)


def _pad(s: str, width: int, align: str = "left") -> str:
    gap = max(0, width - _visible_len(s))
    if align == "right":
        return " " * gap + s
    return s + " " * gap


def table(rows, headers=(), aligns=None) -> str:
    """极简表格：按可见宽度对齐，不依赖任何第三方库。"""
    rows = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
    if headers:
        rows = [[str(h) for h in headers]] + rows
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (ncol - len(r)))
    widths = [max(_visible_len(r[i]) for r in rows) for i in range(ncol)]
    aligns = list(aligns or []) + ["left"] * (ncol - len(aligns))
    lines = []
    for idx, r in enumerate(rows):
        cells = [_pad(r[i], widths[i], aligns[i]) for i in range(ncol)]
        line = "  ".join(cells).rstrip()
        if headers and idx == 0:
            line = c(line, "bold")
        lines.append(line)
    return "\n".join(lines)
