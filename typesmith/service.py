"""命令行与 HTTP 服务共用的顶层封装。

把"字体角色 → 字体对象"、"文本 + 参数 → 文档"这两件事收在一处，免得命令行
和服务器各写一套、结果对不上。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Tuple

from .compare import compare_figure
from .document import BlockStyle, Document, PageSpec, Paginator, parse_markup
from .font import Font, font_collection
from .layout import LayoutOptions, layout_paragraph
from .png import encode_png
from .render import Renderer, text_width_mixed
from .specimen import specimen
from .svg import document_svg
from .system import pick_defaults, scan

__all__ = ["FontBook", "build_document", "render_png_bytes", "page_stats",
           "DEFAULT_PAGE"]


DEFAULT_PAGE = (900, 1180)


class FontBook:
    """按角色持有字体，并按需要补上中文回退。"""

    def __init__(self, paths: Optional[Dict[str, Optional[str]]] = None):
        self.paths = dict(paths or pick_defaults())
        self._cache: Dict[str, Font] = {}
        self._loaded: Dict[str, Optional[Font]] = {}
        self._lock = threading.Lock()

    def get(self, role: str) -> Optional[Font]:
        if role in self._loaded:
            return self._loaded[role]
        with self._lock:
            path = self.paths.get(role)
            font = None
            if path:
                key = os.path.abspath(path)
                if key not in self._cache:
                    try:
                        self._cache[key] = Font(key)
                    except Exception:
                        self._cache[key] = None   # type: ignore[assignment]
                font = self._cache.get(key)
            self._loaded[role] = font
            return font

    def reset(self) -> None:
        """角色指向的路径被改过之后，丢掉缓存重新加载。"""
        with self._lock:
            self._loaded.clear()
            self._cache.clear()

    def chain(self, *roles: str) -> List[Font]:
        out: List[Font] = []
        for role in roles:
            f = self.get(role)
            if f is not None and f not in out:
                out.append(f)
        cjk = self.get("cjk")
        if cjk is not None and cjk not in out:
            out.append(cjk)
        return out

    def listing(self) -> List[Dict[str, object]]:
        out = []
        for role in ("sans", "sans_bold", "serif", "serif_bold", "mono", "cjk"):
            f = self.get(role)
            if f is None:
                continue
            out.append({"role": role, "family": f.family, "style": f.style,
                        "full_name": f.full_name, "path": self.paths.get(role),
                        "glyphs": f.num_glyphs, "units_per_em": f.units_per_em})
        return out


def build_document(text: str, book: FontBook, size: float = 15.0,
                   measure: Optional[float] = None, leading: float = 1.6,
                   align: str = "justify", page: Tuple[int, int] = DEFAULT_PAGE,
                   margin: float = 84.0, body_role: str = "serif",
                   heading_role: str = "sans_bold", title: str = "") -> Tuple[Document, Dict[str, object]]:
    width, height = page
    body_font = book.get(body_role) or book.get("sans")
    heading_font = book.get(heading_role) or body_font
    chain = book.chain(body_role)

    # measure 比"去掉页边距后的宽度"窄时，把版心居中——排版里改行宽就是改版心，
    # 不是把文字挤在左边、右边留一条空白。
    avail = width - 2 * margin
    measure = avail if measure is None else max(80.0, min(float(measure), avail))
    side = (width - measure) / 2.0
    spec = PageSpec(width=width, height=height,
                    margin_top=margin * 0.9, margin_bottom=margin * 0.9,
                    margin_left=side, margin_right=side,
                    header=title, footer=True)

    base = BlockStyle(font=body_font, size=size, leading=leading, align=align,
                      space_after=size * 0.62)
    blocks = parse_markup(text, base, heading_font)
    t0 = time.time()
    doc = Paginator(spec, base, mono=book.get("mono")).layout(blocks, chain)
    stats = {
        "pages": len(doc.pages),
        "lines": doc.line_count,
        "blocks": len(blocks),
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        "measure": round(spec.content_width, 1),
        "chars": len(text),
    }
    return doc, stats


def render_png_bytes(doc: Document, page: int = 0) -> bytes:
    renderer = Renderer(doc)
    bmp = renderer.page_bitmap(doc.pages[page])
    return encode_png(bmp.width, bmp.height, bytes(bmp.pixels))


def page_stats(doc: Document, page: int = 0) -> List[Dict[str, object]]:
    """每行的松紧程度，给前端画柱状图。"""
    out = []
    for pl in doc.pages[page].lines:
        out.append({
            "text": pl.text,
            "ratio": round(pl.line.ratio, 3),
            "badness": round(min(pl.line.badness, 10000.0), 1),
            "width": round(pl.line.natural, 1),
            "fitness": pl.line.fitness,
        })
    return out


def svg_for(doc: Document) -> str:
    return document_svg(doc)


def make_specimen(book: FontBook, width: int = 900, height: int = 1180):
    sans = book.get("sans")
    return specimen(sans, book.get("sans_bold"), book.get("serif") or sans,
                    book.get("mono"), book.get("cjk"), width, height)


def make_compare(book: FontBook, text: str, size: float, measure: float):
    font = book.get("serif") or book.get("sans")
    return compare_figure(text, font, size, measure, cjk=book.get("cjk"))


def system_fonts(limit: int = 40) -> List[Dict[str, object]]:
    out = []
    for path in scan()[:limit]:
        try:
            for font in font_collection(path)[:1]:
                out.append({"path": path, "family": font.family, "style": font.style,
                            "glyphs": font.num_glyphs, "units_per_em": font.units_per_em,
                            "kern": len(font.kern)})
        except Exception:
            continue
    return out
