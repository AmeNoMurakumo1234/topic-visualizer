#!/usr/bin/env python3
"""Proxy survivability: keep-alive + a real listen backlog + thumbnail-sized thumbnails.

Field report #2 (vm-dev-fyibos-newbot, 2026-08-11), verified against source before building:
over a Tailscale HTTPS proxy the board 502'd one script of seven and rendered broken-image
tiles, while loopback was flawless. Two stdlib DEFAULTS were the cause:

- BaseHTTPRequestHandler.protocol_version defaults to HTTP/1.0: no keep-alive, so every
  script/API/thumbnail opens its own TCP connection.
- socketserver.TCPServer.request_queue_size defaults to 5: a listen backlog smaller than one
  browser's parallel-connection count. Loopback connects never queue long enough to matter;
  remote handshakes overlap, the backlog overflows, the proxy turns the refusal into a 502.

And the picker loaded ~31 MB of full-resolution FLUX renders to paint 180px tiles - invisible
on loopback, a timeout storm through a proxy.

HTTP/1.1 PRECONDITION, audited before flipping the switch: with keep-alive, a response that
omits Content-Length HANGS the connection (the client waits for bytes that never end). This
server has exactly two response paths (_json and the static-file block) and both send
Content-Length; the keep-alive test below exercises JSON, static, 404 and image paths over ONE
connection, so a future response path that forgets the header fails here instead of hanging a
real browser.

    python server/test_proxy_hardening.py
"""
from __future__ import annotations

import http.client
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402

PORT = 8998


class ServerDefaultsTests(unittest.TestCase):
    def test_protocol_is_http_1_1(self):
        self.assertEqual(server.Handler.protocol_version, "HTTP/1.1",
                         "HTTP/1.0 = no keep-alive = one TCP handshake per asset")

    def test_listen_backlog_exceeds_a_browser_burst(self):
        self.assertGreaterEqual(server.TopicsServer.request_queue_size, 64,
                                "the stdlib backlog of 5 is smaller than one browser's "
                                "parallel-connection count; remote bursts overflow it and "
                                "a proxy reports the refusal as 502")


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.src = Path(self.tmp.name) / "big.png"
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not importable here; the fallback leg still runs")
        Image.new("RGBA", (1200, 800), (30, 60, 90, 128)).save(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def test_thumbnail_is_generated_cached_and_smaller(self):
        t = server._thumbnail(self.src, 240)
        self.assertIsNotNone(t)
        self.assertTrue(t.exists())
        self.assertLess(t.stat().st_size, self.src.stat().st_size,
                        "a thumbnail bigger than its source is not a thumbnail")
        self.assertEqual(t.suffix, ".webp")
        first_mtime = t.stat().st_mtime_ns
        again = server._thumbnail(self.src, 240)
        self.assertEqual(again, t)
        self.assertEqual(t.stat().st_mtime_ns, first_mtime, "cache was not reused")

    def test_a_replaced_source_regenerates_its_thumbnail(self):
        """Users drop and REPLACE images in backgrounds/ (README contract) - a stale thumb of
        a replaced file would show the OLD image forever, which reads as a caching bug."""
        t = server._thumbnail(self.src, 240)
        from PIL import Image
        time.sleep(0.05)
        Image.new("RGBA", (900, 600), (200, 40, 40, 255)).save(self.src)
        t2 = server._thumbnail(self.src, 240)
        from PIL import Image as I2
        with I2.open(t2) as im:
            px = im.convert("RGBA").getpixel((im.width // 2, im.height // 2))
        self.assertGreater(px[0], 150, "the thumbnail still shows the replaced image")

    def test_width_is_clamped_so_the_cache_cannot_be_spammed(self):
        """?w= is caller-controlled; unbounded values would mint one cache file per distinct
        number. Clamp keeps the cache finite and a giant w from becoming an upscale."""
        t = server._thumbnail(self.src, 999999)
        from PIL import Image
        with Image.open(t) as im:
            self.assertLessEqual(im.width, 640)
        t2 = server._thumbnail(self.src, 1)
        with Image.open(t2) as im:
            self.assertGreaterEqual(im.width, 64)

    def test_no_imaging_library_means_none_not_an_error(self):
        """The report's own constraint: Pillow stays OPTIONAL. Absent, the caller falls back
        to serving the original - current behaviour, degraded, never broken."""
        import unittest.mock as mock
        with mock.patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
            self.assertIsNone(server._thumbnail(self.src, 240))


class KeepAliveOverOneConnectionTests(unittest.TestCase):
    """The behavioural half: several requests of every response SHAPE over ONE connection.
    This is simultaneously the keep-alive proof and the Content-Length tripwire."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = subprocess.Popen(
            [sys.executable, str(HERE / "server.py"),
             "--db", str(Path(cls.tmp.name) / "t.db"), "--port", str(PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=1)
                c.request("GET", "/api/version")
                c.getresponse().read()
                c.close()
                break
            except Exception:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait(timeout=5)
        cls.tmp.cleanup()

    def test_many_mixed_requests_survive_one_connection(self):
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        try:
            # NOTE the slug-detail route answers missing slugs as 200+{"error":...} by contract,
            # so the 404 leg uses the 0.53.0 ghost-project refusal - a genuine 404 body, which
            # also proves that error path keeps the connection alive.
            plan = [("/api/version", 200), ("/api/topics", 200),
                    ("/topics-core.js", 200), ("/topics.css", 200),
                    ("/api/topics/groom?project=ghost-keepalive-check", 404),
                    ("/api/version", 200)]
            for path, want in plan:
                conn.request("GET", path)
                r = conn.getresponse()
                body = r.read()                   # must fully drain to reuse the socket
                self.assertEqual(r.status, want, path)
                self.assertIsNotNone(r.getheader("Content-Length"),
                                     f"{path} omitted Content-Length - under keep-alive "
                                     f"that hangs the connection instead of 'just working'")
        finally:
            conn.close()

    def test_a_backgrounds_thumbnail_rides_the_same_connection(self):
        bg = HERE.parent / "backgrounds"
        pngs = sorted(p for p in bg.glob("*.png")) if bg.is_dir() else []
        if not pngs:
            self.skipTest("no shipped backgrounds to thumbnail")
        name = pngs[0].name
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
        try:
            conn.request("GET", f"/backgrounds/{name}?w=64")
            r = conn.getresponse()
            thumb = r.read()
            self.assertEqual(r.status, 200)
            conn.request("GET", f"/backgrounds/{name}")     # the full original, same socket
            r2 = conn.getresponse()
            full = r2.read()
            self.assertEqual(r2.status, 200)
            try:
                from PIL import Image  # noqa: F401
                self.assertLess(len(thumb), len(full),
                                "?w=64 served the full-size original despite Pillow")
                self.assertEqual(r.getheader("Content-Type"), "image/webp")
            except ImportError:
                self.assertEqual(len(thumb), len(full), "no Pillow -> fallback = original")
        finally:
            conn.close()
            shutil.rmtree(bg / ".thumbs", ignore_errors=True)   # leave the repo clean


if __name__ == "__main__":
    unittest.main(verbosity=2)
