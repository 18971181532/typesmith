"""灰度覆盖栅格化：y 方向 4 倍超采样 + x 方向精确覆盖率。

不追求 stb_truetype 那种逐格累加的极限速度，换来的是**能读懂**：
每个子扫描线求一次交点，非零环绕规则决定填充区间，水平方向算出精确的
像素覆盖率而不是再采样一次。字形掩膜按 (字形, 字号, 1/4 像素相位) 缓存，
所以一页正文只真正栅格化几十次。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = ["rasterize", "Bitmap", "GlyphMasker"]

Point = Tuple[float, float]


def rasterize(polygons: Sequence[Sequence[Point]], width: int, height: int,
              samples: int = 4) -> bytearray:
    """把若干闭合折线环栅格化成覆盖率掩膜（0..255，逐行存储）。"""
    if width <= 0 or height <= 0 or not polygons:
        return bytearray(width * height)

    edges: List[Tuple[float, float, float, float, int]] = []
    for poly in polygons:
        n = len(poly)
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if y0 == y1:
                continue
            if y0 < y1:
                edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0), 1))
            else:
                edges.append((y1, y0, x1, (x0 - x1) / (y0 - y1), -1))
    if not edges:
        return bytearray(width * height)
    edges.sort()

    out = bytearray(width * height)
    step = 1.0 / samples
    n_edges = len(edges)
    # 活跃边：保留边的原始起点 (x0, y0)，每次都用绝对值求交点。
    # 若只存"本行的 x"再逐行累加，边会随着行号漂移，画出来是一条条横纹。
    live: List[Tuple[float, float, float, float, int]] = []   # (y1, x0, y0, slope, wind)
    cursor = 0
    for row in range(height):
        while cursor < n_edges and edges[cursor][0] < row + 1:
            y0, y1, x, slope, wind = edges[cursor]
            if y1 > row:
                live.append((y1, x, y0, slope, wind))
            cursor += 1
        if live:
            live = [e for e in live if e[0] > row]

        cov = [0.0] * (width + 1)
        touched = False
        for k in range(samples):
            ys = row + (k + 0.5) * step
            hits = []
            for y1, x0, y0, slope, wind in live:
                if y0 <= ys < y1:
                    hits.append((x0 + (ys - y0) * slope, wind))
            if len(hits) < 2:
                continue
            hits.sort()
            winding = 0
            span_start = 0.0
            for x, wind in hits:
                prev = winding
                winding += wind
                if prev == 0 and winding != 0:
                    span_start = x
                elif prev != 0 and winding == 0:
                    _add_span(cov, span_start, x, width)
                    touched = True
        if touched:
            for col in range(width):
                v = cov[col]
                if v > 0.0:
                    a = int(v * 255.0 / samples + 0.5)
                    out[row * width + col] = 255 if a > 255 else a
    return out


def _add_span(cov: List[float], xa: float, xb: float, width: int) -> None:
    """把一个水平区间按像素切分，累加精确覆盖率。"""
    if xb <= xa:
        return
    if xa < 0.0:
        xa = 0.0
    if xb > width:
        xb = float(width)
    if xb <= xa:
        return
    ia = int(xa)
    ib = int(xb)
    if ia == ib:
        cov[ia] += xb - xa
        return
    cov[ia] += ia + 1 - xa
    for c in range(ia + 1, ib):
        cov[c] += 1.0
    if ib < width:
        cov[ib] += xb - ib


class Bitmap:
    """RGB 画布，只提供排版需要的几种绘制操作。"""

    __slots__ = ("width", "height", "pixels")

    def __init__(self, width: int, height: int, color: Tuple[int, int, int] = (255, 255, 255)):
        self.width = width
        self.height = height
        self.pixels = bytearray(bytes(color) * (width * height))

    def clear(self, color: Tuple[int, int, int] = (255, 255, 255)) -> None:
        self.pixels[:] = bytes(color) * (self.width * self.height)

    def blend_mask(self, mask: bytearray, mw: int, mh: int, x: int, y: int,
                   color: Tuple[int, int, int] = (0, 0, 0), alpha: float = 1.0) -> None:
        """把灰度掩膜按颜色叠加到画布上（覆盖=不透明）。"""
        if alpha <= 0.0:
            return
        px = self.pixels
        W, H = self.width, self.height
        r, g, b = color
        gain = alpha / 255.0
        for row in range(mh):
            ty = y + row
            if ty < 0 or ty >= H:
                continue
            src = row * mw
            dst = (ty * W + x) * 3
            for col in range(mw):
                a = mask[src + col]
                if not a:
                    continue
                tx = x + col
                if tx < 0 or tx >= W:
                    continue
                f = a * gain
                inv = 1.0 - f
                i = dst + col * 3
                px[i] = int(r * f + px[i] * inv)
                px[i + 1] = int(g * f + px[i + 1] * inv)
                px[i + 2] = int(b * f + px[i + 2] * inv)

    def fill_rect(self, x: int, y: int, w: int, h: int,
                  color: Tuple[int, int, int] = (0, 0, 0), alpha: float = 1.0) -> None:
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + w)
        y1 = min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        r, g, b = color
        row_bytes = bytes((r, g, b)) * (x1 - x0)
        for ty in range(y0, y1):
            i = (ty * self.width + x0) * 3
            if alpha >= 1.0:
                self.pixels[i:i + len(row_bytes)] = row_bytes
            else:
                for col in range(x0, x1):
                    j = (ty * self.width + col) * 3
                    self.pixels[j] = int(r * alpha + self.pixels[j] * (1 - alpha))
                    self.pixels[j + 1] = int(g * alpha + self.pixels[j + 1] * (1 - alpha))
                    self.pixels[j + 2] = int(b * alpha + self.pixels[j + 2] * (1 - alpha))

    def blend_row(self, y: int, x0: int, x1: int,
                  color: Tuple[int, int, int], alpha: float = 1.0) -> None:
        self.fill_rect(x0, y, x1 - x0, 1, color, alpha)


class GlyphMasker:
    """按字号缓存字形掩膜，带 1/4 像素的水平相位。"""

    def __init__(self, font, size_px: float, phases: int = 4, samples: int = 4):
        self.font = font
        self.size = float(size_px)
        self.phases = max(1, phases)
        self.samples = samples
        self.scale = self.size / float(font.units_per_em)
        self._polys: Dict[int, List[List[Point]]] = {}
        self._masks: Dict[Tuple[int, int], Tuple[bytearray, int, int, int, int]] = {}
        self.rasterised = 0

    # -------------------------------------------------------------- 内部
    def _outline(self, gid: int) -> List[List[Point]]:
        got = self._polys.get(gid)
        if got is None:
            from .outline import flatten
            glyph = self.font.glyph(gid)
            got = flatten(glyph.contours, self.scale, -self.scale, 0.0, 0.0,
                          tolerance=0.10)
            self._polys[gid] = got
        return got

    def mask(self, gid: int, phase: int = 0) -> Tuple[bytearray, int, int, int, int]:
        """返回 (掩膜, 宽, 高, 相对笔位 x, 相对基线 y)。"""
        key = (gid, phase % self.phases)
        cached = self._masks.get(key)
        if cached is not None:
            return cached

        polys = self._outline(gid)
        if not polys:
            empty = (bytearray(0), 0, 0, 0, 0)
            self._masks[key] = empty
            return empty

        shift = -(phase % self.phases) / float(self.phases)
        xs = [p[0] for poly in polys for p in poly]
        ys = [p[1] for poly in polys for p in poly]
        x0 = math.floor(min(xs) + shift) - 1
        x1 = math.ceil(max(xs) + shift) + 1
        y0 = math.floor(min(ys)) - 1
        y1 = math.ceil(max(ys)) + 1
        w = max(1, x1 - x0)
        h = max(1, y1 - y0)

        moved = [[(px + shift - x0, py - y0) for px, py in poly] for poly in polys]
        mask = rasterize(moved, w, h, self.samples)
        self.rasterised += 1
        out = (mask, w, h, x0, y0)
        self._masks[key] = out
        return out

    def draw(self, canvas: Bitmap, gid: int, x: float, baseline: float,
             color: Tuple[int, int, int] = (0, 0, 0), alpha: float = 1.0) -> None:
        phase = int(round((x - math.floor(x)) * self.phases)) % self.phases
        mask, w, h, mx, my = self.mask(gid, phase)
        if w:
            canvas.blend_mask(mask, w, h, math.floor(x) + mx, int(round(baseline)) + my,
                              color, alpha)
