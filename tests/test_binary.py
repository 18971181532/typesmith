"""二进制读取器与错误处理。"""

import struct
import unittest

from typesmith.binary import FontError, Reader


class TestReader(unittest.TestCase):
    def test_unsigned(self):
        r = Reader(b"\x7f\xff\xff\xde\xad\xbe\xef")
        self.assertEqual(r.u8(), 0x7F)
        self.assertEqual(r.u16(), 0xFFFF)
        self.assertEqual(r.u32(), 0xDEADBEEF)

    def test_signed(self):
        r = Reader(struct.pack(">bh i", -3, -1000, 123456))
        self.assertEqual(r.i8(), -3)
        self.assertEqual(r.i16(), -1000)
        self.assertEqual(r.i32(), 123456)

    def test_position_advances(self):
        r = Reader(b"\x00\x01\x02\x03")
        start = r.pos
        r.u16()
        self.assertEqual(r.pos, start + 2)
        r.u8()
        self.assertEqual(r.pos, start + 3)

    def test_fixed_point(self):
        r = Reader(b"\x00\x01\x80\x00")
        self.assertAlmostEqual(r.fixed(), 1.5, places=6)

    def test_f2dot14(self):
        r = Reader(b"\x40\x00\xc0\x00")          # 1.0 与 -1.0
        self.assertAlmostEqual(r.f2dot14(), 1.0, places=6)
        self.assertAlmostEqual(r.f2dot14(), -1.0, places=6)

    def test_tag_advances_cursor(self):
        """tag() 忘了前移游标会让整张表目录错位——这是个真踩过的坑。"""
        r = Reader(b"head\x00\x00\x00\x00")
        self.assertEqual(r.tag(), "head")
        self.assertEqual(r.pos, 4)

    def test_skip_and_seek(self):
        r = Reader(bytes(range(10)))
        r.skip(3)
        self.assertEqual(r.u8(), 3)
        r.seek(9)
        self.assertEqual(r.u8(), 9)

    def test_remaining(self):
        r = Reader(b"\x00\x01\x02", 0, 3)
        self.assertEqual(r.remaining(), 3)
        r.u16()
        self.assertEqual(r.remaining(), 1)

    def test_overrun_raises(self):
        with self.assertRaises(FontError):
            Reader(b"\x00").u16()

    def test_seek_out_of_range(self):
        with self.assertRaises(FontError):
            Reader(b"\x00\x01").seek(9)

    def test_array(self):
        r = Reader(struct.pack(">HHH", 1, 2, 3))
        self.assertEqual(r.array_u16(3), [1, 2, 3])
        self.assertEqual(r.remaining(), 0)

    def test_array_signed(self):
        r = Reader(struct.pack(">hhh", -1, 0, 1))
        self.assertEqual(r.array_i16(3), [-1, 0, 1])

    def test_take(self):
        r = Reader(b"abcdef")
        r.skip(1)
        self.assertEqual(r.take(3), b"bcd")
        self.assertEqual(r.remaining(), 2)


if __name__ == "__main__":
    unittest.main()
