"""GPOS 的 ValueRecord 位语义与 PairPos 子表。

这层的难点不在算法，而在"字段是按位出现的，不是按位置出现的"：某个字对的
记录里只设了 XAdvance 时，第一个 i16 就是 xAdvance，而不是 xPlacement。
读错一位，所有字距都会静默变成 0。
"""

import struct
import unittest

from typesmith.binary import Reader
from typesmith.gpos import (GposKern, _class_def, _coverage, _read_pair_pos,
                            _read_value, _value_size)


class TestValueRecord(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_read_value(Reader(b""), 0b0000), (0, 0, 0, 0))

    def test_only_xadvance_occupies_first_slot(self):
        """fmt=0b0100：只出现 XAdvance，它必须落在第 0 个 i16 上。"""
        r = Reader(struct.pack(">h", -152))
        xpl, ypl, xadv, yadv = _read_value(r, 0b0100)
        self.assertEqual((xpl, ypl, xadv, yadv), (0, 0, -152, 0))

    def test_xplacement_and_xadvance(self):
        """fmt=0b0101：两个字段按位号顺序出现，xPlacement 在前。"""
        r = Reader(struct.pack(">hh", 36, -80))
        self.assertEqual(_read_value(r, 0b0101), (36, 0, -80, 0))

    def test_all_four(self):
        r = Reader(struct.pack(">hhhh", 1, 2, 3, 4))
        self.assertEqual(_read_value(r, 0b1111), (1, 2, 3, 4))

    def test_device_tables_are_skipped(self):
        """高四位是 device 偏移，只占位，不进返回值。"""
        r = Reader(struct.pack(">hHH", -50, 0, 0))
        self.assertEqual(_read_value(r, 0b0100_0000), (0, 0, 0, 0))
        self.assertEqual(r.remaining(), 4)
        r = Reader(struct.pack(">HHHH", 9, 9, 9, 9))
        self.assertEqual(_read_value(r, 0b1111_0000), (0, 0, 0, 0))
        self.assertEqual(r.remaining(), 0)

    def test_value_size(self):
        self.assertEqual(_value_size(0b0000), 0)
        self.assertEqual(_value_size(0b0100), 2)
        self.assertEqual(_value_size(0b1111), 8)
        self.assertEqual(_value_size(0b1111_1111), 16)


class TestCoverage(unittest.TestCase):
    def test_format1(self):
        # format=1, count=3, glyphs=[5,7,9]
        data = struct.pack(">HHHHH", 1, 3, 5, 7, 9)
        self.assertEqual(_coverage(Reader(data), 0), {5: 0, 7: 1, 9: 2})

    def test_format2_ranges(self):
        # format=2, count=2, (start=10,end=12,startCoverage=0) (start=20,end=20,idx=3)
        data = struct.pack(">HHHHHHHH", 2, 2, 10, 12, 0, 20, 20, 3)
        cov = _coverage(Reader(data), 0)
        self.assertEqual(cov, {10: 0, 11: 1, 12: 2, 20: 3})


class TestClassDef(unittest.TestCase):
    def test_format1(self):
        # format=1, startGlyph=4, glyphCount=2, classes=[1,2]
        data = struct.pack(">HHHHH", 1, 4, 2, 1, 2)
        self.assertEqual(_class_def(Reader(data), 0), {4: 1, 5: 2})

    def test_format2(self):
        # format=2, rangeCount=1, (start=7,end=9,class=5)
        data = struct.pack(">HHHHHH", 2, 1, 7, 9, 5, 0)
        cls = _class_def(Reader(data), 0)
        self.assertEqual(cls.get(7), 5)
        self.assertEqual(cls.get(9), 5)


class TestPairPos1(unittest.TestCase):
    def _build(self):
        """手工拼一个 PairPos format 1：字形 3 与 4 之间 -152。"""
        # header: posFormat=1, coverageOff, valueFormat1, valueFormat2, pairSetCount
        # 后面接 pairSetOffsets[1]，再后面是 PairSet(recordCount + records)
        # 布局：header(10) | pairSetOffset(2)=12 | PairSet(6) | coverage(从 18 起)
        header = struct.pack(">HHHHH", 1, 18, 0b0100, 0, 1)
        pair_set = struct.pack(">Hhh", 1, 4, -152)       # count, secondGlyph, xAdvance
        coverage = struct.pack(">HHH", 1, 1, 3)          # format=1, count=1, gid=3
        body = header + struct.pack(">H", 12) + pair_set + coverage
        return body

    def test_reads_single_pair(self):
        kern = _read_pair_pos(Reader(self._build()), 0, 0)
        self.assertIsNotNone(kern)
        self.assertEqual(kern.xadvance(3, 4), -152)
        self.assertEqual(kern.xadvance(3, 5), 0)
        self.assertEqual(kern.xadvance(9, 4), 0)


class TestGposKern(unittest.TestCase):
    def test_empty(self):
        kern = GposKern([])
        self.assertEqual(kern.xadvance(1, 2), 0)


if __name__ == "__main__":
    unittest.main()
