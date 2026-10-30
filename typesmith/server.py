"""本地 HTTP 工作台。

只用标准库的 ``http.server``：没有 Flask，没有模板引擎，前端就是一个 HTML
文件加一个 JS 文件。所有重活都在服务端做完（PNG 由同一套代码生成），
浏览器只负责显示和收集参数——这样"网页里看到的"和"命令行导出的"完全一致。

    GET  /                    工作台页面
    GET  /static/<file>       前端资源
    GET  /api/fonts           角色 → 字体，以及系统里扫到的字体清单
    GET  /api/info?path=...   单款字体的表结构与度量
    POST /api/layout          断行结果（每行的 ratio / badness / 文本）
    POST /api/render          PNG，参数见解析函数
    POST /api/render.svg      矢量页
    POST /api/specimen        样张 PNG
    POST /api/compare         断行对照 PNG
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__
from .binary import FontError
from .compare import compare_figure
from .document import BlockStyle, PageSpec, Paginator, parse_markup
from .font import Font
from .layout import LayoutOptions, break_lines, greedy_break, itemize, total_demerits
from .png import encode_png
from .render import Renderer
from .service import (DEFAULT_PAGE, FontBook, build_document, page_stats,
                      svg_for)
from .specimen import specimen
from .system import pick_defaults, scan

__all__ = ["serve", "make_server"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")

DEFAULT_TEXT = (
    "Typographic quality is mostly invisible. Nobody notices a page that breaks "
    "well, but everybody feels a page that breaks badly: a line stretched until "
    "the words float apart, a paragraph with a single orphan word at the top, a "
    "column where one gap is three times wider than its neighbours.\n\n"
    "# 断行不是把字塞进框里\n\n"
    "汉字之间没有空格，断行只能落在字与字之间；标点不能出现在行首，前引号不能"
    "留在行尾。TypeSmith 把这些规则做成字符集合，在生成段落项流时就把不合法的"
    "断点抹掉，而不是先断行再回退修补。\n\n"
    "Knuth–Plass 把整段当成一张图：每个可行断点是节点，行内胶的伸缩量是边的代价，"
    "求一次最短路就得到全局最省的一组断点。代价函数是 badness = 100·|ratio|³，"
    "再加上松紧等级跳变与连字符的惩罚。"
)


# ------------------------------------------------------------------ 工具


def _num(data: Dict[str, Any], key: str, default: float,
         lo: Optional[float] = None, hi: Optional[float] = None) -> float:
    try:
        value = float(data.get(key, default))
    except (TypeError, ValueError):
        return default
    if value != value:                     # NaN
        return default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _str(data: Dict[str, Any], key: str, default: str = "", limit: int = 20000) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        return default
    return value[:limit]


class Bench:
    """把"参数 → 结果"的缓存收在一处。

    样张和对照图是纯函数，参数不变就没必要重画——前端拖滑块时这个缓存让
    交互保持"跟着手走"的手感。
    """

    def __init__(self, paths: Optional[Dict[str, Optional[str]]] = None):
        self.book = FontBook(paths or pick_defaults())
        self._cache: Dict[str, bytes] = {}
        self._lock = threading.Lock()
        self._fonts: Optional[list] = None

    # -- 字体
    def fonts(self) -> list:
        if self._fonts is None:
            self._fonts = []
            for path in scan()[:60]:
                try:
                    font = Font(path, 0)
                except Exception:
                    continue
                self._fonts.append({"path": path, "family": font.family,
                                    "style": font.style, "glyphs": font.num_glyphs,
                                    "upem": font.units_per_em,
                                    "kern": len(font.kern)})
        return self._fonts

    def add_font(self, path: str) -> bool:
        """把用户选的字体挂到 serif 角色上（工作台里"换一款字体看效果"）。

        同一款字体会被每个请求带上，所以这里必须先比对——否则每次请求都清空
        字体缓存与图片缓存，拖滑块会从"跟着手走"变成"一顿一顿"。
        """
        current = self.book.paths.get("serif")
        if current and os.path.abspath(current) == os.path.abspath(path):
            return True
        if not os.path.isfile(path):
            return False
        try:
            Font(path)
        except Exception:
            return False
        self.book.paths["serif"] = path
        self.book.paths["serif_bold"] = path
        self.book.reset()
        self.invalidate()
        return True

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    # -- 渲染
    def _remember(self, key: str, build) -> bytes:
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        blob = build()
        with self._lock:
            if len(self._cache) > 48:
                self._cache.clear()
            self._cache[key] = blob
        return blob

    def _params(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "text": _str(body, "text", DEFAULT_TEXT) or DEFAULT_TEXT,
            "size": _num(body, "size", 15, 6, 120),
            "leading": _num(body, "leading", 1.6, 0.8, 3.0),
            "margin": _num(body, "margin", 84, 20, 220),
            "measure": _num(body, "measure", 0, 0, 4000) or None,
            "align": "left" if _str(body, "align", "justify") == "left" else "justify",
            "role": _str(body, "role", "serif", 24),
            "page": int(_num(body, "page", 0, 0, 999)),
            "width": int(_num(body, "pageWidth", DEFAULT_PAGE[0], 200, 4000)),
            "height": int(_num(body, "pageHeight", DEFAULT_PAGE[1], 200, 6000)),
        }

    def build(self, body: Dict[str, Any]):
        p = self._params(body)
        if body.get("font"):
            self.add_font(_str(body, "font", "", 400))
        doc, stats = build_document(p["text"], self.book, size=p["size"],
                                    measure=p["measure"], leading=p["leading"],
                                    align=p["align"], page=(p["width"], p["height"]),
                                    margin=p["margin"], body_role=p["role"])
        return doc, stats, p

    def render(self, body: Dict[str, Any]) -> bytes:
        p = self._params(body)
        key = "render|%r" % (p,)
        return self._remember(key, lambda: self._render(body, p))

    def _render(self, body, p: Dict[str, Any]) -> bytes:
        doc, _stats, p = self.build(body)
        index = min(p["page"], max(0, len(doc.pages) - 1))
        bmp = Renderer(doc).page_bitmap(doc.pages[index])
        return encode_png(bmp.width, bmp.height, bytes(bmp.pixels))

    def describe(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """给前端"第几页 / 共几页"用的轻量统计。"""
        doc, stats, p = self.build(body)
        return {
            "pages": len(doc.pages),
            "lines": stats["lines"],
            "chars": stats["chars"],
            "measure": stats["measure"],
            "page": min(p["page"], max(0, len(doc.pages) - 1)),
            "ratios": page_stats(doc, min(p["page"], max(0, len(doc.pages) - 1))),
        }

    def specimen(self, body: Dict[str, Any]) -> bytes:
        width = int(_num(body, "width", 900, 300, 2000))
        height = int(_num(body, "height", 1180, 300, 3000))
        if body.get("font"):
            self.add_font(_str(body, "font", "", 400))
        key = f"specimen|{width}x{height}|{self.book.paths.get('serif')}"
        return self._remember(key, lambda: self._specimen(width, height))

    def _specimen(self, width: int, height: int) -> bytes:
        sans = self.book.get("sans")
        if sans is None:
            raise FontError("系统里没有找到任何可用字体")
        canvas, _ = specimen(sans, self.book.get("sans_bold"),
                             self.book.get("serif") or sans,
                             self.book.get("mono"), self.book.get("cjk"),
                             width, height)
        return encode_png(canvas.width, canvas.height, bytes(canvas.pixels))

    def compare(self, body: Dict[str, Any]) -> bytes:
        text = _str(body, "text", "")[:800] or DEFAULT_TEXT.split("\n")[0]
        size = _num(body, "size", 15, 7, 40)
        measure = _num(body, "measure", 380, 120, 900)
        if body.get("font"):
            self.add_font(_str(body, "font", "", 400))
        key = f"compare|{size}|{measure}|{text}|{self.book.paths.get('serif')}"
        return self._remember(key, lambda: self._compare(text, size, measure))

    def _compare(self, text: str, size: float, measure: float) -> bytes:
        font = self.book.get("serif") or self.book.get("sans")
        if font is None:
            raise FontError("系统里没有找到任何可用字体")
        canvas, _ = compare_figure(text, font, size, measure,
                                   cjk=self.book.get("cjk"))
        return encode_png(canvas.width, canvas.height, bytes(canvas.pixels))

    def layout(self, body: Dict[str, Any]) -> Dict[str, Any]:
        text = _str(body, "text", "") or DEFAULT_TEXT
        size = _num(body, "size", 15, 6, 120)
        measure = _num(body, "measure", 380, 60, 4000)
        leading = _num(body, "leading", 1.6, 0.8, 3.0)
        tolerance = _num(body, "tolerance", 4.0, 0.1, 40.0)
        role = _str(body, "role", "serif", 24)
        if body.get("font"):
            self.add_font(_str(body, "font", "", 400))
        fonts = self.book.chain(role)
        if not fonts:
            raise FontError("系统里没有找到任何可用字体")
        opts = LayoutOptions(size=size, leading=leading, measure=measure,
                             align="justify", tolerance=tolerance)
        items = itemize(text.replace("\n", " "), fonts, opts)
        lines = break_lines(items, measure, opts)
        greedy = greedy_break(items, measure, opts)
        return {
            "font": fonts[0].full_name,
            "measure": measure,
            "lines": [{"i": i + 1, "text": ln.text.strip(), "ratio": round(ln.ratio, 3),
                       "badness": round(min(ln.badness, 10000.0), 1),
                       "width": round(ln.natural, 1), "fitness": ln.fitness}
                      for i, ln in enumerate(lines)],
            "totals": {
                "lines": len(lines),
                "demerits": round(total_demerits(lines, opts), 1),
                "greedy_demerits": round(total_demerits(greedy, opts), 1),
                "max_ratio": round(max((abs(l.ratio) for l in lines), default=0), 3),
                "loose": sum(1 for l in lines if l.badness > 500),
            },
        }

    def svg(self, body: Dict[str, Any]) -> str:
        text = _str(body, "text", "") or DEFAULT_TEXT
        size = _num(body, "size", 15, 6, 120)
        margin = _num(body, "margin", 84, 20, 220)
        if body.get("font"):
            self.add_font(_str(body, "font", "", 400))
        doc, _ = build_document(text, self.book, size=size, margin=margin,
                                measure=_num(body, "measure", 0, 0, 4000) or None)
        return svg_for(doc)


# ------------------------------------------------------------------ HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = f"TypeSmith/{__version__}"
    protocol_version = "HTTP/1.1"

    bench: Bench = None                       # 由 serve() 注入

    # -- 输出
    def _send(self, status: int, body: bytes, ctype: str = "application/octet-stream",
              extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, exc: Exception, status: int = 400) -> None:
        self._json({"error": str(exc), "type": type(exc).__name__}, status)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(min(length, 4 * 1024 * 1024))
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype:
            try:
                data = json.loads(raw.decode("utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        parsed = parse_qs(raw.decode("utf-8", "replace"))
        return {k: v[0] for k, v in parsed.items() if v}

    # -- 路由
    def do_GET(self) -> None:                      # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/fonts":
                return self._json(self._fonts_payload())
            if path == "/api/info":
                return self._json(self._info_payload(parse_qs(parsed.query)))
            if path == "/api/health":
                return self._json({"ok": True, "version": __version__})
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            return self._json({"error": "not found", "path": path}, 404)
        except Exception as exc:                   # pragma: no cover - 兜底
            traceback.print_exc()
            return self._error(exc, 500)

    def do_POST(self) -> None:                     # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/doc":
                return self._json(self.bench.describe(body))
            if path == "/api/layout":
                return self._json(self.bench.layout(body))
            if path == "/api/render":
                return self._send(200, self.bench.render(body), "image/png")
            if path == "/api/specimen":
                return self._send(200, self.bench.specimen(body), "image/png")
            if path == "/api/compare":
                return self._send(200, self.bench.compare(body), "image/png")
            if path == "/api/render.svg":
                return self._send(200, self.bench.svg(body).encode("utf-8"),
                                  "image/svg+xml; charset=utf-8")
            return self._json({"error": "not found", "path": path}, 404)
        except FontError as exc:
            return self._error(exc, 422)
        except Exception as exc:                   # pragma: no cover - 兜底
            traceback.print_exc()
            return self._error(exc, 500)

    do_HEAD = do_GET

    # -- 具体
    def _static(self, name: str) -> None:
        safe = os.path.normpath(name).lstrip("\\/")
        full = os.path.join(WEB_DIR, safe)
        if not os.path.abspath(full).startswith(os.path.abspath(WEB_DIR)) \
                or not os.path.isfile(full):
            return self._json({"error": "not found", "file": safe}, 404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "image/svg+xml"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            return self._send(200, fh.read(), ctype)

    def _fonts_payload(self) -> Dict[str, Any]:
        return {
            "roles": self.bench.book.listing(),
            "fonts": self.bench.fonts(),
            "version": __version__,
        }

    def _info_payload(self, query: Dict[str, list]) -> Dict[str, Any]:
        want = (query.get("path") or [""])[0]
        allowed = {f["path"] for f in self.bench.fonts()}
        for role in self.bench.book.paths.values():
            if role:
                allowed.add(os.path.abspath(role))
        if want not in allowed:
            raise FontError("只允许查看系统字体目录里扫到的字体")
        font = Font(want, int(_num({"i": (query.get("index") or [0])[0]}, "i", 0)))
        return font.info()

    def log_message(self, fmt: str, *args) -> None:      # 安静一点
        if os.environ.get("TYPESMITH_VERBOSE"):
            super().log_message(fmt, *args)


def make_server(host: str = "127.0.0.1", port: int = 8790,
                font_paths: Optional[Dict[str, Optional[str]]] = None
                ) -> ThreadingHTTPServer:
    Handler.bench = Bench(font_paths)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def serve(host: str = "127.0.0.1", port: int = 8790, open_browser: bool = True,
          font_paths: Optional[Dict[str, Optional[str]]] = None) -> int:
    from .console import c, force_utf8
    force_utf8()
    httpd = make_server(host, port, font_paths)
    url = f"http://{host}:{port}/"
    print(c("TypeSmith 工作台", "bold") + c(f"  {__version__}", "grey"))
    print("  " + c(url, "cyan"))
    print(c("  Ctrl+C 停止", "grey"))
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(c("\n已停止", "grey"))
    finally:
        httpd.server_close()
    return 0
