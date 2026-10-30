"""把排好的页画成像素。

每个 (字体, 字号) 组合一个 ``GlyphMasker``，字形掩膜在里面按相位缓存；
换行只是改坐标，不会重新栅格化。
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .document import Document, Page, PlacedLine
from .layout import BOX, GLUE
from .png import write_png
from .raster import Bitmap, GlyphMasker

__all__ = ["Renderer", "render_png", "draw_text", "text_width",
           "draw_mixed", "text_width_mixed", "pick_font"]


def text_width(font, text: str, size: float, kern: bool = True,
               tracking: float = 0.0) -> float:
    """一段文字的排版宽度（px），含字距与 tracking。"""
    total = 0.0
    prev = -1
    for ch in text:
        gid = font.glyph_id(ord(ch))
        if kern and prev >= 0:
            total += font.kerning(prev, gid) * size / font.units_per_em
        total += font.advance(gid) * size / font.units_per_em
        total += tracking
        prev = gid
    return total


def draw_text(canvas, masker, font, size: float, text: str, x: float, baseline: float,
              color=(0, 0, 0), kern: bool = True, tracking: float = 0.0,
              alpha: float = 1.0) -> float:
    """在画布上画一行字，返回结束时的 x。"""
    prev = -1
    for ch in text:
        gid = font.glyph_id(ord(ch))
        if kern and prev >= 0:
            x += font.kerning(prev, gid) * size / font.units_per_em
        masker.draw(canvas, gid, x, baseline, color, alpha)
        x += font.advance(gid) * size / font.units_per_em + tracking
        prev = gid
    return x


class Renderer:
    def __init__(self, doc: Document, background: Tuple[int, int, int] = (255, 255, 255),
                 scale: float = 1.0):
        self.doc = doc
        self.background = background
        self.scale = scale
        self._maskers: Dict[Tuple[int, float], GlyphMasker] = {}

    def masker(self, font, size: float) -> GlyphMasker:
        key = (id(font), round(size, 2))
        m = self._maskers.get(key)
        if m is None:
            m = GlyphMasker(font, size)
            self._maskers[key] = m
        return m

    def page_bitmap(self, page: Page) -> Bitmap:
        spec = self.doc.spec
        W = int(spec.width * self.scale)
        H = int(spec.height * self.scale)
        canvas = Bitmap(W, H, self.background)

        for x0, y0, x1, y1, color in page.rules:
            canvas.fill_rect(int(x0 * self.scale), int(y0 * self.scale),
                             max(1, int((x1 - x0) * self.scale)),
                             max(1, int(max(y1, 1.0) * self.scale)), color)

        for pl in page.lines:
            self._draw_line(canvas, pl)
        self._draw_furniture(canvas, page)
        return canvas

    # ------------------------------------------------------------------
    def _draw_line(self, canvas: Bitmap, pl: PlacedLine) -> None:
        style = pl.style
        base = pl.baseline * self.scale
        size = style.size * self.scale
        tracking = style.tracking * self.scale
        opts = self._options(pl)
        line = pl.line

        x = pl.x * self.scale
        if opts.align == "center":
            x += (opts.measure - line.natural) * 0.5 * self.scale
        elif opts.align == "right":
            x += (opts.measure - line.natural) * self.scale

        for i in range(line.start, line.end):
            it = pl.items[i]
            if it.kind == GLUE:
                if opts.align == "justify" and line.ratio:
                    if line.ratio > 0:
                        x += (it.width + line.ratio * it.stretch) * self.scale
                    else:
                        x += (it.width + line.ratio * it.shrink) * self.scale
                else:
                    x += it.width * self.scale
                continue
            if it.kind != BOX:
                continue
            # 一行里可能混着两款字体（拉丁 + 中文回退），每个字形必须用
            # 它自己那款字体的掩膜，否则汉字会拿拉丁字体的字形编号去取形状。
            font = it.font or style.font
            masker = self.masker(font, size)
            prev = -1
            for gid, adv in it.glyphs:
                if prev >= 0:
                    x += font.kerning(prev, gid) * size / font.units_per_em
                masker.draw(canvas, gid, x, base, style.color)
                x += adv * self.scale
                if tracking:
                    x += tracking
                prev = gid

    def _options(self, pl: PlacedLine):
        return pl.style.options(self.doc.spec.content_width - pl.style.indent)

    # ------------------------------------------------------------------
    def _draw_furniture(self, canvas: Bitmap, page: Page) -> None:
        spec = self.doc.spec
        lines = page.lines
        if not lines:
            return
        small = lines[-1].style.font
        size = (lines[0].style.size if lines else 12) * 0.76 * self.scale

        if spec.header:
            masker = self.masker(small, size)
            x = spec.margin_left * self.scale
            y = (spec.margin_top - size * 1.15) * self.scale
            for ch in spec.header:
                gid = small.glyph_id(ord(ch))
                masker.draw(canvas, gid, x, y, (128, 128, 128))
                x += small.advance(gid) * size / small.units_per_em + 0.6 * self.scale

        if spec.footer:
            label = f"{page.index + 1}"
            masker = self.masker(small, size)
            total = sum(small.advance(small.glyph_id(ord(c))) for c in label) * size / small.units_per_em
            x = (spec.width / 2.0) * self.scale - total / 2.0
            y = (spec.height - spec.margin_bottom * 0.45) * self.scale
            for ch in label:
                gid = small.glyph_id(ord(ch))
                masker.draw(canvas, gid, x, y, (140, 140, 140))
                x += small.advance(gid) * size / small.units_per_em

    # ------------------------------------------------------------------
    def render_all(self) -> List[Bitmap]:
        return [self.page_bitmap(p) for p in self.doc.pages]

    def save(self, path: str, page: int = 0) -> None:
        bmp = self.page_bitmap(self.doc.pages[page])
        write_png(path, bmp.width, bmp.height, bytes(bmp.pixels))


def render_png(doc: Document, path: str, page: int = 0, background=(255, 255, 255),
               scale: float = 1.0) -> Bitmap:
    r = Renderer(doc, background, scale)
    r.save(path, page)
    return r.page_bitmap(doc.pages[page])


def pick_font(fonts, ch: str):
    """按顺序找第一个能显示这个字符的字体。"""
    for f in fonts:
        if f is not None and f.glyph_id(ord(ch)):
            return f
    return fonts[0] if fonts else None


def text_width_mixed(fonts, text: str, size: float, kern: bool = True,
                     tracking: float = 0.0) -> float:
    total = 0.0
    prev_font = None
    prev = -1
    for ch in text:
        font = pick_font(fonts, ch)
        gid = font.glyph_id(ord(ch))
        if kern and prev_font is font and prev >= 0:
            total += font.kerning(prev, gid) * size / font.units_per_em
        total += font.advance(gid) * size / font.units_per_em + tracking
        prev_font, prev = font, gid
    return total


def draw_mixed(canvas, maskers: dict, fonts, size: float, text: str,
               x: float, baseline: float, color=(0, 0, 0), kern: bool = True,
               tracking: float = 0.0) -> float:
    """混排绘制：逐字挑字体，跨字体不做字距。``maskers`` 是 (字体, 字号) → Masker。"""
    prev_font = None
    prev = -1
    for ch in text:
        font = pick_font(fonts, ch)
        gid = font.glyph_id(ord(ch))
        key = (id(font), round(size, 2))
        masker = maskers.get(key)
        if masker is None:
            from .raster import GlyphMasker
            masker = GlyphMasker(font, size)
            maskers[key] = masker
        if kern and prev_font is font and prev >= 0:
            x += font.kerning(prev, gid) * size / font.units_per_em
        masker.draw(canvas, gid, x, baseline, color)
        x += font.advance(gid) * size / font.units_per_em + tracking
        prev_font, prev = font, gid
    return x
