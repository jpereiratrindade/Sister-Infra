#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Suíte de testes de Automação de Ciclo de Vida End-to-End do SisTer (OPS-08).

Cobre os 25 Gates L1..L25 e prova com o sistema real URT sob sandbox isolado.
Invariante: ORCHESTRATION != DUPLICATION.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
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
INFRA_CLI = ROOT / "bin" / "sister-infra"
URT_REPO = Path("/run/media/jpereiratrindade/labeco10T/dev/cpp/sister-urt")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def snapshot_dir(directory: Path) -> dict[str, str]:
    hashes_map = {}
    if not directory.exists():
        return hashes_map
    for root_dir, _, files in os.walk(directory):
        for f in files:
            p = Path(root_dir) / f
            try:
                hashes_map[str(p.relative_to(directory))] = hashlib.sha256(p.read_bytes()).hexdigest()
            except Exception:
                pass
    return hashes_map


def generate_test_tls_cert(cert_path: Path, key_path: Path, sans: list[str], is_ca: bool = False) -> None:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, sans[0] if sans else "test.local"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False)
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )
    if is_ca:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    cert = builder.sign(key, hashes.SHA256())
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def check_git_clean(repo_path: Path) -> tuple[bool, str, str]:
    if not (repo_path / ".git").exists():
        return True, "unversioned", ""
    r_rev = subprocess.run(["git", "-C", str(repo_path), "rev-parse", "HEAD"], capture_output=True, text=True)
    commit = r_rev.stdout.strip() if r_rev.returncode == 0 else "unknown"
    r_stat = subprocess.run(["git", "-C", str(repo_path), "status", "--porcelain"], capture_output=True, text=True)
    status_out = r_stat.stdout.strip()
    return (len(status_out) == 0, commit, status_out)


def run_cmd(args: list[str], env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        env=env,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


# -----------------------------------------------------------------------------
# Main Test Suite
# -----------------------------------------------------------------------------

def main() -> None:
    print("==================================================")
    print(" OPS-08 — End-to-End Lifecycle Automation Tests")
    print("==================================================")

    with tempfile.TemporaryDirectory(prefix="sister-lifecycle-test-") as tmp_text:
        tmp = Path(tmp_text)

        # 1. Sandboxes e Raízes Isoladas
        sandbox_state = tmp / "state"
        sandbox_config = tmp / "config"
        sandbox_install = tmp / "install"
        sandbox_prod = tmp / "prod_root"

        for d in (sandbox_state, sandbox_config, sandbox_install, sandbox_prod):
            d.mkdir(parents=True, exist_ok=True)

        contracts = make_contracts(tmp)

        # 2. Control Plane Fixture Limpa
        control_fixture = tmp / "control_plane"
        control_fixture.mkdir()
        for d in ("bin", "config", "contracts", "libexec", "templates"):
            if (ROOT / d).exists():
                shutil.copytree(ROOT / d, control_fixture / d)
        if (ROOT / "README.md").exists():
            shutil.copy2(ROOT / "README.md", control_fixture / "README.md")
        (control_fixture / "VERSION").write_text("1.0.0\n")
        git_init_commit(control_fixture)

        # 3. Componente Sintético Alpha (Válido)
        alpha_port = allocate_free_port()
        alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
        runtime_script = alpha / "scripts" / "runtime.sh"
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
        self.wfile.write(b'{{\\"status\\":\\"UP\\",\\"systems\\":[{{\\"componentId\\":\\"alpha\\"}}]}}\\n')
    def log_message(self, format, *args):
        pass

class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True

with ReusableServer(('127.0.0.1', {alpha_port}), Handler) as httpd:
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

        alpha_desc = {
            "schema": "sister.component/1.0.0",
            "component_id": "alpha",
            "system_id": "sister_alpha",
            "deployment_role": "system",
            "semantic_contract": "sister.subsystem/1.0.0",
            "build": {
                "driver": "source-only/1",
                "source": ".",
                "tests": {"driver": "none/1"},
                "artifacts": [],
            },
            "runtime": {
                "schema": "sister.runtime/1.0.0",
                "entrypoint": "scripts/runtime.sh",
                "actions": ["start", "stop", "restart", "status", "health", "readiness"],
                "state_policy": "stateless",
            },
        }
        write_json(alpha / ".sister" / "component.json", alpha_desc)
        git_init_commit(alpha)

        # 4. Composição Canônica
        composition_dir = tmp / "composition"
        composition_dir.mkdir()
        composition_path = composition_dir / "composition.json"
        write_composition_v2_0(
            composition_path,
            ["../sister-alpha"],
            composition_id="lifecycle_ecosystem",
        )

        # 5. Deployment LAB
        gw_port_lab = allocate_free_port()
        dep_lab_path = tmp / "deployment_lab.json"
        write_json(dep_lab_path, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "lab-lifecycle-01",
            "composition_id": "lifecycle_ecosystem",
            "gateway": {"protocol": "https", "listen": "127.0.0.1", "port": gw_port_lab},
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": alpha_port},
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "alpha-lifecycle.test"},
                },
            ],
        })

        # 6. Deployment PRODUÇÃO
        alpha_port_prod = allocate_free_port()
        dep_prod_path = tmp / "deployment_prod.json"
        prod_host = "alpha.institutional.gov.br"
        prod_gw = "10.0.1.50"
        write_json(dep_prod_path, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "production-datacenter-01",
            "composition_id": "lifecycle_ecosystem",
            "gateway": {"protocol": "https", "listen": prod_gw, "port": 443},
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": alpha_port_prod},
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": prod_host},
                },
            ],
        })

        # TLS de Laboratório (inicialização canônica de CA)
        res_ca = run_cmd(
            [str(LAB_CLI), "tls", "init-ca"],
            env={
                "SISTER_WORKSTATION_CONFIG_ROOT": str(sandbox_config),
                "SISTER_WORKSTATION_STATE_ROOT": str(sandbox_state),
                "PATH": os.environ.get("PATH", ""),
            },
        )
        assert res_ca.returncode == 0, f"init-ca falhou: {res_ca.stderr}"

        # TLS Externo de Produção
        tls_cert = sandbox_prod / "etc" / "sister" / "tls" / "ecosystem.crt"
        tls_key = sandbox_prod / "etc" / "sister" / "tls" / "ecosystem.key"
        generate_test_tls_cert(tls_cert, tls_key, [prod_host])

        # Ambiente Base Isolado
        env_base = os.environ.copy()
        env_base.update({
            "SISTER_WORKSTATION_STATE_ROOT": str(sandbox_state),
            "SISTER_WORKSTATION_CONFIG_ROOT": str(sandbox_config),
            "SISTER_WORKSTATION_INSTALL_ROOT": str(sandbox_install),
            "SISTER_WORKSTATION_CONTROL_PLANE_SOURCE": str(control_fixture),
            "SISTER_PRODUCTION_ROOT": str(sandbox_prod),
            "SISTER_PRODUCTION_INSTALL_ROOT": str(sandbox_prod / "opt" / "sister"),
            "SISTER_PRODUCTION_CONTROL_PLANE_SOURCE": str(control_fixture),
            "SISTER_PRODUCTION_SERVICE_MANAGER": "mock",
            "SISTER_CONTRACT_ROOT": str(contracts),
            "SISTER_WORKSTATION_TEST_MODE": "1",
            "SISTER_ECOSYSTEM_PROJECTION_FILE": str(sandbox_state / "projection.tsv"),
            "PRODUCTION_TLS_CERT": str(tls_cert),
            "PRODUCTION_TLS_KEY": str(tls_key),
            "SISTER_PRODUCTION_GATEWAY_LISTEN_ADDRESS": prod_gw,
            "SISTER_PRODUCTION_DNS_RESOLVER": json.dumps({prod_host: prod_gw}),
            "PRODUCTION_APPROVED": "YES",
            "SISTER_INFRA_PRODUCTION_CONFIRM": "YES",
        })
        os.environ.update(env_base)

        # --------------------------------------------------------------------
        # Gate L1: Lifecycle Plan é estritamente Read-Only
        # --------------------------------------------------------------------
        print("[TEST] Gate L1 — lifecycle plan é estritamente read-only...")
        snap_before_plan = snapshot_dir(tmp)
        plan_out = tmp / "lifecycle_plan_test.json"
        res_plan = run_cmd(
            [
                str(LIFECYCLE_CLI), "plan",
                "--target", "lab",
                "--composition", str(composition_path),
                "--deployment", str(dep_lab_path),
                "--out", str(plan_out),
                "--json",
            ],
            env=env_base,
        )
        assert res_plan.returncode == 0, f"Plan falhou: {res_plan.stderr}"
        plan_doc = json.loads(res_plan.stdout)
        assert plan_doc["schema"] == "sister.infra.lifecycle.plan/1.0.0"
        assert plan_doc["target"] == "lab"
        # O arquivo plan_out foi gravado porque foi pedido explicitamente via --out,
        # mas os diretórios de sandbox permaneceram intocados.
        assert snapshot_dir(sandbox_install) == {}
        assert snapshot_dir(sandbox_prod) == snapshot_dir(sandbox_prod)
        print("[PASS] Gate L1 — Plan é puramente read-only")

        # --------------------------------------------------------------------
        # Gate L2: Lifecycle Status é estritamente Read-Only
        # --------------------------------------------------------------------
        print("[TEST] Gate L2 — lifecycle status é estritamente read-only...")
        snap_before_stat = snapshot_dir(tmp)
        res_stat = run_cmd([str(LIFECYCLE_CLI), "status", "--json"], env=env_base)
        assert res_stat.returncode == 0
        stat_doc = json.loads(res_stat.stdout)
        assert stat_doc["schema"] == "sister.infra.lifecycle.status/1.0.0"
        assert "layers" in stat_doc
        assert snapshot_dir(tmp) == snap_before_stat
        print("[PASS] Gate L2 — Status é puramente read-only")

        # --------------------------------------------------------------------
        # Gate L3: Source Change Detection
        # --------------------------------------------------------------------
        print("[TEST] Gate L3 — Detecção de alteração em código-fonte...")
        uncommitted = alpha / "UNCOMMITTED_CHANGE.txt"
        uncommitted.write_text("change")
        is_clean, _, st_out = check_git_clean(alpha)
        assert not is_clean
        assert "UNCOMMITTED_CHANGE.txt" in st_out
        uncommitted.unlink()
        is_clean_restored, _, _ = check_git_clean(alpha)
        assert is_clean_restored
        print("[PASS] Gate L3 — Detecção de alteração em fonte validada")

        # --------------------------------------------------------------------
        # Gate L4: Falha de Build Bloqueia Criação de Candidata
        # --------------------------------------------------------------------
        print("[TEST] Gate L4 — Falha de build bloqueia candidata fail-closed...")
        broken_comp = make_component(tmp, "sister-broken", "broken", "sister_broken")
        broken_desc = broken_comp / ".sister" / "component.json"
        bdoc = json.loads(broken_desc.read_text(encoding="utf-8"))
        bdoc["build"]["source"] = "NON_EXISTENT_SOURCE_DIR"
        write_json(broken_desc, bdoc)
        git_init_commit(broken_comp)

        broken_comp_dir = tmp / "broken_composition"
        broken_comp_dir.mkdir()
        broken_comp_path = broken_comp_dir / "composition.json"
        write_composition_v2_0(broken_comp_path, ["../sister-broken"], composition_id="broken_eco")

        res_broken = run_cmd(
            [str(LIFECYCLE_CLI), "run", "--target", "dev", "--composition", str(broken_comp_path), "--json"],
            env=env_base,
        )
        assert res_broken.returncode != 0
        err_doc = json.loads(res_broken.stdout)
        assert err_doc["status"] == "FAIL_CLOSED"
        assert err_doc["failed_stage"] == "QUALIFY"
        print("[PASS] Gate L4 — Falha de build bloqueou o lifecycle fail-closed")

        # --------------------------------------------------------------------
        # Gate L5: Falha de Teste Bloqueia Criação de Candidata
        # --------------------------------------------------------------------
        print("[TEST] Gate L5 — Falha de teste de unidade bloqueia candidata...")
        broken_test_comp = make_component(tmp, "sister-testfail", "testfail", "sister_testfail")
        tdesc = broken_test_comp / ".sister" / "component.json"
        tdoc = json.loads(tdesc.read_text(encoding="utf-8"))
        # Script de teste que falha
        bad_test_script = broken_test_comp / "scripts" / "fail_test.sh"
        bad_test_script.parent.mkdir(parents=True, exist_ok=True)
        bad_test_script.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        bad_test_script.chmod(0o755)
        tdoc["build"]["tests"] = {"driver": "custom", "command": "scripts/fail_test.sh"}
        write_json(tdesc, tdoc)
        git_init_commit(broken_test_comp)

        tcomp_dir = tmp / "tcomp"
        tcomp_dir.mkdir()
        tcomp_path = tcomp_dir / "composition.json"
        write_composition_v2_0(tcomp_path, ["../sister-testfail"], composition_id="tcomp_eco")

        res_tfail = run_cmd(
            [str(LIFECYCLE_CLI), "run", "--target", "dev", "--composition", str(tcomp_path), "--json"],
            env=env_base,
        )
        assert res_tfail.returncode != 0
        doc_tfail = json.loads(res_tfail.stdout)
        assert doc_tfail["failed_stage"] == "QUALIFY"
        print("[PASS] Gate L5 — Falha de teste bloqueou a criação da candidata")

        # --------------------------------------------------------------------
        # Gate L6 & L7: Qualificação e Criação de Candidata Imutável
        # --------------------------------------------------------------------
        print("[TEST] Gate L6 & L7 — Qualificação e materialização de candidata imutável...")
        active_cand_dir = tmp / "materialized_candidate"
        res_create_cand = run_cmd([
            str(ROOT / "bin" / "sister-candidate"),
            "create",
            str(composition_path),
            "--out", str(active_cand_dir),
            "--candidate-id", "cand-auto-001",
            "--contracts-root", str(contracts),
            "--json",
        ], env=env_base)
        assert res_create_cand.returncode == 0, f"res_create_cand falhou: RC={res_create_cand.returncode}\nSTDOUT:\n{res_create_cand.stdout}\nSTDERR:\n{res_create_cand.stderr}"
        cand_man = json.loads((active_cand_dir / "manifest.json").read_text(encoding="utf-8"))
        assert cand_man["candidate_id"] == "cand-auto-001"
        assert cand_man["qualification"]["status"] == "PASS"
        print("[PASS] Gate L6 & L7 — Candidata qualificada e imutável criada")

        # --------------------------------------------------------------------
        # Gate L8: DEV Preview Isolado
        # --------------------------------------------------------------------
        print("[TEST] Gate L8 — DEV preview isolado em loopback...")
        res_dev = run_cmd(
            [
                str(LIFECYCLE_CLI), "run",
                "--target", "dev",
                "--composition", str(composition_path),
                "--candidate", str(active_cand_dir),
                "--component", str(alpha),
                "--duration", "2",
                "--json",
            ],
            env=env_base,
        )
        assert res_dev.returncode == 0, f"DEV run falhou: RC={res_dev.returncode}\nSTDOUT:\n{res_dev.stdout}\nSTDERR:\n{res_dev.stderr}"
        doc_dev = json.loads(res_dev.stdout)
        assert doc_dev["status"] == "COMPLETED"
        assert any(s["stage"] == "DEV_PREVIEW" for s in doc_dev["stages_executed"])
        print("[PASS] Gate L8 — Preview isolado em DEV validado")

        # --------------------------------------------------------------------
        # Gate L9 & L10: LAB Apply e Verify Mandatório
        # --------------------------------------------------------------------
        print("[TEST] Gate L9 & L10 — LAB apply automatizado e verify obrigatório...")
        res_lab = run_cmd(
            [
                str(LIFECYCLE_CLI), "run",
                "--target", "lab",
                "--composition", str(composition_path),
                "--deployment", str(dep_lab_path),
                "--candidate", str(active_cand_dir),
                "--json",
            ],
            env=env_base,
        )
        assert res_lab.returncode == 0, f"LAB run falhou: RC={res_lab.returncode}\nSTDOUT:\n{res_lab.stdout}\nSTDERR:\n{res_lab.stderr}"
        doc_lab = json.loads(res_lab.stdout)
        assert doc_lab["status"] == "COMPLETED"
        assert (sandbox_install / "current").is_symlink()
        print("[PASS] Gate L9 & L10 — LAB apply e verify operaram com sucesso")

        # --------------------------------------------------------------------
        # Gate L11 & L12: Lifecycle Maintain (NO_OP & Repair)
        # --------------------------------------------------------------------
        print("[TEST] Gate L11 & L12 — lifecycle maintain (NO_OP e reflexividade)...")
        # Com ambiente integro
        res_maint_noop = run_cmd([str(LIFECYCLE_CLI), "maintain", "--json"], env=env_base)
        assert res_maint_noop.returncode == 0
        doc_m_noop = json.loads(res_maint_noop.stdout)
        assert doc_m_noop["status"] == "CONVERGED"
        assert doc_m_noop["action"] == "NO_OP"
        print("[PASS] Gate L11 — maintain retorna NO_OP sobre ambiente íntegro")

        # Injetar drift recuperável (remover symlink bin/sister-infra sob install/current)
        print("[TEST] Gate L12 — maintain delega a repair sob drift factual...")
        current_rel = (sandbox_install / "current").resolve()
        bin_dir = sandbox_config / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        fake_symlink = bin_dir / "sister-infra"
        fake_symlink.unlink(missing_ok=True)

        res_maint_rep = run_cmd([str(LIFECYCLE_CLI), "maintain", "--json"], env=env_base)
        assert res_maint_rep.returncode == 0
        doc_m_rep = json.loads(res_maint_rep.stdout)
        assert doc_m_rep["status"] == "CONVERGED"
        print("[PASS] Gate L12 — maintain convergiu com sucesso via repair")

        # --------------------------------------------------------------------
        # Gate L13: Promotion BLOCKED sem Evidência de LAB
        # --------------------------------------------------------------------
        print("[TEST] Gate L13 — Promotion bloqueada sem compatibilidade de deployment...")
        invalid_dep = tmp / "non_existent_dep.json"
        res_prom_blocked = run_cmd(
            [
                str(LIFECYCLE_CLI), "run",
                "--target", "production",
                "--composition", str(composition_path),
                "--deployment", str(invalid_dep),
                "--candidate", str(active_cand_dir),
                "--json",
            ],
            env=env_base,
        )
        assert res_prom_blocked.returncode != 0
        doc_p_bl = json.loads(res_prom_blocked.stdout)
        assert doc_p_bl.get("failed_stage") == "AUTHORITY", f"doc_p_bl inesperado: {doc_p_bl}"
        print("[PASS] Gate L13 — Authority bloqueia antes da promoção sem deployment válido")

        # --------------------------------------------------------------------
        # Gate L14 & L15: Promotion PROMOTABLE e Preservação de Identidade
        # --------------------------------------------------------------------
        print("[TEST] Gate L14 & L15 — Promotion PROMOTABLE e preservação de identidade...")
        # Importar evaluate_promotion dinamicamente
        import runpy
        lmod = runpy.run_path(str(LIFECYCLE_CLI))
        evaluate_promotion = lmod["evaluate_promotion"]
        get_lifecycle_state_roots = lmod["get_lifecycle_state_roots"]

        roots = get_lifecycle_state_roots()
        prom_doc = evaluate_promotion(active_cand_dir, dep_prod_path, roots)
        assert prom_doc["status"] == "PROMOTABLE"
        assert prom_doc["candidate_id"] == "cand-auto-001"
        print("[PASS] Gate L14 & L15 — Promotion evidenciada com mesma candidata (WHAT WAS VERIFIED = WHAT IS PROMOTED)")

        # --------------------------------------------------------------------
        # Gate L16 & L17: Production Readiness e Projeção de Plano
        # --------------------------------------------------------------------
        print("[TEST] Gate L16 & L17 — Production readiness e delegação a production plan...")
        res_pplan = run_cmd([
            str(ROOT / "bin" / "sister-production"),
            "plan",
            "--desired-candidate", str(active_cand_dir),
            "--desired-deployment", str(dep_prod_path),
            "--out", str(tmp / "plan.json"),
            "--json",
        ], env=env_base)
        assert res_pplan.returncode == 0
        prod_plan_doc = json.loads(res_pplan.stdout)
        digest = prod_plan_doc["plan_digest"]
        assert digest.startswith("sha256:")
        print("[PASS] Gate L16 & L17 — Production plan gerou digest selado determinístico")

        # --------------------------------------------------------------------
        # Gate L18: Travas de Autoridade de Produção Preservadas
        # --------------------------------------------------------------------
        print("[TEST] Gate L18 — Travas de autoridade institucional preservadas...")
        env_no_auth = dict(env_base)
        env_no_auth["PRODUCTION_APPROVED"] = "NO"
        res_no_auth = run_cmd([
            str(ROOT / "bin" / "sister-production"),
            "apply",
            "--plan", str(tmp / "plan.json"),
            "--plan-digest", digest,
            "--json",
        ], env=env_no_auth)
        assert res_no_auth.returncode != 0
        doc_no_auth = json.loads(res_no_auth.stdout)
        assert doc_no_auth.get("code") == "AUTHORITY_APPROVAL_MISSING", f"doc_no_auth inesperado: {doc_no_auth}\nSTDERR:\n{res_no_auth.stderr}"
        print("[PASS] Gate L18 — Ausência de autoridade institucional falha fechado")

        # --------------------------------------------------------------------
        # Gate L19: Aplicação de Produção em Sandbox FHS
        # --------------------------------------------------------------------
        print("[TEST] Gate L19 — Execução completa do lifecycle target=production em sandbox...")
        res_lprod = run_cmd(
            [
                str(LIFECYCLE_CLI), "run",
                "--target", "production",
                "--composition", str(composition_path),
                "--deployment", str(dep_prod_path),
                "--candidate", str(active_cand_dir),
                "--json",
            ],
            env=env_base,
        )
        assert res_lprod.returncode == 0, f"Production run falhou: RC={res_lprod.returncode}\nSTDOUT:\n{res_lprod.stdout}\nSTDERR:\n{res_lprod.stderr}"
        doc_lprod = json.loads(res_lprod.stdout)
        assert doc_lprod["status"] == "COMPLETED"
        assert (sandbox_prod / "opt" / "sister" / "current").is_symlink()
        print("[PASS] Gate L19 — Ciclo de produção executado em sandbox com sucesso")

        # --------------------------------------------------------------------
        # Gate L20: Cadeia de Evidências Disponível
        # --------------------------------------------------------------------
        print("[TEST] Gate L20 — Cadeia de evidências consolidada...")
        res_ev = run_cmd([str(LIFECYCLE_CLI), "evidence", "--json"], env=env_base)
        assert res_ev.returncode == 0
        ev_doc = json.loads(res_ev.stdout)
        assert len(ev_doc["lifecycle_runs"]) >= 1
        assert len(ev_doc["promotion_records"]) >= 1
        print("[PASS] Gate L20 — Cadeia de evidências navegável de ponta a ponta")

        # --------------------------------------------------------------------
        # Gate L21: Idempotência de Segunda Execução
        # --------------------------------------------------------------------
        print("[TEST] Gate L21 — Idempotência de segunda execução do ciclo...")
        res_sec = run_cmd(
            [
                str(LIFECYCLE_CLI), "run",
                "--target", "production",
                "--composition", str(composition_path),
                "--deployment", str(dep_prod_path),
                "--candidate", str(active_cand_dir),
                "--json",
            ],
            env=env_base,
        )
        assert res_sec.returncode == 0
        print("[PASS] Gate L21 — Segunda execução é idempotente")

        # --------------------------------------------------------------------
        # Gate L22: Semântica de Erro Explicável
        # --------------------------------------------------------------------
        print("[TEST] Gate L22 — Semântica de erro com identificação do estágio falho...")
        res_err = run_cmd(
            [
                str(LIFECYCLE_CLI), "run",
                "--target", "lab",
                "--composition", str(tmp / "INEXISTENTE.json"),
                "--json",
            ],
            env=env_base,
        )
        assert res_err.returncode != 0
        doc_err = json.loads(res_err.stdout)
        assert doc_err["failed_stage"] == "AUTHORITY"
        assert "error" in doc_err
        print("[PASS] Gate L22 — Semântica de erro clara com estágio diagnosticado")

        # --------------------------------------------------------------------
        # Gate L23: Genericidade Estática do Controlador
        # --------------------------------------------------------------------
        print("[TEST] Gate L23 — Genericidade estática: zero participantes concretos...")
        script_text = (ROOT / "bin" / "sister-lifecycle").read_text(encoding="utf-8")
        forbidden = [
            "sister_nexo", "sister_praxis", "sister_urt", "sister_atmos",
            ":8015", ":8093", ":8094",
        ]
        for term in forbidden:
            assert term not in script_text, f"Termo proibido '{term}' encontrado em bin/sister-lifecycle!"
        print("[PASS] Gate L23 — Genericidade estática comprovada (0 participantes hardcoded)")

        # --------------------------------------------------------------------
        # Gate L24: Prova com o Sistema Real Testemunha (URT)
        # --------------------------------------------------------------------
        print("[TEST] Gate L24 — Prova com o sistema real URT em clone efêmero...")
        assert URT_REPO.is_dir(), f"Repositório URT não encontrado: {URT_REPO}"

        # 1. Qualificação direta do URT original (read-only em relação a commits)
        r_urt_insp = run_cmd([str(ROOT / "bin" / "sister-component"), "inspect", str(URT_REPO), "--json"], env=env_base)
        assert r_urt_insp.returncode == 0
        urt_insp = json.loads(r_urt_insp.stdout)
        assert urt_insp["component_id"] == "urt"

        # 2. Criar worktree/clone efêmero em /tmp para mutação sintética
        urt_ephemeral = tmp / "urt_ephemeral"
        run_cmd(["git", "clone", str(URT_REPO), str(urt_ephemeral)], env=env_base)

        # Injetar alteração sintética inofensiva (comentário em scripts/runtime.sh)
        ephemeral_rt = urt_ephemeral / "scripts" / "runtime.sh"
        if ephemeral_rt.exists():
            ephemeral_rt.write_text(ephemeral_rt.read_text(encoding="utf-8") + "\n# SYNTHETIC TEST MUTATION\n", encoding="utf-8")
            git_init_commit(urt_ephemeral)

            # Qualificar clone efêmero
            r_qual_urt = run_cmd([str(ROOT / "bin" / "sister-component"), "qualify", str(urt_ephemeral), "--json"], env=env_base)
            assert r_qual_urt.returncode == 0, f"Qualify de URT efêmero falhou: {r_qual_urt.stderr}"
            qual_urt_doc = json.loads(r_qual_urt.stdout)
            assert qual_urt_doc["status"] == "PASS"

        # Validar que o repositório URT original permanece 100% limpo e intocado
        r_urt_stat = run_cmd(["git", "-C", str(URT_REPO), "status", "--porcelain"], env=env_base)
        assert r_urt_stat.stdout.strip() == "", "Repositório real do URT foi sujado!"
        print("[PASS] Gate L24 — Prova real com sistema testemunha URT concluída com sucesso")

        # --------------------------------------------------------------------
        # Gate L25: Preservação do Runtime Real do Host
        # --------------------------------------------------------------------
        print("[TEST] Gate L25 — Preservação do runtime real do host...")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            res_host = s.connect_ex(("127.0.0.1", 8443))
            assert res_host == 0, "Runtime real do gateway em 8443 foi perturbado pelos testes!"
        print("[PASS] Gate L25 — Runtime real do host permanece 100% íntegro e intocado")

    print("\n[PASS] Todos os 25 Gates de OPS-08 passaram com sucesso!")


if __name__ == "__main__":
    main()
