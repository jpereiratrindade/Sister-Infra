#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-composition"
COMPONENT_CLI = ROOT / "bin" / "sister-component"
SCHEMA = (
    ROOT
    / "contracts"
    / "composition"
    / "1.0.0"
    / "composition.schema.json"
)


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2) + "\n",
        encoding="utf-8",
    )


def run(
    composition: Path,
    contracts: Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(CLI),
            "resolve",
            str(composition),
            "--contracts-root",
            str(contracts),
            *extra,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def make_contracts(root: Path) -> Path:
    contracts = root / "contracts"

    runtime_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://sister.local/contracts/runtime/"
            "1.0.0/runtime.schema.json"
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "entrypoint",
            "actions",
            "state_policy",
        ],
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
                "enum": [
                    "stateless",
                    "persistent-external",
                ]
            },
        },
    }

    component_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://sister.local/contracts/component/"
            "1.0.0/component.schema.json"
        ),
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
            "deployment_role": {
                "enum": [
                    "control_plane",
                    "system",
                ]
            },
            "semantic_contract": {"type": "string"},
            "build": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "driver",
                    "source",
                    "tests",
                    "artifacts",
                ],
                "properties": {
                    "driver": {
                        "enum": [
                            "cmake-ninja/1",
                            "source-only/1",
                        ]
                    },
                    "source": {"const": "."},
                    "build_dir": {"type": "string"},
                    "configuration": {"const": "Release"},
                    "tests": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["driver"],
                        "properties": {
                            "driver": {
                                "enum": [
                                    "ctest/1",
                                    "none/1",
                                ]
                            }
                        },
                    },
                    "artifacts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "id",
                                "path",
                                "executable",
                            ],
                            "properties": {
                                "id": {"type": "string"},
                                "path": {"type": "string"},
                                "executable": {
                                    "type": "boolean"
                                },
                            },
                        },
                    },
                },
            },
            "runtime": {
                "$ref": (
                    "../../runtime/1.0.0/"
                    "runtime.schema.json"
                )
            },
        },
        "allOf": [
            {
                "if": {
                    "properties": {
                        "deployment_role": {
                            "const": "system"
                        }
                    },
                    "required": ["deployment_role"],
                },
                "then": {
                    "required": [
                        "semantic_contract",
                        "runtime",
                    ]
                },
            }
        ],
    }

    write_json(
        contracts
        / "component"
        / "1.0.0"
        / "component.schema.json",
        component_schema,
    )
    write_json(
        contracts
        / "runtime"
        / "1.0.0"
        / "runtime.schema.json",
        runtime_schema,
    )

    return contracts


def make_component(
    root: Path,
    directory: str,
    component_id: str,
    system_id: str,
) -> Path:
    component = root / directory
    descriptor = {
        "schema": "sister.component/1.0.0",
        "component_id": component_id,
        "system_id": system_id,
        "deployment_role": "system",
        "semantic_contract": "example.semantic/1",
        "build": {
            "driver": "source-only/1",
            "source": ".",
            "tests": {"driver": "none/1"},
            "artifacts": [],
        },
        "runtime": {
            "schema": "sister.runtime/1.0.0",
            "entrypoint": "scripts/runtime.sh",
            "actions": [
                "start",
                "stop",
                "status",
                "health",
            ],
            "state_policy": "stateless",
        },
    }
    write_json(
        component / ".sister" / "component.json",
        descriptor,
    )
    runtime = component / "scripts" / "runtime.sh"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(
        "#!/usr/bin/env bash\n",
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    return component


def write_composition(
    path: Path,
    sources: list[str],
    **extra: object,
) -> None:
    document = {
        "schema": "sister.infra.composition/1.0.0",
        "composition_id": "example_workstation",
        "deployment_class": "workstation",
        "components": [
            {"source": source}
            for source in sources
        ],
    }
    document.update(extra)
    write_json(path, document)


def main() -> None:
    assert COMPONENT_CLI.is_file(), (
        "sister-component ausente; CR-01/CR-02 são pré-requisitos"
    )

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
        assert forbidden not in source, (
            "resolvedor contém conhecimento concreto: "
            f"{forbidden}"
        )

    schema_text = SCHEMA.read_text(
        encoding="utf-8"
    ).lower()
    assert '"host"' not in schema_text
    assert '"port"' not in schema_text
    assert '"binding"' not in schema_text

    with tempfile.TemporaryDirectory(
        prefix="sister-composition-resolver-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        contracts = make_contracts(tmp)
        alpha = make_component(
            tmp,
            "sister-alpha",
            "alpha",
            "sister_alpha",
        )
        beta = make_component(
            tmp,
            "sister-beta",
            "beta",
            "sister_beta",
        )

        deployment = tmp / "deployment"
        composition = deployment / "composition.json"
        write_composition(
            composition,
            ["../sister-alpha", "../sister-beta"],
        )

        resolved = run(
            composition,
            contracts,
            "--json",
        )
        assert resolved.returncode == 0, resolved.stderr

        document = json.loads(resolved.stdout)
        assert document["schema"] == (
            "sister.infra.composition.resolved/1"
        )
        assert document["composition_id"] == (
            "example_workstation"
        )
        assert document["deployment_class"] == "workstation"
        assert [
            item["component_id"]
            for item in document["components"]
        ] == ["alpha", "beta"]
        assert [
            item["system_id"]
            for item in document["components"]
        ] == ["sister_alpha", "sister_beta"]
        assert [
            item["role"]
            for item in document["components"]
        ] == ["system", "system"]
        assert document["components"][0]["root"] == str(
            alpha.resolve()
        )
        assert document["components"][1]["root"] == str(
            beta.resolve()
        )

        text = run(composition, contracts)
        assert text.returncode == 0, text.stderr
        for expected in (
            "composition_id   example_workstation",
            "class            workstation",
            "alpha",
            "sister_alpha",
            "beta",
            "sister_beta",
        ):
            assert expected in text.stdout, expected

        invalid_binding = (
            deployment / "invalid-binding.json"
        )
        write_composition(
            invalid_binding,
            ["../sister-alpha"],
            binding={
                "host": "127.0.0.1",
                "port": 9999,
            },
        )
        rejected = run(
            invalid_binding,
            contracts,
        )
        assert rejected.returncode == 2
        assert "composição rejeitada" in rejected.stderr
        assert "binding" in rejected.stderr

        missing_source = (
            deployment / "missing-source.json"
        )
        write_composition(
            missing_source,
            ["../component-missing"],
        )
        missing = run(
            missing_source,
            contracts,
        )
        assert missing.returncode == 2
        assert "componente inválido" in missing.stderr
        assert "component-missing" in missing.stderr

        beta_descriptor = (
            beta / ".sister" / "component.json"
        )
        original_beta = json.loads(
            beta_descriptor.read_text(
                encoding="utf-8"
            )
        )

        duplicate_component = dict(original_beta)
        duplicate_component["component_id"] = "alpha"
        write_json(
            beta_descriptor,
            duplicate_component,
        )
        duplicate = run(
            composition,
            contracts,
        )
        assert duplicate.returncode == 2
        assert "component_id duplicado" in duplicate.stderr

        duplicate_system = dict(original_beta)
        duplicate_system["system_id"] = "sister_alpha"
        write_json(
            beta_descriptor,
            duplicate_system,
        )
        duplicate = run(
            composition,
            contracts,
        )
        assert duplicate.returncode == 2
        assert "system_id duplicado" in duplicate.stderr

        write_json(beta_descriptor, original_beta)

    print(
        "[PASS] generic composition resolver: "
        "declare + validate + resolve + unique identities"
    )


if __name__ == "__main__":
    main()
