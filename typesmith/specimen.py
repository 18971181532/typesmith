"""字体样张：把引擎的能力压在一页上看。

样张不是"好看的截图"，它得能当证据用：

  · 大字号里能数清曲线是不是真的平滑（二次贝塞尔的功劳）
  · 字距演示并排列出 kerning 开 / 关，差值直接标出来
  · 正文段落是 Knuth–Plass 排的，看两端对齐的空隙是否均匀
  · 中文段落证明混排与避头尾
  · 末尾的字形网格把整页填满，顺便覆盖大量轮廓
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .font import Font
from .layout import BOX, GLUE, LayoutOptions, layout_paragraph
from .png import write_png
from .raster import Bitmap, GlyphMasker
from .render import draw_mixed, text_width_mixed

__all__ = ["specimen", "save_specimen", "KERN_PAIRS"]

KERN_PAIRS: List[str] = ["AV", "To", "Wa", "Ya", "LT", "ry"]

# 字形网格按"字符集"分行，而不是把一段字符循环铺满——循环铺满看着像占位图，
# 分行才看得出这款字体到底收了哪些字符。
GRID_ROWS: List[Tuple[str, int, str]] = [
    ("sans", 17, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    ("sans", 17, "abcdefghijklmnopqrstuvwxyz"),
    ("sans", 16, "0123456789"),
    ("sans", 14, "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"),
    ("serif", 15, "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØŒŠÙÚÛÜÝŸŽ"),
    ("serif", 15, "àáâãäåæçèéêëìíîïðñòóôõöøœšùúûüýÿž"),
    ("serif", 15, "–—‘’“”«»‹›…†‡•¶§©®™"),
]
CJK_ROWS: List[str] = [
    "永和九年岁在癸丑暮春之初会于会稽山阴之兰亭",
    "修禊事也群贤毕至少长咸集此地有崇山峻岭",
]

INK = (17, 17, 17)
GREY = (128, 128, 128)
LIGHT = (208, 208, 208)
ACCENT = (192, 68, 38)
GRID = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789&@#$%?!()[]{}/\\<>*+=~^"


def _cap_height(font: Font) -> float:
    g = font.glyph(font.glyph_id(ord("H")))
    return g.ymax if g.contours else 0.7 * font.units_per_em


def _x_height(font: Font) -> float:
    g = font.glyph(font.glyph_id(ord("x")))
    return g.ymax if g.contours else 0.5 * font.units_per_em


def specimen(sans: Font, sans_bold: Optional[Font], serif: Font,
             mono: Optional[Font], cjk: Optional[Font],
             width: int = 900, height: int = 1180) -> Tuple[Bitmap, Dict[str, object]]:
    canvas = Bitmap(width, height, (255, 255, 255))
    maskers: Dict[Tuple[int, float], GlyphMasker] = {}
    bold = sans_bold or sans
    lat = [sans, serif, mono, cjk]
    stats: Dict[str, object] = {}

    def mixed(text: str, size: float, x: float, y: float, color=INK,
              tracking: float = 0.0, fonts=None) -> float:
        return draw_mixed(canvas, maskers, fonts or lat, size, text, x, y,
                          color, tracking=tracking)

    def width_of(text: str, size: float, fonts=None) -> float:
        return text_width_mixed(fonts or lat, text, size)

    left = 72.0
    right = width - 72.0

    # ---------------------------------------------------------------- 页眉
    mixed("TYPESMITH", 11, left, 52, GREY, tracking=2.2, fonts=[bold])
    tail = "字体与排版引擎 · 样张"
    mixed(tail, 11, right - width_of(tail, 11), 52, GREY)
    canvas.fill_rect(int(left), 66, int(right - left), 1, LIGHT)

    # ---------------------------------------------------------------- 标题
    mixed("Reading is a", 38, left, 122, INK, fonts=[bold])
    mixed("typographic act.", 38, left, 170, INK, fonts=[bold])

    # ------------------------------------------------------------ 字距演示
    kx, ky = 512.0, 150.0
    mixed("KERNING · Arial", 10, kx, ky - 34, GREY, tracking=1.4)
    mixed("kerned", 9, kx, ky - 18, GREY)
    mixed("unkerned", 9, kx + 78, ky - 18, GREY)
    mixed("Δ", 9, kx + 156, ky - 18, GREY)
    rows = []
    for i, pair in enumerate(KERN_PAIRS[:4]):
        g1, g2 = (sans.glyph_id(ord(c)) for c in pair)
        kern = sans.kerning(g1, g2) * 19 / sans.units_per_em
        rows.append((pair, round(kern, 2)))
        row_y = ky + i * 31
        mixed(pair, 19, kx, row_y, INK, fonts=[sans])
        mixed(pair, 19, kx + 78, row_y, (196, 196, 196), fonts=[sans])
        label = f"{kern:+.1f}"
        mixed(label, 9.5, kx + 156, row_y - 1, ACCENT if abs(kern) > 0.01 else GREY,
              fonts=[mono] if mono else None)
    stats["kern"] = rows

    # ------------------------------------------------------- 大字 + 度量线
    big = 170.0
    base_big = 400.0
    mixed("Aa", big, left - 6, base_big, INK, fonts=[serif])
    cap = _cap_height(serif) * big / serif.units_per_em
    xh = _x_height(serif) * big / serif.units_per_em
    x0, x1 = left - 8, left + 300
    for value, label, raw in ((cap, "cap height", _cap_height(serif)),
                              (xh, "x-height", _x_height(serif))):
        canvas.fill_rect(int(x0), int(base_big - value), int(x1 - x0), 1, ACCENT)
        mixed(label, 10, x1 + 12, base_big - value + 3, ACCENT)
        em = raw / serif.units_per_em
        mixed(f"{em:.3f} em · {value:.0f} px", 9.5, x1 + 12, base_big - value + 16, GREY)
    canvas.fill_rect(int(x0), int(base_big), int(x1 - x0), 1, GREY)
    mixed("baseline", 10, x1 + 12, base_big + 4, GREY)

    y = base_big + 58
    canvas.fill_rect(int(left), int(y), int(right - left), 1, LIGHT)

    # --------------------------------------------------------------- 字号级
    y += 26
    sample = "Hamburgefonstiv 0123456789"
    for size, gap in ((30, 42), (20, 30), (13, 22)):
        mixed(sample, size, left, y, INK, fonts=[sans])
        label = f"{size} px"
        mixed(label, 9, right - width_of(label, 9), y - 2, GREY)
        y += gap

    # ---------------------------------------------------------------- 正文
    y += 8
    canvas.fill_rect(int(left), int(y), int(right - left), 1, LIGHT)
    y += 24
    mixed("JUSTIFIED · KNUTH–PLASS", 10, left, y, GREY, tracking=1.4)
    y += 16
    body = ("The space between words is not empty: it is a spring. A good typesetter "
            "lets every spring stretch and shrink by the same proportion, so that the "
            "page breathes evenly from the first line to the last. A greedy breaker "
            "cannot do this, because it decides without knowing what comes next. "
            "Knuth and Plass turned the whole paragraph into a shortest-path problem, "
            "and the difference is visible in any narrow measure.")
    opts = LayoutOptions(size=14.5, leading=1.62, measure=right - left, align="justify")
    para = layout_paragraph(body, [serif], opts)
    stats["body_lines"] = len(para.lines)
    stats["body_demerits"] = round(para.demerits, 1)
    y = _draw_paragraph(canvas, maskers, para, left, y, INK)

    # ---------------------------------------------------------------- 中文
    if cjk is not None:
        y += 14
        mixed("CJK · 避头尾", 10, left, y, GREY, tracking=1.4, fonts=[cjk])
        y += 18
        zh = ("排版不是把字形并排摆好。字距、行距、断行位置，决定了读者的眼睛能不能"
              "顺畅地滑过一行字；标点不能出现在行首，行尾也不能留下一个开着的括号。"
              "这些细节单看微不足道，累积起来就是可读与难读的差别。")
        opts_cjk = LayoutOptions(size=15, leading=1.72, measure=right - left,
                                 align="justify")
        para_cjk = layout_paragraph(zh, [cjk, serif], opts_cjk)
        stats["cjk_lines"] = len(para_cjk.lines)
        y = _draw_paragraph(canvas, maskers, para_cjk, left, y, INK)

    # ------------------------------------------------------------ 字形网格
    y += 18
    canvas.fill_rect(int(left), int(y), int(right - left), 1, LIGHT)
    y += 26
    mixed("GLYPHS", 10, left, y, GREY, tracking=1.4)
    y += 14
    cell = 27.0
    cols = int((right - left) // cell)
    plan = list(GRID_ROWS)
    if cjk is not None:
        plan += [("cjk", 20, row) for row in CJK_ROWS]
    budget = int((height - 94 - y) // cell)          # 页脚之前还能塞几行
    plan = plan[:max(0, budget)]
    stats["grid"] = f"{len(plan)}×{cols}"
    for r, (kind, size, text) in enumerate(plan):
        font_list = {"sans": [sans], "serif": [serif], "cjk": [cjk] if cjk else [serif]}[kind]
        for c, ch in enumerate(text[:cols]):
            mixed(ch, size, left + c * cell + 3, y + r * cell + 18,
                  (60, 60, 60), fonts=font_list)

    # ---------------------------------------------------------------- 页脚
    canvas.fill_rect(int(left), height - 60, int(right - left), 1, LIGHT)
    info = f"{sans.full_name} · {serif.full_name}"
    if cjk is not None:
        info += f" · {cjk.full_name}"
    mixed(info, 9.5, left, height - 38, GREY)
    tail2 = f"{width}×{height} px · typesmith"
    mixed(tail2, 9.5, right - width_of(tail2, 9.5), height - 38, GREY)
    return canvas, stats


def _draw_paragraph(canvas, maskers, para, x0: float, y: float, color) -> float:
    opts = para.options
    for line in para.lines:
        x = x0
        for i in range(line.start, line.end):
            it = para.items[i]
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
                    x += it.font.kerning(prev, gid) * opts.size / it.font.units_per_em
                key = (id(it.font), round(opts.size, 2))
                masker = maskers.get(key)
                if masker is None:
                    masker = GlyphMasker(it.font, opts.size)
                    maskers[key] = masker
                masker.draw(canvas, gid, x, y, color)
                x += adv
                prev = gid
        y += opts.size * opts.leading
    return y


def save_specimen(canvas: Bitmap, path: str) -> None:
    write_png(path, canvas.width, canvas.height, bytes(canvas.pixels))
