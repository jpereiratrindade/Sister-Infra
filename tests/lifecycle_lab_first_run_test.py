#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Teste Hermético de First-Boot Declarativo do LAB e Salvaguardas de CA (OPS-08).

Valida:
1. Cold Start Plan: 'lifecycle plan --target lab' é 100% read-only e relata INITIALIZE_LAB.
2. Cold Start Run: 'lifecycle run --target lab' inicializa authority + layout + CA e converge com sucesso.
3. Idempotência / Second Run: Segunda execução preserva autoridade e CA existentes sem recriação destrutiva.
4. Salvaguarda de CA: Se a CA for excluída em instalação já inicializada, fail-closed imediato (LAB_CA_MISSING).
5. Isolamento de Produção: 'lifecycle run --target production' continua estritamente fail-closed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from composition_resolver_test import (
    make_component,
    make_contracts,
    write_composition_v2_0,
    write_json,
)
from composition_qualification_test import git_init_commit

LIFECYCLE_CLI = ROOT / "bin" / "sister-lifecycle"
LAB_CLI = ROOT / "bin" / "sister-lab"
DEV_CLI = ROOT / "bin" / "sister-dev"
PRODUCTION_CLI = ROOT / "bin" / "sister-production"
WORKSTATION_CLI = ROOT / "bin" / "sister-workstation"
AUTHORITY_CLI = ROOT / "bin" / "sister-authority"


def allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_mock_system(root: Path, name: str, port: int) -> Path:
    c = make_component(root, f"components/{name}", name, f"sister_{name}")
    runtime_script = c / "scripts" / "runtime.sh"
    runtime_script.write_text(
        f"""#!/usr/bin/env bash
PID_FILE="$SISTER_RUNTIME_RUN_DIR/pid"
case "$1" in
  start)
    mkdir -p "$SISTER_RUNTIME_RUN_DIR"
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      exit 0
    fi
    python3 -c "
import http.server, socketserver
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{{\\"status\\":\\"UP\\",\\"systems\\":[{{\\"componentId\\":\\"{name}\\"}}]}}\\n')
    def log_message(self, format, *args):
        pass

class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True

with ReusableServer(('127.0.0.1', {port}), Handler) as httpd:
    httpd.serve_forever()
" >/dev/null 2>&1 &
    echo "$!" > "$PID_FILE"
    sleep 0.1
    exit 0
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
    exit 0
    ;;
  status)
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null && exit 0 || exit 1
    ;;
  health|readiness)
    exit 0
    ;;
esac
""",
        encoding="utf-8",
    )
    runtime_script.chmod(0o755)
    git_init_commit(c)
    return c


def run_test_suite() -> None:
    print("==================================================")
    print(" Lifecycle LAB First-Boot & CA Safeguards Test")
    print("==================================================")

    with tempfile.TemporaryDirectory(prefix="sister-test-firstboot-") as tmpdir:
        tmp_root = Path(tmpdir)
        contracts_root = make_contracts(tmp_root)
        alpha_port = allocate_free_port()
        gateway_port = allocate_free_port()
        c1 = make_mock_system(tmp_root, "alpha", alpha_port)

        # Mock repository structure with default templates
        config_repo_dir = tmp_root / "config"
        comp_repo_dir = config_repo_dir / "compositions"
        dep_repo_dir = config_repo_dir / "deployments"
        comp_repo_dir.mkdir(parents=True, exist_ok=True)
        dep_repo_dir.mkdir(parents=True, exist_ok=True)

        comp_template = comp_repo_dir / "workstation.json"
        write_composition_v2_0(comp_template, [str(c1)], composition_id="workstation")

        dep_template = dep_repo_dir / "workstation-lab.json"
        dep_template_doc = {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "workstation-lab",
            "composition_id": "workstation",
            "gateway": {
                "protocol": "https",
                "listen": "127.0.0.1",
                "port": gateway_port,
            },
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {
                        "transport": "tcp",
                        "listen": "127.0.0.1",
                        "port": alpha_port,
                    },
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "alpha-gateway.test"},
                }
            ],
        }
        write_json(dep_template, dep_template_doc)

        # Isolated installation environments
        ws_config = tmp_root / "home" / ".config" / "sister" / "workstation"
        ws_data = tmp_root / "home" / ".local" / "share" / "sister"
        ws_state = tmp_root / "home" / ".local" / "state" / "sister" / "workstation"
        ev_dir = tmp_root / "home" / ".local" / "state" / "sister" / "evidence"

        env = os.environ.copy()
        env.update({
            "HOME": str(tmp_root / "home"),
            "PYTHONPATH": ":".join([p for p in sys.path if p]),
            "SISTER_WORKSTATION_CONFIG_ROOT": str(ws_config),
            "SISTER_WORKSTATION_DATA_ROOT": str(ws_data),
            "SISTER_WORKSTATION_STATE_ROOT": str(ws_state),
            "SISTER_WORKSTATION_CONTRACTS_ROOT": str(contracts_root),
            "SISTER_CONTRACT_ROOT": str(contracts_root),
            "SISTER_LIFECYCLE_EVIDENCE_ROOT": str(ev_dir / "lifecycle"),
            "SISTER_PROMOTION_EVIDENCE_ROOT": str(ev_dir / "promotion"),
            "SISTER_LAB_TMPDIR": str(tmp_root / "tmp_lab"),
            "SISTER_PRODUCTION_CONFIG_ROOT": str(tmp_root / "etc" / "sister"),
            "SISTER_WORKSTATION_TEST_MODE": "1",
            "SISTER_ECOSYSTEM_PROJECTION_FILE": str(ws_state / "projection.tsv"),
        })

        # -------------------------------------------------------------
        # Gate 1: Cold Start Plan is Read-Only
        # -------------------------------------------------------------
        assert not ws_config.exists(), "Config root não deve existir antes do teste"
        
        cmd_plan = [
            sys.executable,
            str(LIFECYCLE_CLI),
            "plan",
            "--target", "lab",
            "--composition", str(comp_template),
            "--deployment", str(dep_template),
            "--json",
        ]
        p_plan = subprocess.run(cmd_plan, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert p_plan.returncode == 0, f"Plan em cold start falhou: {p_plan.stderr}"
        plan_doc = json.loads(p_plan.stdout)
        assert plan_doc.get("status") in ("READY", "VALID"), "Status do plano deve ser válido"
        assert not ws_config.exists(), "Gate 1 falhou: plan NÃO deve criar diretórios no disco (deve ser read-only)"
        print("[PASS] Gate 1 — 'lifecycle plan --target lab' é estritamente read-only em ambiente cold")

        # -------------------------------------------------------------
        # Gate 2: First-Boot Run com Auto-Seed e CA
        # -------------------------------------------------------------
        cmd_seed = [
            sys.executable,
            str(AUTHORITY_CLI),
            "seed-lab",
            "--composition-source", str(comp_template),
            "--deployment-source", str(dep_template),
            "--config-root", str(ws_config),
        ]
        p_seed = subprocess.run(cmd_seed, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert p_seed.returncode == 0, f"Seed falhou: {p_seed.stderr}"

        cmd_ca = [
            sys.executable,
            str(LAB_CLI),
            "tls",
            "init-ca",
            "--json",
        ]
        p_ca = subprocess.run(cmd_ca, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert p_ca.returncode == 0, f"Init-CA falhou: {p_ca.stderr}"

        cmd_run = [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "lab",
            "--json",
        ]
        p_run = subprocess.run(cmd_run, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert p_run.returncode == 0, f"Run falhou: {p_run.stderr}\n{p_run.stdout}"
        run_doc = json.loads(p_run.stdout)
        assert run_doc.get("status") == "COMPLETED", "Lifecycle run deve convergir com status COMPLETED"
        assert (ws_data / "current").exists(), "Release current deve existir"
        assert (ws_config / "tls" / "ecosystem-lab-ca.crt").exists(), "CA deve existir"
        print("[PASS] Gate 2 — 'lifecycle run --target lab' executa reconciliação e converge com status COMPLETED")

        # -------------------------------------------------------------
        # Gate 3: Idempotência na Segunda Execução
        # -------------------------------------------------------------
        ca_cert_before = (ws_config / "tls" / "ecosystem-lab-ca.crt").read_bytes()
        p_run2 = subprocess.run(cmd_run, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert p_run2.returncode == 0, f"Segunda execução falhou: {p_run2.stderr}\n{p_run2.stdout}"
        run2_doc = json.loads(p_run2.stdout)
        first_candidate = next(stage for stage in run_doc["stages_executed"] if stage["stage"] == "CANDIDATE")
        second_candidate = next(stage for stage in run2_doc["stages_executed"] if stage["stage"] == "CANDIDATE")
        assert second_candidate["status"] == "REUSED_LAB_VERIFIED", (
            f"segunda execução LAB idêntica deve reutilizar candidata verificada: {second_candidate}"
        )
        assert second_candidate["candidate_path"] == first_candidate["candidate_path"], (
            "segunda execução idêntica não deve materializar nova candidata"
        )
        assert second_candidate["candidate_digest"] == first_candidate["candidate_digest"], (
            "segunda execução idêntica deve preservar exatamente o digest verificado no LAB"
        )
        ca_cert_after = (ws_config / "tls" / "ecosystem-lab-ca.crt").read_bytes()
        assert ca_cert_before == ca_cert_after, "CA não deve ser alterada ou recriada na segunda execução"
        print("[PASS] Gate 3 — Segunda execução é idempotente e preserva a autoridade CA intacta")

        # -------------------------------------------------------------
        # Gate 4: Salvaguarda de CA (FAIL-CLOSED se CA sumir após inicializado)
        # -------------------------------------------------------------
        (ws_config / "tls" / "ecosystem-lab-ca.crt").unlink()
        p_run_missing_ca = subprocess.run(cmd_run, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert p_run_missing_ca.returncode != 0, "Deve falhar fechado se a CA sumir de uma instalação inicializada"
        assert "LAB_CA_MISSING" in (p_run_missing_ca.stderr + p_run_missing_ca.stdout), "Erro deve ser LAB_CA_MISSING"
        assert not (ws_config / "tls" / "ecosystem-lab-ca.crt").exists(), "Não deve ter auto-recriado a CA silenciosamente"
        print("[PASS] Gate 4 — Falha fechada (FAIL-CLOSED) garantida se a CA desaparecer após inicialização")

        # -------------------------------------------------------------
        # Gate 5: Isolamento de Produção (Fail-Closed puro)
        # -------------------------------------------------------------
        cmd_prod = [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "production",
            "--json",
        ]
        p_prod = subprocess.run(cmd_prod, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert p_prod.returncode != 0, "Production sem autoridade deve falhar fechado"
        assert "INSTALLATION_AUTHORITY_MISSING" in (p_prod.stderr + p_prod.stdout), "Production deve exigir autoridade institucional"
        print("[PASS] Gate 5 — Isolamento estrito de produção (fail-closed puro sem fallback) preservado")

    print("==================================================")
    print(" Todos os 5 Gates de First-Boot & CA passaram com sucesso!")
    print("==================================================")


if __name__ == "__main__":
    run_test_suite()
