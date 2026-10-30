"""Knuth–Plass 断行 + 行内定位。

为什么不用"贪心填行"？因为贪心只看当前一行，会把好看的断点留给后面更差的
一行。Knuth–Plass 把整段当成最短路问题：每个可行断点是一个节点，边的代价是
"这一行的松散程度"（badness）加上惩罚项，用动态规划求全局最优。

代价函数（沿用 TeX 的定义）::

    badness = 100 · |ratio|³
    demerits = (line_penalty + badness)² ± penalty²
               + fitness_demerit·[相邻两行松紧等级差 > 1]
               + flagged_demerit·[相邻两个断点都带连字符]

``ratio`` 是"还需要伸缩多少"：正值要拉开，负值要压紧，小于 -1 表示根本放不下。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = ["Box", "Glue", "Penalty", "LayoutOptions", "Paragraph", "Line",
           "itemize", "break_lines", "layout_items", "layout_paragraph", "greedy_break",
           "total_demerits", "line_ratio"]

BOX, GLUE, PENALTY = 0, 1, 2
INF_PENALTY = 10000.0
INF_BAD = 10000.0

# 这些标点不能出现在行首 / 行尾（简化版避头尾）
NO_LINE_START = "，。、；：？！）】》」』”’,.;:?!)]}%"
NO_LINE_END = "（【《「『“‘([{"


@dataclass
class Box:
    """不可分割的内容（一个单词、一个汉字）。"""

    text: str
    font: object
    size: float
    glyphs: List[Tuple[int, float]]          # (gid, 前进宽度 px)
    width: float
    kind: int = BOX
    flex: bool = False                      # 汉字：两端对齐时可以拉开字距

    def __len__(self) -> int:
        return len(self.glyphs)


@dataclass
class Glue:
    width: float
    stretch: float
    shrink: float
    kind: int = GLUE
    text: str = " "


@dataclass
class Penalty:
    width: float
    penalty: float
    flagged: bool = False
    kind: int = PENALTY
    text: str = ""

    @property
    def forced(self) -> bool:
        return self.penalty <= -INF_PENALTY


@dataclass
class LayoutOptions:
    size: float = 16.0
    leading: float = 1.5
    measure: float = 480.0
    align: str = "justify"                  # justify | left | center | right
    line_penalty: float = 10.0
    fitness_demerit: float = 3000.0
    flagged_demerit: float = 100.0
    tolerance: float = 4.0                  # 允许的最大 ratio
    hyphen_penalty: float = 50.0
    kern: bool = True
    space_stretch: float = 0.5              # 相对 word space 的倍数
    space_shrink: float = 0.333
    cjk_stretch: float = 0.25               # 汉字间可拉伸的比例（em）
    widow_penalty: float = 300.0
    orphan_penalty: float = 300.0

    @property
    def baseline_skip(self) -> float:
        return self.size * self.leading


@dataclass
class Line:
    items: List[int]                        # item 下标区间 [start, end)
    start: int
    end: int
    natural: float
    ratio: float
    badness: float
    demerits: float
    fitness: int
    text: str = ""
    depth: float = 0.0

    @property
    def width(self) -> float:
        return self.natural


@dataclass
class Paragraph:
    lines: List[Line]
    items: List[object]
    options: LayoutOptions
    demerits: float = 0.0
    total_stretch: float = 0.0
    total_shrink: float = 0.0
    text: str = ""

    def placed(self) -> List[List[Tuple[object, int, float, float]]]:
        """把每行展开成 (font, gid, x, y_offset) 的绘制指令。"""
        return [position_line(self.items, line, self.options) for line in self.lines]


# --------------------------------------------------------------------- 断词


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (0x2E80 <= code <= 0x9FFF or 0x3000 <= code <= 0x303F
            or 0xF900 <= code <= 0xFAFF or 0xFF00 <= code <= 0xFFEF
            or 0x20000 <= code <= 0x2FA1F)


def _kern(font, left: int, right: int, size: float, enabled: bool) -> float:
    if not enabled or left < 0 or right < 0:
        return 0.0
    return font.kerning(left, right) * size / font.units_per_em


def _measure_word(text: str, font, size: float, kern: bool) -> Tuple[List[Tuple[int, float]], float]:
    glyphs: List[Tuple[int, float]] = []
    total = 0.0
    prev = -1
    for ch in text:
        gid = font.glyph_id(ord(ch))
        total += _kern(font, prev, gid, size, kern)
        adv = font.advance(gid) * size / font.units_per_em
        glyphs.append((gid, adv))
        total += adv
        prev = gid
    return glyphs, total


def itemize(text: str, fonts: Sequence, options: LayoutOptions,
            font_for=None) -> List[object]:
    """把一段文字拆成 box / glue / penalty 序列。

    ``fonts[0]`` 是主字体；某个字符在主字体里缺失（gid == 0）时，按顺序找
    下一个能显示它的字体。``font_for(ch)`` 可以覆盖这个选择。
    """
    if not fonts:
        raise ValueError("至少需要一个字体")
    size = options.size
    space_w = size / 3.0
    items: List[object] = []
    buf: List[str] = []
    buf_font = None

    def flush() -> None:
        nonlocal buf, buf_font
        if not buf:
            return
        word = "".join(buf)
        glyphs, width = _measure_word(word, buf_font, size, options.kern)
        items.append(Box(word, buf_font, size, glyphs, width))
        buf = []
        buf_font = None

    def pick(ch: str):
        if font_for is not None:
            f = font_for(ch)
            if f is not None:
                return f
        for f in fonts:
            if f.glyph_id(ord(ch)):
                return f
        return fonts[0]

    n = len(text)
    for i, ch in enumerate(text):
        if ch in "\n":
            flush()
            items.append(Penalty(0.0, -INF_PENALTY, text="\n"))
            continue
        if ch == " ":
            flush()
            items.append(Glue(space_w, space_w * options.space_stretch,
                              space_w * options.space_shrink))
            continue
        if _is_cjk(ch):
            flush()
            font = pick(ch)
            glyphs, width = _measure_word(ch, font, size, False)
            items.append(Box(ch, font, size, glyphs, width, flex=True))
            # 汉字之间允许断行；给一点可拉伸量用于两端对齐
            stretch = size * options.cjk_stretch * 0.2
            if i + 1 < n and text[i + 1] not in NO_LINE_START and ch not in NO_LINE_END:
                items.append(Glue(0.0, stretch, 0.0, text=""))
            continue
        # 拉丁：标点吸附在单词上，但行首禁则要处理
        if buf_font is None:
            buf_font = pick(ch)
        buf.append(ch)

    flush()

    # 收尾："""parfillskip""" —— 末行可以短，所以给它无限可拉伸量，
    # 否则最后一行永远算"太松"，整段会退化成一行。
    items.append(Glue(0.0, INF_BAD, 0.0, text=""))
    items.append(Penalty(0.0, -INF_PENALTY, text=""))
    return items


# ----------------------------------------------------------------- 断行核心


class _Node:
    __slots__ = ("pos", "line", "fitness", "total", "prev", "ratio", "demerits",
                 "flagged")

    def __init__(self, pos: int, line: int, fitness: int, total: float,
                 prev: Optional["_Node"], ratio: float, demerits: float):
        self.pos = pos
        self.line = line
        self.fitness = fitness
        self.total = total
        self.prev = prev
        self.ratio = ratio
        self.demerits = demerits
        self.flagged = False


def _fitness(ratio: float) -> int:
    if ratio < -0.5:
        return 0
    if ratio <= 0.5:
        return 1
    if ratio <= 1.0:
        return 2
    return 3


def break_lines(items: Sequence[object], measure: float,
                options: LayoutOptions) -> List[Line]:
    """Knuth–Plass：在 item 序列上求全局最省的断点组合。

    活跃节点列表维护三件事：
      · 某行"太松"（ratio > tolerance）—— 祖先还活着，等更长的断点；
      · 某行"太紧"（ratio < -1）—— 再往后只会更紧，这个祖先可以退休；
      · 同一 (行号, 松紧等级) 只留累计代价最小的节点。
    """
    n = len(items)
    sum_w = [0.0] * (n + 1)
    sum_y = [0.0] * (n + 1)
    sum_z = [0.0] * (n + 1)
    for i, it in enumerate(items):
        w = y = z = 0.0
        if it.kind == BOX:
            w = it.width
        elif it.kind == GLUE:
            w, y, z = it.width, it.stretch, it.shrink
        sum_w[i + 1] = sum_w[i] + w
        sum_y[i + 1] = sum_y[i] + y
        sum_z[i + 1] = sum_z[i] + z

    root = _Node(-1, 0, 1, 0.0, None, 0.0, 0.0)
    active: List[_Node] = [root]
    finished: Optional[_Node] = None          # 最后一个强制断点处的节点

    for b in range(n):
        item = items[b]
        if item.kind == PENALTY:
            if item.penalty >= INF_PENALTY:
                continue
        elif item.kind == GLUE:
            if b == 0 or items[b - 1].kind != BOX:
                continue
        else:
            continue

        forced = item.kind == PENALTY and item.forced
        survivors: List[_Node] = []
        fresh: List[_Node] = []
        finals: List[_Node] = []
        for a in active:
            start_idx = a.pos + 1
            if start_idx > b:
                survivors.append(a)
                continue
            width = sum_w[b] - sum_w[start_idx]
            stretch = sum_y[b] - sum_y[start_idx]
            shrink = sum_z[b] - sum_z[start_idx]
            pen = 0.0
            flagged = False
            if item.kind == PENALTY:
                pen = item.penalty
                flagged = item.flagged
                width += item.width

            ratio = line_ratio(measure, width, stretch, shrink)

            if ratio < -1.0:
                # 已经溢出：换更长的断点只会更糟，祖先退休
                continue
            over = ratio > options.tolerance

            badness = 100.0 * abs(ratio) ** 3
            if over:
                # 太松：仍然连上这条边，否则整段的断点图会被一处极端松行切断，
                # 只能退化成一整行。代价顶格，交给最短路去回避。
                badness = INF_BAD
            if badness > INF_BAD:
                badness = INF_BAD
            base = (options.line_penalty + badness) ** 2
            if pen >= 0.0:
                demerits = base + pen * pen
            elif pen > -INF_PENALTY:
                demerits = base - pen * pen
            else:
                demerits = base
            if a.line > 0 and abs(_fitness(ratio) - a.fitness) > 1:
                demerits += options.fitness_demerit
            if flagged and getattr(a, "flagged", False):
                demerits += options.flagged_demerit

            node = _Node(b, a.line + 1, _fitness(ratio), a.total + demerits,
                         a, ratio, demerits)
            node.flagged = flagged
            if forced:
                finals.append(node)
            else:
                survivors.append(a)
                fresh.append(node)

        if forced:
            # 强制断行把这一段收尾：取最省的一条，然后从它继续下一段。
            # 若把它当成普通候选节点，后面的行就接不上来（链会断在这里）。
            if finals:
                finished = min(finals, key=lambda nd: nd.total)
                active = [finished]
            else:
                active = survivors
            continue

        keep: Dict[Tuple[int, int], _Node] = {}
        for node in fresh:
            key = (node.line, node.fitness)
            old = keep.get(key)
            if old is None or node.total < old.total:
                keep[key] = node
        active = survivors + list(keep.values())
        if len(active) > 600:
            active.sort(key=lambda nd: nd.total)
            active = active[:300]

    if finished is None:
        # 没有强制断点就取当前最省的节点（正常路径下不会走到）
        candidates = [nd for nd in active if nd.pos >= 0]
        finished = min(candidates, key=lambda nd: nd.total) if candidates else None
    if finished is None:
        return _fallback_lines(items, measure, options)

    chain: List[_Node] = []
    node: Optional[_Node] = finished
    while node is not None and node.pos >= 0:
        chain.append(node)
        node = node.prev
    chain.reverse()

    lines: List[Line] = []
    prev_pos = -1
    prev_total = 0.0
    for node in chain:
        b = node.pos
        start_idx = prev_pos + 1
        width = sum_w[b] - sum_w[start_idx]
        if items[b].kind == PENALTY:
            width += items[b].width
        delta = node.total - prev_total
        prev_total = node.total
        lines.append(Line(items=None, start=start_idx, end=b, natural=width,
                          ratio=node.ratio, badness=100.0 * abs(node.ratio) ** 3,
                          demerits=delta, fitness=node.fitness,
                          text=_line_text(items, start_idx, b, items[b])))
        prev_pos = b
    return lines


def _line_text(items: Sequence[object], start: int, end: int, tail=None) -> str:
    out = []
    for i in range(start, end):
        it = items[i]
        if it.kind == BOX:
            out.append(it.text)
        elif it.kind == GLUE:
            out.append(it.text)
    if isinstance(tail, Penalty) and tail.width:
        out.append(tail.text or "-")
    return "".join(out)


def _fallback_lines(items: Sequence[object], measure: float,
                    options: LayoutOptions) -> List[Line]:
    lines: List[Line] = []
    cur: List[int] = []
    width = 0.0
    start = 0
    for i, it in enumerate(items):
        if it.kind == PENALTY and it.forced:
            lines.append(Line(None, start, i, width, 0.0, 0.0, 0.0, 1,
                              _line_text(items, start, i)))
            cur = []
            width = 0.0
            start = i + 1
            continue
        if it.kind == BOX:
            width += it.width
        elif it.kind == GLUE:
            width += it.width
        cur.append(i)
    if cur:
        lines.append(Line(None, start, len(items) - 1, width, 0.0, 0.0, 0.0, 1,
                          _line_text(items, start, len(items) - 1)))
    return lines


def greedy_break(items: Sequence[object], measure: float,
                 options: LayoutOptions) -> List[Line]:
    """贪心断行：塞不下就断。用来和 Knuth–Plass 做对照。

    关键细节：断点处的 glue 必须从该行的宽度里扣掉（TeX 的规则是断点处的
    胶被丢弃）。若不扣，每行的自然宽度会多出一个空格、可伸长量也会多算一份，
    ratio 就被系统性地压低——对照图会得出"贪心反而更省"的假结论。
    """
    n = len(items)
    sw = [0.0] * (n + 1)
    sy = [0.0] * (n + 1)
    sz = [0.0] * (n + 1)
    for i, it in enumerate(items):
        w = y = z = 0.0
        if it.kind == BOX:
            w = it.width
        elif it.kind == GLUE:
            w, y, z = it.width, it.stretch, it.shrink
        sw[i + 1] = sw[i] + w
        sy[i + 1] = sy[i] + y
        sz[i + 1] = sz[i] + z

    def legal(i: int) -> bool:
        it = items[i]
        if it.kind == PENALTY:
            return it.penalty < INF_PENALTY
        if it.kind == GLUE:
            return i > 0 and items[i - 1].kind == BOX
        return False

    lines: List[Line] = []
    start = 0
    while start < n:
        chosen: Optional[Tuple[int, float, float]] = None
        for b in range(start, n):
            it = items[b]
            forced = it.kind == PENALTY and it.forced
            if not forced and not legal(b):
                continue
            width = sw[b] - sw[start] + (it.width if it.kind == PENALTY else 0.0)
            ratio = line_ratio(measure, width, sy[b] - sy[start], sz[b] - sz[start])
            if width <= measure:
                chosen = (b, width, ratio)
                if forced:
                    break
                continue
            # 超宽了：贪心到此为止，退回上一个塞得下的断点
            break
        if chosen is None:
            b = next((k for k in range(start + 1, n) if legal(k)), n - 1)
            width = sw[b] - sw[start]
            chosen = (b, width,
                      line_ratio(measure, width, sy[b] - sy[start], sz[b] - sz[start]))
        b, width, ratio = chosen
        badness = min(100.0 * abs(ratio) ** 3, INF_BAD)
        lines.append(Line(None, start, b, width, ratio, badness, 0.0,
                          _fitness(ratio), _line_text(items, start, b, items[b])))
        start = b + 1
    return lines


def line_ratio(measure: float, width: float, stretch: float, shrink: float) -> float:
    """一行的胶伸缩比例。

    ``stretch`` 为 0 时不能返回 0：那等于说"这一行正好填满"，而实际上它只是
    没有弹性可伸，只能算极端松。这个区别在窄行宽下会直接改变断点选择。
    """
    if width < measure:
        if stretch > 0.0:
            return (measure - width) / stretch
        return 0.0 if abs(width - measure) < 1e-6 else INF_BAD
    return (measure - width) / shrink if shrink > 0.0 else -INF_BAD



# ------------------------------------------------------------------- 定位


def position_line(items: Sequence[object], line: Line,
                  options: LayoutOptions) -> List[Tuple[object, int, float, float]]:
    """把一行展开成 (font, gid, x, dy) —— dy 相对基线。"""
    out: List[Tuple[object, int, float, float]] = []
    x = 0.0
    if options.align == "center":
        x = (options.measure - line.natural) / 2.0
    elif options.align == "right":
        x = options.measure - line.natural

    for i in range(line.start, line.end):
        it = items[i]
        if it.kind == BOX:
            for gid, adv in it.glyphs:
                out.append((it.font, gid, x, 0.0))
                x += adv
        elif it.kind == GLUE:
            if options.align != "justify" or line is None:
                x += it.width
                continue
            if line.ratio > 0:
                x += it.width + line.ratio * it.stretch
            else:
                x += it.width + line.ratio * it.shrink
    if line.end < len(items):
        tail = items[line.end]
        if getattr(tail, "kind", -1) == PENALTY and getattr(tail, "width", 0.0):
            # 连字符：用字体里的 '-' 画
            font = _tail_font(items, line)
            if font is not None:
                gid = font.glyph_id(ord("-"))
                out.append((font, gid, x, 0.0))
    return out


def _tail_font(items: Sequence[object], line: Line):
    for i in range(line.end - 1, line.start - 1, -1):
        if items[i].kind == BOX:
            return items[i].font
    return None


def layout_items(items: Sequence[object], options: LayoutOptions) -> Paragraph:
    """对已经拼好的项流断行。

    有些段落不是一次 itemize 出来的（比如行内代码要换字体），但它们仍要
    走同一个"断不开就放宽容差"的兜底，所以断行逻辑单独拆出来。
    """
    lines = break_lines(items, options.measure, options)
    tolerance = options.tolerance
    tries = 0
    while tries < 3 and len(lines) <= 1 and len(items) > 8:
        tolerance *= 3.0
        tweaked = replace(options, tolerance=tolerance)
        lines = break_lines(items, options.measure, tweaked)
        tries += 1
    total = sum(line.demerits for line in lines)
    return Paragraph(lines=lines, items=list(items), options=options,
                     demerits=total, text="")


def layout_paragraph(text: str, fonts: Sequence, options: LayoutOptions,
                     font_for=None) -> Paragraph:
    """排版一段文字；若一次断不开（行宽过窄 / 长单词），自动放宽容差重试。"""
    para = layout_items(itemize(text, fonts, options, font_for), options)
    para.text = text
    return para


def total_demerits(lines: Sequence[Line], options: LayoutOptions) -> float:
    """按 TeX 的公式把一组行重新算一遍总分，用于横向对比不同断行算法。"""
    total = 0.0
    prev_fitness = None
    for line in lines:
        badness = min(100.0 * abs(line.ratio) ** 3, INF_BAD)
        d = (options.line_penalty + badness) ** 2
        if prev_fitness is not None and abs(line.fitness - prev_fitness) > 1:
            d += options.fitness_demerit
        total += d
        prev_fitness = line.fitness
    return total
