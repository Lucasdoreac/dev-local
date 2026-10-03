#!/usr/bin/env python3
"""Serve a built SPA (build/client) with the index.html fallback for client routes.

Used by ``E2E_WEB_MODE=static ./run-tests.sh e2e``: the Vite dev server plus Chrome do not fit the
4 GB Colima VM (the renderer times out), a static server is nearly free. Set CSP to send a
Content-Security-Policy header (to rehearse a policy); /__csp accepts violation reports.

    python serve-static.py [root=/site] [port=3000]
"""
import http.server
import mimetypes
import os
import sys

ROOT = os.path.realpath(sys.argv[1] if len(sys.argv) > 1 else "/site")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
POLICY = os.environ.get("CSP", "")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if POLICY:
            self.send_header("Content-Security-Policy", POLICY)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        full = os.path.realpath(os.path.join(ROOT, path.lstrip("/")))
        if full.startswith(ROOT + os.sep) and os.path.isfile(full):
            with open(full, "rb") as handle:
                return self._send(200, handle.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")
        with open(os.path.join(ROOT, "index.html"), "rb") as handle:
            return self._send(200, handle.read(), "text/html; charset=utf-8")

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
