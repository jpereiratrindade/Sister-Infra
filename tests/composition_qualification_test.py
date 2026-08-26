#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from composition_resolver_test import (
    make_component,
    make_contracts,
    write_composition,
    write_composition_v2_0,
)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-composition"


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


def run(
    composition: Path,
    contracts: Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(CLI),
            "qualify",
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
        assert forbidden not in source, (
            "qualificador contém conhecimento concreto: "
            f"{forbidden}"
        )

    with tempfile.TemporaryDirectory(
        prefix="sister-composition-qualification-"
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

        alpha_commit = git_init_commit(alpha)
        beta_commit = git_init_commit(beta)

        deployment = tmp / "deployment"
        composition = deployment / "composition.json"
        write_composition(
            composition,
            ["../sister-alpha", "../sister-beta"],
        )

        qualified = run(
            composition,
            contracts,
            "--json",
        )
        assert qualified.returncode == 0, qualified.stderr

        document = json.loads(qualified.stdout)
        assert document["schema"] == (
            "sister.infra.composition.qualification/1"
        )
        assert document["status"] == "PASS"
        assert document["composition_id"] == (
            "example_workstation"
        )
        assert document["deployment_class"] == "workstation"

        components = document["components"]
        assert [item["component_id"] for item in components] == [
            "alpha",
            "beta",
        ]
        assert [
            item["qualification"]["status"]
            for item in components
        ] == ["PASS", "PASS"]
        assert components[0]["qualification"]["source"]["commit"] == (
            alpha_commit
        )
        assert components[1]["qualification"]["source"]["commit"] == (
            beta_commit
        )
        assert components[0]["qualification"]["build"]["tests"] == {
            "driver": "none/1",
            "status": "SKIPPED",
        }

        human = run(composition, contracts)
        assert human.returncode == 0, human.stderr
        for expected in (
            "status           PASS",
            "composition_id   example_workstation",
            "alpha",
            alpha_commit,
            "beta",
            beta_commit,
        ):
            assert expected in human.stdout, expected

        # Test qualification of composition 2.0.0 (environment-neutral)
        comp_v2_0 = deployment / "composition-2.0.0.json"
        write_composition_v2_0(
            comp_v2_0,
            ["../sister-alpha", "../sister-beta"],
            composition_id="env_neutral_qual",
        )
        qualified_v2_0 = run(comp_v2_0, contracts, "--json")
        assert qualified_v2_0.returncode == 0, qualified_v2_0.stderr
        doc_v2_0 = json.loads(qualified_v2_0.stdout)
        assert doc_v2_0["schema"] == "sister.infra.composition.qualification/2"
        assert doc_v2_0["status"] == "PASS"
        assert doc_v2_0["composition_id"] == "env_neutral_qual"
        assert "deployment_class" not in doc_v2_0
        assert len(doc_v2_0["components"]) == 2

        human_v2_0 = run(comp_v2_0, contracts)
        assert human_v2_0.returncode == 0, human_v2_0.stderr
        assert "composition_id   env_neutral_qual" in human_v2_0.stdout
        assert "class            " not in human_v2_0.stdout

        (beta / "README.md").write_text(
            "dirty\n",
            encoding="utf-8",
        )
        failed = run(composition, contracts)
        assert failed.returncode == 2
        assert "qualificação de componente falhou" in failed.stderr
        assert "beta" in failed.stderr
        assert "alterações locais" in failed.stderr

    print(
        "[PASS] generic composition qualification: "
        "resolve + delegate qualify + aggregate evidence + fail closed"
    )


if __name__ == "__main__":
    main()
