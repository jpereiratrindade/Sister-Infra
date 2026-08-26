#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import jsonschema

from composition_resolver_test import (
    make_component,
    make_contracts,
    write_composition,
    write_json,
)
from workstation_composition_candidate_test import (
    add_qualified_artifact,
    git_init_commit,
)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-workstation"


def make_control_plane(workspace: Path) -> Path:
    target = workspace / "sister-infra"
    target.mkdir(parents=True)
    for name in ("bin", "config", "contracts", "templates"):
        shutil.copytree(ROOT / name, target / name)
    shutil.copy2(ROOT / "README.md", target / "README.md")
    git_init_commit(target)
    return target


def deployment(path: Path) -> None:
    write_json(
        path,
        {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "fixture-lab",
            "composition_id": "example_workstation",
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {
                        "transport": "tcp",
                        "listen": "127.0.0.1",
                        "port": 18001,
                    },
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "alpha-gateway.test"},
                },
                {
                    "system_id": "sister_beta",
                    "runtime": {
                        "transport": "unix",
                        "socket": "/tmp/sister-fixture-beta.sock",
                    },
                },
            ],
        },
    )


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def accepted(env: dict[str, str], *args: str) -> str:
    result = run(env, *args)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def rejected(env: dict[str, str], *args: str) -> str:
    result = run(env, *args)
    assert result.returncode != 0, result.stdout
    return result.stderr


def main() -> None:
    source = CLI.read_text(encoding="utf-8").lower()
    lifecycle = source[
        source.index("declarative_release_integrity() {"):
        source.index("release_build_qualification() {")
    ]
    for forbidden in (
        "sister_nexo",
        "sister-nexo",
        "sister_praxis",
        "sister-praxis",
        "sister_urt",
        "sister-urt",
        "8015",
        "8093",
        "8094",
    ):
        assert forbidden not in lifecycle, (
            f"lifecycle declarativo contém conhecimento concreto: {forbidden}"
        )

    with tempfile.TemporaryDirectory(
        prefix="sister-workstation-declarative-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        home = tmp / "home"
        workspace = tmp / "workspace"
        home.mkdir()
        workspace.mkdir()

        contracts = make_contracts(tmp)
        make_control_plane(workspace)

        alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
        beta = make_component(tmp, "sister-beta", "beta", "sister_beta")
        add_qualified_artifact(alpha, "alpha")
        add_qualified_artifact(beta, "beta")
        git_init_commit(alpha)
        git_init_commit(beta)

        declaration_root = tmp / "declaration"
        declaration_root.mkdir()
        composition = declaration_root / "composition.json"
        deployment_file = declaration_root / "deployment.json"
        write_composition(
            composition,
            ["../sister-alpha", "../sister-beta"],
        )
        deployment(deployment_file)

        env = dict(os.environ)
        jsonschema_site = str(Path(jsonschema.__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (jsonschema_site, env.get("PYTHONPATH", "")) if part
        )
        env.update(
            {
                "HOME": str(home),
                "SISTER_SOURCE_WORKSPACE": str(workspace),
                "SISTER_WORKSTATION_INSTALL_ROOT": str(home / "install"),
                "SISTER_WORKSTATION_CONFIG_ROOT": str(home / "config"),
                "SISTER_WORKSTATION_STATE_ROOT": str(home / "state"),
                "SISTER_WORKSTATION_SYSTEMD_ROOT": str(home / "systemd"),
                "SISTER_WORKSTATION_BIN_ROOT": str(home / "bin"),
                "SISTER_WORKSTATION_TEST_MODE": "1",
                "SISTER_WORKSTATION_CONTRACTS_ROOT": str(contracts),
                "SISTER_WORKSTATION_COMPOSITION_FILE": str(composition),
                "SISTER_WORKSTATION_DEPLOYMENT_FILE": str(deployment_file),
            }
        )

        out = accepted(env, "release-create")
        release1_id = out.strip().splitlines()[-1]
        assert release1_id.startswith("wr-")
        release1 = home / "install" / "releases" / release1_id
        manifest1 = json.loads((release1 / "manifest.json").read_text())
        assert manifest1["schema"] == "sister.infra.workstation.release/3"
        assert manifest1["qualification"]["status"] == "PASS"
        assert manifest1["deployment"]["status"] == "READY"

        accepted(env, "install", release1_id)
        unit = (home / "systemd" / "sister-workstation.service").read_text()
        assert "sister-workstation runtime-start" in unit
        accepted(env, "runtime-start")
        accepted(env, "runtime-verify")
        accepted(env, "runtime-stop")

        (alpha / "main.cpp").write_text("int main() { return 0; }\n// v2\n")
        subprocess.run(["git", "-C", str(alpha), "add", "main.cpp"], check=True)
        subprocess.run(
            ["git", "-C", str(alpha), "commit", "-q", "-m", "fixture v2"],
            check=True,
        )

        out = accepted(env, "update")
        release2_id = [
            line for line in out.splitlines() if line.startswith("wr-")
        ][-1]
        release2 = home / "install" / "releases" / release2_id
        current = home / "install" / "current"
        previous = home / "install" / "previous"
        assert current.resolve() == release2.resolve()
        assert previous.resolve() == release1.resolve()

        accepted(env, "rollback")
        assert current.resolve() == release1.resolve()
        assert previous.resolve() == release2.resolve()

        manifest2 = json.loads((release2 / "manifest.json").read_text())
        artifact = manifest2["components"][0]["artifacts"][0]
        artifact_path = (
            release2
            / manifest2["components"][0]["path"]
            / artifact["path"]
        )
        original_artifact = artifact_path.read_bytes()
        artifact_path.write_bytes(original_artifact + b"tamper\n")
        assert "hash divergente" in rejected(env, "install", release2_id)
        artifact_path.write_bytes(original_artifact)

        evidence_path = release2 / manifest2["deployment"]["evidence"]
        original_evidence = evidence_path.read_bytes()
        evidence_path.write_bytes(original_evidence + b"tamper\n")
        assert "hash divergente" in rejected(env, "install", release2_id)
        evidence_path.write_bytes(original_evidence)

        component = manifest2["components"][0]
        component_repo = release2 / component["path"]
        subprocess.run(
            [
                "git", "-C", str(component_repo), "commit",
                "--allow-empty", "-q", "-m", "tamper",
            ],
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
            },
        )
        assert "commit divergente" in rejected(env, "install", release2_id)
        subprocess.run(
            ["git", "-C", str(component_repo), "checkout", "-q", "--detach", component["commit"]],
            check=True,
        )
        accepted(env, "install", release2_id)

    print(
        "[PASS] declarative workstation lifecycle: create + install + "
        "verify + update + rollback + tamper detection"
    )


if __name__ == "__main__":
    main()
