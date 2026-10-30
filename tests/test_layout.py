"""断行：用合成的项流测数学，用真实字体测集成。

合成项流的好处是不依赖任何字体——CI 上只装了 DejaVu 也能跑出同样的数字。
"""

import unittest

from typesmith import Font, LayoutOptions, itemize, layout_paragraph
from typesmith.layout import (INF_BAD, INF_PENALTY, NO_LINE_START, Box, Glue,
                              Penalty, break_lines, greedy_break, line_ratio,
                              total_demerits)
from typesmith.system import pick_defaults

WORD_WIDTHS = [28, 34, 19, 42, 25, 31, 22, 38, 27, 20, 45, 24, 30, 18, 36]
SPACE = (4.0, 2.0, 1.0)


def synthetic(widths=WORD_WIDTHS, space=SPACE):
    """把"若干宽度的词 + 空格胶"拼成 TeX 的项流。"""
    items = []
    for i, w in enumerate(widths):
        items.append(Box(text="w", font=None, size=16, glyphs=[(0, w)], width=w))
        if i < len(widths) - 1:
            items.append(Glue(*space))
    items.append(Glue(0.0, INF_BAD, 0.0, text=""))       # parfillskip
    items.append(Penalty(0.0, -INF_PENALTY))
    return items


class TestItemize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = pick_defaults().get("serif") or pick_defaults().get("sans")
        if not cls.path:
            raise unittest.SkipTest("没有可用字体")
        cls.font = Font(cls.path)

    def test_ends_with_parfillskip_and_forced_break(self):
        items = itemize("hello world", [self.font], LayoutOptions(size=16))
        self.assertEqual(items[-1].kind, 2)
        self.assertTrue(items[-1].forced)
        self.assertEqual(items[-2].kind, 1)
        self.assertGreater(items[-2].stretch, 1000)

    def test_words_become_boxes(self):
        items = itemize("one two", [self.font], LayoutOptions(size=16))
        boxes = [it for it in items if it.kind == 0]
        self.assertEqual(len(boxes), 2)
        self.assertEqual(boxes[0].text, "one")

    def test_spaces_become_glue(self):
        opts = LayoutOptions(size=18)
        items = itemize("a b", [self.font], opts)
        glue = [it for it in items if it.kind == 1 and it.text == " "]
        self.assertEqual(len(glue), 1)
        self.assertAlmostEqual(glue[0].width, 18 / 3.0, places=6)
        self.assertGreater(glue[0].stretch, 0)
        self.assertGreater(glue[0].shrink, 0)

    def test_cjk_has_glue_between_chars(self):
        cjk = pick_defaults().get("cjk")
        if not cjk:
            self.skipTest("没有中文字体")
        font = Font(cjk)
        items = itemize("排版引擎", [font], LayoutOptions(size=16))
        boxes = [it for it in items if it.kind == 0]
        glue = [it for it in items if it.kind == 1 and it.text == ""]
        self.assertEqual(len(boxes), 4)
        self.assertGreaterEqual(len(glue), 3)

    def test_no_break_before_closing_punctuation(self):
        cjk = pick_defaults().get("cjk")
        if not cjk:
            self.skipTest("没有中文字体")
        font = Font(cjk)
        opts = LayoutOptions(size=16, measure=120)
        lines = layout_paragraph("一二三四五六七八九十，十一十二。", [font], opts).lines
        for line in lines[:-1]:
            self.assertTrue(line.text)
            self.assertNotIn(line.text.strip()[0], NO_LINE_START,
                             f"行首出现了 {line.text.strip()[0]!r}: {line.text!r}")


class TestBreakLines(unittest.TestCase):
    def check(self, measure, tolerance=4.0):
        opts = LayoutOptions(size=16, measure=measure, tolerance=tolerance)
        items = synthetic()
        lines = break_lines(items, measure, opts)
        self.assertTrue(lines, f"measure={measure} 断不出行")
        for line in lines:
            self.assertGreaterEqual(line.ratio, -1.0 - 1e-9,
                                    f"measure={measure} 行溢出：{line.ratio}")
        # 词的顺序不能乱，也不能丢
        joined = "".join(line.text for line in lines).replace(" ", "")
        self.assertEqual(joined, "w" * len(WORD_WIDTHS))
        return lines, opts

    def test_many_measures(self):
        for measure in (120, 160, 200, 240, 300, 400, 600):
            with self.subTest(measure=measure):
                self.check(measure)

    def test_last_line_is_loose_by_parfillskip(self):
        # parfillskip 的伸缩量很大但不是无限，所以末行的 ratio 是个很小的正数
        lines, _ = self.check(200)
        self.assertAlmostEqual(lines[-1].ratio, 0.0, delta=0.05)

    def test_lines_are_not_absurdly_wide(self):
        # natural 可以略微超过 measure（靠 shrink 压回来），但不该超太多
        lines, _ = self.check(220)
        for line in lines[:-1]:
            self.assertLessEqual(line.natural, 220 * 1.12)

    def test_knuth_not_worse_than_greedy(self):
        """K–P 求的是全局最优，所以任何行宽下它的总代价都不该高于贪心。"""
        for measure in (140, 180, 220, 260, 320, 420):
            opts = LayoutOptions(size=16, measure=measure)
            items = synthetic()
            knuth = break_lines(items, measure, opts)
            greedy = greedy_break(items, measure, opts)
            dk = total_demerits(knuth, opts)
            dg = total_demerits(greedy, opts)
            with self.subTest(measure=measure):
                self.assertLessEqual(dk, dg + 1e-6,
                                     f"measure={measure}: K–P {dk:.0f} > 贪心 {dg:.0f}")

    def test_matches_exhaustive_search(self):
        """小规模下与暴力枚举所有断点组合的结果对齐。"""
        widths = [20, 30, 15, 25, 18]
        measure = 120.0
        opts = LayoutOptions(size=16, measure=measure)
        items = synthetic(widths)
        lines = break_lines(items, measure, opts)
        best = total_demerits(lines, opts)

        # 断点 = 词之间的每个 glue（这里是 4 个），枚举全部 16 种组合
        breaks = [i for i, it in enumerate(items) if it.kind == 1 and it.text == " "]
        best_brute = None
        for mask in range(1 << len(breaks)):
            picks = [breaks[k] for k in range(len(breaks)) if mask & (1 << k)]
            picks.append(len(items) - 1)
            positions = [-1] + picks
            if any(positions[i] >= positions[i + 1] for i in range(len(positions) - 1)):
                continue
            cost = 0.0
            ok = True
            for a, b in zip(positions, positions[1:]):
                line = self._line_cost(items, a + 1, b, measure, opts)
                if line is None:
                    ok = False
                    break
                cost += line
            if ok and (best_brute is None or cost < best_brute):
                best_brute = cost
        self.assertIsNotNone(best_brute)
        self.assertAlmostEqual(best, best_brute, delta=max(1.0, best_brute * 1e-6))

    @staticmethod
    def _line_cost(items, start, end, measure, opts):
        width = stretch = shrink = 0.0
        for i in range(start, end):
            it = items[i]
            if it.kind == 0:
                width += it.width
            elif it.kind == 1:
                width += it.width
                stretch += it.stretch
                shrink += it.shrink
        tail = items[end]
        if tail.kind == 2:
            width += tail.width
        ratio = line_ratio(measure, width, stretch, shrink)
        if ratio < -1:
            return None
        badness = 100 * abs(ratio) ** 3
        if ratio > opts.tolerance:            # 与断行器同一套规则：超容差代价顶格
            badness = INF_BAD
        badness = min(badness, INF_BAD)
        return (opts.line_penalty + badness) ** 2

    def test_forced_break_splits(self):
        items = synthetic([20, 20, 20])
        forced = Penalty(0.0, -INF_PENALTY)
        items.insert(3, forced)              # 第一个词之后强制断
        opts = LayoutOptions(size=16)
        lines = break_lines(items, 500, opts)
        self.assertEqual(len(lines), 2)

    def test_empty_input(self):
        self.assertEqual(break_lines([], 200, LayoutOptions()), [])
        self.assertEqual(greedy_break([], 200, LayoutOptions()), [])

    def test_narrow_measure_does_not_hang(self):
        opts = LayoutOptions(size=16, measure=5)
        lines = break_lines(synthetic(), 5, opts)
        self.assertGreaterEqual(len(lines), 1)

    def test_deterministic(self):
        a = break_lines(synthetic(), 220, LayoutOptions(size=16, measure=220))
        b = break_lines(synthetic(), 220, LayoutOptions(size=16, measure=220))
        self.assertEqual([l.text for l in a], [l.text for l in b])
        self.assertEqual([round(l.ratio, 9) for l in a], [round(l.ratio, 9) for l in b])


class TestGreedy(unittest.TestCase):
    def test_greedy_fills_lines(self):
        opts = LayoutOptions(size=16)
        lines = greedy_break(synthetic(), 200, opts)
        self.assertGreaterEqual(len(lines), 2)
        for line in lines[:-1]:
            self.assertLessEqual(line.natural, 200 + 1e-6)

    def test_greedy_never_overflows_hard(self):
        for measure in (150, 250, 350):
            for line in greedy_break(synthetic(), measure, LayoutOptions()):
                self.assertGreaterEqual(line.ratio, -1.0 - 1e-9)


if __name__ == "__main__":
    unittest.main()
