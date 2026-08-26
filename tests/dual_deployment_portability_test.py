#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from composition_resolver_test import (
    make_component,
    make_contracts,
    write_composition_v2_0,
    write_json,
)
from composition_qualification_test import git_init_commit


ROOT = Path(__file__).resolve().parents[1]
COMPOSITION_CLI = ROOT / "bin" / "sister-composition"
CANDIDATE_CLI = ROOT / "bin" / "sister-candidate"
DEPLOYMENT_CLI = ROOT / "bin" / "sister-deployment"
GATEWAY_CLI = ROOT / "bin" / "sister-gateway"


def run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_dual_deployment_portability() -> None:
    with tempfile.TemporaryDirectory(prefix="sister-dual-deployment-") as tmp_text:
        tmp = Path(tmp_text)
        contracts = make_contracts(tmp)

        # 1. Componentes sintéticos reais
        alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
        beta = make_component(tmp, "sister-beta", "beta", "sister_beta")

        # Adiciona artefato qualificado a alpha
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

        # 2. Composição declarativa neutra de ambiente (schema 2.0.0)
        composition_dir = tmp / "composition"
        composition_path = composition_dir / "composition.json"
        write_composition_v2_0(
            composition_path,
            ["../sister-alpha", "../sister-beta"],
            composition_id="portable_ecosystem",
        )

        # 3. Materialização da candidata através do produtor real (sister-candidate)
        candidate_dir = tmp / "candidate_desktop_server"
        res_cand = run_cmd([
            str(CANDIDATE_CLI),
            "create",
            str(composition_path),
            "--out", str(candidate_dir),
            "--candidate-id", "cand-portable-001",
            "--contracts-root", str(contracts),
            "--json",
        ])
        assert res_cand.returncode == 0, f"Falha ao criar candidata: {res_cand.stderr}"

        # 4. Verificação da candidata pelo validador fail-closed real (sister-candidate verify)
        res_ver = run_cmd([str(CANDIDATE_CLI), "verify", str(candidate_dir), "--json"])
        assert res_ver.returncode == 0, f"Falha ao verificar candidata: {res_ver.stderr}"
        cand_doc = json.loads(res_ver.stdout)
        assert cand_doc["schema"] == "sister.infra.candidate/1"
        assert cand_doc["candidate_id"] == "cand-portable-001"
        assert cand_doc["qualification"]["status"] == "PASS"
        assert cand_doc["deployment"]["status"] == "PENDING_BINDINGS"
        assert len(cand_doc["components"]) == 2

        candidate_manifest_file = candidate_dir / "manifest.json"

        # 5. Declaração do Deployment LAB: workstation/lab (8443, .test, loopback/local)
        deployment_lab_file = tmp / "deployment_lab.json"
        write_json(deployment_lab_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "lab-desktop-01",
            "composition_id": "portable_ecosystem",
            "gateway": {
                "protocol": "https",
                "port": 8443,
            },
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {
                        "transport": "tcp",
                        "listen": "127.0.0.1",
                        "port": 18001,
                    },
                    "probe": {"health_path": "/api/health"},
                    "gateway": {"host": "alpha-gateway.test"},
                },
                {
                    "system_id": "sister_beta",
                    "runtime": {
                        "transport": "tcp",
                        "listen": "127.0.0.1",
                        "port": 18002,
                    },
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "beta-gateway.test"},
                },
            ],
        })

        # 6. Declaração do Deployment SERVER: server/production (443, institutional domain, server-local)
        deployment_server_file = tmp / "deployment_server.json"
        write_json(deployment_server_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "server-production-01",
            "composition_id": "portable_ecosystem",
            "gateway": {
                "protocol": "https",
                "port": 443,
            },
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {
                        "transport": "tcp",
                        "listen": "10.0.1.50",
                        "port": 8080,
                    },
                    "probe": {"health_path": "/api/health"},
                    "gateway": {"host": "alpha.example.org"},
                },
                {
                    "system_id": "sister_beta",
                    "runtime": {
                        "transport": "unix",
                        "socket": "/run/sister/production/beta.sock",
                    },
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "beta.example.org"},
                },
            ],
        })

        # 7. Resolução da candidata contra o Deployment LAB
        res_lab = run_cmd([
            str(DEPLOYMENT_CLI),
            "resolve",
            str(candidate_manifest_file),
            str(deployment_lab_file),
            "--json",
        ])
        assert res_lab.returncode == 0, f"Falha ao resolver deployment LAB: {res_lab.stderr}"
        resolved_lab = json.loads(res_lab.stdout)
        assert resolved_lab["status"] == "READY"
        assert resolved_lab["deployment_id"] == "lab-desktop-01"
        assert resolved_lab["candidate_id"] == "cand-portable-001"

        lab_comps = {c["component_id"]: c for c in resolved_lab["components"]}
        assert lab_comps["alpha"]["gateway"]["host"] == "alpha-gateway.test"
        assert lab_comps["alpha"]["gateway"]["public_url"] == "https://alpha-gateway.test:8443"
        assert lab_comps["alpha"]["runtime"]["listen"] == "127.0.0.1"
        assert lab_comps["alpha"]["runtime"]["port"] == 18001

        assert lab_comps["beta"]["gateway"]["host"] == "beta-gateway.test"
        assert lab_comps["beta"]["gateway"]["public_url"] == "https://beta-gateway.test:8443"
        assert lab_comps["beta"]["runtime"]["listen"] == "127.0.0.1"
        assert lab_comps["beta"]["runtime"]["port"] == 18002

        # 8. Resolução DA MESMA candidata contra o Deployment SERVER
        res_server = run_cmd([
            str(DEPLOYMENT_CLI),
            "resolve",
            str(candidate_manifest_file),
            str(deployment_server_file),
            "--json",
        ])
        assert res_server.returncode == 0, f"Falha ao resolver deployment SERVER: {res_server.stderr}"
        resolved_server = json.loads(res_server.stdout)
        assert resolved_server["status"] == "READY"
        assert resolved_server["deployment_id"] == "server-production-01"
        assert resolved_server["candidate_id"] == "cand-portable-001"

        srv_comps = {c["component_id"]: c for c in resolved_server["components"]}
        assert srv_comps["alpha"]["gateway"]["host"] == "alpha.example.org"
        # Porta 443 para HTTPS é omitida em public_url
        assert srv_comps["alpha"]["gateway"]["public_url"] == "https://alpha.example.org"
        assert srv_comps["alpha"]["runtime"]["listen"] == "10.0.1.50"
        assert srv_comps["alpha"]["runtime"]["port"] == 8080

        assert srv_comps["beta"]["gateway"]["host"] == "beta.example.org"
        assert srv_comps["beta"]["gateway"]["public_url"] == "https://beta.example.org"
        assert srv_comps["beta"]["runtime"]["transport"] == "unix"
        assert srv_comps["beta"]["runtime"]["socket"] == "/run/sister/production/beta.sock"

        # 9. Renderização do gateway HAProxy para ambos os deployments
        dummy_pem = tmp / "test.pem"
        dummy_pem.write_text("DUMMY_CERT", encoding="utf-8")

        resolved_lab_file = tmp / "resolved_lab.json"
        write_json(resolved_lab_file, resolved_lab)
        gw_lab = run_cmd([
            str(GATEWAY_CLI),
            "render",
            str(resolved_lab_file),
            "--listen-address", "127.0.0.1",
            "--listen-port", "8443",
            "--tls-pem", str(dummy_pem),
        ])
        assert gw_lab.returncode == 0, f"Falha ao renderizar HAProxy LAB: {gw_lab.stderr}"
        assert "alpha-gateway.test" in gw_lab.stdout
        assert "beta-gateway.test" in gw_lab.stdout

        resolved_server_file = tmp / "resolved_server.json"
        write_json(resolved_server_file, resolved_server)
        gw_server = run_cmd([
            str(GATEWAY_CLI),
            "render",
            str(resolved_server_file),
            "--listen-address", "0.0.0.0",
            "--listen-port", "443",
            "--tls-pem", str(dummy_pem),
        ])
        assert gw_server.returncode == 0, f"Falha ao renderizar HAProxy SERVER: {gw_server.stderr}"
        assert "alpha.example.org" in gw_server.stdout
        assert "beta.example.org" in gw_server.stdout
        assert "unix@/run/sister/production/beta.sock" in gw_server.stdout

        # 10. Gate de Integridade: alteração de evidência de qualificação deve bloquear deployment resolve
        qual_file = candidate_dir / "evidence" / "composition" / "qualification.json"
        qual_orig = qual_file.read_bytes()
        qual_file.write_bytes(qual_orig + b"\n")
        try:
            res_tamper_qual = run_cmd([
                str(DEPLOYMENT_CLI),
                "resolve",
                str(candidate_manifest_file),
                str(deployment_lab_file),
                "--json",
            ])
            assert res_tamper_qual.returncode != 0, "sister-deployment resolve deveria falhar com qualificação adulterada"
            assert "verificação autoritativa da candidata falhou" in res_tamper_qual.stderr
            assert "hash divergente da evidência de qualificação" in res_tamper_qual.stderr
        finally:
            qual_file.write_bytes(qual_orig)

        # 11. Gate de Integridade: alteração de artefato binário deve bloquear deployment resolve
        art_file = candidate_dir / "components" / "alpha" / "scripts" / "runtime.sh"
        art_orig = art_file.read_bytes()
        art_file.write_bytes(art_orig + b"\n# tampered\n")
        try:
            res_tamper_art = run_cmd([
                str(DEPLOYMENT_CLI),
                "resolve",
                str(candidate_manifest_file),
                str(deployment_lab_file),
                "--json",
            ])
            assert res_tamper_art.returncode != 0, "sister-deployment resolve deveria falhar com artefato adulterado"
            assert "verificação autoritativa da candidata falhou" in res_tamper_art.stderr
            assert "hash divergente do artefato" in res_tamper_art.stderr
        finally:
            art_file.write_bytes(art_orig)


def test_extensibility() -> None:
    """Test Gate D: atravessa o ciclo declarativo completo com sister-candidate e sister-deployment."""
    with tempfile.TemporaryDirectory(prefix="sister-extensibility-") as tmp_text:
        tmp = Path(tmp_text)
        contracts = make_contracts(tmp)

        alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
        beta = make_component(tmp, "sister-beta", "beta", "sister_beta")
        gamma = make_component(tmp, "sister-gamma", "gamma", "sister_gamma")

        git_init_commit(alpha)
        git_init_commit(beta)
        git_init_commit(gamma)

        composition_dir = tmp / "composition"
        composition_path = composition_dir / "composition.json"

        # -------------------------------------------------------------------
        # Passo 1: Composição inicial com alpha + beta
        # -------------------------------------------------------------------
        write_composition_v2_0(
            composition_path,
            ["../sister-alpha", "../sister-beta"],
            composition_id="extensible_ecosystem",
        )

        cand_1_dir = tmp / "cand_1"
        res_c1 = run_cmd([
            str(CANDIDATE_CLI),
            "create",
            str(composition_path),
            "--out", str(cand_1_dir),
            "--contracts-root", str(contracts),
            "--json",
        ])
        assert res_c1.returncode == 0, res_c1.stderr

        dep_1_file = tmp / "deployment_1.json"
        write_json(dep_1_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "dep-ext-01",
            "composition_id": "extensible_ecosystem",
            "gateway": {"protocol": "https", "port": 443},
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 9001},
                    "gateway": {"host": "alpha.example.org"},
                },
                {
                    "system_id": "sister_beta",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 9002},
                    "gateway": {"host": "beta.example.org"},
                },
            ],
        })

        res_1 = run_cmd([
            str(DEPLOYMENT_CLI),
            "resolve",
            str(cand_1_dir / "manifest.json"),
            str(dep_1_file),
            "--json",
        ])
        assert res_1.returncode == 0, res_1.stderr
        doc_r1 = json.loads(res_1.stdout)
        assert doc_r1["status"] == "READY"
        assert {c["component_id"] for c in doc_r1["components"]} == {"alpha", "beta"}

        # -------------------------------------------------------------------
        # Passo 2: Alteração na composição declarativa: + gamma
        # -------------------------------------------------------------------
        write_composition_v2_0(
            composition_path,
            ["../sister-alpha", "../sister-beta", "../sister-gamma"],
            composition_id="extensible_ecosystem",
        )

        cand_2_dir = tmp / "cand_2"
        res_c2 = run_cmd([
            str(CANDIDATE_CLI),
            "create",
            str(composition_path),
            "--out", str(cand_2_dir),
            "--contracts-root", str(contracts),
            "--json",
        ])
        assert res_c2.returncode == 0, res_c2.stderr

        dep_2_file = tmp / "deployment_2.json"
        write_json(dep_2_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "dep-ext-02",
            "composition_id": "extensible_ecosystem",
            "gateway": {"protocol": "https", "port": 443},
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 9001},
                    "gateway": {"host": "alpha.example.org"},
                },
                {
                    "system_id": "sister_beta",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 9002},
                    "gateway": {"host": "beta.example.org"},
                },
                {
                    "system_id": "sister_gamma",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 9003},
                    "gateway": {"host": "gamma.example.org"},
                },
            ],
        })

        # Validação negativa: candidata K2 com deployment D1 (faltando binding de gamma) falha fechado
        res_mismatch_1 = run_cmd([
            str(DEPLOYMENT_CLI),
            "resolve",
            str(cand_2_dir / "manifest.json"),
            str(dep_1_file),
            "--json",
        ])
        assert res_mismatch_1.returncode != 0
        assert "binding faltante para: sister_gamma" in res_mismatch_1.stderr

        # Validação positiva: candidata K2 com deployment D2 resolve READY com 3 componentes
        res_2 = run_cmd([
            str(DEPLOYMENT_CLI),
            "resolve",
            str(cand_2_dir / "manifest.json"),
            str(dep_2_file),
            "--json",
        ])
        assert res_2.returncode == 0, res_2.stderr
        doc_r2 = json.loads(res_2.stdout)
        assert doc_r2["status"] == "READY"
        assert {c["component_id"] for c in doc_r2["components"]} == {"alpha", "beta", "gamma"}

        # -------------------------------------------------------------------
        # Passo 3: Alteração na composição declarativa: remove beta
        # -------------------------------------------------------------------
        write_composition_v2_0(
            composition_path,
            ["../sister-alpha", "../sister-gamma"],
            composition_id="extensible_ecosystem",
        )

        cand_3_dir = tmp / "cand_3"
        res_c3 = run_cmd([
            str(CANDIDATE_CLI),
            "create",
            str(composition_path),
            "--out", str(cand_3_dir),
            "--contracts-root", str(contracts),
            "--json",
        ])
        assert res_c3.returncode == 0, res_c3.stderr

        dep_3_file = tmp / "deployment_3.json"
        write_json(dep_3_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "dep-ext-03",
            "composition_id": "extensible_ecosystem",
            "gateway": {"protocol": "https", "port": 443},
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 9001},
                    "gateway": {"host": "alpha.example.org"},
                },
                {
                    "system_id": "sister_gamma",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 9003},
                    "gateway": {"host": "gamma.example.org"},
                },
            ],
        })

        # Validação negativa: candidata K3 com deployment D2 (contendo binding excedente de beta) falha fechado
        res_mismatch_2 = run_cmd([
            str(DEPLOYMENT_CLI),
            "resolve",
            str(cand_3_dir / "manifest.json"),
            str(dep_2_file),
            "--json",
        ])
        assert res_mismatch_2.returncode != 0
        assert "binding desconhecido: sister_beta" in res_mismatch_2.stderr

        # Validação positiva: candidata K3 com deployment D3 resolve READY com alpha e gamma (sem beta)
        res_3 = run_cmd([
            str(DEPLOYMENT_CLI),
            "resolve",
            str(cand_3_dir / "manifest.json"),
            str(dep_3_file),
            "--json",
        ])
        assert res_3.returncode == 0, res_3.stderr
        doc_r3 = json.loads(res_3.stdout)
        assert doc_r3["status"] == "READY"
        assert {c["component_id"] for c in doc_r3["components"]} == {"alpha", "gamma"}
        assert "beta" not in {c["component_id"] for c in doc_r3["components"]}


def test_absence_of_concrete_knowledge() -> None:
    """Test Gate G: Motor scripts must not contain hardcoded knowledge of concrete participants."""
    motor_scripts = [
        ROOT / "bin" / "sister-composition",
        ROOT / "bin" / "sister-candidate",
        ROOT / "bin" / "sister-deployment",
        ROOT / "bin" / "sister-gateway",
    ]

    forbidden_terms = [
        "nexo",
        "praxis",
        "urt",
        "sister_urt",
        "atmos",
        "8015",
        "8093",
        "8094",
    ]

    for script in motor_scripts:
        assert script.is_file(), f"Script ausente: {script}"
        content = script.read_text(encoding="utf-8").lower()
        for term in forbidden_terms:
            assert term not in content, (
                f"Motor genérico {script.name} contém conhecimento concreto: {term!r}"
            )


def main() -> None:
    test_dual_deployment_portability()
    test_extensibility()
    test_absence_of_concrete_knowledge()
    print("[PASS] dual deployment portability, extensibility, and genericness gates")


if __name__ == "__main__":
    main()
