"""字体解析：拿真实系统字体跑，没有字体就跳过。

测试只断言"物理上必须成立"的关系（宽度为正、字形数大于零、字距不改变
字形的可读性），不把某个具体数字写死——否则换一台机器就红。
"""

import os
import unittest

from typesmith.binary import FontError
from typesmith.font import Font, font_collection
from typesmith.system import pick_defaults, scan

FONTS = [p for p in pick_defaults().values() if p]
HAVE = bool(FONTS)

REQUIRED = ["head", "hhea", "maxp", "cmap", "loca", "glyf", "hmtx"]


@unittest.skipUnless(HAVE, "系统里没有可用字体")
class TestFont(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = pick_defaults().get("sans") or FONTS[0]
        cls.font = Font(cls.path)

    def test_required_tables(self):
        for tag in REQUIRED:
            self.assertIn(tag, self.font.tables, f"缺表 {tag}")

    def test_header(self):
        self.assertGreater(self.font.num_glyphs, 26)
        self.assertIn(self.font.units_per_em, (16, 64, 256, 1000, 1024, 2048))
        self.assertGreater(self.font.ascent, 0)
        self.assertLess(self.font.descent, 1)      # descent 在 hhea 里通常是负数
        self.assertGreater(self.font.xmax, self.font.xmin)

    def test_cmap_roundtrip(self):
        for ch in "AZag09":
            gid = self.font.glyph_id(ord(ch))
            self.assertGreater(gid, 0, f"{ch} 没有字形")
            glyph = self.font.glyph(gid)
            self.assertGreater(glyph.advance, 0, f"{ch} 前进宽度不为正")
            self.assertTrue(glyph.contours or ch == " ", f"{ch} 没有轮廓")

    def test_missing_codepoint(self):
        self.assertEqual(self.font.glyph_id(0x10FFFD), 0)

    def test_hmtx_advance(self):
        gid = self.font.glyph_id(ord("M"))
        adv = self.font.glyph(gid).advance
        # advance 是字体单位，换算成像素后应该落在合理区间
        px = adv * 16 / self.font.units_per_em
        self.assertGreater(px, 2)
        self.assertLess(px, 40)

    def test_glyph_cache_identity(self):
        gid = self.font.glyph_id(ord("A"))
        self.assertIs(self.font.glyph(gid), self.font.glyph(gid))

    def test_text_width(self):
        one = self.font.text_width("A", 16)
        three = self.font.text_width("AAA", 16)
        self.assertGreater(three, one * 2.5)
        self.assertLess(three, one * 3.5)
        self.assertAlmostEqual(self.font.text_width("", 16), 0.0)

    def test_kerning_is_small_and_signed(self):
        for pair in ("AV", "To", "Wa"):
            left = self.font.glyph_id(ord(pair[0]))
            right = self.font.glyph_id(ord(pair[1]))
            if not left or not right:
                continue
            value = self.font.kerning(left, right)
            self.assertIsInstance(value, int)
            self.assertLess(abs(value), self.font.units_per_em)
            kerned = self.font.text_width(pair, 32, kern=True)
            flat = self.font.text_width(pair, 32, kern=False)
            self.assertAlmostEqual(kerned - flat,
                                   value * 32 / self.font.units_per_em, places=4)

    def test_kerning_symmetric(self):
        left = self.font.glyph_id(ord("A"))
        right = self.font.glyph_id(ord("V"))
        self.assertEqual(self.font.kerning(left, right), self.font.kerning(left, right))

    def test_info(self):
        info = self.font.info()
        for key in ("family", "style", "glyphs", "units_per_em", "tables", "kern_pairs"):
            self.assertIn(key, info)
        self.assertIsInstance(info["family"], str)
        self.assertTrue(info["tables"])
        self.assertIn("glyf", info["tables"])

    def test_bbox_cover_glyphs(self):
        for ch in "Hx0":
            g = self.font.glyph(self.font.glyph_id(ord(ch)))
            self.assertLessEqual(g.xmin, self.font.xmax)
            self.assertGreaterEqual(g.ymax, g.ymin)

    def test_bad_file(self):
        here = os.path.dirname(os.path.abspath(__file__))
        bad = os.path.join(here, "_broken.ttf")
        with open(bad, "wb") as fh:
            fh.write(b"\x00\x01\x00\x00garbage")
        try:
            with self.assertRaises(FontError):
                Font(bad)
        finally:
            os.remove(bad)

    def test_missing_file(self):
        with self.assertRaises(OSError):
            Font(os.path.join(os.path.dirname(__file__), "nope.ttf"))


@unittest.skipUnless(HAVE, "系统里没有可用字体")
class TestCollection(unittest.TestCase):
    def test_single_font(self):
        path = pick_defaults()["sans"]
        fonts = font_collection(path)
        self.assertGreaterEqual(len(fonts), 1)
        self.assertEqual(fonts[0].family, Font(path).family)

    def test_ttc(self):
        ttc = [p for p in scan() if p.lower().endswith(".ttc")]
        if not ttc:
            self.skipTest("没有 .ttc 字体")
        fonts = font_collection(ttc[0])
        self.assertGreaterEqual(len(fonts), 1)
        self.assertEqual({f.index for f in fonts}, set(range(len(fonts))))


if __name__ == "__main__":
    unittest.main()
