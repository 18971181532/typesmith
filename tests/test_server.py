"""HTTP 工作台：路由、参数校验、路径穿越防护。"""

import json
import threading
import unittest
import urllib.error
import urllib.request

from typesmith.server import make_server
from typesmith.system import pick_defaults

HAVE = any(pick_defaults().values())


@unittest.skipUnless(HAVE, "系统里没有可用字体")
class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = make_server(port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=20) as res:
            return res.status, res.headers.get("Content-Type"), res.read()

    def post(self, path, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url(path), data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.status, res.headers.get("Content-Type"), res.read()

    def test_health(self):
        status, ctype, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertIn("json", ctype)
        self.assertTrue(json.loads(body)["ok"])

    def test_index(self):
        status, ctype, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"TypeSmith", body)

    def test_static(self):
        for name in ("/static/style.css", "/static/app.js"):
            status, ctype, body = self.get(name)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 100)

    def test_static_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/static/../typesmith/font.py")
        self.assertEqual(ctx.exception.code, 404)

    def test_unknown_route(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_fonts(self):
        status, _, body = self.get("/api/fonts")
        data = json.loads(body)
        self.assertIn("roles", data)
        self.assertIn("fonts", data)
        self.assertTrue(data["roles"])
        for row in data["roles"]:
            self.assertGreater(row["glyphs"], 0)

    def test_layout(self):
        status, ctype, body = self.post("/api/layout", {
            "text": "The quick brown fox jumps over the lazy dog. " * 4,
            "size": 15, "measure": 260,
        })
        data = json.loads(body)
        self.assertIn("json", ctype)
        self.assertGreater(data["totals"]["lines"], 1)
        self.assertTrue(data["lines"])
        self.assertIn("ratio", data["lines"][0])
        self.assertLessEqual(data["totals"]["demerits"],
                             data["totals"]["greedy_demerits"] + 1)

    def test_layout_clamps_bad_params(self):
        _, _, body = self.post("/api/layout", {
            "text": "hello world again", "size": "abc", "measure": -5,
            "tolerance": "NaN",
        })
        data = json.loads(body)
        self.assertGreaterEqual(data["measure"], 60)

    def test_render_png(self):
        status, ctype, body = self.post("/api/render", {
            "text": "# T\n\nbody text", "size": 14, "pageWidth": 400,
            "pageHeight": 300, "margin": 40,
        })
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_render_page_out_of_range(self):
        status, _, body = self.post("/api/render", {"text": "one line", "page": 99})
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_doc(self):
        _, _, body = self.post("/api/doc", {
            "text": "para one\n\npara two", "pageWidth": 600, "pageHeight": 400,
            "margin": 40, "size": 14,
        })
        data = json.loads(body)
        self.assertEqual(data["pages"], 1)
        self.assertGreater(data["lines"], 0)

    def test_specimen(self):
        status, ctype, body = self.post("/api/specimen", {"width": 620, "height": 820})
        self.assertEqual(ctype, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_compare(self):
        status, ctype, body = self.post("/api/compare", {
            "text": "The quick brown fox jumps over the lazy dog while the "
                    "typesetter watches the glue ratios creep upward.",
            "size": 14, "measure": 260,
        })
        self.assertEqual(ctype, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_svg(self):
        status, ctype, body = self.post("/api/render.svg", {"text": "hello"})
        self.assertIn("svg", ctype)
        self.assertTrue(body.startswith(b"<svg"))

    def test_caching_returns_same_bytes(self):
        payload = {"text": "same input", "size": 15}
        _, _, first = self.post("/api/specimen", {"width": 600, "height": 800})
        _, _, again = self.post("/api/specimen", {"width": 600, "height": 800})
        self.assertEqual(first, again)
        self.assertTrue(payload)


if __name__ == "__main__":
    unittest.main()
