"""扫描线栅格化：覆盖率、非零环绕、孔洞、边缘平滑。"""

import unittest

from typesmith.raster import Bitmap, rasterize

SQUARE = [(2.0, 2.0), (8.0, 2.0), (8.0, 8.0), (2.0, 8.0)]
HOLE = [(4.0, 4.0), (4.0, 6.0), (6.0, 6.0), (6.0, 4.0)]      # 反向，形成孔洞


def at(mask, width, x, y):
    return mask[y * width + x]


class TestRasterize(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(rasterize([], 10, 10), bytearray(100))
        self.assertEqual(rasterize([SQUARE], 0, 0), bytearray(0))

    def test_interior_is_solid(self):
        mask = rasterize([SQUARE], 10, 10)
        self.assertEqual(len(mask), 100)
        for y in range(3, 7):
            for x in range(3, 7):
                self.assertEqual(at(mask, 10, x, y), 255, f"({x},{y}) 应该是实心")

    def test_outside_is_empty(self):
        mask = rasterize([SQUARE], 10, 10)
        self.assertEqual(at(mask, 10, 0, 0), 0)
        self.assertEqual(at(mask, 10, 9, 9), 0)

    def test_edges_are_antialiased(self):
        """半像素错位的边应该落在 0 与 255 之间，而不是硬邦邦的跳变。"""
        shifted = [(x + 0.5, y + 0.5) for x, y in SQUARE]
        mask = rasterize([shifted], 10, 10)
        edge = [at(mask, 10, x, 4) for x in (1, 2)]
        self.assertEqual(edge[0], 0)
        self.assertTrue(0 < edge[1] < 255, f"边缘覆盖率 {edge[1]} 应该是中间值")

    def test_hole_with_reverse_winding(self):
        mask = rasterize([SQUARE, HOLE], 10, 10)
        self.assertEqual(at(mask, 10, 5, 5), 0, "反向环绕应该挖出孔洞")
        self.assertEqual(at(mask, 10, 3, 5), 255, "孔洞外侧仍是实心")

    def test_same_winding_does_not_punch_hole(self):
        same = [(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)]
        mask = rasterize([SQUARE, same], 10, 10)
        self.assertEqual(at(mask, 10, 5, 5), 255, "同向环绕不该挖洞")

    def test_coverage_sums_to_area(self):
        """整块面积 36 px，覆盖率总和应接近 36×255。"""
        mask = rasterize([SQUARE], 10, 10, samples=8)
        total = sum(mask) / 255.0
        self.assertAlmostEqual(total, 36.0, delta=1.5)

    def test_clipped_to_canvas(self):
        big = [(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)]
        mask = rasterize([big], 8, 8)
        self.assertEqual(len(mask), 64)
        self.assertTrue(all(v == 255 for v in mask))

    def test_triangle(self):
        tri = [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0)]
        mask = rasterize([tri], 10, 10)
        self.assertEqual(at(mask, 10, 1, 1), 255)
        self.assertEqual(at(mask, 10, 8, 8), 0)

    def test_zero_area_polygon(self):
        line = [(0.0, 0.0), (10.0, 0.0), (10.0, 0.0)]
        self.assertEqual(sum(rasterize([line], 10, 10)), 0)


class TestBitmap(unittest.TestCase):
    def setUp(self):
        self.bmp = Bitmap(6, 4, (255, 255, 255))

    def test_size(self):
        self.assertEqual(len(self.bmp.pixels), 6 * 4 * 3)
        self.assertTrue(all(v == 255 for v in self.bmp.pixels))

    def test_fill_rect(self):
        self.bmp.fill_rect(1, 1, 2, 2, (0, 0, 0))
        idx = (1 * 6 + 1) * 3
        self.assertEqual(self.bmp.pixels[idx:idx + 3], bytes((0, 0, 0)))
        idx_out = (0 * 6 + 0) * 3
        self.assertEqual(self.bmp.pixels[idx_out:idx_out + 3], bytes((255, 255, 255)))

    def test_fill_rect_clipped(self):
        self.bmp.fill_rect(-5, -5, 8, 8, (10, 20, 30))
        self.assertEqual(self.bmp.pixels[0:3], bytes((10, 20, 30)))
        idx = (3 * 6 + 3) * 3
        self.assertEqual(self.bmp.pixels[idx:idx + 3], bytes((255, 255, 255)))

    def test_blend_mask(self):
        mask = bytearray([255, 128, 0, 0])          # 2×2，左上角实心
        self.bmp.blend_mask(mask, 2, 2, 1, 1, (0, 0, 0))
        self.assertEqual(self.bmp.pixels[(1 * 6 + 1) * 3:(1 * 6 + 1) * 3 + 3],
                         bytes((0, 0, 0)))
        second = (1 * 6 + 2) * 3
        self.assertTrue(0 < self.bmp.pixels[second] < 255)
        self.assertEqual(self.bmp.pixels[(0 * 6 + 1) * 3:(0 * 6 + 1) * 3 + 3],
                         bytes((255, 255, 255)))

    def test_blend_mask_out_of_bounds_is_safe(self):
        mask = bytearray([255] * 4)
        self.bmp.blend_mask(mask, 2, 2, 5, 3, (0, 0, 0))     # 完全在画布外
        self.bmp.blend_mask(mask, 2, 2, -1, -1, (0, 0, 0))   # 左上角越界

    def test_blend_row(self):
        self.bmp.blend_row(1, 2, 4, (0, 0, 0))
        self.assertEqual(self.bmp.pixels[(1 * 6 + 2) * 3:(1 * 6 + 4) * 3],
                         bytes((0, 0, 0)) * 2)
        self.assertEqual(self.bmp.pixels[(1 * 6 + 4) * 3:(1 * 6 + 4) * 3 + 3],
                         bytes((255, 255, 255)))


if __name__ == "__main__":
    unittest.main()
