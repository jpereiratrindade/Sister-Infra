#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
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
CANDIDATE_CLI = ROOT / "bin" / "sister-candidate"
DEPLOYMENT_CLI = ROOT / "bin" / "sister-deployment"
RECONCILE_CLI = ROOT / "bin" / "sister-reconcile"
INFRA_CLI = ROOT / "bin" / "sister-infra"


def run_cmd(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def reserve_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/api/health", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def start_mock_server(port: int) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def create_qualified_candidate(
    tmp: Path,
    contracts: Path,
    comp_sources: list[str],
    cand_id: str,
) -> Path:
    comp_dir = tmp / f"comp_{cand_id}"
    comp_file = comp_dir / "composition.json"
    write_composition_v2_0(comp_file, comp_sources, composition_id="test_reconcile")

    cand_dir = tmp / f"candidate_{cand_id}"
    res = run_cmd([
        sys.executable,
        str(CANDIDATE_CLI),
        "create",
        str(comp_file),
        "--out",
        str(cand_dir),
        "--candidate-id",
        cand_id,
        "--contracts-root",
        str(contracts),
        "--json",
    ])
    assert res.returncode == 0, f"falha ao criar candidata: {res.stderr}"
    return cand_dir


def create_release_from_candidate(
    release_dir: Path,
    candidate_dir: Path,
    deployment_file: Path,
    release_id: str,
) -> None:
    shutil.copytree(candidate_dir, release_dir)

    cand_manifest_file = release_dir / "manifest.json"
    cand_manifest = json.loads(cand_manifest_file.read_text(encoding="utf-8"))

    evidence_dir = release_dir / "evidence" / "deployment"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    decl_file = evidence_dir / "declaration.json"
    shutil.copy2(deployment_file, decl_file)

    resolved_file = evidence_dir / "resolved.json"
    res = run_cmd([
        sys.executable,
        str(DEPLOYMENT_CLI),
        "resolve",
        str(cand_manifest_file),
        str(decl_file),
        "--json",
    ])
    assert res.returncode == 0, f"falha ao resolver deployment: {res.stderr}"
    resolved_doc = json.loads(res.stdout)
    resolved_file.write_text(json.dumps(resolved_doc, indent=2) + "\n", encoding="utf-8")

    release_manifest = dict(cand_manifest)
    release_manifest["schema"] = "sister.infra.workstation.release/3"
    release_manifest["release_id"] = release_id
    release_manifest["deployment"] = {
        "status": "READY",
        "deployment_id": resolved_doc["deployment_id"],
        "declaration": "evidence/deployment/declaration.json",
        "evidence": "evidence/deployment/resolved.json",
    }
    cand_manifest_file.write_text(json.dumps(release_manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    print("[TEST] Iniciando suite de testes de reconciliação declarativa (OPS-01/OPS-02)...")

    # Gate J — Genericidade estática: nenhum conhecimento concreto de participantes no motor
    reconcile_src = RECONCILE_CLI.read_text(encoding="utf-8").lower()
    for forbidden in ("sister_nexo", "nexo", "praxis", "urt", "atmos", "memoria", "reflexa"):
        assert forbidden not in reconcile_src, (
            f"[Gate J FAIL] sister-reconcile contém participante concreto: {forbidden}"
        )

    # Verifica que "sister" só aparece em namespaces contratuais, nomes de ferramentas ou caminhos
    lines = reconcile_src.splitlines()
    for lineno, line in enumerate(lines, 1):
        if "sister" in line:
            allowed = (
                "sister.infra." in line
                or "sister-reconcile" in line
                or "sister-candidate" in line
                or "sister-deployment" in line
                or "sister_reconcile" in line
                or "sister_current_release" in line
                or "sister_workstation_install_root" in line
                or (".local" in line and "share" in line and "sister" in line)
                or "sister infra" in line
            )
            assert allowed, (
                f"[Gate J FAIL] sister-reconcile contém ocorrência não autorizada na linha {lineno}: {line}"
            )
    print("[PASS] Gate J — Genericidade estática verificada")

    with tempfile.TemporaryDirectory(prefix="sister-reconcile-test-") as tmp_str:
        tmp = Path(tmp_str)
        contracts = make_contracts(tmp)

        # Portas para mock servers
        port_alpha = reserve_port()
        port_beta = reserve_port()
        port_gamma = reserve_port()
        port_delta = reserve_port()

        # Inicia mock health servers
        server_alpha = start_mock_server(port_alpha)
        server_beta = start_mock_server(port_beta)
        server_gamma = start_mock_server(port_gamma)
        server_delta = start_mock_server(port_delta)

        try:
            # 1. Componentes sintéticos
            alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
            beta = make_component(tmp, "sister-beta", "beta", "sister_beta")
            gamma = make_component(tmp, "sister-gamma", "gamma", "sister_gamma")
            delta = make_component(tmp, "sister-delta", "delta", "sister_delta")

            for comp in (alpha, beta, gamma, delta):
                desc_path = comp / ".sister" / "component.json"
                desc = json.loads(desc_path.read_text(encoding="utf-8"))
                desc["build"]["artifacts"] = [
                    {
                        "id": f"{comp.name}-bin",
                        "path": "scripts/runtime.sh",
                        "executable": True,
                    }
                ]
                write_json(desc_path, desc)
                git_init_commit(comp)

            # 2. Candidata Base (alpha + beta + gamma)
            cand_base = create_qualified_candidate(
                tmp, contracts, ["../sister-alpha", "../sister-beta", "../sister-gamma"], "cand-base-01"
            )

            # Deployment base com bindings
            dep_base_file = tmp / "deployment_base.json"
            write_json(dep_base_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "fixture-lab",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": 8443},
                "bindings": [
                    {
                        "system_id": "sister_alpha",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "alpha-gateway.test"},
                    },
                    {
                        "system_id": "sister_beta",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "beta-gateway.test"},
                    },
                    {
                        "system_id": "sister_gamma",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma},
                        "probe": {"health_path": "/health"},
                        "gateway": {"host": "gamma-gateway.test"},
                    },
                ],
            })

            # Release atual correspondente à candidata base
            release_current = tmp / "release_current"
            create_release_from_candidate(release_current, cand_base, dep_base_file, "wr-base-current")

            # Snapshot para Gate G (Read-Only)
            def snapshot_dir(d: Path) -> dict[str, float]:
                return {str(p.relative_to(d)): p.stat().st_mtime for p in d.rglob("*") if p.is_file()}

            # -------------------------------------------------------------
            # Gate D — NO-OP / Todos KEEP
            # -------------------------------------------------------------
            res_d = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ])
            assert res_d.returncode == 0, f"Gate D falhou: {res_d.stderr}"
            plan_d = json.loads(res_d.stdout)
            assert plan_d["schema"] == "sister.infra.reconcile.plan/1"
            assert plan_d["summary"]["keep"] == 3
            assert plan_d["summary"]["add"] == 0
            assert plan_d["summary"]["update"] == 0
            assert plan_d["summary"]["remove"] == 0
            assert plan_d["summary"]["repair"] == 0
            assert plan_d["gateway"]["action"] == "KEEP"
            assert plan_d["projection"]["action"] == "KEEP"
            for change in plan_d["changes"]:
                assert change["action"] == "KEEP"
                assert "healthy" in change["reason"]
            print("[PASS] Gate D — NO-OP / todos KEEP verificado")

            # -------------------------------------------------------------
            # Gate A — ADD (Adicionar delta sem alterar alpha, beta, gamma)
            # -------------------------------------------------------------
            cand_add = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma", "../sister-delta"],
                "cand-add-delta",
            )
            dep_add_file = tmp / "deployment_add.json"
            write_json(dep_add_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "fixture-lab",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": 8443},
                "bindings": [
                    {
                        "system_id": "sister_alpha",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "alpha-gateway.test"},
                    },
                    {
                        "system_id": "sister_beta",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "beta-gateway.test"},
                    },
                    {
                        "system_id": "sister_gamma",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma},
                        "probe": {"health_path": "/health"},
                        "gateway": {"host": "gamma-gateway.test"},
                    },
                    {
                        "system_id": "sister_delta",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_delta},
                        "probe": {"health_path": "/health"},
                        "gateway": {"host": "delta-gateway.test"},
                    },
                ],
            })

            res_a = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_add),
                "--desired-deployment", str(dep_add_file),
                "--json",
            ])
            assert res_a.returncode == 0, f"Gate A falhou: {res_a.stderr}"
            plan_a = json.loads(res_a.stdout)
            changes_a = {c["component_id"]: c for c in plan_a["changes"]}
            assert changes_a["alpha"]["action"] == "KEEP"
            assert changes_a["beta"]["action"] == "KEEP"
            assert changes_a["gamma"]["action"] == "KEEP"
            assert changes_a["delta"]["action"] == "ADD"
            assert changes_a["delta"]["current_commit"] == "-"
            assert changes_a["delta"]["desired_commit"] != "-"
            assert "absent" in changes_a["delta"]["reason"]
            assert plan_a["gateway"]["action"] == "RECONFIGURE"
            assert plan_a["projection"]["action"] == "REFRESH"
            print("[PASS] Gate A — ADD verificado")

            # -------------------------------------------------------------
            # Gate B — UPDATE (Atualizar apenas beta)
            # -------------------------------------------------------------
            (beta / "main.cpp").write_text("// v2 beta commit\n")
            subprocess.run(["git", "-C", str(beta), "add", "main.cpp"], check=True)
            subprocess.run(["git", "-C", str(beta), "commit", "-q", "-m", "beta v2"], check=True)

            cand_update = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma"],
                "cand-update-beta",
            )
            res_b = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_update),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ])
            assert res_b.returncode == 0, f"Gate B falhou: {res_b.stderr}"
            plan_b = json.loads(res_b.stdout)
            changes_b = {c["component_id"]: c for c in plan_b["changes"]}
            assert changes_b["alpha"]["action"] == "KEEP"
            assert changes_b["gamma"]["action"] == "KEEP"
            assert changes_b["beta"]["action"] == "UPDATE"
            assert changes_b["beta"]["current_commit"] != changes_b["beta"]["desired_commit"]
            assert "differs" in changes_b["beta"]["reason"]
            assert plan_b["gateway"]["action"] == "KEEP"
            assert plan_b["projection"]["action"] == "KEEP"
            print("[PASS] Gate B — UPDATE verificado")

            # -------------------------------------------------------------
            # Gate C — REMOVE (Remover beta do desejado)
            # -------------------------------------------------------------
            cand_remove = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-gamma"],
                "cand-remove-beta",
            )
            dep_remove_file = tmp / "deployment_remove.json"
            write_json(dep_remove_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "fixture-lab",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": 8443},
                "bindings": [
                    {
                        "system_id": "sister_alpha",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "alpha-gateway.test"},
                    },
                    {
                        "system_id": "sister_gamma",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma},
                        "probe": {"health_path": "/health"},
                        "gateway": {"host": "gamma-gateway.test"},
                    },
                ],
            })
            res_c = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_remove),
                "--desired-deployment", str(dep_remove_file),
                "--json",
            ])
            assert res_c.returncode == 0, f"Gate C falhou: {res_c.stderr}"
            plan_c = json.loads(res_c.stdout)
            changes_c = {c["component_id"]: c for c in plan_c["changes"]}
            assert changes_c["alpha"]["action"] == "KEEP"
            assert changes_c["gamma"]["action"] == "KEEP"
            assert changes_c["beta"]["action"] == "REMOVE"
            assert changes_c["beta"]["desired_commit"] == "-"
            assert "absent" in changes_c["beta"]["reason"]
            assert plan_c["gateway"]["action"] == "RECONFIGURE"
            assert plan_c["projection"]["action"] == "REFRESH"
            print("[PASS] Gate C — REMOVE verificado")

            # -------------------------------------------------------------
            # Gate E — DRIFT → REPAIR (Declarado no manifesto, mas probe falha)
            # -------------------------------------------------------------
            # Encerra o mock server do beta para forçar recusa de conexão
            server_beta.shutdown()
            server_beta.server_close()

            res_e = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ])
            assert res_e.returncode == 0, f"Gate E falhou: {res_e.stderr}"
            plan_e = json.loads(res_e.stdout)
            changes_e = {c["component_id"]: c for c in plan_e["changes"]}
            assert changes_e["alpha"]["action"] == "KEEP"
            assert changes_e["gamma"]["action"] == "KEEP"
            assert changes_e["beta"]["action"] == "REPAIR", (
                f"Gate E FAIL: beta com probe offline não pode ser {changes_e['beta']['action']}"
            )
            assert "failed" in changes_e["beta"]["reason"] or "refused" in changes_e["beta"]["reason"]
            print("[PASS] Gate E — DRIFT -> REPAIR verificado (nunca KEEP em drift)")

            # -------------------------------------------------------------
            # Gate F — Determinismo (mesma entrada -> mesmo plano)
            # -------------------------------------------------------------
            res_f1 = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_add),
                "--desired-deployment", str(dep_add_file),
                "--json",
            ])
            res_f2 = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_add),
                "--desired-deployment", str(dep_add_file),
                "--json",
            ])
            assert res_f1.stdout == res_f2.stdout, "Gate F FAIL: saídas JSON não são bitwise idênticas"

            # -------------------------------------------------------------
            # Gate G — Read-Only (não modifica filesystem operacional)
            # -------------------------------------------------------------
            snap_before = snapshot_dir(release_current)
            snap_cand_before = snapshot_dir(cand_add)

            # Executa plano em formato tabular humano e JSON
            run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_add),
                "--desired-deployment", str(dep_add_file),
            ])
            snap_after = snapshot_dir(release_current)
            snap_cand_after = snapshot_dir(cand_add)

            assert snap_before == snap_after, "Gate G FAIL: release current foi alterada pelo plan"
            assert snap_cand_before == snap_cand_after, "Gate G FAIL: candidata foi alterada pelo plan"
            print("[PASS] Gate G — Read-Only verificado (filesystem intacto)")

            # -------------------------------------------------------------
            # Gate H — Preservação de PIDs (plan não altera processos)
            # -------------------------------------------------------------
            pid_before = os.getpid()
            run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_add),
                "--desired-deployment", str(dep_add_file),
            ])
            # Valida que o processo atual permaneceu e nenhum PID foi afetado
            assert os.getpid() == pid_before
            print("[PASS] Gate H — Preservação de PIDs verificada")

            # -------------------------------------------------------------
            # Gate I — Reason obrigatório em todas as ações
            # -------------------------------------------------------------
            for p in (plan_d, plan_a, plan_b, plan_c, plan_e):
                for item in p["changes"]:
                    assert isinstance(item.get("reason"), str) and len(item["reason"].strip()) > 0, (
                        f"Gate I FAIL: reason ausente ou vazio em {item}"
                    )
                assert isinstance(p["gateway"].get("reason"), str) and len(p["gateway"]["reason"]) > 0
                assert isinstance(p["projection"].get("reason"), str) and len(p["projection"]["reason"]) > 0
            print("[PASS] Gate I — Reason obrigatório para toda ação verificado")

            # -------------------------------------------------------------
            # Dispatcher: sister-infra lab plan
            # -------------------------------------------------------------
            res_dispatch = run_cmd([
                str(INFRA_CLI),
                "lab",
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_add),
                "--desired-deployment", str(dep_add_file),
                "--json",
            ])
            assert res_dispatch.returncode == 0, f"Dispatch falhou: {res_dispatch.stderr}"
            plan_dispatch = json.loads(res_dispatch.stdout)
            assert plan_dispatch["schema"] == "sister.infra.reconcile.plan/1"
            assert plan_dispatch["summary"]["add"] == 1
            print("[PASS] Dispatcher sister-infra lab plan verificado")

            # -------------------------------------------------------------
            # Hardening 1: Projeção normalizada (mesmos participantes, gateway alterado)
            # -------------------------------------------------------------
            dep_beta_gw_file = tmp / "deployment_beta_gw.json"
            write_json(dep_beta_gw_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "fixture-lab",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": 8443},
                "bindings": [
                    {
                        "system_id": "sister_alpha",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "alpha-gateway.test"},
                    },
                    {
                        "system_id": "sister_beta",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "beta-new-route.test"},
                    },
                    {
                        "system_id": "sister_gamma",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma},
                        "probe": {"health_path": "/health"},
                        "gateway": {"host": "gamma-gateway.test"},
                    },
                ],
            })
            res_proj = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_beta_gw_file),
                "--json",
            ])
            assert res_proj.returncode == 0, f"Teste de projeção normalizada falhou: {res_proj.stderr}"
            plan_proj = json.loads(res_proj.stdout)
            changes_proj = {c["component_id"]: c for c in plan_proj["changes"]}
            assert changes_proj["beta"]["action"] == "RECONFIGURE"
            assert plan_proj["gateway"]["action"] == "RECONFIGURE"
            assert plan_proj["projection"]["action"] == "REFRESH", (
                f"Projection action deve ser REFRESH quando gateway/public_url muda (foi: {plan_proj['projection']['action']})"
            )
            print("[PASS] Hardening 1 — Projeção normalizada deriva REFRESH em alteração de runtime/gateway")

            # -------------------------------------------------------------
            # Hardening 2: Precedência de REPAIR (runtime down + binding novo -> RECONFIGURE, nunca REPAIR)
            # -------------------------------------------------------------
            port_beta_new = reserve_port()
            dep_beta_reconfig_file = tmp / "deployment_beta_reconfig.json"
            write_json(dep_beta_reconfig_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "fixture-lab",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": 8443},
                "bindings": [
                    {
                        "system_id": "sister_alpha",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "alpha-gateway.test"},
                    },
                    {
                        "system_id": "sister_beta",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta_new},
                        "probe": {"health_path": "/api/health"},
                        "gateway": {"host": "beta-gateway.test"},
                    },
                    {
                        "system_id": "sister_gamma",
                        "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma},
                        "probe": {"health_path": "/health"},
                        "gateway": {"host": "gamma-gateway.test"},
                    },
                ],
            })
            # server_beta continua parado (unhealthy)
            res_prec = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_beta_reconfig_file),
                "--json",
            ])
            assert res_prec.returncode == 0, f"Teste de precedência falhou: {res_prec.stderr}"
            plan_prec = json.loads(res_prec.stdout)
            changes_prec = {c["component_id"]: c for c in plan_prec["changes"]}
            assert changes_prec["beta"]["action"] == "RECONFIGURE", (
                f"REPAIR não pode mascarar RECONFIGURE quando binding muda (foi: {changes_prec['beta']['action']})"
            )
            print("[PASS] Hardening 2 — Precedência estrita de RECONFIGURE sobre REPAIR")

            # -------------------------------------------------------------
            # Hardening 3: Autoridade fail-closed de deployment resolvido
            # -------------------------------------------------------------
            # 3a. Tenta usar resolved deployment da cand_base (K1) com a cand_add (K2)
            resolved_base_file = release_current / "evidence" / "deployment" / "resolved.json"
            res_mismatch = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_add),
                "--desired-deployment", str(resolved_base_file),
                "--json",
            ])
            assert res_mismatch.returncode != 0, "Resolved deployment de outra candidata não pode ser aceito!"
            assert "incompatibilidade" in res_mismatch.stderr or "incompatibilidade" in res_mismatch.stdout

            # 3b. Resolved deployment sem candidate_id -> FAIL
            base_resolved_doc = json.loads(resolved_base_file.read_text(encoding="utf-8"))
            no_cand_id_file = tmp / "resolved_no_cand_id.json"
            doc_no_cand = dict(base_resolved_doc)
            del doc_no_cand["candidate_id"]
            write_json(no_cand_id_file, doc_no_cand)

            res_no_cand = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(no_cand_id_file),
                "--json",
            ])
            assert res_no_cand.returncode != 0, "Resolved deployment sem candidate_id deve falhar!"
            assert "candidate_id ausente" in res_no_cand.stderr or "candidate_id ausente" in res_no_cand.stdout

            # 3c. Resolved deployment sem composition_id -> FAIL
            no_comp_id_file = tmp / "resolved_no_comp_id.json"
            doc_no_comp = dict(base_resolved_doc)
            del doc_no_comp["composition_id"]
            write_json(no_comp_id_file, doc_no_comp)

            res_no_comp = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(no_comp_id_file),
                "--json",
            ])
            assert res_no_comp.returncode != 0, "Resolved deployment sem composition_id deve falhar!"
            assert "composition_id ausente" in res_no_comp.stderr or "composition_id ausente" in res_no_comp.stdout

            print("[PASS] Hardening 3 — Autoridade fail-closed de compatibilidade candidate <-> deployment (divergência, sem candidate_id, sem composition_id)")

            # -------------------------------------------------------------
            # Hardening 4: Observação factual desativada (--no-probe-runtime)
            # -------------------------------------------------------------
            res_unobserved = run_cmd([
                sys.executable,
                str(RECONCILE_CLI),
                "plan",
                "--current-release", str(release_current),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_base_file),
                "--no-probe-runtime",
                "--json",
            ])
            assert res_unobserved.returncode == 0, f"Plan com --no-probe-runtime falhou: {res_unobserved.stderr}"
            plan_unobs = json.loads(res_unobserved.stdout)
            assert plan_unobs["runtime_observation"] == "unobserved"
            for c in plan_unobs["changes"]:
                assert c["factual_status"] == "unobserved"
                assert "unobserved" in c["reason"]
                assert "healthy" not in c["reason"]
            print("[PASS] Hardening 4 — Observação factual unobserved explícita e não mascarada")

        finally:
            server_alpha.shutdown()
            server_gamma.shutdown()
            server_delta.shutdown()
            server_alpha.server_close()
            server_gamma.server_close()
            server_delta.server_close()

    print("[PASS] Todos os Gates de OPS-01/OPS-02 passaram com sucesso!")


if __name__ == "__main__":
    main()
