"""SVG 输出：同一份轮廓，走矢量而不是像素。

像素渲染证明栅格化器对了；矢量输出证明**轮廓解析**对了——两边共用
``contour_segments``，所以 SVG 里是真二次贝塞尔，不是把折线原样搬过去。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from .document import Document
from .layout import BOX, GLUE
from .outline import contour_segments

__all__ = ["glyph_path", "page_svg", "document_svg"]


def _n(v: float) -> str:
    s = f"{v:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def glyph_path(font, gid: int, size: float, x: float, baseline: float) -> str:
    """把一个字形变成 SVG path 的 ``d`` 属性。"""
    glyph = font.glyph(gid)
    if not glyph.contours:
        return ""
    s = size / float(font.units_per_em)
    parts: List[str] = []
    for contour in glyph.contours:
        segs, start = contour_segments(contour)
        if not segs:
            continue
        sx = start[0] * s + x
        sy = baseline - start[1] * s
        parts.append(f"M{_n(sx)} {_n(sy)}")
        for seg in segs:
            if seg[0] == "L":
                px, py = seg[1]
                parts.append(f"L{_n(px * s + x)} {_n(baseline - py * s)}")
            else:
                cx, cy = seg[1]
                px, py = seg[2]
                parts.append(f"Q{_n(cx * s + x)} {_n(baseline - cy * s)} "
                             f"{_n(px * s + x)} {_n(baseline - py * s)}")
        parts.append("Z")
    return "".join(parts)


def page_svg(doc: Document, index: int = 0, background: str = "#ffffff") -> str:
    spec = doc.spec
    page = doc.pages[index]
    out: List[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{spec.width}" '
               f'height="{spec.height}" viewBox="0 0 {spec.width} {spec.height}">')
    out.append(f'<rect width="{spec.width}" height="{spec.height}" fill="{background}"/>')

    for x0, y0, x1, y1, color in page.rules:
        hexc = "#%02x%02x%02x" % color
        out.append(f'<rect x="{_n(x0)}" y="{_n(y0)}" width="{_n(x1 - x0)}" '
                   f'height="{_n(max(y1, 1.0))}" fill="{hexc}"/>')

    for pl in page.lines:
        style = pl.style
        font = style.font
        color = "#%02x%02x%02x" % style.color
        opts = style.options(spec.content_width - style.indent)
        line = pl.line
        x = pl.x
        if opts.align == "center":
            x += (opts.measure - line.natural) * 0.5
        elif opts.align == "right":
            x += opts.measure - line.natural

        ds: List[str] = []
        for i in range(line.start, line.end):
            it = pl.items[i]
            if it.kind == GLUE:
                if opts.align == "justify" and line.ratio:
                    if line.ratio > 0:
                        x += it.width + line.ratio * it.stretch
                    else:
                        x += it.width + line.ratio * it.shrink
                else:
                    x += it.width
                continue
            if it.kind != BOX:
                continue
            prev = -1
            for gid, adv in it.glyphs:
                if prev >= 0:
                    x += font.kerning(prev, gid) * style.size / font.units_per_em
                d = glyph_path(font, gid, style.size, x, pl.baseline)
                if d:
                    ds.append(d)
                x += adv + style.tracking
                prev = gid
        if ds:
            out.append(f'<path fill="{color}" d="{" ".join(ds)}"/>')

    out.append("</svg>")
    return "\n".join(out)


def document_svg(doc: Document, background: str = "#ffffff") -> str:
    parts = []
    for i in range(len(doc.pages)):
        parts.append(page_svg(doc, i, background))
    return "\n".join(parts)
