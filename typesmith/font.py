"""TrueType / OpenType 字体解析（只读 ``glyf`` 轮廓，不做 hinting）。

支持的东西恰好是排版需要的那些：

  head  hhea  maxp   —— 度量与字形数
  cmap  4 / 12       —— 字符 → 字形
  loca  glyf         —— 轮廓（含复合字形的仿射变换）
  hmtx               —— 前进宽度与左侧承距
  kern  format 0     —— 字距调整
  name               —— 家族名与样式名
  TTC                —— 字体集合（Windows 的微软雅黑就是 .ttc）

不支持的：CFF/OTF 轮廓、变体轴、GSUB 连字、hinting 指令。遇到 CFF 字体
会明确报错，而不是画出一堆空白。
"""

from __future__ import annotations

import bisect
import os
import struct
from typing import Dict, List, Optional, Tuple

from .binary import FontError, Reader
from .gpos import load_kern_lookups

__all__ = ["Font", "Glyph"]

Point = Tuple[float, float, bool]        # x, y, 是否在曲线上
Contour = List[Point]
Outline = List[Contour]

# 复合字形的标志位
_ARG_1_AND_2_ARE_WORDS = 0x0001
_ARGS_ARE_XY_VALUES = 0x0002
_WE_HAVE_A_SCALE = 0x0008
_MORE_COMPONENTS = 0x0020
_WE_HAVE_AN_X_AND_Y_SCALE = 0x0040
_WE_HAVE_A_TWO_BY_TWO = 0x0080
_WE_HAVE_INSTRUCTIONS = 0x0100


class Glyph:
    """一个已经解析好的字形。"""

    __slots__ = ("gid", "advance", "lsb", "contours", "xmin", "ymin", "xmax", "ymax")

    def __init__(self, gid: int, advance: int, lsb: int):
        self.gid = gid
        self.advance = advance          # 字体单位
        self.lsb = lsb
        self.contours: Outline = []
        self.xmin = self.ymin = self.xmax = self.ymax = 0

    @property
    def is_empty(self) -> bool:
        return not self.contours

    def bbox(self) -> Tuple[float, float, float, float]:
        if self.contours:
            xs = [p[0] for c in self.contours for p in c]
            ys = [p[1] for c in self.contours for p in c]
            return min(xs), min(ys), max(xs), max(ys)
        return 0.0, 0.0, 0.0, 0.0

    def transformed(self, xx: float = 1.0, xy: float = 0.0,
                    yx: float = 0.0, yy: float = 1.0,
                    dx: float = 0.0, dy: float = 0.0) -> Outline:
        return [[(x * xx + y * yx + dx, x * xy + y * yy + dy, on)
                 for (x, y, on) in contour] for contour in self.contours]

    def __repr__(self) -> str:
        return f"<Glyph {self.gid} adv={self.advance} contours={len(self.contours)}>"


class Cmap:
    """一个 cmap 子表。格式 4 用二分查段，格式 12 用二分查组。"""

    def __init__(self, kind: int, **kw):
        self.kind = kind
        self.__dict__.update(kw)

    def lookup(self, code: int) -> int:
        if self.kind == 4:
            segs = self.segs
            i = bisect.bisect_left(segs, (code,))
            if i == len(segs):
                return 0
            end, start, delta, range_off, glyphs = segs[i]
            if not (start <= code <= end):
                return 0
            if range_off == 0:
                return (code + delta) & 0xFFFF
            idx = range_off // 2 + (code - start) - (len(segs) - i)
            if 0 <= idx < len(glyphs):
                g = glyphs[idx]
                return (g + delta) & 0xFFFF if g else 0
            return 0
        if self.kind == 12:
            starts = self.starts
            i = bisect.bisect_right(starts, code) - 1
            if i < 0:
                return 0
            s, e, g = self.groups[i]
            return g + (code - s) if s <= code <= e else 0
        if self.kind == 0:
            return self.table[code] if 0 <= code < 256 else 0
        if self.kind == 6:
            i = code - self.first
            return self.table[i] if 0 <= i < len(self.table) else 0
        return 0


class Font:
    """一个 TrueType 字体（或 TTC 中的某一款）。"""

    def __init__(self, source, index: int = 0):
        if isinstance(source, (bytes, bytearray)):
            self.data = bytes(source)
            self.path = None
        else:
            self.path = os.fspath(source)
            with open(self.path, "rb") as fh:
                self.data = fh.read()
        self.index = index
        self.tables: Dict[str, Tuple[int, int]] = {}

        base = self._sfnt_base(index)
        self._read_table_directory(base)
        self._read_head()
        self._read_hhea()
        self._read_maxp()
        self._read_cmap()
        self._read_hmtx()
        self._read_loca()
        self._read_kern()
        self._read_names()
        self._gpos = None
        self._gpos_tried = False
        self._cache: Dict[int, Glyph] = {}

    # ------------------------------------------------------------ 目录
    def _sfnt_base(self, index: int) -> int:
        data = self.data
        if len(data) < 12:
            raise FontError("文件太短，不是字体")
        tag = data[:4]
        if tag == b"ttcf":
            r = Reader(data, 4)
            r.u16()                       # majorVersion
            r.u16()                       # minorVersion
            count = r.u32()
            if index >= count:
                raise FontError(f"TTC 只有 {count} 款字体，请求第 {index} 款")
            offsets = r.array_u32(count)
            return offsets[index]
        if tag not in (b"\x00\x01\x00\x00", b"true", b"OTTO", b"typ1"):
            raise FontError("不是 TrueType/OpenType 文件")
        if index != 0:
            raise FontError("单字体文件不支持 index != 0")
        return 0

    def _read_table_directory(self, base: int) -> None:
        r = Reader(self.data, base)
        version = r.u32()
        if version == 0x4F54544F:          # 'OTTO'
            raise FontError("这是 CFF 轮廓的 OpenType 字体，本项目只支持 glyf")
        n = r.u16()                        # numTables
        r.skip(6)                          # searchRange / entrySelector / rangeShift
        for _ in range(n):
            tag = r.tag()
            r.u32()                        # checksum
            off = r.u32()
            length = r.u32()
            self.tables[tag] = (off, length)
        for need in ("head", "hhea", "maxp", "cmap", "loca", "glyf", "hmtx"):
            if need not in self.tables:
                raise FontError(f"缺少必需的表：{need}")

    def _table(self, tag: str) -> Reader:
        if tag not in self.tables:
            raise FontError(f"没有 {tag} 表")
        off, length = self.tables[tag]
        return Reader(self.data, off, off + length)

    def has(self, tag: str) -> bool:
        return tag in self.tables

    # ------------------------------------------------------------ 度量
    def _read_head(self) -> None:
        r = self._table("head")
        r.skip(18)
        self.units_per_em = r.u16()
        if self.units_per_em == 0:
            raise FontError("unitsPerEm 为 0")
        r.skip(16)                         # created / modified
        self.xmin = r.i16()
        self.ymin = r.i16()
        self.xmax = r.i16()
        self.ymax = r.i16()
        r.skip(6)                          # macStyle, lowestRecPPEM, fontDirectionHint
        self.index_to_loc = r.i16()

    def _read_hhea(self) -> None:
        r = self._table("hhea")
        r.skip(4)
        self.ascent = r.i16()
        self.descent = r.i16()
        self.line_gap = r.i16()
        r.skip(24)
        self.num_hmetrics = r.u16()

    def _read_maxp(self) -> None:
        r = self._table("maxp")
        r.skip(4)
        self.num_glyphs = r.u16()

    def _read_hmtx(self) -> None:
        r = self._table("hmtx")
        n = self.num_hmetrics
        self._advances: List[int] = [0] * self.num_glyphs
        self._lsb: List[int] = [0] * self.num_glyphs
        last = 0
        for i in range(min(n, self.num_glyphs)):
            last = r.u16()
            self._advances[i] = last
            self._lsb[i] = r.i16()
        for i in range(n, self.num_glyphs):
            self._advances[i] = last
            if r.remaining() >= 2:
                self._lsb[i] = r.i16()

    def _read_loca(self) -> None:
        r = self._table("loca")
        n = self.num_glyphs
        if self.index_to_loc == 0:
            raw = r.array_u16(min(n + 1, r.remaining() // 2))
            self._loca = [v * 2 for v in raw]
        else:
            raw = r.array_u32(min(n + 1, r.remaining() // 4))
            self._loca = list(raw)
        while len(self._loca) <= n:
            self._loca.append(self._loca[-1] if self._loca else 0)

    def _read_kern(self) -> None:
        self.kern: Dict[Tuple[int, int], int] = {}
        if "kern" not in self.tables:
            return
        try:
            r = self._table("kern")
            version = r.u16()
            if version != 0:
                return
            n = r.u16()
            for _ in range(n):
                r.u16()                    # subtable version
                length = r.u16()
                coverage = r.u16()
                start = r.pos
                fmt = coverage >> 8
                if fmt == 0 and (coverage & 0x1):
                    pairs = r.u16()
                    r.skip(6)              # searchRange / entrySelector / rangeShift
                    for _ in range(pairs):
                        left = r.u16()
                        right = r.u16()
                        value = r.i16()
                        if value:
                            self.kern[(left, right)] = value
                r.seek(start + length)
        except (FontError, struct.error):
            self.kern = {}

    def _read_names(self) -> None:
        self.family = "?"
        self.style = ""
        self.full_name = "?"
        if "name" not in self.tables:
            return
        try:
            r = self._table("name")
            fmt = r.u16()
            count = r.u16()
            string_offset = r.u16()
            records = []
            for _ in range(count):
                platform = r.u16()
                encoding = r.u16()
                language = r.u16()
                name_id = r.u16()
                length = r.u16()
                offset = r.u16()
                records.append((platform, encoding, language, name_id, length, offset))
            base = self.tables["name"][0] + string_offset

            def decode(rec) -> str:
                platform, encoding, language, name_id, length, offset = rec
                raw = self.data[base + offset: base + offset + length]
                if platform == 3 or (platform == 0):
                    try:
                        return raw.decode("utf-16-be")
                    except UnicodeDecodeError:
                        return ""
                return raw.decode("latin-1", "replace")

            best: Dict[int, str] = {}
            for rec in records:
                platform, encoding, language, name_id = rec[:4]
                if name_id not in (1, 2, 4, 6):
                    continue
                score = 0
                if platform == 3 and language == 0x409:
                    score = 3
                elif platform == 3:
                    score = 2
                elif platform == 1 and language == 0:
                    score = 1
                if score and (name_id not in best or score >= best[name_id][0]):
                    best[name_id] = (score, decode(rec))
            if 1 in best:
                self.family = best[1][1]
            if 2 in best:
                self.style = best[2][1]
            if 4 in best:
                self.full_name = best[4][1]
            elif 6 in best:
                self.full_name = best[6][1]
        except (FontError, struct.error):
            pass

    # ------------------------------------------------------------ cmap
    def _read_cmap(self) -> None:
        r = self._table("cmap")
        r.u16()                            # version
        n = r.u16()
        best: Optional[Tuple[int, int, int]] = None   # (rank, offset, format)
        for _ in range(n):
            platform = r.u16()
            encoding = r.u16()
            offset = r.u32()
            sub = Reader(self.data, self.tables["cmap"][0] + offset)
            fmt = sub.u16()
            if fmt not in (0, 4, 6, 12):
                continue
            if platform == 3 and encoding == 10:
                rank = 5
            elif platform == 3 and encoding == 1:
                rank = 4
            elif platform == 0:
                rank = 3 if fmt == 12 else 2
            elif platform == 1 and encoding == 0:
                rank = 1
            else:
                continue
            if best is None or rank > best[0]:
                best = (rank, offset, fmt)
        if best is None:
            raise FontError("没有可用的 cmap 子表（只支持格式 0/4/6/12）")
        _, offset, fmt = best
        self._read_cmap_sub(self.tables["cmap"][0] + offset, fmt)

    def _read_cmap_sub(self, offset: int, fmt: int) -> None:
        r = Reader(self.data, offset)
        r.u16()                            # format
        if fmt == 0:
            r.u16()                        # length
            r.u16()                        # language
            table = list(r.take(256))
            self.cmap = Cmap(0, table=table)
        elif fmt == 6:
            r.u16()
            r.u16()
            first = r.u16()
            count = r.u16()
            table = r.array_u16(count)
            self.cmap = Cmap(6, table=table, first=first)
        elif fmt == 4:
            r.u16()                        # length
            r.u16()                        # language
            seg_x2 = r.u16()
            seg = seg_x2 // 2
            r.skip(6)                      # searchRange / entrySelector / rangeShift
            ends = r.array_u16(seg)
            r.u16()                        # reservedPad
            starts = r.array_u16(seg)
            deltas = r.array_i16(seg)
            range_offsets = r.array_u16(seg)
            glyph_array_pos = r.pos
            glyphs = r.array_u16(max(0, (r.remaining()) // 2))
            segs = []
            for i in range(seg):
                segs.append((ends[i], starts[i], deltas[i],
                             range_offsets[i], glyphs))
            self.cmap = Cmap(4, segs=segs, glyph_array_pos=glyph_array_pos)
        else:                              # fmt == 12
            r.u16()
            r.u32()                        # length
            r.u32()                        # language
            n = r.u32()
            groups = []
            for _ in range(n):
                groups.append((r.u32(), r.u32(), r.u32()))
            starts = [g[0] for g in groups]
            self.cmap = Cmap(12, groups=groups, starts=starts)

    # ------------------------------------------------------------ 字形
    def glyph_id(self, code: int) -> int:
        gid = self.cmap.lookup(code)
        return gid if gid < self.num_glyphs else 0

    def glyph_ids(self, text: str) -> List[int]:
        return [self.glyph_id(ord(ch)) for ch in text]

    def advance(self, gid: int) -> int:
        return self._advances[gid] if 0 <= gid < self.num_glyphs else 0

    def side_bearing(self, gid: int) -> int:
        return self._lsb[gid] if 0 <= gid < self.num_glyphs else 0

    def _ensure_gpos(self) -> None:
        if self._gpos_tried:
            return
        self._gpos_tried = True
        if "GPOS" not in self.tables:
            return
        off, length = self.tables["GPOS"]
        try:
            self._gpos = load_kern_lookups(self.data, off, off + length)
        except (FontError, IndexError, KeyError, ValueError):
            self._gpos = None

    def kerning(self, left: int, right: int) -> int:
        """字距调整，字体单位。优先用 GPOS，退回 kern 表。"""
        self._ensure_gpos()
        if self._gpos:
            value = self._gpos.xadvance(left, right)
            if value:
                return value
        return self.kern.get((left, right), 0)

    def glyph(self, gid: int) -> Glyph:
        cached = self._cache.get(gid)
        if cached is not None:
            return cached
        g = Glyph(gid, self.advance(gid), self.side_bearing(gid))
        if 0 <= gid < self.num_glyphs:
            g.contours = self._load_contours(gid, depth=0)
        if g.contours:
            xs = [p[0] for c in g.contours for p in c]
            ys = [p[1] for c in g.contours for p in c]
            g.xmin, g.xmax = min(xs), max(xs)
            g.ymin, g.ymax = min(ys), max(ys)
        self._cache[gid] = g
        return g

    def _glyph_range(self, gid: int) -> Tuple[int, int]:
        if gid + 1 >= len(self._loca):
            return 0, 0
        return self._loca[gid], self._loca[gid + 1]

    def _load_contours(self, gid: int, depth: int) -> Outline:
        start, end = self._glyph_range(gid)
        if end <= start:
            return []
        off = self.tables["glyf"][0]
        r = Reader(self.data, off + start, off + end)
        n_contours = r.i16()
        r.skip(8)                          # xMin / yMin / xMax / yMax
        if n_contours >= 0:
            return self._simple_glyph(r, n_contours)
        if depth > 4:
            return []                      # 复合字形套娃，防递归
        return self._composite_glyph(r, depth)

    def _simple_glyph(self, r: Reader, n_contours: int) -> Outline:
        ends = r.array_u16(n_contours)
        n_points = ends[-1] + 1 if ends else 0
        instruction_length = r.u16()
        r.skip(instruction_length)

        flags: List[int] = []
        while len(flags) < n_points:
            f = r.u8()
            flags.append(f)
            if f & 0x08:                   # REPEAT_FLAG
                flags.extend([f] * r.u8())
        flags = flags[:n_points]

        xs: List[int] = []
        v = 0
        for f in flags:
            if f & 0x02:                   # X_SHORT_VECTOR
                d = r.u8()
                v += d if (f & 0x10) else -d
            elif not (f & 0x10):
                v += r.i16()
            xs.append(v)
        ys: List[int] = []
        v = 0
        for f in flags:
            if f & 0x04:
                d = r.u8()
                v += d if (f & 0x20) else -d
            elif not (f & 0x20):
                v += r.i16()
            ys.append(v)

        contours: Outline = []
        start = 0
        for end_idx in ends:
            contour = [(float(xs[i]), float(ys[i]), bool(flags[i] & 0x01))
                       for i in range(start, end_idx + 1)]
            if contour:
                contours.append(contour)
            start = end_idx + 1
        return contours

    def _composite_glyph(self, r: Reader, depth: int) -> Outline:
        out: Outline = []
        while True:
            flags = r.u16()
            component = r.u16()
            if flags & _ARG_1_AND_2_ARE_WORDS:
                a1 = r.i16()
                a2 = r.i16()
            else:
                if flags & _ARGS_ARE_XY_VALUES:
                    a1 = r.i8()
                    a2 = r.i8()
                else:
                    a1 = r.u8()
                    a2 = r.u8()
            dx = dy = 0.0
            if flags & _ARGS_ARE_XY_VALUES:
                dx, dy = float(a1), float(a2)
            xx = yy = 1.0
            xy = yx = 0.0
            if flags & _WE_HAVE_A_SCALE:
                xx = yy = r.f2dot14()
            elif flags & _WE_HAVE_AN_X_AND_Y_SCALE:
                xx = r.f2dot14()
                yy = r.f2dot14()
            elif flags & _WE_HAVE_A_TWO_BY_TWO:
                xx = r.f2dot14()
                xy = r.f2dot14()
                yx = r.f2dot14()
                yy = r.f2dot14()
            if 0 <= component < self.num_glyphs:
                sub = self._load_contours(component, depth + 1)
                for contour in sub:
                    out.append([(x * xx + y * yx + dx, x * xy + y * yy + dy, on)
                                for (x, y, on) in contour])
            if not (flags & _MORE_COMPONENTS):
                break
        if flags & _WE_HAVE_INSTRUCTIONS:
            # 有指令时长度字段在后面，但我们不做 hinting，忽略即可
            pass
        return out

    # ------------------------------------------------------------ 辅助
    def scale(self, size_px: float) -> float:
        return size_px / float(self.units_per_em)

    def text_width(self, text: str, size_px: float, kern: bool = True) -> float:
        s = self.scale(size_px)
        total = 0.0
        prev = -1
        for gid in self.glyph_ids(text):
            total += self.advance(gid)
            if kern and prev >= 0:
                total += self.kerning(prev, gid)
            prev = gid
        return total * s

    def info(self) -> Dict[str, object]:
        return {
            "family": self.family, "style": self.style,
            "full_name": self.full_name, "index": self.index,
            "glyphs": self.num_glyphs, "units_per_em": self.units_per_em,
            "ascent": self.ascent, "descent": self.descent,
            "line_gap": self.line_gap,
            "bbox": [self.xmin, self.ymin, self.xmax, self.ymax],
            "kern_pairs": len(self.kern),
            "gpos": bool(self._gpos) if self._gpos_tried else ("GPOS" in self.tables),
            "tables": sorted(self.tables),
        }

    def __repr__(self) -> str:
        return f"<Font {self.full_name!r} {self.num_glyphs} glyphs>"


def open_font(path: str, index: int = 0) -> Font:
    return Font(path, index)


def font_collection(path: str) -> List[Font]:
    """列出 TTC 里所有字体（普通 TTF 只返回一款）。"""
    with open(path, "rb") as fh:
        head = fh.read(12)
    if head[:4] != b"ttcf":
        return [Font(path, 0)]
    count = struct.unpack_from(">I", head, 8)[0]
    out = []
    for i in range(count):
        try:
            out.append(Font(path, i))
        except FontError:
            pass
    return out
