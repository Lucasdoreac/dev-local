#!/usr/bin/env python3
"""Encaminha CONNECT HTTPS do Colima ao PyPI, sem abrir proxy geral.

O Colima deste ambiente só tem saída IPv4, enquanto o host alcança o PyPI
por IPv6. O listener fica preso ao loopback do host e aceita apenas os hosts
de distribuição Python necessários ao runner descartável.
"""
from __future__ import annotations

import select
import socket
import socketserver
import sys

ALLOWED_HOSTS = {"pypi.org", "files.pythonhosted.org", "pypi.python.org"}
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18888


class ProxyHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(10)
        request = self.rfile.readline(8192).decode("ascii", "replace").strip().split()
        if len(request) < 2 or request[0].upper() != "CONNECT":
            self.connection.sendall(b"HTTP/1.1 405 CONNECT required\r\nConnection: close\r\n\r\n")
            return

        try:
            hostname, port_text = request[1].rsplit(":", 1)
            hostname = hostname.strip("[]").lower()
            if hostname not in ALLOWED_HOSTS or int(port_text) != 443:
                self.connection.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return

            while self.rfile.readline(8192) not in (b"\r\n", b"\n", b""):
                pass

            upstream = socket.create_connection((hostname, 443), timeout=10)
            upstream.settimeout(None)
            self.connection.settimeout(None)
            self.connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            sockets = (self.connection, upstream)
            while True:
                readable, _, exceptional = select.select(sockets, (), sockets, 60)
                if exceptional or not readable:
                    return
                for source in readable:
                    payload = source.recv(65536)
                    if not payload:
                        return
                    destination = upstream if source is self.connection else self.connection
                    destination.sendall(payload)
        except (OSError, ValueError):
            try:
                self.connection.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            except OSError:
                pass


class ThreadedProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with ThreadedProxy(("127.0.0.1", PORT), ProxyHandler) as server:
        print(f"PyPI-only CONNECT proxy listening on 127.0.0.1:{PORT}", flush=True)
        server.serve_forever()
