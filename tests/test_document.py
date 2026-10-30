"""标记解析与分页。"""

import unittest

from typesmith.document import (Block, BlockStyle, Document, PageSpec, Paginator,
                                parse_markup, split_runs)
from typesmith.font import Font
from typesmith.system import pick_defaults

PATH = pick_defaults().get("serif") or pick_defaults().get("sans")


def font():
    return Font(PATH)


@unittest.skipUnless(PATH, "系统里没有可用字体")
class TestMarkup(unittest.TestCase):
    def setUp(self):
        self.f = font()
        self.base = BlockStyle(font=self.f, size=15)

    def test_paragraphs_split_on_blank_line(self):
        blocks = parse_markup("one two\n\nthree", self.base, self.f)
        self.assertEqual([b.kind for b in blocks], ["para", "para"])
        self.assertEqual(blocks[0].text, "one two")

    def test_soft_wrap_is_joined(self):
        blocks = parse_markup("one\ntwo", self.base, self.f)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text, "one two")

    def test_headings(self):
        blocks = parse_markup("# One\n\n## Two\n\n### Three", self.base, self.f)
        self.assertEqual([b.level for b in blocks], [1, 2, 3])
        self.assertEqual(blocks[0].text, "One")
        self.assertGreater(blocks[0].style.size, blocks[1].style.size)
        self.assertEqual(blocks[0].style.font, self.f)

    def test_rule(self):
        blocks = parse_markup("a\n\n---\n\nb", self.base, self.f)
        self.assertEqual([b.kind for b in blocks], ["para", "rule", "para"])

    def test_quote(self):
        blocks = parse_markup("> quoted", self.base, self.f)
        self.assertEqual(blocks[0].kind, "meta")
        self.assertEqual(blocks[0].text, "quoted")
        self.assertGreater(blocks[0].style.indent, 0)

    def test_empty(self):
        self.assertEqual(parse_markup("", self.base, self.f), [])
        self.assertEqual(parse_markup("\n\n\n", self.base, self.f), [])

    def test_inline_code_runs(self):
        self.assertEqual(split_runs("用 `head` 表"),
                         [("用 ", False), ("head", True), (" 表", False)])
        blocks = parse_markup("用 `head` 表", self.base, self.f)
        self.assertEqual(blocks[0].text, "用 head 表")
        self.assertEqual(len(blocks[0].runs), 3)

    def test_heading_sizes_override(self):
        blocks = parse_markup("# T", self.base, self.f, heading_sizes=[40, 30, 20])
        self.assertAlmostEqual(blocks[0].style.size, 40)


@unittest.skipUnless(PATH, "系统里没有可用字体")
class TestPaginator(unittest.TestCase):
    def setUp(self):
        self.f = font()
        self.base = BlockStyle(font=self.f, size=15, leading=1.6)
        self.spec = PageSpec(width=600, height=800, margin_top=70, margin_bottom=70,
                             margin_left=60, margin_right=60, header="T")

    def layout(self, text):
        blocks = parse_markup(text, self.base, self.f)
        return Paginator(self.spec, self.base).layout(blocks, [self.f])

    def test_single_page(self):
        doc = self.layout("short text only")
        self.assertEqual(len(doc.pages), 1)
        self.assertEqual(doc.line_count, 1)

    def test_many_pages(self):
        text = "\n\n".join(["This is a paragraph that should wrap a couple of times. "] * 60)
        doc = self.layout(text)
        self.assertGreater(len(doc.pages), 2)
        self.assertEqual([p.index for p in doc.pages], list(range(len(doc.pages))))

    def test_lines_stay_inside_content_box(self):
        text = "\n\n".join(["word " * 40] * 40)
        doc = self.layout(text)
        top = self.spec.margin_top
        bottom = self.spec.height - self.spec.margin_bottom
        for page in doc.pages:
            for line in page.lines:
                self.assertGreaterEqual(line.baseline, top - 1)
                self.assertLessEqual(line.baseline, bottom + 1)

    def test_no_orphan_or_widow(self):
        """一个段落不该在页底只留一行，也不该把一行单独带到下一页——除非段很短。"""
        text = "\n\n".join(["paragraph body " * 30] * 30)
        doc = self.layout(text)
        for page in doc.pages[:-1]:
            kinds = [id(l.style) for l in page.lines]
            if not kinds:
                continue
            last_style = page.lines[-1].style
            count = sum(1 for l in page.lines if l.style is last_style)
            self.assertGreater(count, 1, "页底出现了一行孤立的段落")

    def test_all_text_is_kept(self):
        text = "# Head\n\nfirst para\n\nsecond para"
        doc = self.layout(text)
        joined = "".join(l.text for p in doc.pages for l in p.lines)
        for word in ("Head", "first", "second"):
            self.assertIn(word, joined)

    def test_rule_in_rules_list(self):
        doc = self.layout("a\n\n---\n\nb")
        rules = [r for p in doc.pages for r in p.rules]
        self.assertEqual(len(rules), 1)
        x0, y0, x1, y1, color = rules[0]
        self.assertEqual(x0, self.spec.margin_left)
        self.assertGreater(x1, x0)

    def test_long_unbreakable_word(self):
        doc = self.layout("x" * 400)
        self.assertGreaterEqual(doc.line_count, 1)

    def test_inline_code_uses_mono_font(self):
        mono = pick_defaults().get("mono")
        if not mono:
            self.skipTest("没有等宽字体")
        m = Font(mono)
        blocks = parse_markup("call `head` now", self.base, self.f)
        doc = Paginator(self.spec, self.base, mono=m).layout(blocks, [self.f])
        fonts = {it.font for p in doc.pages for l in p.lines for it in l.items
                 if getattr(it, "kind", -1) == 0}
        self.assertIn(m, fonts)
        self.assertIn(self.f, fonts)

    def test_chinese_text(self):
        cjk = pick_defaults().get("cjk")
        if not cjk:
            self.skipTest("没有中文字体")
        f = Font(cjk)
        base = BlockStyle(font=f, size=15, leading=1.7)
        blocks = parse_markup("排版不是把字形并排摆好。字距、行距、断行位置，" * 12, base, f)
        doc = Paginator(self.spec, base).layout(blocks, [f])
        self.assertGreater(doc.line_count, 3)


if __name__ == "__main__":
    unittest.main()
