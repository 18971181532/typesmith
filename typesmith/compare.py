"""两种断行的并排对照图。

左边贪心、右边 Knuth–Plass，同一段文字、同一个行宽。图下面给出四项指标：
总 demerits、最松的一行、超松行数、右边缘的锯齿程度。数字和图形放在一起，
比只说"我们的算法更好"有说服力。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .font import Font
from .layout import (BOX, GLUE, INF_BAD, LayoutOptions, Line, break_lines,
                     greedy_break, itemize, total_demerits)
from .png import write_png
from .raster import Bitmap, GlyphMasker
from .render import draw_mixed, text_width_mixed

__all__ = ["compare_figure", "breaker_stats"]

INK = (24, 24, 24)
GREY = (128, 128, 128)
LIGHT = (215, 215, 215)
GOOD = (30, 110, 70)
BAD = (176, 60, 40)


def breaker_stats(lines: List[Line], measure: float) -> Dict[str, float]:
    if not lines:
        return {"lines": 0, "demerits": 0.0, "max_ratio": 0.0, "loose": 0, "ragged": 0.0}
    ratios = [abs(line.ratio) for line in lines]
    loose = sum(1 for line in lines if line.badness > 500)
    ragged = sum(abs(line.natural - measure) for line in lines[:-1])
    return {
        "lines": len(lines),
        "demerits": round(total_demerits(lines, LayoutOptions(measure=measure)), 1),
        "max_ratio": round(max(ratios), 2),
        "loose": loose,
        "ragged": round(ragged, 1),
    }


def _draw_lines(canvas: Bitmap, maskers, items, lines: List[Line], x0: float,
                y0: float, measure: float, size: float, leading: float,
                font: Font, color=INK) -> float:
    y = y0
    for line in lines:
        x = x0
        for i in range(line.start, line.end):
            it = items[i]
            if it.kind == GLUE:
                if line.ratio > 0:
                    x += it.width + line.ratio * it.stretch
                else:
                    x += it.width + line.ratio * it.shrink
                continue
            if it.kind != BOX:
                continue
            prev = -1
            for gid, adv in it.glyphs:
                if prev >= 0:
                    x += font.kerning(prev, gid) * size / font.units_per_em
                key = (id(font), round(size, 2))
                masker = maskers.get(key)
                if masker is None:
                    masker = GlyphMasker(font, size)
                    maskers[key] = masker
                masker.draw(canvas, gid, x, y, color)
                x += adv
                prev = gid
        y += size * leading
    return y


def compare_figure(text: str, font: Font, size: float = 15.0, measure: float = 380.0,
                   leading: float = 1.62, cjk: Font = None
                   ) -> Tuple[Bitmap, Dict[str, object]]:
    """画一张"同一段文字、同一行宽、两种断行"的对照图。

    画布宽度由 measure 反推，不另外传：两栏一样宽才对得上。
    """
    opts = LayoutOptions(size=size, leading=leading, measure=measure, align="justify")
    items = itemize(text, [font], opts)
    greedy = greedy_break(items, measure, opts)
    knuth = break_lines(items, measure, opts)

    st_g = breaker_stats(greedy, measure)
    st_k = breaker_stats(knuth, measure)

    # 版面按 measure 反推：两栏等宽、中间留一条细缝给"最松行"的数字，
    # 这样 measure 一变图也跟着变，不会出现文字顶到右边框的情况。
    left_x = 68.0
    gutter = 34.0
    right_x = left_x + measure + gutter
    width = int(round(right_x + measure + left_x))
    label_y = 116.0
    top = label_y + 24.0
    rows = max(len(greedy), len(knuth))
    height = int(top + rows * size * leading + 176)

    canvas = Bitmap(width, height, (255, 255, 255))
    maskers: Dict[Tuple[int, float], GlyphMasker] = {}

    chain = [font, cjk] if cjk is not None else [font]

    def text_at(s: str, px: float, x: float, y: float, color=INK, track: float = 0.0):
        return draw_mixed(canvas, maskers, chain, px, s, x, y, color, tracking=track)

    def width_at(s: str, px: float) -> float:
        return text_width_mixed(chain, s, px)

    # 标题
    text_at("Greedy  vs  Knuth–Plass", 20, left_x, 52, INK)
    text_at(f"同一段文字 · 行宽 {measure:.0f} px · {size:.0f}/{size * leading:.0f} px",
            10.5, left_x, 74, GREY)
    canvas.fill_rect(int(left_x), 90, int(width - left_x * 2), 1, LIGHT)
    text_at("贪心：塞不下就断", 11, left_x, label_y, BAD)
    text_at("Knuth–Plass：整段一起算", 11, right_x, label_y, GOOD)

    # 标出贪心最糟的那一行：底纹给行，数字放中间那条缝里
    if greedy:
        worst = max(range(len(greedy)), key=lambda k: greedy[k].ratio)
        wy = top + worst * size * leading - size * 0.86
        canvas.fill_rect(int(left_x - 8), int(wy), int(measure + 16),
                         int(size * 1.05), (255, 226, 220))
        # 数字放在左边距里，用一小段引线连到色块——挤在两栏中间会被读成正文
        label = f"{greedy[worst].ratio:.2f}"
        lw = width_at(label, 9)
        canvas.fill_rect(int(left_x - 15), int(wy + size * 0.5), 6, 1, BAD)
        text_at(label, 9, left_x - 17 - lw, wy + size * 0.78, BAD)

    # 内容
    _draw_lines(canvas, maskers, items, greedy, left_x, top, measure, size, leading, font)
    _draw_lines(canvas, maskers, items, knuth, right_x, top, measure, size, leading, font)

    # 指标表：列宽按内容实测，数字右对齐
    y = top + rows * size * leading + 48
    canvas.fill_rect(int(left_x), int(y - 32), int(width - left_x * 2), 1, LIGHT)
    headers = ["算法", "行数", "总 demerits", "最松 ratio", "超松行", "右侧锯齿"]
    entries = [("greedy", st_g, BAD), ("knuth-plass", st_k, GOOD)]
    cells = [[name, f"{int(st['lines'])}", f"{st['demerits']:,.0f}",
              f"{st['max_ratio']:.2f}", f"{int(st['loose'])}",
              f"{st['ragged']:.0f} px"] for name, st, _ in entries]
    col_w = []
    for c, head in enumerate(headers):
        cw = width_at(head, 9.5)
        for r in cells:
            cw = max(cw, width_at(r[c], 11))
        col_w.append(cw)
    gap = (width - left_x * 2 - sum(col_w)) / (len(headers) - 1)
    gap = max(26.0, min(88.0, gap))
    xs = [left_x]
    for cw in col_w[:-1]:
        xs.append(xs[-1] + cw + gap)

    for c, head in enumerate(headers):
        hx = xs[c] if c == 0 else xs[c] + col_w[c] - width_at(head, 9.5)
        text_at(head, 9.5, hx, y - 8, GREY)

    def row(yy: float, name: str, st: Dict[str, float], color) -> None:
        vals = [name, f"{int(st['lines'])}", f"{st['demerits']:,.0f}",
                f"{st['max_ratio']:.2f}", f"{int(st['loose'])}",
                f"{st['ragged']:.0f} px"]
        for c, val in enumerate(vals):
            px = 11.0 if c == 0 else 11.0
            cx = xs[c] if c == 0 else xs[c] + col_w[c] - width_at(val, px)
            ink = color if c == 0 else INK
            if c == 3 and st["max_ratio"] > 2:
                ink = BAD
            if c == 4 and st["loose"]:
                ink = BAD
            text_at(val, px, cx, yy, ink)

    row(y + 16, "greedy", st_g, BAD)
    row(y + 42, "knuth-plass", st_k, GOOD)

    better = st_k["demerits"] < st_g["demerits"]
    if better and st_g["demerits"]:
        drop = (1 - st_k["demerits"] / st_g["demerits"]) * 100
        verdict = f"demerits 降低 {drop:.1f}%"
    else:
        verdict = "两者持平"
    text_at(f"结论：{verdict}；超松行 {int(st_g['loose'])} → {int(st_k['loose'])}",
            10.5, left_x, y + 78, GOOD if better else GREY)
    return canvas, {"greedy": st_g, "knuth": st_k, "verdict": verdict}


def save_compare(canvas: Bitmap, path: str) -> None:
    write_png(path, canvas.width, canvas.height, bytes(canvas.pixels))
