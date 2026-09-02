#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-gateway"


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolved() -> dict[str, Any]:
    return {
        "schema": "sister.infra.deployment.resolved/1",
        "status": "READY",
        "deployment_id": "fixture",
        "candidate_id": "wc-fixture",
        "composition_id": "fixture",
        "components": [
            {
                "component_id": "alpha",
                "system_id": "system_alpha",
                "component_path": "components/alpha",
                "runtime": {
                    "transport": "tcp",
                    "listen": "127.0.0.1",
                    "port": 18001,
                },
                "probe": {"health_path": "/health"},
                "gateway": {"host": "alpha-gateway.test"},
            },
            {
                "component_id": "beta",
                "system_id": "system_beta",
                "component_path": "components/beta",
                "runtime": {
                    "transport": "unix",
                    "socket": "/run/user/1000/fixture/beta.sock",
                },
                "probe": {"health_path": "/ready"},
                "gateway": {"host": "beta-gateway.test"},
            },
            {
                "component_id": "internal",
                "system_id": "system_internal",
                "component_path": "components/internal",
                "runtime": {
                    "transport": "tcp",
                    "listen": "127.0.0.1",
                    "port": 18003,
                },
                "probe": {"health_path": "/health"},
            },
        ],
    }


def invoke(path: Path, tls_pem: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(CLI),
            "render",
            str(path),
            "--listen-address",
            "127.0.0.1",
            "--listen-port",
            "18443",
            "--tls-pem",
            str(tls_pem),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> None:
    source = CLI.read_text(encoding="utf-8").lower()
    runtime_source = (
        ROOT / "libexec" / "sister-infra" / "runtime-gateway"
    ).read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "nexo",
        "praxis",
        "urt",
        "__sister_host__",
        "__nexo_host__",
        "__praxis_host__",
        "__urt_host__",
    ):
        assert forbidden not in source, f"renderer contém {forbidden}"

    renderer_start = runtime_source.index("render_gateway() {")
    renderer_end = runtime_source.index("\npid_alive() {", renderer_start)
    infra_renderer = runtime_source[renderer_start:renderer_end].lower()
    for forbidden in ("sister_host", "nexo_host", "praxis_host", "urt_host"):
        assert forbidden not in infra_renderer, (
            f"adapter do renderer contém {forbidden}"
        )

    with tempfile.TemporaryDirectory(
        prefix="sister-gateway-renderer-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        path = tmp / "resolved.json"
        key = tmp / "gateway.key"
        certificate = tmp / "gateway.crt"
        pem = tmp / "gateway.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=fixture.test",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        pem.write_bytes(certificate.read_bytes() + key.read_bytes())

        write_json(path, resolved())
        result = invoke(path, pem)
        assert result.returncode == 0, result.stderr
        config = result.stdout

        assert config.count("\nbackend component_") == 2
        assert "alpha-gateway.test" in config
        assert "beta-gateway.test" in config
        assert "127.0.0.1:18001" in config
        assert "unix@/run/user/1000/fixture/beta.sock" in config
        assert "system_internal" not in config
        assert "18003" not in config
        assert "__" not in config
        assert "deny deny_status 421 unless" in config

        config_path = tmp / "haproxy.cfg"
        config_path.write_text(config, encoding="utf-8")
        haproxy = shutil.which("haproxy")
        if haproxy is None:
            versioned = Path("/usr/local/sbin/haproxy-3.2.22")
            haproxy = str(versioned) if versioned.is_file() else None
        assert haproxy is not None, "HAProxy necessário para validar config"
        validation = subprocess.run(
            [haproxy, "-c", "-f", str(config_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert validation.returncode == 0, (
            validation.stdout + validation.stderr
        )

        ip_ports = {
            "schema": "sister.infra.deployment.resolved/1",
            "status": "READY",
            "deployment_id": "fixture-ip-ports",
            "candidate_id": "wc-fixture",
            "composition_id": "fixture",
            "gateway": {
                "protocol": "http",
                "listen": "192.0.2.10",
                "exposure": "ip-ports",
            },
            "components": [
                {
                    "component_id": "alpha",
                    "system_id": "system_alpha",
                    "component_path": "components/alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 18001},
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "192.0.2.10", "port": 18001, "public_url": "http://192.0.2.10:18001"},
                },
                {
                    "component_id": "beta",
                    "system_id": "system_beta",
                    "component_path": "components/beta",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 18002},
                    "probe": {"health_path": "/ready"},
                    "gateway": {"host": "192.0.2.10", "port": 18002, "public_url": "http://192.0.2.10:18002"},
                },
            ],
        }
        write_json(path, ip_ports)
        rendered_ip_ports = subprocess.run(
            [str(CLI), "render", str(path), "--listen-address", "192.0.2.10"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert rendered_ip_ports.returncode == 0, rendered_ip_ports.stderr
        ip_config = rendered_ip_ports.stdout
        assert "bind 192.0.2.10:18001" in ip_config
        assert "bind 192.0.2.10:18002" in ip_config
        assert " ssl crt " not in ip_config
        assert "deny_status 421" not in ip_config
        assert "default_backend component_0_alpha" in ip_config
        assert "default_backend component_1_beta" in ip_config

        ip_config_path = tmp / "haproxy-ip-ports.cfg"
        ip_config_path.write_text(ip_config, encoding="utf-8")
        validation_ip = subprocess.run(
            [haproxy, "-c", "-f", str(ip_config_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert validation_ip.returncode == 0, validation_ip.stdout + validation_ip.stderr

        invalid = resolved()
        invalid["components"][0]["gateway"]["host"] = (
            "alpha.test\nbackend injected"
        )
        write_json(path, invalid)
        rejected = invoke(path, pem)
        assert rejected.returncode != 0
        assert "inseguro" in rejected.stderr

    print(
        "[PASS] generic gateway renderer: tcp + unix + unpublished + "
        "fail closed"
    )


if __name__ == "__main__":
    main()
