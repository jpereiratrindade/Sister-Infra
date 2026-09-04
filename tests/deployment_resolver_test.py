#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from composition_resolver_test import (
    make_component,
    make_contracts,
    write_composition_v2_0,
)
from composition_qualification_test import git_init_commit


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-deployment"
CANDIDATE_CLI = ROOT / "bin" / "sister-candidate"


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
                "interaction_surfaces": [{
                    "surface_id": "alpha-work",
                    "label": "Alpha",
                    "purpose": "Executar trabalho Alpha",
                    "path": "/work",
                    "access_class": "authenticated",
                }],
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


def test_canonical_candidate_lifecycle(tmp: Path) -> None:
    contracts = make_contracts(tmp / "contracts_canonical")
    alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
    beta = make_component(tmp, "sister-beta", "beta", "sister_beta")

    # Add a qualified artifact to alpha
    alpha_desc_path = alpha / ".sister" / "component.json"
    alpha_desc = json.loads(alpha_desc_path.read_text(encoding="utf-8"))
    alpha_desc["build"]["artifacts"] = [
        {
            "id": "alpha-runtime",
            "path": "scripts/runtime.sh",
            "executable": True,
        }
    ]
    write_json(alpha_desc_path, alpha_desc)

    git_init_commit(alpha)
    git_init_commit(beta)

    comp_dir = tmp / "composition"
    comp_path = comp_dir / "composition.json"
    write_composition_v2_0(
        comp_path,
        ["../sister-alpha", "../sister-beta"],
        composition_id="canonical_fixture",
    )

    cand_dir = tmp / "canonical_candidate"
    res_cand = subprocess.run(
        [
            str(CANDIDATE_CLI),
            "create",
            str(comp_path),
            "--out",
            str(cand_dir),
            "--candidate-id",
            "cand-canonical-001",
            "--contracts-root",
            str(contracts),
            "--json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert res_cand.returncode == 0, f"Falha ao criar candidata canônica: {res_cand.stderr}"

    dep_file = tmp / "canonical_deployment.json"
    write_json(
        dep_file,
        {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "canonical-dep-01",
            "composition_id": "canonical_fixture",
            "gateway": {"protocol": "https", "port": 8443},
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {
                        "transport": "tcp",
                        "listen": "127.0.0.1",
                        "port": 18001,
                    },
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "alpha-canonical.test"},
                },
                {
                    "system_id": "sister_beta",
                    "runtime": {
                        "transport": "unix",
                        "socket": str(tmp / "beta.sock"),
                    },
                },
            ],
        },
    )

    manifest_file = cand_dir / "manifest.json"

    # 1. Candidata válida gerada pelo produtor real é resolvida com sucesso
    res_ok = subprocess.run(
        [str(CLI), "resolve", str(manifest_file), str(dep_file), "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert res_ok.returncode == 0, res_ok.stderr
    resolved_doc = json.loads(res_ok.stdout)
    assert resolved_doc["schema"] == "sister.infra.deployment.resolved/1"
    assert resolved_doc["status"] == "READY"
    assert resolved_doc["candidate_id"] == "cand-canonical-001"

    # 2. Teste negativo obrigatório: adulterar evidence/composition/qualification.json -> FAIL
    qual_file = cand_dir / "evidence" / "composition" / "qualification.json"
    qual_orig = qual_file.read_bytes()
    qual_file.write_bytes(qual_orig + b"\n")
    try:
        res_tamper_qual = subprocess.run(
            [str(CLI), "resolve", str(manifest_file), str(dep_file), "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert res_tamper_qual.returncode != 0, "Deveria falhar com qualificação adulterada"
        assert "verificação autoritativa da candidata falhou" in res_tamper_qual.stderr
        assert "hash divergente da evidência de qualificação" in res_tamper_qual.stderr
    finally:
        qual_file.write_bytes(qual_orig)

    # 3. Teste negativo obrigatório: alterar artefato qualificado -> FAIL
    art_file = cand_dir / "components" / "alpha" / "scripts" / "runtime.sh"
    art_orig = art_file.read_bytes()
    art_file.write_bytes(art_orig + b"\n# tampered\n")
    try:
        res_tamper_art = subprocess.run(
            [str(CLI), "resolve", str(manifest_file), str(dep_file), "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert res_tamper_art.returncode != 0, "Deveria falhar com artefato adulterado"
        assert "verificação autoritativa da candidata falhou" in res_tamper_art.stderr
        assert "hash divergente do artefato" in res_tamper_art.stderr
    finally:
        art_file.write_bytes(art_orig)


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
        assert resolved["components"][0]["gateway"]["host"] == "alpha-gateway.test"
        assert (
            resolved["components"][0]["gateway"]["public_url"]
            == "https://alpha-gateway.test:8443"
        )
        assert resolved["components"][0]["interaction_surfaces"] == [{
            "surface_id": "alpha-work",
            "label": "Alpha",
            "purpose": "Executar trabalho Alpha",
            "access_class": "authenticated",
            "public_url": "https://alpha-gateway.test:8443/work",
        }]
        assert resolved["components"][1]["runtime"]["transport"] == "unix"
        assert "gateway" not in resolved["components"][1]

        # Fabricated canonical candidate without producer / integrity must be rejected
        fabricated_cand = copy.deepcopy(base_candidate)
        fabricated_cand["schema"] = "sister.infra.candidate/1"
        rejected(
            tmp,
            fabricated_cand,
            base_deployment,
            "manifesto de candidata canônica deve ser 'manifest.json'",
        )

        fake_dir = tmp / "fake_candidate"
        fake_dir.mkdir(parents=True, exist_ok=True)
        fake_manifest = fake_dir / "manifest.json"
        write_json(fake_manifest, fabricated_cand)
        fake_dep = fake_dir / "deployment.json"
        write_json(fake_dep, base_deployment)
        res_fake = subprocess.run(
            [str(CLI), "resolve", str(fake_manifest), str(fake_dep), "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert res_fake.returncode != 0
        assert "verificação autoritativa da candidata falhou" in res_fake.stderr

        # Canonical candidate end-to-end lifecycle & mandatory negative tests
        test_canonical_candidate_lifecycle(tmp)

        # Extensibility test: add delta component dynamically
        ext_candidate = copy.deepcopy(base_candidate)
        ext_candidate["components"].append({
            "component_id": "delta",
            "system_id": "system_delta",
            "path": "components/delta",
        })
        ext_deployment = copy.deepcopy(base_deployment)
        ext_deployment["bindings"].append({
            "system_id": "system_delta",
            "runtime": {
                "transport": "tcp",
                "listen": "127.0.0.1",
                "port": 18003,
            },
            "probe": {"health_path": "/health"},
            "gateway": {"host": "delta-gateway.test"},
        })
        ext_resolved = accepted(tmp, ext_candidate, ext_deployment)
        assert len(ext_resolved["components"]) == 3
        delta_comp = next(
            c for c in ext_resolved["components"] if c["component_id"] == "delta"
        )
        assert delta_comp["gateway"]["host"] == "delta-gateway.test"
        assert delta_comp["gateway"]["public_url"] == "https://delta-gateway.test:8443"

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
