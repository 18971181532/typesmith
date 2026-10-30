"""命令行入口。

    python -m typesmith fonts
    python -m typesmith info C:/Windows/Fonts/arial.ttf
    python -m typesmith specimen --out docs/01-specimen.png
    python -m typesmith layout --text "……" --size 15 --measure 300
    python -m typesmith compare --out docs/02-compare.png
    python -m typesmith render examples/article.md --out-dir out
    python -m typesmith serve --port 8790
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, List, Optional

from . import __version__
from .binary import FontError
from .console import c, force_utf8, human, rule, table
from .document import Paginator, PageSpec, parse_markup, BlockStyle
from .font import Font, font_collection
from .layout import LayoutOptions, break_lines, greedy_break, itemize, total_demerits
from .png import encode_png
from .render import Renderer
from .service import (DEFAULT_PAGE, FontBook, build_document, make_compare,
                      make_specimen, page_stats, svg_for)
from .system import DEFAULT_CHAINS, font_dirs, pick_defaults, scan

SAMPLE_TEXT = (
    "Typographic quality is mostly invisible. Nobody notices a page that breaks "
    "well, but everybody feels a page that breaks badly: a line stretched until "
    "the words float apart, a paragraph with a single orphan word at the top, a "
    "column where one gap is three times wider than its neighbours. TypeSmith "
    "takes the classic Knuth–Plass model seriously — every feasible breakpoint "
    "is kept, badness is a cubic function of the glue ratio, and the whole "
    "paragraph is chosen by total demerits rather than by a greedy scan.\n\n"
    "中文排版另有麻烦。汉字之间没有空格，断行只能落在字与字之间；标点不能出现在"
    "行首，前引号不能留在行尾。这里把这两条规则做成字符集合，在生成段落项流时"
    "就把不合法的断点抹掉，而不是先断行再回退修补——回退修补会把已经算好的最优点"
    "全部作废，整段重新开算。"
)

SAMPLE_SHORT = (
    "Typography is the craft of endowing human language with a durable visual "
    "form, and thus with an independent existence. Its heartwood is calligraphy. "
    "It is a book art, a poster art, a sign, a signal. The typographer works "
    "with a set of inherited shapes and a few rules about how they may be "
    "arranged, and out of that narrow vocabulary builds something that either "
    "holds the eye or lets it slide away."
)


# ---------------------------------------------------------------- 辅助


def _book(args) -> FontBook:
    paths = pick_defaults()
    for role, value in (("sans", getattr(args, "sans", None)),
                        ("serif", getattr(args, "serif", None)),
                        ("mono", getattr(args, "mono", None)),
                        ("cjk", getattr(args, "cjk", None))):
        if value:
            paths[role] = value
    if getattr(args, "serif_bold", None):
        paths["serif_bold"] = args.serif_bold
    if getattr(args, "sans_bold", None):
        paths["sans_bold"] = args.sans_bold
    return FontBook(paths)


def _text(args) -> str:
    if getattr(args, "text_file", None):
        with open(args.text_file, "r", encoding="utf-8") as fh:
            return fh.read()
    if getattr(args, "text", None):
        return args.text
    return SAMPLE_TEXT


def _ensure_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def _ratio_bar(ratio: float, width: int = 12) -> str:
    """把 glue ratio 画成一条以 0 为中心的小条。"""
    if ratio < -1 or ratio > 4:
        return c("!" * width, "red")
    pos = int(round((ratio / 4.0) * width))
    pos = max(0, min(width, pos))
    body = ["·"] * width
    body[pos] = "|"
    s = "".join(body)
    if ratio > 1.6:
        return c(s, "yellow")
    if ratio < -0.25:
        return c(s, "magenta")
    return c(s, "green")


# ---------------------------------------------------------------- 子命令


def cmd_fonts(args) -> int:
    force_utf8()
    dirs = font_dirs()
    print(c("TypeSmith", "bold") + c(f"  {__version__}", "grey")
          + c("   系统字体发现", "grey"))
    print(rule())
    print(c("搜索目录", "bold"))
    for d in dirs:
        print("  " + d)
    if not dirs:
        print(c("  没有找到任何字体目录", "red"))
        return 1

    t0 = time.time()
    paths = scan()
    elapsed = (time.time() - t0) * 1000
    print()
    print(c("找到 ", "bold") + c(str(len(paths)), "cyan", "bold")
          + c(f" 个字体文件，用时 {elapsed:.0f} ms", "grey"))

    defaults = pick_defaults()
    picked = {os.path.abspath(p) for p in defaults.values() if p}
    # 被选中的角色字体排在最前面，否则默认的 Arial 会被 "AGENCYB" 之类挤到屏幕外
    paths.sort(key=lambda p: (os.path.abspath(p) not in picked, p.lower()))
    shown = paths if args.all else paths[:args.limit]

    rows = []
    for path in shown:
        try:
            fonts = font_collection(path)
        except Exception as exc:                       # 损坏的字体不该中断列表
            rows.append([os.path.basename(path), c("解析失败", "red"),
                         "", "", str(exc)[:32]])
            continue
        for font in fonts[:2]:
            mark = c("*", "green", "bold") if os.path.abspath(path) in picked else " "
            rows.append([mark, font.family, font.style, str(font.num_glyphs),
                         str(font.units_per_em), os.path.basename(path)])
    print()
    print(table(rows, headers=["", "家族", "样式", "字形", "upem", "文件"],
                aligns=["left", "left", "left", "right", "right", "left"]))

    if len("".join(shown)) < len("".join(paths)) and not args.all:
        print(c(f"\n… 还有 {len(paths) - len(shown)} 个文件，用 --all 全部列出", "grey"))

    print()
    print(c("默认角色分配", "bold"))
    print(rule(68, "·"))
    for role, path in defaults.items():
        f = None
        if path:
            try:
                f = Font(path)
            except Exception:
                f = None
        label = f"{role:<10}"
        if f is None:
            print(f"  {label} " + c("（缺）", "red"))
        else:
            print(f"  {label} {f.full_name:<28} "
                  + c(os.path.basename(path), "grey"))
    return 0


def cmd_info(args) -> int:
    force_utf8()
    path = args.path
    if not os.path.isfile(path):
        print(c(f"文件不存在：{path}", "red"))
        return 2
    try:
        fonts = font_collection(path)
    except FontError as exc:
        print(c(f"解析失败：{exc}", "red"))
        return 1

    if len(fonts) > 1 and args.index is None:
        print(c(f"{os.path.basename(path)} 是字体集合，共 {len(fonts)} 款：", "bold"))
        rows = [[str(i), f.family, f.style, str(f.num_glyphs)]
                for i, f in enumerate(fonts)]
        print(table(rows, headers=["#", "家族", "样式", "字形"],
                    aligns=["right", "left", "left", "right"]))
        print(c("\n用 --index N 查看其中一款的详情", "grey"))
        return 0

    font = fonts[args.index or 0]
    info = font.info()
    print(c(font.full_name, "bold", "cyan") + c(f"   #{font.index}", "grey"))
    print(rule())
    rows = [
        ["家族", info["family"]],
        ["样式", info["style"]],
        ["字形数", f'{info["glyphs"]:,}'],
        ["unitsPerEm", info["units_per_em"]],
        ["ascent / descent", f'{info["ascent"]} / {info["descent"]}'],
        ["lineGap", info["line_gap"]],
        ["bbox", " ".join(str(v) for v in info["bbox"])],
        ["kern 对数", f'{info["kern_pairs"]:,}'],
        ["GPOS", "有" if info["gpos"] else "无"],
        ["表数量", len(info["tables"])],
    ]
    print(table(rows, aligns=["left", "left"]))
    print()
    print(c("表目录", "bold"))
    line = "  "
    for tag in info["tables"]:
        chunk = tag + "  "
        if len(line) + len(chunk) > 76:
            print(c(line, "grey"))
            line = "  "
        line += chunk
    print(c(line, "grey"))

    text = args.text or "AVATAR To Vo LY fi ffi 0123 — Hello, World!"
    print()
    print(c("宽度实测", "bold") + c(f"   （字号 {args.size}px，upem {font.units_per_em}）", "grey"))
    print(rule(68, "·"))
    rows = []
    for chunk in ("AV", "To", "AVATAR", "Hello", "Hello, World!"):
        w_kern = font.text_width(chunk, args.size, kern=True)
        w_flat = font.text_width(chunk, args.size, kern=False)
        delta = w_kern - w_flat
        rows.append([chunk, f"{w_kern:.2f}", f"{w_flat:.2f}",
                     c(f"{delta:+.2f}", "green" if delta < 0 else "grey")])
    print(table(rows, headers=["文本", "含字距", "不含字距", "差值"],
                aligns=["left", "right", "right", "right"]))

    if args.glyphs:
        print()
        print(c("cmap 抽样", "bold"))
        print(rule(68, "·"))
        rows = []
        for ch in text[:24]:
            gid = font.glyph_id(ord(ch))
            g = font.glyph(gid) if gid else None
            adv = f"{g.advance}" if g else "—"
            box = f"{g.xmin},{g.ymin} {g.xmax},{g.ymax}" if g else "—"
            rows.append([repr(ch), str(ord(ch)), str(gid), adv, box])
        print(table(rows, headers=["字符", "码位", "gid", "advance", "bbox"],
                    aligns=["left", "right", "right", "right", "left"]))
    return 0


def cmd_specimen(args) -> int:
    force_utf8()
    book = _book(args)
    if book.get("sans") is None:
        print(c("没有可用的字体，先跑 `python -m typesmith fonts` 看看", "red"))
        return 1
    t0 = time.time()
    canvas, stats = make_specimen(book, args.width, args.height)
    raw = encode_png(canvas.width, canvas.height, bytes(canvas.pixels))
    _ensure_dir(args.out)
    with open(args.out, "wb") as fh:
        fh.write(raw)
    elapsed = (time.time() - t0) * 1000
    print(c("样张已生成", "green", "bold") + f"  {args.out}")
    print(c(f"  {canvas.width}×{canvas.height}  {human(len(raw))}B  {elapsed:.0f} ms  "
            f"正文字形 {stats.get('body_lines', '—')} 行  "
            f"demerits {stats.get('body_demerits', 0):,.0f}  "
            f"网格 {stats.get('grid', '—')}", "grey"))
    return 0


def cmd_layout(args) -> int:
    force_utf8()
    book = _book(args)
    fonts = book.chain(args.role)
    if not fonts:
        print(c("没有可用的字体", "red"))
        return 1
    text = _text(args).replace("\n", " ").strip()
    opts = LayoutOptions(size=args.size, leading=args.leading, measure=args.measure,
                         align=args.align, tolerance=args.tolerance)
    t0 = time.time()
    items = itemize(text, fonts, opts)
    knuth = break_lines(items, args.measure, opts)
    greedy = greedy_break(items, args.measure, opts)
    elapsed = (time.time() - t0) * 1000

    if not knuth:
        print(c("断不出任何行（measure 太小？）", "red"))
        return 1

    print(c("断行结果", "bold") + c(f"   {fonts[0].family} {args.size}px / "
                                    f"measure {args.measure:g}", "grey"))
    print(rule(78))
    rows = []
    for i, ln in enumerate(knuth, 1):
        rows.append([str(i), f"{ln.natural:7.1f}", f"{ln.ratio:+6.2f}",
                     _ratio_bar(ln.ratio), _fit_label(ln.fitness),
                     ln.text.strip()[:38]])
    print(table(rows, headers=["#", "宽度", "ratio", "松紧", "fitness", "文本"],
                aligns=["right", "right", "right", "left", "left", "left"]))
    print(rule(78))

    dk = total_demerits(knuth, opts)
    dg = total_demerits(greedy, opts)
    worst = max(knuth, key=lambda l: l.ratio)
    print(c("Knuth–Plass ", "bold") + f"{len(knuth)} 行  "
          + c(f"demerits {dk:,.0f}", "cyan") + c(f"  最大 ratio {worst.ratio:+.2f}", "grey"))
    print(c("贪心断行   ", "bold") + f"{len(greedy)} 行  "
          + c(f"demerits {dg:,.0f}", "yellow")
          + c(f"  最大 ratio {max(l.ratio for l in greedy):+.2f}", "grey"))
    if dg > 0:
        drop = (dg - dk) / dg * 100
        print(c(f"总代价降低 {drop:.1f}%", "green", "bold")
              + c(f"   用时 {elapsed:.0f} ms", "grey"))
    return 0


def _fit_label(fitness: int) -> str:
    return {0: "tight", 1: "decent", 2: "loose", 3: "very loose"}.get(fitness, str(fitness))


def cmd_compare(args) -> int:
    force_utf8()
    book = _book(args)
    font = book.get("serif") or book.get("sans")
    if font is None:
        print(c("没有可用的字体", "red"))
        return 1
    text = _text(args) if (args.text or args.text_file) else SAMPLE_SHORT
    t0 = time.time()
    canvas, stats = make_compare(book, text, args.size, args.measure)
    raw = encode_png(canvas.width, canvas.height, bytes(canvas.pixels))
    _ensure_dir(args.out)
    with open(args.out, "wb") as fh:
        fh.write(raw)
    elapsed = (time.time() - t0) * 1000

    print(c("对比图已生成", "green", "bold") + f"  {args.out}")
    print(c(f"  {canvas.width}×{canvas.height}  {human(len(raw))}B  {elapsed:.0f} ms", "grey"))
    print()
    g, k = stats.get("greedy", {}), stats.get("knuth", {})
    rows = [
        ["行数", str(g.get("lines", "—")), str(k.get("lines", "—"))],
        ["总 demerits", f'{g.get("demerits", 0):,.0f}', f'{k.get("demerits", 0):,.0f}'],
        ["最大 ratio", f'{g.get("max_ratio", 0):+.2f}', f'{k.get("max_ratio", 0):+.2f}'],
        ["超松行数", str(g.get("loose", 0)), str(k.get("loose", 0))],
    ]
    print(table(rows, headers=["指标", "贪心", "Knuth–Plass"],
                aligns=["left", "right", "right"]))
    return 0


def cmd_render(args) -> int:
    force_utf8()
    book = _book(args)
    text = _text(args)
    width, height = args.page
    doc, stats = build_document(text, book, size=args.size, measure=args.measure,
                               leading=args.leading, align=args.align,
                               page=(width, height), margin=args.margin,
                               body_role=args.role, title=args.title)
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    renderer = Renderer(doc)
    written: List[str] = []
    pages = range(len(doc.pages)) if args.page_index is None else [args.page_index]
    for idx in pages:
        if idx >= len(doc.pages):
            print(c(f"第 {idx + 1} 页不存在（共 {len(doc.pages)} 页）", "red"))
            return 1
        bmp = renderer.page_bitmap(doc.pages[idx])
        base = os.path.join(out_dir, f"page{idx + 1}")
        with open(base + ".png", "wb") as fh:
            fh.write(encode_png(bmp.width, bmp.height, bytes(bmp.pixels)))
        written.append(base + ".png")
        if args.svg:
            with open(base + ".svg", "w", encoding="utf-8") as fh:
                fh.write(svg_for(doc) if len(doc.pages) == 1
                         else _page_svg(doc, idx))
            written.append(base + ".svg")
    elapsed = (time.time() - t0) * 1000

    print(c("渲染完成", "green", "bold"))
    print(rule())
    rows = [
        ["页数", str(stats["pages"])],
        ["行数", str(stats["lines"])],
        ["字符数", f'{stats["chars"]:,}'],
        ["版心宽度", f'{stats["measure"]:.0f} px'],
        ["排版耗时", f'{stats["elapsed_ms"]:.0f} ms'],
        ["渲染耗时", f"{elapsed:.0f} ms"],
    ]
    print(table(rows, aligns=["left", "right"]))
    print()
    for path in written:
        print("  " + c("→", "green") + " " + path)

    if args.stats:
        print()
        print(c("第 1 页每行松紧", "bold"))
        print(rule(60, "·"))
        for row in page_stats(doc, 0)[:40]:
            print(f'  {row["ratio"]:+6.2f}  {_ratio_bar(row["ratio"], 10)}  '
                  f'{row["text"][:44]}')
    return 0


def _page_svg(doc, index: int) -> str:
    from .svg import page_svg
    return page_svg(doc, index)


def cmd_serve(args) -> int:
    force_utf8()
    from .server import serve
    return serve(host=args.host, port=args.port, open_browser=not args.no_open,
                 font_paths=_book(args).paths)


# ---------------------------------------------------------------- 解析器


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="typesmith",
        description="TypeSmith —— 零依赖的字体解析与排版引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python -m typesmith fonts\n"
               "  python -m typesmith specimen --out docs/01-specimen.png\n"
               "  python -m typesmith layout --text \"A long paragraph…\" --measure 320\n"
               "  python -m typesmith render examples/article.md --out-dir out\n")
    p.add_argument("-V", "--version", action="version", version=f"typesmith {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="命令")

    def add_font_overrides(sp):
        sp.add_argument("--sans", metavar="PATH", help="覆盖无衬线字体")
        sp.add_argument("--sans-bold", metavar="PATH", help="覆盖无衬线粗体")
        sp.add_argument("--serif", metavar="PATH", help="覆盖衬线字体")
        sp.add_argument("--serif-bold", metavar="PATH", help="覆盖衬线粗体")
        sp.add_argument("--mono", metavar="PATH", help="覆盖等宽字体")
        sp.add_argument("--cjk", metavar="PATH", help="覆盖中文回退字体")

    sp = sub.add_parser("fonts", help="列出系统里能找到的字体")
    sp.add_argument("--all", action="store_true", help="列出全部文件")
    sp.add_argument("--limit", type=int, default=24, help="最多显示多少个文件")
    sp.set_defaults(func=cmd_fonts)

    sp = sub.add_parser("info", help="查看一款字体的表结构与度量")
    sp.add_argument("path", help=".ttf / .ttc / .otf 路径")
    sp.add_argument("--index", type=int, default=None, help="TTC 内的序号")
    sp.add_argument("--size", type=float, default=16.0, help="测宽用的字号")
    sp.add_argument("--text", default="", help="抽样文本")
    sp.add_argument("--glyphs", action="store_true", help="附带 cmap 抽样表")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("specimen", help="生成字体样张 PNG")
    sp.add_argument("--out", default="out/specimen.png")
    sp.add_argument("--width", type=int, default=900)
    sp.add_argument("--height", type=int, default=1180)
    add_font_overrides(sp)
    sp.set_defaults(func=cmd_specimen)

    sp = sub.add_parser("layout", help="只做断行，打印每行的松紧")
    sp.add_argument("--text", default="")
    sp.add_argument("--text-file", default=None)
    sp.add_argument("--size", type=float, default=15.0)
    sp.add_argument("--measure", type=float, default=340.0)
    sp.add_argument("--leading", type=float, default=1.6)
    sp.add_argument("--align", default="justify", choices=["justify", "left"])
    sp.add_argument("--tolerance", type=float, default=4.0)
    sp.add_argument("--role", default="serif", help="用哪个角色的字体")
    add_font_overrides(sp)
    sp.set_defaults(func=cmd_layout)

    sp = sub.add_parser("compare", help="贪心断行 vs Knuth–Plass 并排对照图")
    sp.add_argument("--out", default="out/compare.png")
    sp.add_argument("--text", default="")
    sp.add_argument("--text-file", default=None)
    sp.add_argument("--size", type=float, default=15.0)
    sp.add_argument("--measure", type=float, default=380.0)
    add_font_overrides(sp)
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("render", help="把标记文本排成分页文档并导出 PNG/SVG")
    sp.add_argument("input", nargs="?", default=None, help="输入 .md/.txt")
    sp.add_argument("--out-dir", default="out")
    sp.add_argument("--text", default="")
    sp.add_argument("--text-file", default=None)
    sp.add_argument("--size", type=float, default=15.0)
    sp.add_argument("--measure", type=float, default=None)
    sp.add_argument("--leading", type=float, default=1.6)
    sp.add_argument("--margin", type=float, default=84.0)
    sp.add_argument("--align", default="justify", choices=["justify", "left"])
    sp.add_argument("--page", type=int, nargs=2, default=list(DEFAULT_PAGE),
                    metavar=("W", "H"))
    sp.add_argument("--page-index", type=int, default=None, help="只渲染某一页（从 0 起）")
    sp.add_argument("--role", default="serif")
    sp.add_argument("--title", default="")
    sp.add_argument("--svg", action="store_true", help="同时导出矢量 SVG")
    sp.add_argument("--stats", action="store_true", help="打印第 1 页每行松紧")
    add_font_overrides(sp)
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("serve", help="启动本地 HTTP 工作台")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8790)
    sp.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    add_font_overrides(sp)
    sp.set_defaults(func=cmd_serve)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    force_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "input", None) and not args.text_file:
        args.text_file = args.input

    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except FontError as exc:
        print(c(f"字体解析失败：{exc}", "red"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(c("\n已中断", "grey"))
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
