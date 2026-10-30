"""TypeSmith —— 零依赖的字体解析与排版引擎。

整条流水线：

    .ttf/.ttc ──Font──> 字形轮廓 ──outline──> 折线 ──raster──> 覆盖掩膜
                                                                  │
    文本 ──layout(itemize/break_lines)──> 行 ──document──> 页 ──render──> PNG
                                                     └─svg──> 矢量页

最常用的三个入口：

    >>> from typesmith import Font, LayoutOptions, layout_paragraph
    >>> f = Font("C:/Windows/Fonts/arial.ttf")
    >>> f.text_width("AVATAR", 16)
    >>> lines = layout_paragraph("要断行的段落……", [f], LayoutOptions(size=15))

    >>> from typesmith import FontBook, build_document, render_png
    >>> doc, stats = build_document("# 标题\\n\\n正文……", FontBook())
    >>> render_png(doc, "page1.png")
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = [
    "__version__",
    # 字体
    "Font", "Glyph", "FontError", "font_collection", "open_font",
    # 轮廓与栅格
    "flatten", "flatten_glyph", "contour_segments",
    "rasterize", "Bitmap", "GlyphMasker",
    # 断行
    "Box", "Glue", "Penalty", "Line", "LayoutOptions",
    "itemize", "break_lines", "greedy_break", "layout_paragraph",
    "total_demerits",
    # 文档
    "Block", "BlockStyle", "PageSpec", "Page", "PlacedLine",
    "Document", "Paginator", "parse_markup",
    # 输出
    "Renderer", "render_png", "draw_text", "draw_mixed", "text_width",
    "text_width_mixed", "pick_font",
    "encode_png", "write_png", "read_png_size",
    "page_svg", "document_svg", "glyph_path",
    # 顶层封装
    "FontBook", "build_document", "render_png_bytes", "page_stats",
    "svg_for", "make_specimen", "make_compare", "system_fonts",
    # 字体发现
    "font_dirs", "scan", "find_font", "pick_defaults", "DEFAULT_CHAINS",
    # 图
    "specimen", "compare_figure",
]

from .binary import FontError
from .compare import compare_figure
from .document import (Block, BlockStyle, Document, Page, PageSpec, Paginator,
                       PlacedLine, parse_markup)
from .font import Font, Glyph, font_collection, open_font
from .layout import (Box, Glue, LayoutOptions, Line, Penalty, break_lines,
                     greedy_break, itemize, layout_paragraph, total_demerits)
from .outline import contour_segments, flatten, flatten_glyph
from .png import encode_png, read_png_size, write_png
from .raster import Bitmap, GlyphMasker, rasterize
from .render import (Renderer, draw_mixed, draw_text, pick_font, render_png,
                     text_width, text_width_mixed)
from .service import (FontBook, build_document, make_compare, make_specimen,
                      page_stats, render_png_bytes, svg_for, system_fonts)
from .specimen import specimen
from .svg import document_svg, glyph_path, page_svg
from .system import DEFAULT_CHAINS, find as find_font, font_dirs, pick_defaults, scan
