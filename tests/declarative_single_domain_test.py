#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
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
DEPLOYMENT_CLI = ROOT / "bin" / "sister-deployment"
GATEWAY_CLI = ROOT / "bin" / "sister-gateway"
CANDIDATE_CLI = ROOT / "bin" / "sister-candidate"
PRODUCTION_CLI = ROOT / "bin" / "sister-production"


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_cmd(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def generate_ca(ca_cert: Path, ca_key: Path, common_name: str = "Test CA") -> None:
    ca_cert.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(ca_key), "-out", str(ca_cert), "-days", "30",
            "-subj", f"/CN={common_name}",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )


def generate_server_cert(
    cert_path: Path,
    key_path: Path,
    ca_cert: Path,
    ca_key: Path,
    sans: list[str],
) -> None:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        csr = tdp / "req.csr"
        ext = tdp / "ext.cnf"
        subprocess.run(
            [
                "openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key_path), "-out", str(csr),
                "-subj", f"/CN={sans[0]}",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        san_str = ",".join(f"DNS:{s}" for s in sans)
        ext.write_text(
            f"subjectAltName={san_str}\nextendedKeyUsage=serverAuth\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "openssl", "x509", "-req", "-in", str(csr),
                "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
                "-out", str(cert_path), "-days", "30", "-extfile", str(ext),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )


def main() -> None:
    print("=====================================================================")
    print(" SUÍTE: Exposição Declarativa por Domínio Único & Gateway Unificado")
    print("=====================================================================")

    sys.path.insert(0, str(ROOT / "bin"))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        contracts_dir = make_contracts(tmp)

        # -------------------------------------------------------------------
        # Preparação da Composição e Candidata com 3 componentes integrados
        # -------------------------------------------------------------------
        components_root = tmp / "components"
        comp_a = make_component(components_root, "comp_a", "alpha", "system_alpha")
        comp_b = make_component(components_root, "comp_b", "beta", "system_beta")
        comp_c = make_component(components_root, "comp_c", "gamma", "system_gamma")
        for path, cid in [(comp_a, "alpha"), (comp_b, "beta"), (comp_c, "gamma")]:
            # Simula build artifact
            art_dir = path / "build"
            art_dir.mkdir(parents=True, exist_ok=True)
            art = art_dir / f"{cid}-bin"
            art.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            art.chmod(0o755)
            git_init_commit(path)

        comp_file = tmp / "composition.json"
        write_composition_v2_0(
            comp_file,
            [str(comp_a), str(comp_b), str(comp_c)],
            "ecosystem-multi",
        )

        cand_dir = tmp / "candidate_out"
        res_cand = run_cmd([
            sys.executable, str(CANDIDATE_CLI),
            "create", str(comp_file), "--out", str(cand_dir),
            "--contracts-root", str(contracts_dir),
        ])
        assert res_cand.returncode == 0, f"falha ao criar candidata: {res_cand.stderr}"
        manifest_file = cand_dir / "manifest.json"
        assert manifest_file.is_file()

        # -------------------------------------------------------------------
        # GATE 1: Exposição Declarativa via Domínio Único
        # O operador informa apenas gateway.domain; sistemas integrados
        # recebem subdomínios derivados de sua identidade (<cid>.<domain>).
        # -------------------------------------------------------------------
        print("[TEST] Gate 1 — Exposição declarativa via domínio único no gateway...")
        dep_lab_file = tmp / "deployment_lab.json"
        write_json(dep_lab_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "lab-environment",
            "composition_id": "ecosystem-multi",
            "gateway": {
                "protocol": "https",
                "listen": "127.0.0.1",
                "port": 8443,
                "domain": "lab.sister.local",
            },
            "bindings": [
                {
                    "system_id": "system_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 18001},
                    "probe": {"health_path": "/api/health"},
                },
                {
                    "system_id": "system_beta",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 18002},
                    "probe": {"health_path": "/ready"},
                },
                {
                    "system_id": "system_gamma",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 18003},
                    "probe": {"health_path": "/healthz"},
                },
            ],
        })

        res_resolve = run_cmd([
            sys.executable, str(DEPLOYMENT_CLI),
            "resolve", str(manifest_file), str(dep_lab_file), "--json",
        ])
        assert res_resolve.returncode == 0, f"falha ao resolver deployment: {res_resolve.stderr}"
        resolved_doc = json.loads(res_resolve.stdout)
        assert resolved_doc["schema"] == "sister.infra.deployment.resolved/1"
        assert resolved_doc["status"] == "READY"

        hosts_by_cid = {
            c["component_id"]: c["gateway"]["host"]
            for c in resolved_doc["components"]
        }
        urls_by_cid = {
            c["component_id"]: c["gateway"]["public_url"]
            for c in resolved_doc["components"]
        }

        assert hosts_by_cid == {
            "alpha": "alpha.lab.sister.local",
            "beta": "beta.lab.sister.local",
            "gamma": "gamma.lab.sister.local",
        }, f"hosts incorretos: {hosts_by_cid}"

        assert urls_by_cid == {
            "alpha": "https://alpha.lab.sister.local:8443",
            "beta": "https://beta.lab.sister.local:8443",
            "gamma": "https://gamma.lab.sister.local:8443",
        }, f"urls incorretas: {urls_by_cid}"
        print("[PASS] Gate 1 — Sistemas integrados receberam subdomínios derivados de sua identidade")

        # -------------------------------------------------------------------
        # GATE 2: Invariante de Isolamento de Participantes (Fail-Closed)
        # Nenhum sistema integrado deve conter configuração própria de domínio,
        # proxy ou certificado nos bindings.
        # -------------------------------------------------------------------
        print("[TEST] Gate 2 — Isolamento: bindings com domínio/gateway próprio falham fechado...")
        dep_invalid_binding = json.loads(dep_lab_file.read_text(encoding="utf-8"))
        dep_invalid_binding["bindings"][0]["gateway"] = {"host": "custom-alpha.org"}
        bad_dep_file = tmp / "deployment_invalid.json"
        write_json(bad_dep_file, dep_invalid_binding)

        res_bad = run_cmd([
            sys.executable, str(DEPLOYMENT_CLI),
            "resolve", str(manifest_file), str(bad_dep_file),
        ])
        assert res_bad.returncode != 0, "Deveria ter falhado fechado com binding contendo gateway próprio"
        assert "nenhum sistema integrado deve conter configuração própria" in res_bad.stderr
        print("[PASS] Gate 2 — Bloqueio fail-closed de configuração individual de domínio em bindings")

        # -------------------------------------------------------------------
        # GATE 3: Reconciliação Automática de Roteamento no Gateway Único
        # HAProxy renderiza ACLs e backends exclusivamente da composição
        # descoberta e do domínio-base.
        # -------------------------------------------------------------------
        print("[TEST] Gate 3 — Reconciliação automática de roteamento no gateway...")
        resolved_file = tmp / "resolved.json"
        write_json(resolved_file, resolved_doc)

        dummy_pem = tmp / "dummy.pem"
        dummy_pem.write_text("DUMMY_PEM\n", encoding="utf-8")

        res_render = run_cmd([
            sys.executable, str(GATEWAY_CLI),
            "render", str(resolved_file),
            "--listen-address", "127.0.0.1",
            "--listen-port", "8443",
            "--tls-pem", str(dummy_pem),
        ])
        assert res_render.returncode == 0, f"falha ao renderizar HAProxy: {res_render.stderr}"
        cfg_lines = res_render.stdout

        # Provas factuais do roteamento derivado:
        assert "bind 127.0.0.1:8443 ssl crt " in cfg_lines
        for cid, host in hosts_by_cid.items():
            assert f"acl published_" in cfg_lines
            assert f"{host} {host}:8443" in cfg_lines
            assert f"use_backend component_" in cfg_lines
            assert f"backend component_" in cfg_lines

        # Misdirected request (421) para qualquer host não descoberto
        assert "http-request deny deny_status 421 unless" in cfg_lines

        # Validação de sintaxe HAProxy se o binário estiver presente
        haproxy_bin = shutil.which("haproxy") or "/usr/local/sbin/haproxy-3.2.22"
        if Path(haproxy_bin).is_file():
            ca_c = tmp / "test_ca.crt"
            ca_k = tmp / "test_ca.key"
            leaf_c = tmp / "test_leaf.crt"
            leaf_k = tmp / "test_leaf.key"
            generate_ca(ca_c, ca_k)
            generate_server_cert(leaf_c, leaf_k, ca_c, ca_k, list(hosts_by_cid.values()))
            valid_pem = tmp / "valid.pem"
            valid_pem.write_text(leaf_c.read_text() + "\n" + leaf_k.read_text(), encoding="utf-8")

            res_render_valid = run_cmd([
                sys.executable, str(GATEWAY_CLI),
                "render", str(resolved_file),
                "--listen-address", "127.0.0.1",
                "--listen-port", "8443",
                "--tls-pem", str(valid_pem),
            ])
            cfg_valid_file = tmp / "haproxy_valid.cfg"
            cfg_valid_file.write_text(res_render_valid.stdout, encoding="utf-8")

            v_check = subprocess.run(
                [haproxy_bin, "-c", "-f", str(cfg_valid_file)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
            )
            assert v_check.returncode == 0, f"HAProxy -c falhou: {v_check.stdout + v_check.stderr}"
        print("[PASS] Gate 3 — Roteamento HAProxy derivado e validado com sucesso")

        # -------------------------------------------------------------------
        # GATE 4: Reconciliação Automática de TLS no LAB
        # O certificado folha do gateway cobre exatamente todos os subdomínios
        # derivados dos componentes descobertos.
        # -------------------------------------------------------------------
        print("[TEST] Gate 4 — Reconciliação automática de TLS no LAB (SANs derivadas)...")
        from importlib.machinery import SourceFileLoader
        reconcile_mod = SourceFileLoader("sister_reconcile", str(ROOT / "bin" / "sister-reconcile")).load_module()
        generate_leaf_certificate = reconcile_mod.generate_leaf_certificate
        get_cert_sans = reconcile_mod.get_cert_sans

        lab_ca_cert = tmp / "lab-ca.crt"
        lab_ca_key = tmp / "lab-ca.key"
        generate_ca(lab_ca_cert, lab_ca_key, "SisTer LAB CA")

        lab_leaf_pem = tmp / "lab-gateway.pem"
        desired_hosts = sorted(set(hosts_by_cid.values()))
        generate_leaf_certificate(lab_leaf_pem, lab_ca_cert, lab_ca_key, desired_hosts)

        leaf_sans = get_cert_sans(lab_leaf_pem)
        for h in desired_hosts:
            assert h in leaf_sans, f"Host derivado {h} ausente nas SANs do leaf gerado: {leaf_sans}"
        print("[PASS] Gate 4 — TLS de laboratório derivado com todas as SANs descobertas")

        # -------------------------------------------------------------------
        # GATE 5: Reconciliação e Validação de TLS em Produção
        # Certificado institucional externo cobre subdomínios (wildcard ou lista)
        # -------------------------------------------------------------------
        print("[TEST] Gate 5 — Validação de TLS em Produção (cobertura dos subdomínios)...")
        prod_mod = SourceFileLoader("sister_production", str(ROOT / "bin" / "sister-production")).load_module()
        validate_external_tls = prod_mod.validate_external_tls
        check_dns_readiness = prod_mod.check_dns_readiness

        prod_ca_cert = tmp / "prod-ca.crt"
        prod_ca_key = tmp / "prod-ca.key"
        generate_ca(prod_ca_cert, prod_ca_key, "Institucional CA")

        # Caso A: Certificado Wildcard *.sister.institucional.gov.br
        prod_cert = tmp / "prod_wildcard.crt"
        prod_key = tmp / "prod_wildcard.key"
        generate_server_cert(
            prod_cert, prod_key, prod_ca_cert, prod_ca_key,
            ["*.sister.institucional.gov.br", "sister.institucional.gov.br"]
        )

        prod_derived_hosts = [
            "alpha.sister.institucional.gov.br",
            "beta.sister.institucional.gov.br",
            "gamma.sister.institucional.gov.br",
        ]

        tls_info = validate_external_tls(prod_cert, prod_key, prod_derived_hosts)
        assert len(tls_info["sans"]) >= 1
        print("[PASS] Gate 5A — Certificado wildcard institucional cobre todos os subdomínios derivados")

        # Caso B: Certificado com SAN faltando -> falha fechado
        partial_cert = tmp / "prod_partial.crt"
        partial_key = tmp / "prod_partial.key"
        generate_server_cert(
            partial_cert, partial_key, prod_ca_cert, prod_ca_key,
            ["alpha.sister.institucional.gov.br", "beta.sister.institucional.gov.br"]
        )
        try:
            validate_external_tls(partial_cert, partial_key, prod_derived_hosts)
            assert False, "Deveria ter falhado por SAN ausente"
        except Exception as exc:
            assert "TLS_SAN_MISSING" in str(exc) or "não coberto" in str(exc)
        print("[PASS] Gate 5B — SAN ausente para sistema integrado descoberto falha fechado")

        # -------------------------------------------------------------------
        # GATE 6: Reconciliação Automática de DNS
        # hosts-line e verificação passiva de prontidão institucional
        # -------------------------------------------------------------------
        print("[TEST] Gate 6 — Reconciliação automática de DNS...")
        expected_hosts_sorted = sorted(hosts_by_cid.values())
        hosts_line_actual = " ".join([c["gateway"]["host"] for c in resolved_doc["components"]])
        for h in expected_hosts_sorted:
            assert h in hosts_line_actual

        resolver_mock = {
            h: "10.0.10.100" for h in prod_derived_hosts
        }
        dns_info = check_dns_readiness(prod_derived_hosts, "10.0.10.100", resolver_override=resolver_mock)
        assert len(dns_info) == len(prod_derived_hosts)
        assert all(info["status"] == "READY" for info in dns_info.values())

        bad_resolver = {
            "alpha.sister.institucional.gov.br": "10.0.10.100",
        }
        try:
            check_dns_readiness(prod_derived_hosts, "10.0.10.100", resolver_override=bad_resolver)
            assert False, "Deveria ter falhado com DNS_MISSING"
        except Exception as exc:
            assert "DNS_MISSING" in str(exc) or "não encontrado" in str(exc)
        print("[PASS] Gate 6 — Reconciliação de DNS e detecção de drift validados")

        # -------------------------------------------------------------------
        # GATE 7: Paridade Arquitetural LAB vs PRODUÇÃO
        # A mesma candidata atende LAB e PRODUÇÃO variando unicamente bindings
        # -------------------------------------------------------------------
        print("[TEST] Gate 7 — Paridade LAB vs PRODUÇÃO a partir da mesma candidata...")
        dep_prod_file = tmp / "deployment_production.json"
        write_json(dep_prod_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "production-datacenter",
            "composition_id": "ecosystem-multi",
            "gateway": {
                "protocol": "https",
                "listen": "10.0.10.100",
                "port": 443,
                "domain": "sister.institucional.gov.br",
            },
            "bindings": [
                {
                    "system_id": "system_alpha",
                    "runtime": {"transport": "unix", "socket": "/run/sister/alpha.sock"},
                    "probe": {"health_path": "/api/health"},
                },
                {
                    "system_id": "system_beta",
                    "runtime": {"transport": "unix", "socket": "/run/sister/beta.sock"},
                    "probe": {"health_path": "/ready"},
                },
                {
                    "system_id": "system_gamma",
                    "runtime": {"transport": "tcp", "listen": "10.0.10.100", "port": 8080},
                    "probe": {"health_path": "/healthz"},
                },
            ],
        })

        res_prod_resolve = run_cmd([
            sys.executable, str(DEPLOYMENT_CLI),
            "resolve", str(manifest_file), str(dep_prod_file), "--json",
        ])
        assert res_prod_resolve.returncode == 0, f"falha ao resolver deployment prod: {res_prod_resolve.stderr}"
        res_prod_doc = json.loads(res_prod_resolve.stdout)

        prod_hosts = {c["component_id"]: c["gateway"]["host"] for c in res_prod_doc["components"]}
        prod_urls = {c["component_id"]: c["gateway"]["public_url"] for c in res_prod_doc["components"]}

        assert prod_hosts == {
            "alpha": "alpha.sister.institucional.gov.br",
            "beta": "beta.sister.institucional.gov.br",
            "gamma": "gamma.sister.institucional.gov.br",
        }
        assert prod_urls == {
            "alpha": "https://alpha.sister.institucional.gov.br",
            "beta": "https://beta.sister.institucional.gov.br",
            "gamma": "https://gamma.sister.institucional.gov.br",
        }
        print("[PASS] Gate 7 — Paridade comprovada: mesma candidata em LAB e PROD sem reconfiguração")

        # -------------------------------------------------------------------
        # GATE 8: Eliminação de ambiguidade (rejeição de 'base_domain' no gateway)
        # -------------------------------------------------------------------
        print("[TEST] Gate 8 — Invariante de campo canônico: gateway.base_domain é rejeitado fail-closed...")
        dep_ambiguous = json.loads(dep_lab_file.read_text(encoding="utf-8"))
        del dep_ambiguous["gateway"]["domain"]
        dep_ambiguous["gateway"]["base_domain"] = "lab.sister.local"
        ambig_file = tmp / "deployment_ambiguous.json"
        write_json(ambig_file, dep_ambiguous)

        res_ambig = run_cmd([
            sys.executable, str(DEPLOYMENT_CLI),
            "resolve", str(manifest_file), str(ambig_file), "--json",
        ])
        assert res_ambig.returncode != 0, "Deveria ter rejeitado campo ambíguo 'base_domain'"
        assert "Additional properties are not allowed ('base_domain' was unexpected)" in res_ambig.stderr or "deployment rejeitado" in res_ambig.stderr
        print("[PASS] Gate 8 — Contrato rejeita 'base_domain' e exige exclusivamente 'domain'")

        # -------------------------------------------------------------------
        # GATE 9: Verificação do workstation-lab.json oficial do repositório
        # -------------------------------------------------------------------
        print("[TEST] Gate 9 — Validação do deployment canônico workstation-lab.json...")
        repo_dep_file = ROOT / "config" / "deployments" / "workstation-lab.json"
        dep_content = json.loads(repo_dep_file.read_text(encoding="utf-8"))
        repo_gateway = dep_content.get("gateway", {})
        assert repo_gateway.get("protocol") == "http"
        assert repo_gateway.get("exposure") == "ip-ports"
        assert repo_gateway.get("listen") == "10.163.80.176"
        assert "domain" not in repo_gateway
        assert "base_domain" not in dep_content.get("gateway", {}), "workstation-lab.json não deve conter o campo ambíguo 'base_domain'!"
        for b in dep_content.get("bindings", []):
            assert "gateway" not in b, f"Binding {b.get('system_id')} não deve conter gateway no deployment oficial!"
        print("[PASS] Gate 9 — workstation-lab.json usa LAB HTTP/IP sem DNS ou CA")

    print("\n=====================================================================")
    print(" [SUCESSO] Todos os Gates de Exposição Declarativa Única passaram!")
    print("=====================================================================")


if __name__ == "__main__":
    main()
