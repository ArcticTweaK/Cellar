"""Discord alerts with a picture of a background account's screen: the PNG encoder, the screen grab over VNC
(against a tiny fake RFB server) and the upload Discord gets (against a local HTTP server)."""

import http.server
import json
import os
import socket
import struct
import tempfile
import threading
import unittest
import zlib
from pathlib import Path

from cellar import background, webhook


def _frame(w, h):
    """A BGRX test frame: pixel (x, y) = R x, G y, B 200."""
    return bytes(b for y in range(h) for x in range(w) for b in (200, y, x, 0))


def _read_png(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        crc = struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0]
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF, kind
        chunks.setdefault(kind, b"")
        chunks[kind] += body
        pos += 12 + n
    w, h, depth, ctype = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    return w, h, depth, ctype, zlib.decompress(chunks[b"IDAT"])


class Png(unittest.TestCase):
    def test_pixels_survive(self):
        w, h = 7, 5
        width, height, depth, ctype, raw = _read_png(background.encode_png(_frame(w, h), w, h))
        self.assertEqual((width, height, depth, ctype), (7, 5, 8, 2))         # 8-bit RGB
        self.assertEqual(len(raw), h * (1 + w * 3))
        row = 1 + w * 3
        for y in range(h):
            self.assertEqual(raw[y * row], 0)                                # filter: none
            for x in range(w):
                o = y * row + 1 + x * 3
                self.assertEqual(tuple(raw[o:o + 3]), (x, y, 200))


class FakeScreen:
    """Speaks just enough RFB 3.8 (no auth, one raw full-screen update) for VNC + grab_png."""

    def __init__(self, w, h):
        self.dir = tempfile.mkdtemp(prefix="cvnc")                         # short: unix socket paths max 108
        self.vnc = Path(self.dir) / "s"
        self.w, self.h = w, h
        self.srv = socket.socket(socket.AF_UNIX)
        self.srv.bind(str(self.vnc))
        self.srv.listen(1)
        threading.Thread(target=self._serve, daemon=True).start()

    def _rx(self, c, n):
        b = b""
        while len(b) < n:
            b += c.recv(n - len(b))
        return b

    def _serve(self):
        c, _ = self.srv.accept()
        c.sendall(b"RFB 003.008\n")
        self._rx(c, 12)
        c.sendall(bytes([1, 1]))                     # one security type: none
        self._rx(c, 1)
        c.sendall(struct.pack(">I", 0))
        self._rx(c, 1)                               # shared
        c.sendall(struct.pack(">HH", self.w, self.h) + bytes(16) + struct.pack(">I", 4) + b"test")
        self._rx(c, 20 + 8 + 10)                     # SetPixelFormat, SetEncodings (raw), FramebufferUpdateRequest
        c.sendall(struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, self.w, self.h, 0) + _frame(self.w, self.h))
        c.close()

    def close(self):
        self.srv.close()
        os.unlink(self.vnc)
        os.rmdir(self.dir)


class Grab(unittest.TestCase):
    def test_grab_png_from_a_screen(self):
        scr = FakeScreen(16, 9)
        try:
            png = background.grab_png(scr, timeout=3)
        finally:
            scr.close()
        self.assertIsNotNone(png)
        w, h, _, _, raw = _read_png(png)
        self.assertEqual((w, h), (16, 9))
        o = 3 * (1 + 16 * 3) + 1 + 5 * 3                                     # pixel (5, 3)
        self.assertEqual(tuple(raw[o:o + 3]), (5, 3, 200))

    def test_grab_gives_none_when_the_screen_is_gone(self):
        class Gone:
            vnc = Path(tempfile.gettempdir()) / "cellar-test-no-such-socket"
        self.assertIsNone(background.grab_png(Gone(), timeout=1))


class Upload(unittest.TestCase):
    def test_alert_with_picture_is_multipart_with_the_embed_pointing_at_it(self):
        got = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                got["type"] = self.headers["Content-Type"]
                got["body"] = self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        png = background.encode_png(_frame(4, 4), 4, 4)
        err = webhook.post(f"http://127.0.0.1:{srv.server_port}/hook", "Disconnected", "alt2 - kicked (267).",
                           webhook.RED, sync=True, image=png)
        srv.server_close()
        self.assertEqual(err, "")
        self.assertTrue(got["type"].startswith("multipart/form-data"))
        body = got["body"]
        self.assertIn(png, body)
        self.assertIn(b'filename="screen.png"', body)
        start = body.index(b'name="payload_json"')
        payload = body[body.index(b"\r\n\r\n", start) + 4:body.index(b"\r\n--", start)]
        embed = json.loads(payload)["embeds"][0]
        self.assertEqual(embed["image"]["url"], "attachment://screen.png")
        self.assertEqual(embed["title"], "Disconnected")


if __name__ == "__main__":
    unittest.main()
