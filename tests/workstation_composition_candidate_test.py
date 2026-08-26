#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import json
import os
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


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-workstation"


def git_init_commit(path: Path) -> str:
    subprocess.run(
        ["git", "-C", str(path), "init", "-q"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "config",
            "user.email",
            "test@example.invalid",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "config",
            "user.name",
            "SisTer Test",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", "fixture"],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip()


def add_qualified_artifact(
    component: Path,
    artifact_id: str,
) -> None:
    descriptor_path = component / ".sister" / "component.json"
    descriptor = json.loads(
        descriptor_path.read_text(encoding="utf-8")
    )

    artifact_rel = f"build/{artifact_id}-service"

    (component / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n"
        f"project(test_{artifact_id} LANGUAGES CXX)\n"
        "enable_testing()\n"
        f"add_executable({artifact_id}-service main.cpp)\n"
        f"add_test(NAME {artifact_id}_runs COMMAND {artifact_id}-service)\n",
        encoding="utf-8",
    )
    (component / "main.cpp").write_text(
        "int main() { return 0; }\n",
        encoding="utf-8",
    )

    gitignore = component / ".gitignore"
    gitignore.write_text(
        (gitignore.read_text(encoding="utf-8") if gitignore.exists() else "")
        + "build/\n",
        encoding="utf-8",
    )

    descriptor["build"] = {
        "driver": "cmake-ninja/1",
        "source": ".",
        "build_dir": "build",
        "configuration": "Release",
        "tests": {
            "driver": "ctest/1",
        },
        "artifacts": [
            {
                "id": f"{artifact_id}-service",
                "path": artifact_rel,
                "executable": True,
            }
        ],
    }
    write_json(descriptor_path, descriptor)


def make_infra(workspace: Path) -> tuple[Path, str]:
    infra = workspace / "sister-infra"
    (infra / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (infra / "README.md").write_text(
        "control plane fixture\n",
        encoding="utf-8",
    )
    commit = git_init_commit(infra)
    return infra, commit


def run(
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = CLI.read_text(encoding="utf-8")
    begin = source.index(
        "# SISTER-INFRA-CR05-COMPOSITION-BEGIN"
    )
    end = source.index(
        "# SISTER-INFRA-CR05-COMPOSITION-END"
    )
    generic = source[begin:end].lower()

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
        assert forbidden not in generic, (
            "caminho CR-05 contém conhecimento concreto: "
            f"{forbidden}"
        )

    with tempfile.TemporaryDirectory(
        prefix="sister-workstation-composition-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        home = tmp / "home"
        workspace = tmp / "workspace"
        home.mkdir(parents=True)
        workspace.mkdir(parents=True)

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

        add_qualified_artifact(alpha, "alpha")
        add_qualified_artifact(beta, "beta")

        alpha_commit = git_init_commit(alpha)
        beta_commit = git_init_commit(beta)
        _, infra_commit = make_infra(workspace)

        deployment = tmp / "deployment"
        composition = deployment / "composition.json"
        write_composition(
            composition,
            ["../sister-alpha", "../sister-beta"],
        )

        env = dict(os.environ)

        # O teste troca HOME para isolar a workstation. Preserve explicitamente
        # o site-packages que fornece jsonschema ao subprocesso Python.
        jsonschema_site = str(
            Path(jsonschema.__file__).resolve().parent.parent
        )
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (jsonschema_site, existing_pythonpath)
            if part
        )

        env.update(
            {
                "HOME": str(home),
                "SISTER_WORKSTATION_INSTALL_ROOT": str(
                    home / ".local" / "share" / "sister"
                ),
                "SISTER_WORKSTATION_CONFIG_ROOT": str(
                    home / ".config" / "sister" / "workstation"
                ),
                "SISTER_WORKSTATION_STATE_ROOT": str(
                    home / ".local" / "state" / "sister" / "workstation"
                ),
                "SISTER_WORKSTATION_SYSTEMD_ROOT": str(
                    home / ".config" / "systemd" / "user"
                ),
                "SISTER_WORKSTATION_BIN_ROOT": str(
                    home / ".local" / "bin"
                ),
                "SISTER_WORKSTATION_TEST_MODE": "1",
                "SISTER_WORKSTATION_CONTROL_PLANE_SOURCE": str(
                    workspace / "sister-infra"
                ),
                "SISTER_WORKSTATION_CONTRACTS_ROOT": str(contracts),
            }
        )

        created = run(
            env,
            "candidate-create",
            str(composition),
        )
        assert created.returncode == 0, (
            created.stdout + created.stderr
        )

        candidate_id = created.stdout.strip().splitlines()[-1]
        assert candidate_id.startswith("wc-")

        candidate = (
            home
            / ".local"
            / "share"
            / "sister"
            / "candidates"
            / candidate_id
        )
        manifest_path = candidate / "manifest.json"
        assert manifest_path.is_file()

        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        assert manifest["schema"] == (
            "sister.infra.workstation.candidate/1"
        )
        assert manifest["deployment"] == {
            "status": "PENDING_BINDINGS"
        }
        assert manifest["qualification"]["status"] == "PASS"
        assert manifest["control_plane"]["commit"] == infra_commit

        components = manifest["components"]
        assert [
            component["component_id"]
            for component in components
        ] == ["alpha", "beta"]
        assert [
            component["commit"]
            for component in components
        ] == [alpha_commit, beta_commit]
        assert [
            component["system_id"]
            for component in components
        ] == ["sister_alpha", "sister_beta"]
        assert all(
            component["runtime"]["entrypoint"]
            == "scripts/runtime.sh"
            for component in components
        )

        for component in components:
            component_id = component["component_id"]
            artifact = component["artifacts"][0]
            materialized = (
                candidate
                / component["path"]
                / artifact["path"]
            )
            assert materialized.is_file()
            assert os.access(materialized, os.X_OK)
            assert sha256(materialized) == artifact["sha256"]
            assert component_id in materialized.name

        verified = run(
            env,
            "candidate-verify",
            candidate_id,
        )
        assert verified.returncode == 0, (
            verified.stdout + verified.stderr
        )

        tampered = (
            candidate
            / "components"
            / "beta"
            / "build"
            / "beta-service"
        )
        tampered.write_bytes(
            tampered.read_bytes() + b"tamper\\n"
        )

        rejected = run(
            env,
            "candidate-verify",
            candidate_id,
        )
        assert rejected.returncode != 0
        assert "hash divergente" in rejected.stderr

    print(
        "[PASS] generic workstation candidate: "
        "qualified composition -> exact commits -> artifacts -> integrity"
    )


if __name__ == "__main__":
    main()
