#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-deployment"


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def candidate() -> dict[str, Any]:
    return {
        "schema": "sister.infra.workstation.candidate/1",
        "candidate_id": "wc-fixture",
        "composition": {"composition_id": "fixture"},
        "qualification": {"status": "PASS"},
        "deployment": {"status": "PENDING_BINDINGS"},
        "components": [
            {
                "component_id": "alpha",
                "system_id": "system_alpha",
                "path": "components/alpha",
            },
            {
                "component_id": "beta",
                "system_id": "system_beta",
                "path": "components/beta",
            },
        ],
    }


def deployment() -> dict[str, Any]:
    return {
        "schema": "sister.infra.deployment/1.0.0",
        "deployment_id": "fixture-lab",
        "composition_id": "fixture",
        "bindings": [
            {
                "system_id": "system_alpha",
                "runtime": {
                    "transport": "tcp",
                    "listen": "127.0.0.1",
                    "port": 18001,
                },
                "probe": {"health_path": "/health"},
                "gateway": {"host": "alpha-gateway.test"},
            },
            {
                "system_id": "system_beta",
                "runtime": {
                    "transport": "unix",
                    "socket": "/run/user/1000/fixture/beta.sock",
                },
            },
        ],
    }


def invoke(
    directory: Path,
    candidate_value: dict[str, Any],
    deployment_value: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    candidate_path = directory / "candidate.json"
    deployment_path = directory / "deployment.json"
    write_json(candidate_path, candidate_value)
    write_json(deployment_path, deployment_value)
    return subprocess.run(
        [str(CLI), "resolve", str(candidate_path), str(deployment_path), "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def accepted(
    directory: Path,
    candidate_value: dict[str, Any],
    deployment_value: dict[str, Any],
) -> dict[str, Any]:
    result = invoke(directory, candidate_value, deployment_value)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def rejected(
    directory: Path,
    candidate_value: dict[str, Any],
    deployment_value: dict[str, Any],
    message: str,
) -> None:
    result = invoke(directory, candidate_value, deployment_value)
    assert result.returncode != 0, result.stdout
    assert message in result.stderr, result.stderr


def main() -> None:
    source = CLI.read_text(encoding="utf-8").lower()
    for forbidden in ("nexo", "praxis", "urt", "8015", "8093", "8094"):
        assert forbidden not in source, f"resolvedor contém {forbidden}"

    with tempfile.TemporaryDirectory(
        prefix="sister-deployment-resolver-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        base_candidate = candidate()
        base_deployment = deployment()

        resolved = accepted(tmp, base_candidate, base_deployment)
        assert resolved["schema"] == "sister.infra.deployment.resolved/1"
        assert resolved["status"] == "READY"
        assert resolved["candidate_id"] == "wc-fixture"
        assert [item["system_id"] for item in resolved["components"]] == [
            "system_alpha",
            "system_beta",
        ]
        assert resolved["components"][0]["runtime"]["transport"] == "tcp"
        assert resolved["components"][1]["runtime"]["transport"] == "unix"
        assert "gateway" not in resolved["components"][1]

        changed = copy.deepcopy(base_candidate)
        changed["qualification"]["status"] = "FAIL"
        rejected(tmp, changed, base_deployment, "qualification=PASS")

        changed = copy.deepcopy(base_candidate)
        changed["deployment"]["status"] = "READY"
        rejected(tmp, changed, base_deployment, "PENDING_BINDINGS")

        changed = copy.deepcopy(base_deployment)
        changed["composition_id"] = "other"
        rejected(tmp, base_candidate, changed, "composição incompatível")

        changed = copy.deepcopy(base_deployment)
        changed["bindings"][1]["system_id"] = "system_unknown"
        rejected(tmp, base_candidate, changed, "binding desconhecido")

        changed = copy.deepcopy(base_deployment)
        changed["bindings"].pop()
        rejected(tmp, base_candidate, changed, "binding faltante")

        changed = copy.deepcopy(base_deployment)
        changed["bindings"][1]["system_id"] = "system_alpha"
        rejected(tmp, base_candidate, changed, "system_id duplicado nos bindings")

        changed = copy.deepcopy(base_candidate)
        changed["components"][1]["system_id"] = "system_alpha"
        rejected(tmp, changed, base_deployment, "system_id duplicado na candidata")

        changed = copy.deepcopy(base_deployment)
        changed["bindings"][1]["runtime"] = {
            "transport": "tcp",
            "listen": "127.0.0.1",
            "port": 18001,
        }
        rejected(tmp, base_candidate, changed, "conflito de endpoint TCP")

        changed = copy.deepcopy(base_deployment)
        changed["bindings"][1]["gateway"] = {
            "host": "ALPHA-GATEWAY.TEST"
        }
        rejected(tmp, base_candidate, changed, "gateway host duplicado")

        for invalid_runtime in (
            {"transport": "tcp", "listen": "127.0.0.1"},
            {
                "transport": "tcp",
                "listen": "127.0.0.1",
                "port": 0,
            },
            {
                "transport": "tcp",
                "listen": "127.0.0.1",
                "port": 18001,
                "socket": "/tmp/forbidden.sock",
            },
        ):
            changed = copy.deepcopy(base_deployment)
            changed["bindings"][0]["runtime"] = invalid_runtime
            rejected(tmp, base_candidate, changed, "deployment rejeitado")

        for invalid_runtime in (
            {"transport": "unix"},
            {"transport": "unix", "socket": "relative.sock"},
            {
                "transport": "unix",
                "socket": "/tmp/fixture.sock",
                "port": 18002,
            },
        ):
            changed = copy.deepcopy(base_deployment)
            changed["bindings"][1]["runtime"] = invalid_runtime
            rejected(tmp, base_candidate, changed, "deployment rejeitado")

    print("[PASS] declarative deployment resolver")


if __name__ == "__main__":
    main()
