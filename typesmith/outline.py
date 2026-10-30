"""TrueType 二次贝塞尔轮廓 → 设备坐标折线。

TrueType 的轮廓是**二次**贝塞尔：控制点夹在两个曲线上点之间。连续两个控制点
之间隐含一个曲线上点（两者中点），这是规范里最容易被忽略的一条，漏掉就会
把圆形画成多边形的尖角。
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

__all__ = ["contour_segments", "flatten", "flatten_glyph"]

Point = Tuple[float, float]


def contour_segments(pts: Sequence[Tuple[float, float, bool]]):
    """把一条轮廓拆成 ('L', p) / ('Q', c, p) 段，起点由第一个元素给出。"""
    n = len(pts)
    if n == 0:
        return [], (0.0, 0.0)
    if n == 1:
        return [], (pts[0][0], pts[0][1])

    # 找一个曲线上点当起点；全是控制点时（比如整圆）取首尾中点
    start_idx = next((i for i, p in enumerate(pts) if p[2]), None)
    if start_idx is None:
        x0 = (pts[-1][0] + pts[0][0]) / 2.0
        y0 = (pts[-1][1] + pts[0][1]) / 2.0
        ordered = [(x0, y0, True)] + list(pts) + [(x0, y0, True)]
    else:
        ordered = list(pts[start_idx:]) + list(pts[:start_idx]) + [pts[start_idx]]

    start = (ordered[0][0], ordered[0][1])
    segs = []
    pending_ctrl = None
    for p in ordered[1:]:
        x, y, on = p
        if on:
            if pending_ctrl is None:
                segs.append(("L", (x, y)))
            else:
                segs.append(("Q", pending_ctrl, (x, y)))
                pending_ctrl = None
        else:
            if pending_ctrl is not None:
                mid = ((pending_ctrl[0] + x) / 2.0, (pending_ctrl[1] + y) / 2.0)
                segs.append(("Q", pending_ctrl, mid))
            pending_ctrl = (x, y)
    if pending_ctrl is not None:
        segs.append(("Q", pending_ctrl, start))
    return segs, start


def _flatten_quad(p0: Point, c: Point, p1: Point, tol: float,
                  out: List[Point], depth: int = 0) -> None:
    # 控制点到弦的距离：小于容差就认为够直
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    chord = math.hypot(dx, dy)
    if depth >= 12 or chord < 1e-9:
        out.append(p1)
        return
    cross = abs((c[0] - p0[0]) * dy - (c[1] - p0[1]) * dx) / chord
    if cross <= tol:
        out.append(p1)
        return
    # de Casteljau 一分为二
    ax = (p0[0] + c[0]) / 2.0
    ay = (p0[1] + c[1]) / 2.0
    bx = (c[0] + p1[0]) / 2.0
    by = (c[1] + p1[1]) / 2.0
    mx = (ax + bx) / 2.0
    my = (ay + by) / 2.0
    _flatten_quad(p0, (ax, ay), (mx, my), tol, out, depth + 1)
    _flatten_quad((mx, my), (bx, by), p1, tol, out, depth + 1)


def flatten(contours: Sequence[Sequence[Tuple[float, float, bool]]],
            sx: float = 1.0, sy: float = 1.0, dx: float = 0.0, dy: float = 0.0,
            tolerance: float = 0.12) -> List[List[Point]]:
    """把整个字形的轮廓转成设备坐标折线环。

    ``sx``/``sy`` 负责缩放（``sy`` 取负数就能翻转 y 轴，因为字体坐标向上、
    屏幕坐标向下）；``dx``/``dy`` 是平移。容差按**设备像素**算。
    """
    polys: List[List[Point]] = []
    for contour in contours:
        segs, start = contour_segments(contour)
        if not segs:
            continue
        pts: List[Point] = [(start[0] * sx + dx, start[1] * sy + dy)]
        cur = pts[0]
        for seg in segs:
            if seg[0] == "L":
                x, y = seg[1]
                nxt = (x * sx + dx, y * sy + dy)
                pts.append(nxt)
                cur = nxt
            else:
                cx, cy = seg[1]
                x, y = seg[2]
                end = (x * sx + dx, y * sy + dy)
                ctrl = (cx * sx + dx, cy * sy + dy)
                _flatten_quad(cur, ctrl, end, tolerance, pts)
                cur = end
        if len(pts) >= 3:
            polys.append(pts)
    return polys


def flatten_glyph(font, gid: int, size_px: float, x: float = 0.0, y: float = 0.0,
                  tolerance: float = 0.12) -> List[List[Point]]:
    """按字号把字形展平成折线，``x``/``y`` 是**基线原点**。"""
    g = font.glyph(gid)
    if not g.contours:
        return []
    s = size_px / float(font.units_per_em)
    return flatten(g.contours, s, -s, x, y, tolerance)
