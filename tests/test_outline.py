"""轮廓展平：二次贝塞尔的隐含中点、整圆起点、y 轴翻转。"""

import math
import unittest

from typesmith.outline import contour_segments, flatten, flatten_glyph

SQUARE = [(0.0, 0.0, True), (10.0, 0.0, True), (10.0, 10.0, True), (0.0, 10.0, True)]


class TestSegments(unittest.TestCase):
    def test_square_is_all_lines(self):
        segs, start = contour_segments(SQUARE)
        # 三段边走完 + 一段回到起点的收口线
        self.assertEqual(len(segs), 4)
        self.assertTrue(all(s[0] == "L" for s in segs))
        self.assertEqual(segs[-1][1], start)
        self.assertEqual(start, (0.0, 0.0))

    def test_single_quadratic(self):
        pts = [(0.0, 0.0, True), (5.0, 10.0, False), (10.0, 0.0, True)]
        segs, start = contour_segments(pts)
        self.assertEqual(len(segs), 2)                 # 曲线 + 回到底边的收口线
        kind, ctrl, end = segs[0]
        self.assertEqual(kind, "Q")
        self.assertEqual(ctrl, (5.0, 10.0))
        self.assertEqual(end, (10.0, 0.0))
        self.assertEqual(start, (0.0, 0.0))

    def test_two_control_points_get_implicit_midpoint(self):
        """连续两个控制点之间必须补一个曲线上点，否则圆会变成多边形。"""
        pts = [(0.0, 0.0, True), (0.0, 10.0, False), (10.0, 10.0, False),
               (10.0, 0.0, True)]
        segs, _ = contour_segments(pts)
        self.assertEqual(len(segs), 3)
        self.assertEqual(segs[0][0], "Q")
        self.assertEqual(segs[0][2], (5.0, 10.0))   # (0,10) 与 (10,10) 的中点
        self.assertEqual(segs[1][0], "Q")

    def test_all_control_points_start_at_midpoint(self):
        """整圆没有曲线上点，起点取首尾控制点的中点。"""
        pts = [(0.0, 10.0, False), (10.0, 10.0, False),
               (10.0, 0.0, False), (0.0, 0.0, False)]
        segs, start = contour_segments(pts)
        self.assertAlmostEqual(start[0], 0.0)
        self.assertAlmostEqual(start[1], 5.0)          # 首尾控制点 (0,0)/(0,10) 的中点
        self.assertEqual(len(segs), 4)                 # 四段二次曲线，正好闭合
        self.assertEqual(segs[-1][2], start)

    def test_degenerate(self):
        self.assertEqual(contour_segments([]), ([], (0.0, 0.0)))
        self.assertEqual(contour_segments([(1.0, 2.0, True)]), ([], (1.0, 2.0)))


class TestFlatten(unittest.TestCase):
    def test_square_keeps_corners(self):
        polys = flatten([SQUARE], 1.0, 1.0, 0.0, 0.0)
        self.assertEqual(len(polys), 1)
        pts = polys[0]
        for corner in ((0, 0), (10, 0), (10, 10), (0, 10)):
            self.assertIn(corner, [tuple(p) for p in pts])

    def test_quadratic_curve_stays_below_control(self):
        pts = [(0.0, 0.0, True), (50.0, 100.0, False), (100.0, 0.0, True)]
        poly = flatten([pts], 1.0, 1.0, 0.0, 0.0)[0]
        self.assertGreater(len(poly), 3)
        self.assertEqual(poly[0], (0.0, 0.0))
        self.assertIn((100.0, 0.0), [tuple(p) for p in poly])
        self.assertEqual(poly[-1], (0.0, 0.0))          # 收口线回到起点
        mid = max(poly, key=lambda p: p[1])
        self.assertAlmostEqual(mid[0], 50.0, delta=2.0)
        self.assertAlmostEqual(mid[1], 50.0, delta=1.0)   # 二次贝塞尔顶点是中点的一半

    def test_tolerance_controls_density(self):
        pts = [(0.0, 0.0, True), (50.0, 100.0, False), (100.0, 0.0, True)]
        coarse = flatten([pts], 1.0, 1.0, 0.0, 0.0, tolerance=4.0)[0]
        fine = flatten([pts], 1.0, 1.0, 0.0, 0.0, tolerance=0.05)[0]
        self.assertLess(len(coarse), len(fine))

    def test_scale_and_translate(self):
        poly = flatten([SQUARE], 2.0, 2.0, 100.0, 50.0)[0]
        self.assertIn((100.0, 50.0), [tuple(p) for p in poly])
        self.assertIn((120.0, 70.0), [tuple(p) for p in poly])

    def test_negative_scale_flips(self):
        poly = flatten([SQUARE], 1.0, -1.0, 0.0, 100.0)[0]
        ys = [p[1] for p in poly]
        self.assertAlmostEqual(min(ys), 90.0)
        self.assertAlmostEqual(max(ys), 100.0)

    def test_degenerate_contour_ignored(self):
        self.assertEqual(flatten([[]], 1.0, 1.0, 0.0, 0.0), [])
        self.assertEqual(flatten([[SQUARE[0]]], 1.0, 1.0, 0.0, 0.0), [])


class FakeFont:
    """只提供 flatten_glyph 需要的三个属性。"""

    units_per_em = 1000

    def glyph(self, gid):
        class G:
            contours = [SQUARE]
            xmin, ymin, xmax, ymax = 0.0, 0.0, 10.0, 10.0
        return G()


class TestFlattenGlyph(unittest.TestCase):
    def test_y_flips_down(self):
        """字体坐标 y 向上，屏幕 y 向下；基线以上的点必须落到更小的 y。"""
        poly = flatten_glyph(FakeFont(), 0, 100.0, 0.0, 100.0)[0]
        ys = [p[1] for p in poly]
        self.assertLessEqual(max(ys), 100.0 + 1e-9)
        self.assertGreaterEqual(min(ys), 100.0 - 100.0 * 10 / 1000 - 1e-9)

    def test_scale_follows_size(self):
        small = flatten_glyph(FakeFont(), 0, 10.0, 0.0, 0.0)[0]
        big = flatten_glyph(FakeFont(), 0, 100.0, 0.0, 0.0)[0]
        w_small = max(p[0] for p in small) - min(p[0] for p in small)
        w_big = max(p[0] for p in big) - min(p[0] for p in big)
        self.assertAlmostEqual(w_big / w_small, 10.0, places=3)


if __name__ == "__main__":
    unittest.main()
