#!/usr/bin/env python3
"""一次生成 docs/ 里的全部示例图。

    python run_demos.py            # 全部
    python run_demos.py --only compare
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typesmith.compare import compare_figure
from typesmith.console import c, force_utf8, human, rule
from typesmith.document import BlockStyle, PageSpec, Paginator, parse_markup
from typesmith.font import Font
from typesmith.png import encode_png
from typesmith.render import Renderer
from typesmith.service import FontBook, build_document
from typesmith.specimen import specimen
from typesmith.svg import document_svg
from typesmith.system import pick_defaults

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
SAMPLE = os.path.join(HERE, "examples", "article.md")

COMPARE_TEXT = (
    "Typography is the craft of endowing human language with a durable visual "
    "form, and thus with an independent existence. Its heartwood is calligraphy. "
    "It is a book art, a poster art, a sign, a signal. The typographer works "
    "with a set of inherited shapes and a few rules about how they may be "
    "arranged, and out of that narrow vocabulary builds something that either "
    "holds the eye or lets it slide away."
)


def write(path: str, blob: bytes) -> str:
    with open(path, "wb") as fh:
        fh.write(blob)
    return path


def demo_specimen(book: FontBook) -> list:
    sans = book.get("sans")
    canvas, stats = specimen(sans, book.get("sans_bold"),
                             book.get("serif") or sans, book.get("mono"),
                             book.get("cjk"), 900, 1180)
    path = write(os.path.join(DOCS, "01-specimen.png"),
                 encode_png(canvas.width, canvas.height, bytes(canvas.pixels)))
    print("  样张        " + c(path, "green")
          + c(f"   {len(stats['kern'])} 组字距 · 正文 {stats['body_lines']} 行 · "
              f"网格 {stats['grid']}", "grey"))
    return [path]


def demo_compare(book: FontBook) -> list:
    font = book.get("serif") or book.get("sans")
    canvas, stats = compare_figure(COMPARE_TEXT, font, 15, 380, cjk=book.get("cjk"))
    path = write(os.path.join(DOCS, "02-compare.png"),
                 encode_png(canvas.width, canvas.height, bytes(canvas.pixels)))
    g, k = stats["greedy"], stats["knuth"]
    print("  对照        " + c(path, "green")
          + c(f"   贪心 {g['demerits']:,.0f} → K–P {k['demerits']:,.0f} "
              f"demerits（{stats['verdict']}）", "grey"))
    return [path]


def demo_pages(book: FontBook) -> list:
    text = open(SAMPLE, encoding="utf-8").read()
    doc, stats = build_document(text, book, size=15, title="TypeSmith")
    renderer = Renderer(doc)
    out = []
    for idx in range(len(doc.pages)):
        bmp = renderer.page_bitmap(doc.pages[idx])
        out.append(write(os.path.join(DOCS, f"03-page{idx + 1}.png"),
                         encode_png(bmp.width, bmp.height, bytes(bmp.pixels))))
    svg = os.path.join(DOCS, "03-page1.svg")
    with open(svg, "w", encoding="utf-8") as fh:
        fh.write(document_svg(doc))
    out.append(svg)
    print("  分页        " + c(f"{len(doc.pages)} 页 · {stats['lines']} 行", "green")
          + c(f"   {out[0]} …（另存 SVG）", "grey"))
    return out


def demo_glyphs(book: FontBook) -> list:
    """把一款字体的 ASCII 全部放大画成一张表，检查轮廓与栅格化。"""
    font = book.get("serif") or book.get("sans")
    from typesmith.png import write_png  # noqa: F401  (保持依赖显式)
    from typesmith.raster import Bitmap, GlyphMasker

    cols, cell = 16, 64
    chars = [chr(c) for c in range(0x21, 0x7F)]
    rows = (len(chars) + cols - 1) // cols
    width, height = cols * cell, rows * cell + 64
    canvas = Bitmap(width, height, (255, 255, 255))
    masker = GlyphMasker(font, 36)
    for idx, ch in enumerate(chars):
        gid = font.glyph_id(ord(ch))
        if not gid:
            continue
        cx = (idx % cols) * cell
        cy = (idx // cols) * cell
        canvas.fill_rect(cx, cy, cell - 1, cell - 1, (246, 245, 242))
        masker.draw(canvas, gid, cx + (cell - font.glyph(gid).advance
                                       * 36 / font.units_per_em) / 2, cy + 46,
                    (20, 20, 20))
        canvas.fill_rect(cx, cy + cell - 6, cell - 1, 1, (222, 219, 214))
    path = write(os.path.join(DOCS, "04-glyphs.png"),
                 encode_png(canvas.width, canvas.height, bytes(canvas.pixels)))
    print("  字形表      " + c(path, "green")
          + c(f"   {len(chars)} 个字符 @ 36 px · {font.full_name}", "grey"))
    return [path]


DEMOS = {
    "specimen": demo_specimen,
    "compare": demo_compare,
    "pages": demo_pages,
    "glyphs": demo_glyphs,
}


def main(argv=None) -> int:
    force_utf8()
    parser = argparse.ArgumentParser(description="生成 TypeSmith 的示例图")
    parser.add_argument("--only", action="append", choices=sorted(DEMOS),
                        help="只跑其中一个（可重复）")
    args = parser.parse_args(argv)

    os.makedirs(DOCS, exist_ok=True)
    book = FontBook()
    if book.get("sans") is None:
        print(c("系统里没有找到任何字体，先跑 `python run.py fonts` 看看", "red"))
        return 1

    print(c("TypeSmith", "bold") + c("  生成示例图", "grey"))
    print(rule())
    roles = " · ".join(f"{r['role']}={r['family']}" for r in book.listing())
    print(c("  字体  " + roles, "grey"))
    print()

    names = args.only or list(DEMOS)
    total = 0
    t0 = time.time()
    for name in names:
        start = time.time()
        paths = DEMOS[name](book)
        total += len(paths)
        size = sum(os.path.getsize(p) for p in paths)
        print(c(f"  用时 {(time.time() - start) * 1000:.0f} ms · {human(size)}B", "grey"))
    print()
    print(c(f"完成：{total} 个文件，总耗时 {(time.time() - t0):.1f} s", "green", "bold"))
    print(c(f"输出目录：{DOCS}", "grey"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
