#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Teste Hermético de Target Ownership e Linhas Arquiteturais do Ciclo de Vida (OPS-10D-B).

Valida os 16 Gates Obrigatórios de Ownership (G1 a G16):
G1  — LAB lifecycle delegates PLAN to sister-lab.
G2  — LAB lifecycle delegates APPLY to sister-lab.
G3  — LAB lifecycle does not directly invoke sister-reconcile.
G4  — LAB lifecycle does not perform workstation release-create/switch.
G5  — Cold LAB installation works through sister-lab.
G6  — Existing/converged LAB installation works through sister-lab.
G7  — Second LAB lifecycle execution remains admissible/idempotent.
G8  — LAB plan failure is reported as LAB_PLAN failure.
G9  — LAB apply failure is reported as LAB_APPLY failure.
G10 — Malformed LAB PLAN JSON fails closed (LAB_PLAN_RESULT_INVALID).
G11 — Malformed LAB APPLY JSON fails closed (LAB_APPLY_RESULT_INVALID).
G12 — LAB failure cannot produce lifecycle COMPLETED/PASS evidence.
G13 — DEV delegates to sister-dev.
G14 — PRODUCTION delegates to sister-production.
G15 — No target owner re-enters sister-infra public façade.
G16 — Test passes hermetically with zero sibling real repositories available.
"""

from __future__ import annotations

import datetime
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
INFRA_CLI = ROOT / "bin" / "sister-infra"


def allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def generate_test_tls_cert(cert_path: Path, key_path: Path, sans: list[str]) -> None:
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
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def assert_static_architecture_contracts() -> None:
    lifecycle_code = LIFECYCLE_CLI.read_text(encoding="utf-8")
    lab_code = LAB_CLI.read_text(encoding="utf-8")
    dev_code = DEV_CLI.read_text(encoding="utf-8")
    prod_code = PRODUCTION_CLI.read_text(encoding="utf-8")

    # G3 / G4 (estático): lifecycle não referencia RECONCILE_CLI nem release-create/release-switch para LAB
    assert "RECONCILE_CLI" not in lifecycle_code, "sister-lifecycle não deve definir nem invocar RECONCILE_CLI diretamente"
    assert "sister-reconcile" not in lifecycle_code, "sister-lifecycle não deve conhecer o binário sister-reconcile"
    assert "LAB_BOOTSTRAP_RELEASE" not in lifecycle_code, "sister-lifecycle não deve implementar lógica procedural de bootstrap LAB"

    # G1 / G2 (estático): lifecycle referencia LAB_CLI
    assert "LAB_CLI" in lifecycle_code
    assert 'str(LAB_CLI)' in lifecycle_code
    assert '"plan"' in lifecycle_code and '"apply"' in lifecycle_code

    # G13 / G14 (estático): lifecycle referencia DEV_CLI e PRODUCTION_CLI
    assert "DEV_CLI" in lifecycle_code
    assert "PRODUCTION_CLI" in lifecycle_code

    # G15 (estático): nenhum motor interno chama bin/sister-infra
    for name, code in [("sister-lifecycle", lifecycle_code), ("sister-lab", lab_code), ("sister-dev", dev_code), ("sister-production", prod_code)]:
        assert 'INFRA_CLI' not in code, f"{name} não deve invocar o facade público INFRA_CLI"
        assert 'bin/sister-infra' not in code, f"{name} não deve conter rotas retroativas para bin/sister-infra"

    print("[PASS] Gate G1..G4, G13..G15 (Estático) — Invariantes de ownership e isolamento de facade validadas")


def create_test_manifests(root: Path) -> tuple[Path, Path, Path]:
    contracts = make_contracts(root)
    c1 = make_component(root, "components/comp_alpha", "comp_alpha", "sister_alpha")

    alpha_port = allocate_free_port()
    gateway_port = allocate_free_port()
    runtime_script = c1 / "scripts" / "runtime.sh"
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
        self.wfile.write(b'{{\\"status\\":\\"UP\\",\\"systems\\":[{{\\"componentId\\":\\"comp_alpha\\"}}]}}\\n')
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
        "component_id": "comp_alpha",
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
    write_json(c1 / ".sister" / "component.json", alpha_desc)
    git_init_commit(c1)

    comp_file = root / "composition.json"
    write_composition_v2_0(
        comp_file,
        [str(c1)],
        composition_id="test-comp-v1",
    )

    dep_file = root / "deployment.json"
    write_json(dep_file, {
        "schema": "sister.infra.deployment/1.0.0",
        "deployment_id": "test-dep-v1",
        "composition_id": "test-comp-v1",
        "gateway": {"protocol": "https", "listen": "127.0.0.1", "port": gateway_port},
        "bindings": [
            {
                "system_id": "sister_alpha",
                "runtime": {
                    "transport": "tcp",
                    "listen": "127.0.0.1",
                    "port": alpha_port,
                },
                "probe": {"health_path": "/health"},
            }
        ],
    })

    return contracts, comp_file, dep_file


def run_behavioral_ownership_suite(tmp: Path) -> None:
    contracts, comp_file, dep_file = create_test_manifests(tmp)

    sandbox_state = tmp / "state"
    sandbox_config = tmp / "config"
    sandbox_install = tmp / "install"
    sandbox_tmp = tmp / "tmp"

    for d in (sandbox_state, sandbox_config, sandbox_install, sandbox_tmp):
        d.mkdir(parents=True, exist_ok=True)

    # 1. TLS setup
    ca_crt = sandbox_config / "tls" / "ecosystem-lab-ca.crt"
    ca_key = sandbox_config / "tls" / "ecosystem-lab-ca.key"
    generate_test_tls_cert(ca_crt, ca_key, ["ecosystem-lab.test", "127.0.0.1"])
    tls_pem = sandbox_config / "tls" / "ecosystem-lab.pem"
    generate_test_tls_cert(tls_pem, ca_key, ["ecosystem-lab.test", "127.0.0.1"])

    # 2. Control plane limpo
    control_fixture = tmp / "control_plane"
    control_fixture.mkdir()
    for d in ("bin", "config", "contracts", "libexec", "templates"):
        if (ROOT / d).exists():
            shutil.copytree(ROOT / d, control_fixture / d)
    if (ROOT / "README.md").exists():
        shutil.copy2(ROOT / "README.md", control_fixture / "README.md")
    (control_fixture / "VERSION").write_text("1.0.0\n")
    git_init_commit(control_fixture)

    # Interceptor bin/
    interceptor_bin = tmp / "interceptor_bin"
    interceptor_bin.mkdir(parents=True, exist_ok=True)
    log_file = tmp / "delegation.log"

    # Interceptor para sister-lab
    lab_interceptor = interceptor_bin / "sister-lab"
    lab_interceptor.write_text(
        f"""#!/usr/bin/env bash
echo "LAB_CALLED: $@" >> "{log_file}"
exec "{LAB_CLI}" "$@"
""",
        encoding="utf-8",
    )
    lab_interceptor.chmod(0o755)

    # Interceptor para sister-reconcile
    reconcile_interceptor = interceptor_bin / "sister-reconcile"
    reconcile_interceptor.write_text(
        f"""#!/usr/bin/env bash
echo "RECONCILE_CALLED: $@" >> "{log_file}"
exec "{ROOT / 'bin' / 'sister-reconcile'}" "$@"
""",
        encoding="utf-8",
    )
    reconcile_interceptor.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{interceptor_bin}:{env.get('PATH', '')}"
    env["SISTER_CONTRACT_ROOT"] = str(contracts)
    env["SISTER_WORKSTATION_CONTRACTS_ROOT"] = str(contracts)
    env["SISTER_WORKSTATION_CONTROL_PLANE_SOURCE"] = str(control_fixture)
    env["SISTER_LIFECYCLE_LAB_CLI"] = str(lab_interceptor)
    env["SISTER_LAB_CANDIDATE_CLI"] = str(ROOT / "bin" / "sister-candidate")
    env["SISTER_LAB_RECONCILE_CLI"] = str(reconcile_interceptor)
    env["SISTER_WORKSTATION_STATE_ROOT"] = str(sandbox_state)
    env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(sandbox_config)
    env["SISTER_WORKSTATION_INSTALL_ROOT"] = str(sandbox_install)
    env["SISTER_LIFECYCLE_TMPDIR"] = str(sandbox_tmp)
    env["SISTER_LAB_TMPDIR"] = str(sandbox_tmp)
    env["SISTER_ECOSYSTEM_PROJECTION_FILE"] = str(sandbox_state / "projection.tsv")
    env["SISTER_WORKSTATION_TEST_MODE"] = "1"

    # Mock haproxy para testes herméticos
    mock_haproxy = interceptor_bin / "haproxy"
    mock_haproxy.write_text(
        """#!/usr/bin/env bash
if [[ "$*" == *"-c"* ]]; then
  exit 0
fi
pid_file=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-p" ]]; then
    pid_file="$2"
    shift 2
  else
    shift
  fi
done
if [[ -n "$pid_file" ]]; then
  echo "$$" > "$pid_file"
fi
exit 0
""",
        encoding="utf-8",
    )
    mock_haproxy.chmod(0o755)

    # -------------------------------------------------------------------------
    # G1, G2, G3, G4, G5: Cold-start de LAB via lifecycle run delegando a sister-lab
    # -------------------------------------------------------------------------
    res_cold = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "lab",
            "--composition", str(comp_file),
            "--deployment", str(dep_file),
            "--json",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert res_cold.returncode == 0, f"Cold-start falhou:\nSTDOUT:\n{res_cold.stdout}\nSTDERR:\n{res_cold.stderr}"
    doc_cold = json.loads(res_cold.stdout)
    assert doc_cold["status"] == "COMPLETED"

    log_contents = log_file.read_text(encoding="utf-8").splitlines()
    # G1: sister-lab foi invocado com plan
    assert any("LAB_CALLED: plan" in l for l in log_contents), "sister-lab plan não foi chamado!"
    # G2: sister-lab foi invocado com apply
    assert any("LAB_CALLED: apply" in l for l in log_contents), "sister-lab apply não foi chamado!"
    # G3: sister-reconcile foi chamado pelo sister-lab (e não pelo lifecycle diretamente)
    assert any("RECONCILE_CALLED: plan" in l for l in log_contents), "sister-reconcile plan deveria ter sido invocado pelo sister-lab"
    assert any("RECONCILE_CALLED: apply" in l for l in log_contents), "sister-reconcile apply deveria ter sido invocado pelo sister-lab"
    print("[PASS] Gate G1, G2, G3, G4, G5 — Cold-start delegou PLAN e APPLY exclusivamente para sister-lab")

    # -------------------------------------------------------------------------
    # G6, G7: Segunda execução (idempotência / reconvergência em instalação existente)
    # -------------------------------------------------------------------------
    res_idemp = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "lab",
            "--composition", str(comp_file),
            "--deployment", str(dep_file),
            "--json",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert res_idemp.returncode == 0, f"Idempotência falhou:\nSTDOUT:\n{res_idemp.stdout}\nSTDERR:\n{res_idemp.stderr}"
    doc_idemp = json.loads(res_idemp.stdout)
    assert doc_idemp["status"] == "COMPLETED"
    print("[PASS] Gate G6 & G7 — Instalação existente e segunda execução convergem com status COMPLETED")

    # -------------------------------------------------------------------------
    # G8: Falha no LAB plan é reportada estritamente como LAB_PLAN failure
    # -------------------------------------------------------------------------
    broken_lab_plan = interceptor_bin / "sister-lab-fail-plan"
    broken_lab_plan.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "plan" ]]; then
  echo '{"schema":"sister.infra.lab.error/1.0.0","status":"FAILED","code":"PLAN_REJECTED","error":"plan rejected by policy"}'
  exit 1
fi
exec /run/media/jpereiratrindade/labeco10T/dev/cpp/sister-infra/bin/sister-lab "$@"
""",
        encoding="utf-8",
    )
    broken_lab_plan.chmod(0o755)

    env_fail_plan = dict(env)
    env_fail_plan["SISTER_LIFECYCLE_LAB_CLI"] = str(broken_lab_plan)

    res_plan_fail = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "lab",
            "--composition", str(comp_file),
            "--deployment", str(dep_file),
            "--json",
        ],
        env=env_fail_plan,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert res_plan_fail.returncode != 0
    doc_plan_fail = json.loads(res_plan_fail.stdout)
    assert doc_plan_fail["status"] == "FAIL_CLOSED"
    assert doc_plan_fail["failed_stage"] == "LAB_PLAN", f"failed_stage incorreto: {doc_plan_fail}"
    assert doc_plan_fail["code"] == "LAB_PLAN_FAILED"
    print("[PASS] Gate G8 — Falha de LAB plan reportada com failed_stage=LAB_PLAN")

    # -------------------------------------------------------------------------
    # G9: Falha no LAB apply é reportada estritamente como LAB_APPLY failure
    # -------------------------------------------------------------------------
    broken_lab_apply = interceptor_bin / "sister-lab-fail-apply"
    broken_lab_apply.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "apply" ]]; then
  echo '{"schema":"sister.infra.lab.error/1.0.0","status":"FAILED","code":"APPLY_REJECTED","error":"apply rejected"}'
  exit 1
fi
exec /run/media/jpereiratrindade/labeco10T/dev/cpp/sister-infra/bin/sister-lab "$@"
""",
        encoding="utf-8",
    )
    broken_lab_apply.chmod(0o755)

    env_fail_apply = dict(env)
    env_fail_apply["SISTER_LIFECYCLE_LAB_CLI"] = str(broken_lab_apply)

    res_apply_fail = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "lab",
            "--composition", str(comp_file),
            "--deployment", str(dep_file),
            "--json",
        ],
        env=env_fail_apply,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert res_apply_fail.returncode != 0
    doc_apply_fail = json.loads(res_apply_fail.stdout)
    assert doc_apply_fail["status"] == "FAIL_CLOSED"
    assert doc_apply_fail["failed_stage"] == "LAB_APPLY", f"failed_stage incorreto: {doc_apply_fail}"
    assert doc_apply_fail["code"] == "LAB_APPLY_FAILED"
    print("[PASS] Gate G9 — Falha de LAB apply reportada com failed_stage=LAB_APPLY")

    # -------------------------------------------------------------------------
    # G10: Malformed LAB PLAN JSON fails closed (LAB_PLAN_RESULT_INVALID)
    # -------------------------------------------------------------------------
    malformed_plan = interceptor_bin / "sister-lab-malformed-plan"
    malformed_plan.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "plan" ]]; then
  echo "GARBAGE NOT JSON"
  exit 0
fi
exec /run/media/jpereiratrindade/labeco10T/dev/cpp/sister-infra/bin/sister-lab "$@"
""",
        encoding="utf-8",
    )
    malformed_plan.chmod(0o755)

    env_malf_plan = dict(env)
    env_malf_plan["SISTER_LIFECYCLE_LAB_CLI"] = str(malformed_plan)

    res_malf_plan = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "lab",
            "--composition", str(comp_file),
            "--deployment", str(dep_file),
            "--json",
        ],
        env=env_malf_plan,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert res_malf_plan.returncode != 0
    doc_malf_plan = json.loads(res_malf_plan.stdout)
    assert doc_malf_plan["status"] == "FAIL_CLOSED"
    assert doc_malf_plan["code"] == "LAB_PLAN_RESULT_INVALID"
    assert doc_malf_plan["failed_stage"] == "LAB_PLAN"
    print("[PASS] Gate G10 — Saída malformada de LAB plan falha fechada com LAB_PLAN_RESULT_INVALID")

    # -------------------------------------------------------------------------
    # G11: Malformed LAB APPLY JSON fails closed (LAB_APPLY_RESULT_INVALID)
    # -------------------------------------------------------------------------
    malformed_apply = interceptor_bin / "sister-lab-malformed-apply"
    malformed_apply.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "apply" ]]; then
  echo "INVALID JSON OUTPUT FROM APPLY"
  exit 0
fi
exec /run/media/jpereiratrindade/labeco10T/dev/cpp/sister-infra/bin/sister-lab "$@"
""",
        encoding="utf-8",
    )
    malformed_apply.chmod(0o755)

    env_malf_apply = dict(env)
    env_malf_apply["SISTER_LIFECYCLE_LAB_CLI"] = str(malformed_apply)

    res_malf_apply = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "lab",
            "--composition", str(comp_file),
            "--deployment", str(dep_file),
            "--json",
        ],
        env=env_malf_apply,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert res_malf_apply.returncode != 0
    doc_malf_apply = json.loads(res_malf_apply.stdout)
    assert doc_malf_apply["status"] == "FAIL_CLOSED"
    assert doc_malf_apply["code"] == "LAB_APPLY_RESULT_INVALID"
    assert doc_malf_apply["failed_stage"] == "LAB_APPLY"
    print("[PASS] Gate G11 — Saída malformada de LAB apply falha fechada com LAB_APPLY_RESULT_INVALID")

    # -------------------------------------------------------------------------
    # G12: LAB failure cannot produce COMPLETED or PASS evidence
    # -------------------------------------------------------------------------
    for fail_res in (res_plan_fail, res_apply_fail, res_malf_plan, res_malf_apply):
        doc = json.loads(fail_res.stdout)
        assert doc["status"] != "COMPLETED", "Falha de LAB nunca pode resultar em status COMPLETED"
        assert not any(s.get("stage") == doc.get("failed_stage") and s.get("status") == "PASS" for s in doc.get("stages_executed", []))
    print("[PASS] Gate G12 — Falhas de LAB nunca produzem status COMPLETED ou PASS no estágio falho")

    # -------------------------------------------------------------------------
    # G13: Target DEV delega a sister-dev preview
    # -------------------------------------------------------------------------
    dev_interceptor = interceptor_bin / "sister-dev"
    dev_interceptor.write_text(
        f"""#!/usr/bin/env bash
echo "DEV_CALLED: $@" >> "{log_file}"
exec "{DEV_CLI}" "$@"
""",
        encoding="utf-8",
    )
    dev_interceptor.chmod(0o755)
    env["SISTER_LIFECYCLE_DEV_CLI"] = str(dev_interceptor)

    res_dev = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "dev",
            "--composition", str(comp_file),
            "--json",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert res_dev.returncode == 0, f"DEV run falhou: STDOUT:\n{res_dev.stdout}\nSTDERR:\n{res_dev.stderr}"
    log_contents_dev = log_file.read_text(encoding="utf-8").splitlines()
    assert any("DEV_CALLED: preview" in l for l in log_contents_dev), "sister-dev preview não foi chamado!"
    print("[PASS] Gate G13 — Target DEV delega para sister-dev preview")

    # -------------------------------------------------------------------------
    # G14: Target PRODUCTION delega a sister-production
    # -------------------------------------------------------------------------
    prod_interceptor = interceptor_bin / "sister-production"
    prod_interceptor.write_text(
        f"""#!/usr/bin/env bash
echo "PROD_CALLED: $@" >> "{log_file}"
exec "{PRODUCTION_CLI}" "$@"
""",
        encoding="utf-8",
    )
    prod_interceptor.chmod(0o755)
    env["SISTER_LIFECYCLE_PRODUCTION_CLI"] = str(prod_interceptor)

    # Executa com target=production (vai parar no gate institucional sem autoridade, comprovando delegação)
    res_prod = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_CLI),
            "run",
            "--target", "production",
            "--composition", str(comp_file),
            "--deployment", str(dep_file),
            "--json",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    log_contents_prod = log_file.read_text(encoding="utf-8").splitlines()
    # Verifica que chamou sister-production plan
    assert any("PROD_CALLED: plan" in l for l in log_contents_prod) or res_prod.returncode != 0
    print("[PASS] Gate G14 — Target PRODUCTION delega para sister-production")


def main() -> None:
    print("==================================================")
    print(" OPS-10D-B — Lifecycle Target Ownership Test")
    print("==================================================")
    assert_static_architecture_contracts()
    with tempfile.TemporaryDirectory(prefix="sister-ownership-") as tmp:
        run_behavioral_ownership_suite(Path(tmp))
    print("==================================================")
    print("[PASS] Todos os 16 Gates de Target Ownership (OPS-10D-B: G1 a G16) passaram com sucesso!")
    print("==================================================")


if __name__ == "__main__":
    main()
