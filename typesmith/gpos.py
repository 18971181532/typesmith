"""GPOS 字距调整（只读 pair positioning）。

现代字体（Arial / Times / Georgia）早就不写 ``kern`` 表了，字距全在 GPOS 的
``kern`` 特性里。不读它，``AV`` ``To`` ``Yo`` 这些经典组合就会松垮垮地散开——
排版和"把字形并排摆好"的差别，一半在这里。

只实现 PairPos 的 format 1（逐对列表）与 format 2（类矩阵），其余查找类型
一律跳过，不影响正确性。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .binary import FontError, Reader

__all__ = ["load_kern_lookups", "GposKern"]


def _coverage(r: Reader, off: int) -> Dict[int, int]:
    """读 Coverage 表，返回 glyph -> coverage index。"""
    r.seek(off)
    fmt = r.u16()
    out: Dict[int, int] = {}
    if fmt == 1:
        n = r.u16()
        for i in range(n):
            out[r.u16()] = i
    elif fmt == 2:
        n = r.u16()
        idx = 0
        for _ in range(n):
            start = r.u16()
            end = r.u16()
            idx = r.u16()               # startCoverageIndex
            for g in range(start, end + 1):
                out[g] = idx
                idx += 1
    else:
        raise FontError(f"未知 Coverage 格式 {fmt}")
    return out


def _class_def(r: Reader, off: int) -> Dict[int, int]:
    r.seek(off)
    fmt = r.u16()
    out: Dict[int, int] = {}
    if fmt == 1:
        start = r.u16()
        n = r.u16()
        for i in range(n):
            cls = r.u16()
            if cls:
                out[start + i] = cls
    elif fmt == 2:
        n = r.u16()
        for _ in range(n):
            start = r.u16()
            end = r.u16()
            cls = r.u16()
            if cls:
                for g in range(start, end + 1):
                    out[g] = cls
    else:
        raise FontError(f"未知 ClassDef 格式 {fmt}")
    return out


def _value_size(fmt: int) -> int:
    """ValueRecord 的字节数：八个字段全是 2 字节（设备表字段是 Offset16）。"""
    return 2 * bin(fmt & 0xFF).count("1")


def _read_value(r: Reader, fmt: int) -> Tuple[int, int, int, int]:
    """返回 (xPla, yPla, xAdv, yAdv)；设备表偏移直接丢弃。

    字段是**按位出现**的，不是按位置出现——只设了 XAdvance 的字体，
    第一个 i16 就是 xAdvance，不能当成 xPlacement。
    """
    vals = [0, 0, 0, 0]
    for bit in range(4):
        if fmt & (1 << bit):
            vals[bit] = r.i16()
    for bit in range(4, 8):
        if fmt & (1 << bit):
            r.u16()
    return vals[0], vals[1], vals[2], vals[3]


class _PairPos1:
    __slots__ = ("coverage", "pairs", "vf1", "vf2")

    def __init__(self, coverage, pairs, vf1, vf2):
        self.coverage = coverage
        self.pairs = pairs
        self.vf1 = vf1
        self.vf2 = vf2

    def xadvance(self, left: int, right: int) -> int:
        row = self.pairs.get(left)
        if not row:
            return 0
        return row.get(right, 0)


class _PairPos2:
    __slots__ = ("coverage", "class1", "class2", "matrix", "vf1", "vf2")

    def __init__(self, coverage, class1, class2, matrix, vf1, vf2):
        self.coverage = coverage
        self.class1 = class1
        self.class2 = class2
        self.matrix = matrix
        self.vf1 = vf1
        self.vf2 = vf2

    def xadvance(self, left: int, right: int) -> int:
        if left not in self.coverage:
            return 0
        c1 = self.class1.get(left, 0)
        c2 = self.class2.get(right, 0)
        if c1 >= len(self.matrix) or c2 >= len(self.matrix[c1]):
            return 0
        return self.matrix[c1][c2]


def _read_pair_pos(r: Reader, base: int, off: int):
    """读一个 PairPos 子表。``off`` 是子表相对 ``base`` 的偏移。

    所有子表内部偏移都相对子表自身，所以先算好 ``here``，读偏移量的时候
    绝不能先跳去解析覆盖表——游标是共享的。
    """
    here = base + off
    r.seek(here)
    fmt = r.u16()
    cov_off = r.u16()
    vf1 = r.u16()
    vf2 = r.u16()
    size2 = _value_size(vf2)
    if fmt == 1:
        n = r.u16()
        pair_offsets = [r.u16() for _ in range(n)]
        coverage = _coverage(r, here + cov_off)
        pairs: Dict[int, Dict[int, int]] = {}
        for left_gid, rel in zip(list(coverage.keys()), pair_offsets):
            r.seek(here + rel)
            count = r.u16()
            row: Dict[int, int] = {}
            for _ in range(count):
                second = r.u16()
                _, _, xadv, _ = _read_value(r, vf1)
                if size2:
                    r.skip(size2)
                if xadv:
                    row[second] = xadv
            if row:
                pairs[left_gid] = row
        return _PairPos1(coverage, pairs, vf1, vf2)
    if fmt == 2:
        cd1 = r.u16()
        cd2 = r.u16()
        n1 = r.u16()
        n2 = r.u16()
        matrix_pos = r.pos
        coverage = _coverage(r, here + cov_off)
        class1 = _class_def(r, here + cd1)
        class2 = _class_def(r, here + cd2)
        r.seek(matrix_pos)
        matrix: List[List[int]] = []
        for _ in range(n1):
            row = []
            for _ in range(n2):
                _, _, xadv, _ = _read_value(r, vf1)
                if size2:
                    r.skip(size2)
                row.append(xadv)
            matrix.append(row)
        return _PairPos2(coverage, class1, class2, matrix, vf1, vf2)
    return None


class GposKern:
    """按字体顺序累积 GPOS kerning。"""

    __slots__ = ("pair_pos",)

    def __init__(self, pair_pos):
        self.pair_pos = pair_pos

    def __bool__(self) -> bool:
        return bool(self.pair_pos)

    def xadvance(self, left: int, right: int) -> int:
        total = 0
        for pp in self.pair_pos:
            total += pp.xadvance(left, right)
        return total


def load_kern_lookups(data: bytes, base: int, end: int,
                      tags: Tuple[str, ...] = ("kern",)) -> Optional[GposKern]:
    """从 GPOS 表里挑出 pair positioning 查找，串成一个 kerning 对象。"""
    r = Reader(data, base, end)
    version = r.u16()
    r.u16()
    script_list = base + r.u16()
    feature_list = base + r.u16()
    lookup_list = base + r.u16()
    if version not in (1,):
        return None

    # --- 找到 'latn'（或第一个）脚本下的默认 LangSys
    r.seek(script_list)
    script_count = r.u16()
    script_offsets: Dict[str, int] = {}
    for _ in range(script_count):
        tag = r.tag()
        script_offsets[tag] = script_list + r.u16()
    script = script_offsets.get("latn") or script_offsets.get("DFLT")
    feature_indices: List[int] = []
    if script is not None:
        r.seek(script)
        default_off = r.u16()                      # defaultLangSys
        lang_count = r.u16()
        r.skip(6 * lang_count)
        if default_off:
            r.seek(script + default_off)
            r.u16()                                # lookupOrder
            r.u16()                                # reqFeatureIndex
            n = r.u16()
            feature_indices = [r.u16() for _ in range(n)]
    wanted_features = set(feature_indices)

    # --- 收集 kern 特性里的 lookup 序号
    r.seek(feature_list)
    feature_count = r.u16()
    records = []
    for _ in range(feature_count):
        tag = r.tag()
        records.append((tag, feature_list + r.u16()))
    wanted: List[int] = []
    for idx, (tag, off) in enumerate(records):
        if tag not in tags:
            continue
        if wanted_features and idx not in wanted_features:
            continue
        r.seek(off)
        r.u16()                                    # featureParams
        n = r.u16()
        wanted.extend(r.u16() for _ in range(n))

    # --- 读 lookup
    r.seek(lookup_list)
    lookup_count = r.u16()
    lookup_offsets = [lookup_list + r.u16() for _ in range(lookup_count)]
    pair_pos = []
    seen = set()
    for li in wanted:
        if li in seen or li >= len(lookup_offsets):
            continue
        seen.add(li)
        r.seek(lookup_offsets[li])
        lookup_type = r.u16()
        r.u16()                                    # lookupFlag
        sub_count = r.u16()
        subs = [lookup_offsets[li] + r.u16() for _ in range(sub_count)]
        if lookup_type == 9:                       # Extension：套一层壳
            real = []
            for sub in subs:
                r.seek(sub)
                fmt = r.u16()
                if fmt != 1:
                    continue
                inner_type = r.u16()
                delta = r.u32()
                if inner_type == 2:
                    real.append(sub + delta)
            lookup_type = 2
            subs = real
        if lookup_type != 2:
            continue
        for sub in subs:
            try:
                pp = _read_pair_pos(r, 0, sub)
            except FontError:
                pp = None
            if pp is not None:
                pair_pos.append(pp)
    return GposKern(pair_pos) if pair_pos else None
