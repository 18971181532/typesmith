"""PNG 编码：块结构、CRC、滤波、像素无损。"""

import struct
import unittest
import zlib

from typesmith.png import _SIGNATURE, encode_png, png_chunks, read_png_size, write_png

import os
import tempfile


def solid(width, height, color=(10, 20, 30)):
    return bytes(color) * (width * height)


def chunks(data):
    """把 PNG 拆成 [(tag, payload), ...]。"""
    out = []
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4:pos + 8]
        out.append((tag, data[pos + 8:pos + 8 + length]))
        pos += 12 + length
    return out


class TestEncode(unittest.TestCase):
    def test_signature_and_chunks(self):
        data = encode_png(4, 3, solid(4, 3))
        self.assertTrue(data.startswith(_SIGNATURE))
        tags = [tag for tag, _ in chunks(data)]
        self.assertEqual(tags[0], b"IHDR")
        self.assertEqual(tags[-1], b"IEND")
        self.assertIn(b"IDAT", tags)

    def test_ihdr_fields(self):
        data = encode_png(7, 5, solid(7, 5))
        ihdr = dict(chunks(data))[b"IHDR"]
        width, height, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", ihdr)
        self.assertEqual((width, height), (7, 5))
        self.assertEqual(depth, 8)
        self.assertEqual(ctype, 2)                 # 真彩色
        self.assertEqual((comp, filt, interlace), (0, 0, 0))

    def test_crc_is_valid(self):
        data = encode_png(3, 3, solid(3, 3))
        pos = len(_SIGNATURE)
        while pos < len(data):
            length = struct.unpack_from(">I", data, pos)[0]
            tag = data[pos + 4:pos + 8]
            payload = data[pos + 8:pos + 8 + length]
            crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
            self.assertEqual(crc, zlib.crc32(tag + payload) & 0xFFFFFFFF)
            pos += 12 + length

    def test_pixels_roundtrip(self):
        width, height = 5, 4
        pixels = bytes((i * 7 + 3) % 256 for i in range(width * height * 3))
        data = encode_png(width, height, pixels)
        raw = zlib.decompress(b"".join(payload for tag, payload in chunks(data)
                                       if tag == b"IDAT"))
        stride = width * 3
        self.assertEqual(len(raw), height * (1 + stride))
        out = bytearray()
        prev = bytes(stride)
        for row in range(height):
            ftype = raw[row * (1 + stride)]
            line = bytearray(raw[row * (1 + stride) + 1:(row + 1) * (1 + stride)])
            if ftype == 1:                          # Sub
                for i in range(3, stride):
                    line[i] = (line[i] + line[i - 3]) & 0xFF
            elif ftype == 2:                        # Up
                for i in range(stride):
                    line[i] = (line[i] + prev[i]) & 0xFF
            self.assertIn(ftype, (0, 1, 2))
            out.extend(line)
            prev = bytes(line)
        self.assertEqual(bytes(out), pixels)

    def test_repeated_rows_use_up_filter(self):
        """整行相同的图（比如纯白背景）应该走到 Up 滤波上去。"""
        data = encode_png(6, 4, solid(6, 4))
        raw = zlib.decompress(b"".join(p for t, p in chunks(data) if t == b"IDAT"))
        stride = 6 * 3
        self.assertEqual(raw[0], 0)
        self.assertEqual(raw[1 + stride], 2)

    def test_size_mismatch(self):
        with self.assertRaises(ValueError):
            encode_png(2, 2, b"\x00" * 5)

    def test_read_png_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.png")
            write_png(path, 11, 9, solid(11, 9))
            self.assertEqual(read_png_size(path), (11, 9))

    def test_empty_image(self):
        data = encode_png(0, 0, b"")
        self.assertTrue(data.startswith(_SIGNATURE))


if __name__ == "__main__":
    unittest.main()
