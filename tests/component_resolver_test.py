#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-component"


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def make_contracts(root: Path) -> Path:
    contracts = root / "contracts"

    runtime_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://sister.local/contracts/runtime/1.0.0/runtime.schema.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "entrypoint", "actions", "state_policy"],
        "properties": {
            "schema": {"const": "sister.runtime/1.0.0"},
            "entrypoint": {"type": "string"},
            "actions": {
                "type": "array",
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "start",
                        "stop",
                        "restart",
                        "status",
                        "health",
                        "readiness",
                    ]
                },
            },
            "state_policy": {
                "enum": ["stateless", "persistent-external"]
            },
        },
    }

    component_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://sister.local/contracts/component/1.0.0/component.schema.json",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "component_id",
            "system_id",
            "deployment_role",
            "build",
        ],
        "properties": {
            "schema": {"const": "sister.component/1.0.0"},
            "component_id": {"type": "string"},
            "system_id": {"type": "string"},
            "deployment_role": {"enum": ["control_plane", "system"]},
            "semantic_contract": {"type": "string"},
            "build": {
                "type": "object",
                "additionalProperties": False,
                "required": ["driver", "source", "tests", "artifacts"],
                "properties": {
                    "driver": {"enum": ["cmake-ninja/1", "source-only/1"]},
                    "source": {"const": "."},
                    "build_dir": {"type": "string"},
                    "configuration": {"const": "Release"},
                    "tests": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["driver"],
                        "properties": {
                            "driver": {"enum": ["ctest/1", "none/1"]}
                        },
                    },
                    "artifacts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["id", "path", "executable"],
                            "properties": {
                                "id": {"type": "string"},
                                "path": {"type": "string"},
                                "executable": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
            "runtime": {
                "$ref": "../../runtime/1.0.0/runtime.schema.json"
            },
        },
        "allOf": [
            {
                "if": {
                    "properties": {
                        "deployment_role": {"const": "system"}
                    },
                    "required": ["deployment_role"],
                },
                "then": {"required": ["semantic_contract", "runtime"]},
            }
        ],
    }

    write_json(
        contracts / "component/1.0.0/component.schema.json",
        component_schema,
    )
    write_json(
        contracts / "runtime/1.0.0/runtime.schema.json",
        runtime_schema,
    )

    return contracts


def make_component(root: Path) -> Path:
    component = root / "sister-example"
    descriptor = {
        "schema": "sister.component/1.0.0",
        "component_id": "example",
        "system_id": "sister_example",
        "deployment_role": "system",
        "semantic_contract": "sister.subsystem/1.0.0",
        "build": {
            "driver": "cmake-ninja/1",
            "source": ".",
            "build_dir": "build",
            "configuration": "Release",
            "tests": {"driver": "ctest/1"},
            "artifacts": [
                {
                    "id": "example-service",
                    "path": "build/example-service",
                    "executable": True,
                }
            ],
        },
        "runtime": {
            "schema": "sister.runtime/1.0.0",
            "entrypoint": "scripts/runtime.sh",
            "actions": [
                "start",
                "stop",
                "restart",
                "status",
                "health",
            ],
            "state_policy": "stateless",
        },
    }
    write_json(component / ".sister/component.json", descriptor)
    return component


def make_control_plane(root: Path) -> Path:
    component = root / "sister-control-example"
    descriptor = {
        "schema": "sister.component/1.0.0",
        "component_id": "control_example",
        "system_id": "sister_control_example",
        "deployment_role": "control_plane",
        "build": {
            "driver": "source-only/1",
            "source": ".",
            "tests": {"driver": "none/1"},
            "artifacts": [],
        },
    }
    write_json(component / ".sister/component.json", descriptor)
    return component


def main() -> None:
    source = CLI.read_text(encoding="utf-8").lower()
    for forbidden in (
        "sister_urt",
        "sister-urt",
        "sister_nexo",
        "sister-nexo",
        "sister_praxis",
        "sister-praxis",
        "8094",
        "8015",
        "8093",
    ):
        assert forbidden not in source, f"resolver contém conhecimento concreto: {forbidden}"

    with tempfile.TemporaryDirectory(prefix="sister-component-resolver-") as tmp_text:
        tmp = Path(tmp_text)
        contracts = make_contracts(tmp)
        component = make_component(tmp)
        control_plane = make_control_plane(tmp)

        control_validated = run(
            "validate",
            str(control_plane),
            "--contracts-root",
            str(contracts),
        )
        assert control_validated.returncode == 0, control_validated.stderr
        assert "control_example atende sister.component/1.0.0" in control_validated.stdout

        validated = run(
            "validate",
            str(component),
            "--contracts-root",
            str(contracts),
        )
        assert validated.returncode == 0, validated.stderr
        assert "[PASS] example atende sister.component/1.0.0" in validated.stdout

        inspected = run(
            "inspect",
            str(component),
            "--contracts-root",
            str(contracts),
        )
        assert inspected.returncode == 0, inspected.stderr
        for expected in (
            "component_id     example",
            "system_id        sister_example",
            "driver         cmake-ninja/1",
            "example-service",
            "scripts/runtime.sh",
            "start stop restart status health",
        ):
            assert expected in inspected.stdout, expected

        inspected_json = run(
            "inspect",
            str(component),
            "--contracts-root",
            str(contracts),
            "--json",
        )
        assert inspected_json.returncode == 0, inspected_json.stderr
        parsed = json.loads(inspected_json.stdout)
        assert parsed["component_id"] == "example"
        assert parsed["system_id"] == "sister_example"

        descriptor_path = component / ".sister/component.json"
        invalid = json.loads(descriptor_path.read_text(encoding="utf-8"))
        invalid["binding"] = {"host": "127.0.0.1", "port": 9999}
        write_json(descriptor_path, invalid)

        rejected = run(
            "validate",
            str(component),
            "--contracts-root",
            str(contracts),
        )
        assert rejected.returncode == 2
        assert "descritor rejeitado" in rejected.stderr
        assert "binding" in rejected.stderr

        missing = run(
            "inspect",
            str(tmp / "missing-component"),
            "--contracts-root",
            str(contracts),
        )
        assert missing.returncode == 2
        assert "raiz de componente inexistente" in missing.stderr

    print("[PASS] generic component resolver: discover + validate + describe")


if __name__ == "__main__":
    main()
