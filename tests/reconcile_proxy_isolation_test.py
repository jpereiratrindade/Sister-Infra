#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import http.server
import importlib.machinery
import os
from pathlib import Path
import socket
import threading


ROOT = Path(__file__).resolve().parents[1]
RECONCILE = ROOT / "bin" / "sister-reconcile"


def reserve_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}\n')

    def log_message(self, fmt: str, *args: object) -> None:
        pass


class ProxyTrapHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(403)
        self.end_headers()
        self.wfile.write(b"PROXY MUST NOT BE USED\n")

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def start_server(
    address: str,
    port: int,
    handler: type[http.server.BaseHTTPRequestHandler],
) -> http.server.HTTPServer:
    server = http.server.HTTPServer((address, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> None:
    health_port = reserve_port()
    proxy_port = reserve_port()

    health = start_server("127.0.0.1", health_port, HealthHandler)
    proxy = start_server("127.0.0.1", proxy_port, ProxyTrapHandler)

    saved = dict(os.environ)

    try:
        proxy_url = f"http://127.0.0.1:{proxy_port}"

        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["http_proxy"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ["https_proxy"] = proxy_url
        os.environ["ALL_PROXY"] = proxy_url
        os.environ["all_proxy"] = proxy_url

        # Nenhuma ajuda de NO_PROXY: a ferramenta deve ser correta por si.
        os.environ["NO_PROXY"] = ""
        os.environ["no_proxy"] = ""

        loader = importlib.machinery.SourceFileLoader(
            "sister_reconcile_proxy_test",
            str(RECONCILE),
        )
        module = loader.load_module()

        ok, detail = module.probe_runtime_endpoint(
            {
                "transport": "tcp",
                "listen": "127.0.0.1",
                "port": health_port,
            },
            {
                "health_path": "/api/health",
            },
        )

        assert ok, (
            "runtime probe foi afetado pelo proxy ambiental: "
            f"{detail}"
        )
        assert detail == "PASS (HTTP 200)", detail

        print(
            "[PASS] runtime probe ignores ambient HTTP/HTTPS/ALL proxy "
            "configuration"
        )

    finally:
        os.environ.clear()
        os.environ.update(saved)

        health.shutdown()
        health.server_close()
        proxy.shutdown()
        proxy.server_close()


if __name__ == "__main__":
    main()
