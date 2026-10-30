"""排版结构：块 → 行 → 页。

竖排的断页用的是"贪心 + 孤行寡行修正"：先按可用高度顺序往下填，遇到
"段落只剩一行在本页"或者"下一页开头只剩一行"时，整段或一行的挪动一下。
横排的断行才值得用 Knuth–Plass，竖排不需要——页高是固定的，代价函数
简单到不值得做全局搜索。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .layout import (INF_BAD, LayoutOptions, Line, Paragraph, itemize,
                     layout_items)

__all__ = ["Block", "BlockStyle", "PageSpec", "PlacedLine", "Page", "Document",
           "Paginator", "parse_markup", "split_runs"]


@dataclass
class BlockStyle:
    font: object = None
    size: float = 16.0
    leading: float = 1.5
    color: Tuple[int, int, int] = (17, 17, 17)
    align: str = "justify"
    space_before: float = 0.0
    space_after: float = 0.0
    indent: float = 0.0
    tracking: float = 0.0                # 字间距（px），标题常用

    def options(self, measure: float) -> LayoutOptions:
        return LayoutOptions(size=self.size, leading=self.leading,
                             measure=measure, align=self.align)

    @property
    def baseline_skip(self) -> float:
        return self.size * self.leading


@dataclass
class Block:
    kind: str                            # "para" | "heading" | "rule" | "meta" | "code"
    text: str = ""
    style: BlockStyle = field(default_factory=BlockStyle)
    level: int = 1
    height: float = 0.0                  # 只有 rule 用
    rule_color: Tuple[int, int, int] = (0, 0, 0)
    runs: List[Tuple[str, bool]] = field(default_factory=list)   # (片段, 是否行内代码)


@dataclass
class PageSpec:
    width: int = 900
    height: int = 1220
    margin_top: float = 96.0
    margin_bottom: float = 96.0
    margin_left: float = 88.0
    margin_right: float = 88.0
    header: str = ""
    footer: bool = True

    @property
    def content_width(self) -> float:
        return self.width - self.margin_left - self.margin_right

    @property
    def content_height(self) -> float:
        return self.height - self.margin_top - self.margin_bottom


@dataclass
class PlacedLine:
    page: int
    x: float
    baseline: float
    items: List[object]
    line: Line
    style: BlockStyle
    text: str = ""
    depth: float = 0.0


@dataclass
class Page:
    index: int
    lines: List[PlacedLine] = field(default_factory=list)
    rules: List[Tuple[float, float, float, float, Tuple[int, int, int]]] = field(default_factory=list)


@dataclass
class Document:
    pages: List[Page]
    spec: PageSpec
    blocks: List[Block]
    measured: Dict[str, float] = field(default_factory=dict)

    @property
    def line_count(self) -> int:
        return sum(len(p.lines) for p in self.pages)


_CODE_RE = re.compile(r"`([^`]+)`")


def split_runs(text: str) -> List[Tuple[str, bool]]:
    """把 ``用 `head` 表`` 切成 [("用 ", False), ("head", True), (" 表", False)]。"""
    out: List[Tuple[str, bool]] = []
    pos = 0
    for m in _CODE_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def parse_markup(text: str, base: BlockStyle,
                 heading_font=None, heading_sizes: Optional[Sequence[float]] = None
                 ) -> List[Block]:
    """把极简标记解析成块。

    ``# `` / ``## `` 是标题，``---`` 是分隔线，空行分段，``> `` 是引言。
    """
    blocks: List[Block] = []
    sizes = list(heading_sizes or [base.size * 2.0, base.size * 1.4, base.size * 1.15])
    para: List[str] = []

    def flush() -> None:
        if para:
            text_ = " ".join(s.strip() for s in para).strip()
            if text_:
                blocks.append(Block("para", _plain(text_), base,
                                    runs=split_runs(text_)))
            para.clear()

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("---"):
            flush()
            blocks.append(Block("rule", "", base, height=1.0,
                                rule_color=(200, 200, 200)))
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = stripped[level:].strip()
            flush()
            size = sizes[min(level - 1, len(sizes) - 1)]
            style = BlockStyle(font=heading_font, size=size,
                               leading=1.22, color=base.color, align="left",
                               space_before=size * 0.9, space_after=size * 0.35)
            blocks.append(Block("heading", _plain(heading), style, level=level,
                                runs=split_runs(heading)))
            continue
        if stripped.startswith(">"):
            flush()
            style = BlockStyle(font=base.font, size=base.size, leading=base.leading,
                               color=(90, 90, 90), align="left",
                               space_before=base.size * 0.4,
                               space_after=base.size * 0.4, indent=base.size)
            quote = stripped[1:].strip()
            blocks.append(Block("meta", _plain(quote), style, runs=split_runs(quote)))
            continue
        para.append(line)
    flush()
    return blocks


def _plain(text: str) -> str:
    """去掉行内代码的反引号，作为块的纯文本。"""
    return _CODE_RE.sub(r"\1", text)


class Paginator:
    """把块流排成页。"""

    def __init__(self, spec: PageSpec, base: BlockStyle, mono=None):
        self.spec = spec
        self.base = base
        self.mono = mono                      # 行内代码用的等宽字体

    def _items(self, block: Block, fonts: Sequence, opts: LayoutOptions):
        """段落项流；带行内代码时按片段分开 itemize 再拼起来。"""
        runs = block.runs
        if not runs or self.mono is None or not any(code for _, code in runs):
            return itemize(block.text, fonts, opts)
        items: List[object] = []
        for idx, (text, is_code) in enumerate(runs):
            if not text:
                continue
            sub = itemize(text, [self.mono] if is_code else fonts, opts)
            if idx < len(runs) - 1:
                # 去掉这一段自己的 parfillskip 与强制断行，保留前面的空格胶，
                # 否则代码前后会粘成一个不可断的长词。
                if len(sub) >= 2 and sub[-1].kind == 2 and sub[-1].forced:
                    sub = sub[:-2]
            items.extend(sub)
        return items

    def layout(self, blocks: Sequence[Block], fonts: Sequence) -> Document:
        spec = self.spec
        pages: List[Page] = [Page(0)]
        y = spec.margin_top
        bottom = spec.height - spec.margin_bottom
        measure = spec.content_width

        def new_page() -> None:
            nonlocal y
            pages.append(Page(len(pages)))
            y = spec.margin_top

        for block in blocks:
            if block.kind == "rule":
                h = block.height
                if y + block.style.space_before + h > bottom:
                    new_page()
                y += block.style.space_before
                pages[-1].rules.append((spec.margin_left, y, spec.margin_left + measure,
                                        h, block.rule_color))
                y += h + block.style.space_after
                continue

            style = block.style
            if style.font is None:
                style.font = fonts[0]
            opts = style.options(measure - style.indent)
            para = layout_items(self._items(block, fonts, opts), opts)
            if not para.lines:
                continue

            skip = style.baseline_skip
            space_before = style.space_before
            lines = para.lines
            n = len(lines)

            # 页面顶部不留空段前距
            if y <= spec.margin_top + 0.01:
                space_before = 0.0

            need_first = space_before + skip
            if y + need_first > bottom:
                new_page()
                space_before = 0.0
            y += space_before

            i = 0
            while i < n:
                remaining = bottom - y
                fits = int(remaining // skip)
                if fits <= 0:
                    new_page()
                    continue
                chunk = min(fits, n - i)
                left = n - i - chunk
                # 寡行：不要只把一行留在页底
                if 0 < left and chunk == 1 and n > 2:
                    new_page()
                    continue
                # 孤行：不要只把一行带下一页
                if left == 1 and chunk >= 2:
                    chunk -= 1
                    left = 1
                for k in range(chunk):
                    line = lines[i + k]
                    pages[-1].lines.append(PlacedLine(
                        page=pages[-1].index,
                        x=spec.margin_left + style.indent,
                        baseline=y + skip * 0.80,
                        items=para.items,
                        line=line,
                        style=style,
                        text=line.text,
                        depth=opts.baseline_skip * 0.2))
                    y += skip
                i += chunk
                if i < n:
                    new_page()
            y += style.space_after
        return Document(pages=pages, spec=spec, blocks=list(blocks))
