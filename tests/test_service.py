"""顶层封装：字体角色、文档构建、PNG / SVG 输出。"""

import unittest

from typesmith.png import read_png_size
from typesmith.service import (FontBook, build_document, make_compare,
                               make_specimen, page_stats, render_png_bytes,
                               svg_for, system_fonts)
from typesmith.system import pick_defaults
import os
import tempfile

DEFAULTS = pick_defaults()
HAVE = any(DEFAULTS.values())

TEXT = ("# 标题\n\nThe quick brown fox jumps over the lazy dog, and the typesetter "
        "watches the glue ratios creep upward.\n\n---\n\n> 引用一行。\n\n中文段落用来"
        "检查混排与避头尾是否生效。")


@unittest.skipUnless(HAVE, "系统里没有可用字体")
class TestFontBook(unittest.TestCase):
    def test_roles(self):
        book = FontBook()
        self.assertIsNotNone(book.get("sans"))
        self.assertEqual(book.get("nope"), None)

    def test_chain_has_cjk_last(self):
        book = FontBook()
        chain = book.chain("serif")
        self.assertGreaterEqual(len(chain), 1)
        self.assertEqual(chain[0], book.get("serif"))
        cjk = book.get("cjk")
        if cjk is not None:
            self.assertIs(chain[-1], cjk)

    def test_chain_deduplicates(self):
        book = FontBook()
        chain = book.chain("sans", "sans", "serif")
        self.assertEqual(len(chain), len({id(f) for f in chain}))

    def test_listing(self):
        rows = FontBook().listing()
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("role", row)
            self.assertIn("glyphs", row)
            self.assertGreater(row["glyphs"], 0)

    def test_custom_paths(self):
        book = FontBook({"serif": DEFAULTS["serif"], "sans": None})
        self.assertIsNone(book.get("sans"))
        self.assertIsNotNone(book.get("serif"))

    def test_broken_path_is_none(self):
        book = FontBook({"serif": os.path.join(os.path.dirname(__file__), "no.ttf")})
        self.assertIsNone(book.get("serif"))

    def test_reset(self):
        book = FontBook()
        first = book.get("serif")
        book.reset()
        self.assertIsNot(book.get("serif"), first)


@unittest.skipUnless(HAVE, "系统里没有可用字体")
class TestBuildDocument(unittest.TestCase):
    def test_build(self):
        book = FontBook()
        doc, stats = build_document(TEXT, book, size=14, page=(700, 900), margin=60)
        self.assertGreaterEqual(len(doc.pages), 1)
        self.assertEqual(stats["pages"], len(doc.pages))
        self.assertEqual(stats["lines"], doc.line_count)
        self.assertGreater(stats["chars"], 100)
        self.assertAlmostEqual(stats["measure"], 700 - 120, places=1)

    def test_measure_override(self):
        doc, stats = build_document(TEXT, FontBook(), size=14, measure=250,
                                    page=(700, 900), margin=60)
        self.assertAlmostEqual(stats["measure"], 250, places=1)
        for page in doc.pages:
            for line in page.lines:
                self.assertLessEqual(line.line.natural, 250 * 1.15)

    def test_png_bytes(self):
        doc, _ = build_document("hello", FontBook(), size=14, page=(400, 300), margin=40)
        blob = render_png_bytes(doc)
        self.assertTrue(blob.startswith(b"\x89PNG"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.png")
            with open(path, "wb") as fh:
                fh.write(blob)
            self.assertEqual(read_png_size(path), (400, 300))

    def test_page_stats(self):
        doc, _ = build_document(TEXT, FontBook(), size=14, page=(700, 900), margin=60)
        rows = page_stats(doc, 0)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("ratio", row)
            self.assertIn("text", row)
            self.assertLessEqual(row["badness"], 10000.0)

    def test_svg(self):
        doc, _ = build_document("hello", FontBook(), size=14, page=(400, 300), margin=40)
        svg = svg_for(doc)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("</svg>", svg)
        self.assertIn("<path", svg)

    def test_cjk_page_actually_has_ink(self):
        """整页中文必须画出字来：曾经因为一行共用拉丁字体的掩膜，汉字全成空白。"""
        doc, _ = build_document("汉字排版测试。汉字排版测试。汉字排版测试。" * 6,
                                FontBook(), size=18, page=(500, 400), margin=40)
        from typesmith.render import Renderer
        bmp = Renderer(doc).page_bitmap(doc.pages[0])
        dark = sum(1 for v in bmp.pixels if v < 128)
        self.assertGreater(dark / len(bmp.pixels), 0.01)

    def test_empty_text(self):
        doc, stats = build_document("", FontBook())
        self.assertEqual(stats["lines"], 0)
        self.assertEqual(len(doc.pages), 1)


@unittest.skipUnless(HAVE, "系统里没有可用字体")
class TestFigures(unittest.TestCase):
    def test_specimen(self):
        canvas, stats = make_specimen(FontBook(), 640, 900)
        self.assertEqual((canvas.width, canvas.height), (640, 900))
        self.assertEqual(len(canvas.pixels), 640 * 900 * 3)
        self.assertGreater(stats["body_lines"], 0)
        self.assertIn("grid", stats)

    def test_compare(self):
        canvas, stats = make_compare(FontBook(), "The quick brown fox jumps over the "
                                     "lazy dog while the typesetter watches.", 14, 260)
        self.assertGreater(canvas.width, 400)
        self.assertIn("greedy", stats)
        self.assertIn("knuth", stats)
        self.assertLessEqual(stats["knuth"]["demerits"], stats["greedy"]["demerits"] + 1)

    def test_system_fonts(self):
        rows = system_fonts(limit=6)
        self.assertTrue(rows)
        self.assertIn("family", rows[0])
        self.assertLessEqual(len(rows), 6)


if __name__ == "__main__":
    unittest.main()
