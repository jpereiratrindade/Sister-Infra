#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-gateway"


def component(
    component_id: str,
    host: str,
    public_port: int | None,
    runtime_port: int,
    health_path: str,
) -> dict:
    gateway = {"host": host}
    if public_port is not None:
        gateway["port"] = public_port

    return {
        "component_id": component_id,
        "gateway": gateway,
        "probe": {
            "health_path": health_path,
        },
        "runtime": {
            "transport": "tcp",
            "listen": "127.0.0.1",
            "port": runtime_port,
        },
    }


def render(
    document: dict,
    *,
    listen_address: str,
    listen_port: int | None = None,
    tls_pem: str | None = None,
) -> str:
    with tempfile.TemporaryDirectory(
        prefix="sister-public-exploration-"
    ) as temporary:
        deployment = Path(temporary) / "resolved.json"
        deployment.write_text(
            json.dumps(document),
            encoding="utf-8",
        )

        command = [
            sys.executable,
            str(CLI),
            "render",
            str(deployment),
            "--listen-address",
            listen_address,
        ]

        if listen_port is not None:
            command.extend(["--listen-port", str(listen_port)])

        if tls_pem is not None:
            command.extend(["--tls-pem", tls_pem])

        result = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout


components_ip_ports = [
    component("sister", "sister.test", 8000, 8000, "/api/health"),
    component("nexo", "nexo.test", 8015, 8015, "/api/health"),
    component("praxis", "praxis.test", 8093, 8093, "/health"),
    component("urt", "urt.test", 8094, 8094, "/_sister/health"),
    component("atmos", "atmos.test", 8095, 8095, "/_sister/health"),
]

ip_ports_document = {
    "schema": "sister.infra.deployment.resolved/1",
    "status": "READY",
    "gateway": {
        "protocol": "http",
        "exposure": "ip-ports",
    },
    "components": components_ip_ports,
}

ip_ports_output = render(
    ip_ports_document,
    listen_address="10.163.80.176",
)

expected_ip_targets = {
    "sister": 8000,
    "nexo": 8015,
    "praxis": 8093,
    "urt": 8094,
    "atmos": 8095,
}

for component_id, public_port in expected_ip_targets.items():
    route = f"/_sister/open/{component_id}"
    location = f"http://10.163.80.176:{public_port}/"

    if route not in ip_ports_output:
        raise SystemExit(
            f"FAIL: missing ip-ports navigation route: {route}"
        )

    if location not in ip_ports_output:
        raise SystemExit(
            f"FAIL: missing ip-ports public target: {location}"
        )


components_host = [
    component("sister", "sister.example.test", None, 8000, "/api/health"),
    component("nexo", "nexo.example.test", None, 8015, "/api/health"),
    component("praxis", "praxis.example.test", None, 8093, "/health"),
    component("urt", "urt.example.test", None, 8094, "/_sister/health"),
    component("atmos", "atmos.example.test", None, 8095, "/_sister/health"),
]

host_document = {
    "schema": "sister.infra.deployment.resolved/1",
    "status": "READY",
    "gateway": {
        "protocol": "https",
        "exposure": "host",
    },
    "components": components_host,
}

host_output = render(
    host_document,
    listen_address="127.0.0.1",
    listen_port=8443,
    tls_pem="/tmp/sister-test.pem",
)

expected_host_targets = {
    "sister": "sister.example.test",
    "nexo": "nexo.example.test",
    "praxis": "praxis.example.test",
    "urt": "urt.example.test",
    "atmos": "atmos.example.test",
}

for component_id, host in expected_host_targets.items():
    route = f"/_sister/open/{component_id}"
    location = f"https://{host}:8443/"

    if route not in host_output:
        raise SystemExit(
            f"FAIL: missing host navigation route: {route}"
        )

    if location not in host_output:
        raise SystemExit(
            f"FAIL: missing host public target: {location}"
        )

if "/login" in ip_ports_output or "/login" in host_output:
    raise SystemExit(
        "FAIL: gateway navigation unexpectedly depends on login"
    )

print("public exploration gateway contract ok")
