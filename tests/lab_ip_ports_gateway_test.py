#!/usr/bin/env python3
"""Prova hermética da publicação LAB HTTP/IP sem DNS ou autoridade TLS."""

from __future__ import annotations

import http.client
import http.server
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_GATEWAY = ROOT / "libexec" / "sister-infra" / "runtime-gateway"


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"UP"}\n')

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    haproxy = shutil.which("haproxy") or "/usr/local/sbin/haproxy-3.2.22"
    assert Path(haproxy).is_file(), "HAProxy necessário para o gate LAB ip-ports"

    ports = [free_port(), free_port()]
    servers = [http.server.ThreadingHTTPServer(("127.0.0.1", port), HealthHandler) for port in ports]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()

    with tempfile.TemporaryDirectory(prefix="sister-lab-ip-ports-") as tmp_text:
        tmp = Path(tmp_text)
        resolved = tmp / "resolved.json"
        resolved.write_text(
            json.dumps(
                {
                    "schema": "sister.infra.deployment.resolved/1",
                    "status": "READY",
                    "deployment_id": "lab-ip-ports-test",
                    "candidate_id": "fixture",
                    "composition_id": "fixture",
                    "gateway": {
                        "protocol": "http",
                        "listen": "127.0.0.2",
                        "exposure": "ip-ports",
                    },
                    "components": [
                        {
                            "component_id": component_id,
                            "system_id": f"system_{component_id}",
                            "runtime": {
                                "transport": "tcp",
                                "listen": "127.0.0.1",
                                "port": port,
                            },
                            "probe": {"health_path": "/health"},
                            "gateway": {
                                "host": "127.0.0.2",
                                "port": port,
                                "public_url": f"http://127.0.0.2:{port}",
                            },
                        }
                        for component_id, port in zip(("alpha", "beta"), ports)
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        env = os.environ.copy()
        env.update(
            {
                "SISTER_RESOLVED_DEPLOYMENT_FILE": str(resolved),
                "SISTER_INFRA_RUN_ROOT": str(tmp / "run"),
                "SISTER_WORKSTATION_CONFIG_ROOT": str(tmp / "config-without-tls"),
                "HAPROXY_BIN": str(haproxy),
                "TLS_PEM": str(tmp / "missing.pem"),
                "CA_CERT": str(tmp / "missing-ca.crt"),
            }
        )

        started = subprocess.run(
            [str(RUNTIME_GATEWAY), "up", "--profile", "lan"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        try:
            assert started.returncode == 0, started.stdout + started.stderr
            assert not Path(env["TLS_PEM"]).exists()
            assert not Path(env["CA_CERT"]).exists()
            for port in ports:
                connection = http.client.HTTPConnection("127.0.0.2", port, timeout=3)
                connection.request("GET", "/health")
                response = connection.getresponse()
                response.read()
                connection.close()
                assert response.status == 200
        finally:
            subprocess.run(
                [str(RUNTIME_GATEWAY), "down", "--profile", "lan"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    for server in servers:
        server.shutdown()
        server.server_close()

    production = SourceFileLoader(
        "sister_production_ip_ports_gate", str(ROOT / "bin" / "sister-production")
    ).load_module()
    try:
        production.validate_production_gateway_policy(
            {"gateway": {"protocol": "http", "exposure": "ip-ports"}}
        )
    except production.ProductionError as exc:
        assert exc.code == "PRODUCTION_TLS_REQUIRED"
    else:
        raise AssertionError("produção aceitou indevidamente gateway HTTP/ip-ports")

    production.validate_production_gateway_policy(
        {"gateway": {"protocol": "https", "exposure": "host"}}
    )

    print("[PASS] LAB ip-ports sem TLS/DNS; produção permanece HTTPS/host fail-closed")


if __name__ == "__main__":
    main()
