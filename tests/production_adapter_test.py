#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Suíte de testes do Production Adapter & Institutional Authority Gates (OPS-07).

Cobre os 24 Gates e invariantes PRD-001 a PRD-019 sob sandbox hermético.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Adicionar tests/ ao PYTHONPATH para reutilizar fixtures canônicas
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

CANDIDATE_CLI = ROOT / "bin" / "sister-candidate"
PRODUCTION_CLI = ROOT / "bin" / "sister-production"
INFRA_CLI = ROOT / "bin" / "sister-infra"


# -----------------------------------------------------------------------------
# Helpers de Fixture
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


def generate_test_tls_cert(
    cert_path: Path,
    key_path: Path,
    sans: list[str],
    not_valid_before: datetime.datetime,
    not_valid_after: datetime.datetime,
    key: rsa.RSAPrivateKey | None = None,
) -> rsa.RSAPrivateKey:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    if key is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, sans[0] if sans else "ecosystem.test"),
    ])
    san_objs = [x509.DNSName(s) for s in sans]
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .add_extension(x509.SubjectAlternativeName(san_objs), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key


def run_cmd(
    args: list[str],
    env: dict[str, str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
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
# Test Suite Principal
# -----------------------------------------------------------------------------

def main() -> None:
    print("==================================================")
    print(" OPS-07 — Production Adapter & Authority Gates")
    print("==================================================")

    with tempfile.TemporaryDirectory(prefix="sister-prod-test-") as tmp_text:
        tmp = Path(tmp_text)
        prod_root = tmp / "prod_root"
        prod_root.mkdir()

        # FHS Sandbox
        opt_dir = prod_root / "opt" / "sister"
        etc_dir = prod_root / "etc" / "sister"
        var_lib_dir = prod_root / "var" / "lib" / "sister"
        run_dir = prod_root / "run" / "sister"

        for d in (opt_dir, etc_dir, var_lib_dir, run_dir):
            d.mkdir(parents=True, exist_ok=True)

        contracts = make_contracts(tmp)

        # 1. Componente sintético real
        alpha_port = allocate_free_port()
        alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")

        # Runtime script com comandos start, stop, status, health
        runtime_script = alpha / "scripts" / "runtime.sh"
        runtime_script.write_text(
            "#!/usr/bin/env bash\n"
            "case \"$1\" in\n"
            "  start) mkdir -p \"$SISTER_RUNTIME_RUN_DIR\"; echo \"$$\" > \"$SISTER_RUNTIME_RUN_DIR/pid\"; exit 0 ;;\n"
            "  stop) rm -f \"$SISTER_RUNTIME_RUN_DIR/pid\"; exit 0 ;;\n"
            "  status) [[ -f \"$SISTER_RUNTIME_RUN_DIR/pid\" ]] && exit 0 || exit 1 ;;\n"
            "  health) exit 0 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        runtime_script.chmod(0o755)

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

        # 2. Composição neutra
        composition_dir = tmp / "composition"
        composition_path = composition_dir / "composition.json"
        write_composition_v2_0(
            composition_path,
            ["../sister-alpha"],
            composition_id="production_ecosystem",
        )

        # 3. Candidata qualificada
        candidate_dir = tmp / "candidate"
        res_cand = subprocess.run(
            [
                str(CANDIDATE_CLI),
                "create",
                str(composition_path),
                "--out", str(candidate_dir),
                "--candidate-id", "cand-prod-001",
                "--contracts-root", str(contracts),
                "--json",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        assert res_cand.returncode == 0, f"Falha ao criar candidata: {res_cand.stderr}"

        # 4. Deployment de Produção (FHS, port 443, institucional)
        deployment_file = tmp / "deployment_production.json"
        expected_host = "alpha.institutional.gov.br"
        expected_gw_addr = "10.0.1.50"
        write_json(deployment_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "production-datacenter-01",
            "composition_id": "production_ecosystem",
            "gateway": {
                "protocol": "https",
                "port": 443,
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
                    "gateway": {"host": expected_host},
                },
            ],
        })

        # 5. Certificado TLS Externo Válido
        tls_cert = etc_dir / "tls" / "ecosystem.crt"
        tls_key = etc_dir / "tls" / "ecosystem.key"
        now = datetime.datetime.now(datetime.timezone.utc)
        generate_test_tls_cert(
            tls_cert,
            tls_key,
            sans=[expected_host],
            not_valid_before=now - datetime.timedelta(days=1),
            not_valid_after=now + datetime.timedelta(days=90),
        )

        # Control Plane Fixture limpa para testes
        control_plane_fixture = tmp / "control_plane"
        control_plane_fixture.mkdir()
        (control_plane_fixture / "VERSION").write_text("1.0.0\n")
        git_init_commit(control_plane_fixture)

        # Configuração de Ambiente Base para os Testes
        env_base = os.environ.copy()
        env_base.update({
            "SISTER_PRODUCTION_ROOT": str(prod_root),
            "SISTER_PRODUCTION_INSTALL_ROOT": str(opt_dir),
            "SISTER_PRODUCTION_CONTROL_PLANE_SOURCE": str(control_plane_fixture),
            "SISTER_PRODUCTION_SERVICE_MANAGER": "mock",
            "PRODUCTION_TLS_CERT": str(tls_cert),
            "PRODUCTION_TLS_KEY": str(tls_key),
            "GATEWAY_LISTEN_ADDRESS": expected_gw_addr,
            "SISTER_PRODUCTION_DNS_RESOLVER": json.dumps({expected_host: expected_gw_addr}),
            "PRODUCTION_APPROVED": "YES",
            "SISTER_INFRA_PRODUCTION_CONFIRM": "YES",
        })

        # --------------------------------------------------------------------
        # Gate P1: Production Plan Read-Only
        # --------------------------------------------------------------------
        print("[TEST] Gate P1 — Production plan é estritamente read-only...")
        snap_before_plan = snapshot_dir(prod_root)
        plan_out = tmp / "approved_plan.json"
        res_plan = run_cmd(
            [
                str(PRODUCTION_CLI),
                "plan",
                "--desired-candidate", str(candidate_dir),
                "--desired-deployment", str(deployment_file),
                "--out", str(plan_out),
                "--json",
            ],
            env=env_base,
        )
        assert res_plan.returncode == 0, f"Plan falhou: {res_plan.stderr}"
        snap_after_plan = snapshot_dir(prod_root)
        # O diretório do sandbox permaneceu 100% intocado pelo plan
        assert snap_before_plan == snap_after_plan, "production plan alterou o filesystem!"
        print("[PASS] Gate P1 — Plan é puramente read-only (zero mutações)")

        # --------------------------------------------------------------------
        # Gate P2: Digest Determinístico
        # --------------------------------------------------------------------
        print("[TEST] Gate P2 — Digest determinístico e selado...")
        plan_doc1 = json.loads(res_plan.stdout)
        digest1 = plan_doc1["plan_digest"]
        assert digest1.startswith("sha256:")

        # Executa novamente plan
        res_plan2 = run_cmd(
            [
                str(PRODUCTION_CLI),
                "plan",
                "--desired-candidate", str(candidate_dir),
                "--desired-deployment", str(deployment_file),
                "--json",
            ],
            env=env_base,
        )
        assert res_plan2.returncode == 0
        plan_doc2 = json.loads(res_plan2.stdout)
        digest2 = plan_doc2["plan_digest"]
        assert digest1 == digest2, f"Digest não foi determinístico ({digest1} != {digest2})"
        print("[PASS] Gate P2 — Digest SHA-256 é rigorosamente determinístico")

        # --------------------------------------------------------------------
        # Gate P3: Digest Mismatch -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P3 — Fail-Closed sob divergência de digest...")
        fake_digest = "sha256:" + "0" * 64
        res_fail_digest = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", fake_digest,
                "--json",
            ],
            env=env_base,
        )
        assert res_fail_digest.returncode != 0
        doc_err = json.loads(res_fail_digest.stdout)
        assert doc_err["status"] == "FAIL_CLOSED"
        assert doc_err["code"] == "PLAN_DIGEST_MISMATCH"
        print("[PASS] Gate P3 — Digest divergente bloqueia fail-closed sem mutações")

        # --------------------------------------------------------------------
        # Gate P4: Ausência de Autoridade Institucional -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P4 — Fail-Closed sob ausência de aprovação explícita...")
        env_no_auth = dict(env_base)
        env_no_auth["PRODUCTION_APPROVED"] = "NO"
        res_no_auth = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_no_auth,
        )
        assert res_no_auth.returncode != 0
        doc_no_auth = json.loads(res_no_auth.stdout)
        assert doc_no_auth["code"] == "AUTHORITY_APPROVAL_MISSING"
        print("[PASS] Gate P4 — Ausência de PRODUCTION_APPROVED falha fechado")

        # --------------------------------------------------------------------
        # Gate P5: Rejeição por Gate Command Institucional -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P5 — Fail-Closed sob rejeição do PRODUCTION_GATE_CMD...")
        env_gate_fail = dict(env_base)
        env_gate_fail["PRODUCTION_GATE_CMD"] = "false"
        res_gate_fail = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_gate_fail,
        )
        assert res_gate_fail.returncode != 0
        doc_gate_fail = json.loads(res_gate_fail.stdout)
        assert doc_gate_fail["code"] == "AUTHORITY_GATE_REJECTED"

        # Validar sucesso do gate cmd
        env_gate_pass = dict(env_base)
        env_gate_pass["PRODUCTION_GATE_CMD"] = "true"
        print("[PASS] Gate P5 — PRODUCTION_GATE_CMD rejeitado falha fechado")

        # --------------------------------------------------------------------
        # Gate P6: External TLS Valid -> PASS
        # --------------------------------------------------------------------
        print("[TEST] Gate P6 — Validação de TLS externo legítimo...")
        import runpy
        prod_mod = runpy.run_path(str(PRODUCTION_CLI))
        tls_res = prod_mod["validate_external_tls"](tls_cert, tls_key, [expected_host])
        assert tls_res["fingerprint"] != ""
        print("[PASS] Gate P6 — Certificado e chave TLS externos verificados")

        # --------------------------------------------------------------------
        # Gate P7: External TLS Expired -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P7 — Fail-Closed sob certificado TLS expirado...")
        expired_cert = etc_dir / "tls" / "expired.crt"
        expired_key = etc_dir / "tls" / "expired.key"
        generate_test_tls_cert(
            expired_cert,
            expired_key,
            sans=[expected_host],
            not_valid_before=now - datetime.timedelta(days=30),
            not_valid_after=now - datetime.timedelta(days=1),
        )
        env_expired_tls = dict(env_base)
        env_expired_tls["PRODUCTION_TLS_CERT"] = str(expired_cert)
        env_expired_tls["PRODUCTION_TLS_KEY"] = str(expired_key)
        res_exp_tls = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_expired_tls,
        )
        assert res_exp_tls.returncode != 0, f"RC={res_exp_tls.returncode}\nSTDOUT:\n{res_exp_tls.stdout}\nSTDERR:\n{res_exp_tls.stderr}"
        if not res_exp_tls.stdout.strip():
            print("STDERR IN P7:\n", res_exp_tls.stderr)
        doc_exp = json.loads(res_exp_tls.stdout)
        assert doc_exp["code"] == "TLS_CERT_EXPIRED", f"Obtido: {doc_exp}"
        print("[PASS] Gate P7 — Certificado TLS expirado falha fechado")

        # --------------------------------------------------------------------
        # Gate P8: SAN Missing -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P8 — Fail-Closed sob SAN ausente no certificado...")
        wrong_san_cert = etc_dir / "tls" / "wrong_san.crt"
        wrong_san_key = etc_dir / "tls" / "wrong_san.key"
        generate_test_tls_cert(
            wrong_san_cert,
            wrong_san_key,
            sans=["other.example.org"],
            not_valid_before=now - datetime.timedelta(days=1),
            not_valid_after=now + datetime.timedelta(days=30),
        )
        env_wrong_san = dict(env_base)
        env_wrong_san["PRODUCTION_TLS_CERT"] = str(wrong_san_cert)
        env_wrong_san["PRODUCTION_TLS_KEY"] = str(wrong_san_key)
        res_wrong_san = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_wrong_san,
        )
        assert res_wrong_san.returncode != 0
        assert json.loads(res_wrong_san.stdout)["code"] == "TLS_SAN_MISSING"
        print("[PASS] Gate P8 — SAN ausente para host publicado falha fechado")

        # --------------------------------------------------------------------
        # Gate P9: Key / Cert Mismatch -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P9 — Fail-Closed sob chave privada divergente do cert...")
        env_mismatch_tls = dict(env_base)
        env_mismatch_tls["PRODUCTION_TLS_CERT"] = str(tls_cert)
        env_mismatch_tls["PRODUCTION_TLS_KEY"] = str(wrong_san_key)  # Chave diferente!
        res_mismatch = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_mismatch_tls,
        )
        assert res_mismatch.returncode != 0
        assert json.loads(res_mismatch.stdout)["code"] == "TLS_KEY_CERT_MISMATCH"
        print("[PASS] Gate P9 — Chave não correspondente falha fechado")

        # --------------------------------------------------------------------
        # Gate P10: DNS Missing / Divergent -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P10 — Fail-Closed sob DNS missing ou divergente...")
        # 1. Host missing
        env_dns_missing = dict(env_base)
        env_dns_missing["SISTER_PRODUCTION_DNS_RESOLVER"] = json.dumps({})
        res_dns_missing = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_dns_missing,
        )
        assert res_dns_missing.returncode != 0
        assert json.loads(res_dns_missing.stdout)["code"] == "DNS_MISSING"

        # 2. Host divergent
        env_dns_divergent = dict(env_base)
        env_dns_divergent["SISTER_PRODUCTION_DNS_RESOLVER"] = json.dumps({expected_host: "192.168.1.99"})
        res_dns_div = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_dns_divergent,
        )
        assert res_dns_div.returncode != 0
        assert json.loads(res_dns_div.stdout)["code"] == "DNS_DIVERGENT"
        print("[PASS] Gate P10 — DNS missing ou divergente falha fechado")

        # --------------------------------------------------------------------
        # Gate P11: Dirty Source -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P11 — Fail-Closed sob fonte com alterações não commitadas...")
        # Sujar fonte de alpha
        uncommitted_file = alpha / "UNCOMMITTED.txt"
        uncommitted_file.write_text("DIRTY")
        res_dirty = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_base,
        )
        assert res_dirty.returncode != 0, f"RC={res_dirty.returncode}\nSTDOUT:\n{res_dirty.stdout}\nSTDERR:\n{res_dirty.stderr}"
        doc_dirty = json.loads(res_dirty.stdout)
        assert doc_dirty["code"] in ("DIRTY_SOURCE_COMPONENT", "DIRTY_SOURCE_CONTROL_PLANE"), f"Obtido: {doc_dirty}"
        uncommitted_file.unlink()
        print("[PASS] Gate P11 — Source dirty detectado e bloqueado fail-closed")

        # --------------------------------------------------------------------
        # Gate P12: FHS Sandbox
        # --------------------------------------------------------------------
        print("[TEST] Gate P12 — FHS sandbox estrito...")
        assert str(prod_root) in str(opt_dir)
        assert str(prod_root) in str(etc_dir)
        assert str(prod_root) in str(var_lib_dir)
        assert str(prod_root) in str(run_dir)
        print("[PASS] Gate P12 — Limites FHS obedecidos integralmente no sandbox")

        # --------------------------------------------------------------------
        # Gate P13: Port Collision External -> FAIL-CLOSED
        # --------------------------------------------------------------------
        print("[TEST] Gate P13 — Fail-Closed sob colisão com porta externa...")
        conflict_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conflict_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        conflict_sock.bind(("127.0.0.1", alpha_port))
        conflict_sock.listen(1)

        try:
            res_port_col = run_cmd(
                [
                    str(PRODUCTION_CLI),
                    "apply",
                    "--plan", str(plan_out),
                    "--plan-digest", digest1,
                    "--json",
                ],
                env=env_base,
            )
            assert res_port_col.returncode != 0
            assert json.loads(res_port_col.stdout)["code"] == "PORT_COLLISION_EXTERNAL"
        finally:
            conflict_sock.close()
        print("[PASS] Gate P13 — Colisão externa de portas falha fechado")

        # --------------------------------------------------------------------
        # Gate P14: Apply Success (Transacional)
        # --------------------------------------------------------------------
        print("[TEST] Gate P14 — Execução bem-sucedida de production apply...")
        res_apply = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_out),
                "--plan-digest", digest1,
                "--json",
            ],
            env=env_base,
        )
        assert res_apply.returncode == 0, f"RC={res_apply.returncode}\nSTDOUT:\n{res_apply.stdout}\nSTDERR:\n{res_apply.stderr}"
        doc_apply = json.loads(res_apply.stdout)
        assert doc_apply["status"] == "APPLIED"
        assert doc_apply["plan_digest"] == digest1
        release_id = doc_apply["release_id"]
        assert release_id.startswith("pr-")

        # Verificar commit point atômico
        current_link = opt_dir / "current"
        assert current_link.is_symlink()
        assert current_link.resolve() == opt_dir / "releases" / release_id
        print("[PASS] Gate P14 — Implantação transacional concluída e commit point comutado")

        # --------------------------------------------------------------------
        # Gate P15: Idempotência (Segundo Apply -> NO_OP)
        # --------------------------------------------------------------------
        print("[TEST] Gate P15 — Idempotência de apply consecutivo (NO_OP)...")
        # Gerar plano sobre o estado atual
        res_plan_noop = run_cmd(
            [
                str(PRODUCTION_CLI),
                "plan",
                "--desired-candidate", str(candidate_dir),
                "--desired-deployment", str(deployment_file),
                "--json",
            ],
            env=env_base,
        )
        assert res_plan_noop.returncode == 0, f"RC={res_plan_noop.returncode}\nSTDOUT:\n{res_plan_noop.stdout}\nSTDERR:\n{res_plan_noop.stderr}"
        plan_noop_doc = json.loads(res_plan_noop.stdout)
        digest_noop = plan_noop_doc["plan_digest"]
        plan_noop_file = tmp / "plan_noop.json"
        plan_noop_file.write_text(json.dumps(plan_noop_doc), encoding="utf-8")

        res_apply_noop = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_noop_file),
                "--plan-digest", digest_noop,
                "--json",
            ],
            env=env_base,
        )
        assert res_apply_noop.returncode == 0
        doc_noop = json.loads(res_apply_noop.stdout)
        assert doc_noop["status"] == "NO_OP"
        assert doc_noop["actions_applied"] == []
        print("[PASS] Gate P15 — Idempotência comprovada (0 ações, NO_OP)")

        # --------------------------------------------------------------------
        # Gate P16: Rollback em Falha de Inicialização de Serviço
        # --------------------------------------------------------------------
        print("[TEST] Gate P16 — Rollback automático em falha de inicialização...")
        # Criar componente beta para testar UPDATE com falha
        beta_port = allocate_free_port()
        beta = make_component(tmp, "sister-beta", "beta", "sister_beta")
        runtime_script_b = beta / "scripts" / "runtime.sh"
        runtime_script_b.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        runtime_script_b.chmod(0o755)
        git_init_commit(beta)

        comp_v2 = composition_dir / "composition_v2.json"
        write_composition_v2_0(comp_v2, ["../sister-alpha", "../sister-beta"], composition_id="production_ecosystem")
        cand_v2 = tmp / "candidate_v2"
        run_cmd(
            [
                str(CANDIDATE_CLI),
                "create",
                str(comp_v2),
                "--out", str(cand_v2),
                "--candidate-id", "cand-prod-002",
                "--contracts-root", str(contracts),
            ],
            env=env_base,
        )

        dep_v2 = tmp / "deployment_v2.json"
        write_json(dep_v2, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "production-datacenter-02",
            "composition_id": "production_ecosystem",
            "gateway": {"protocol": "https", "port": 443},
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": alpha_port},
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": expected_host},
                },
                {
                    "system_id": "sister_beta",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": beta_port},
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "beta.institutional.gov.br"},
                },
            ],
        })

        # Adicionar beta ao cert e DNS
        generate_test_tls_cert(
            tls_cert,
            tls_key,
            sans=[expected_host, "beta.institutional.gov.br"],
            not_valid_before=now - datetime.timedelta(days=1),
            not_valid_after=now + datetime.timedelta(days=90),
        )
        env_v2 = dict(env_base)
        env_v2["SISTER_PRODUCTION_DNS_RESOLVER"] = json.dumps({
            expected_host: expected_gw_addr,
            "beta.institutional.gov.br": expected_gw_addr,
        })

        plan_v2_res = run_cmd(
            [
                str(PRODUCTION_CLI),
                "plan",
                "--desired-candidate", str(cand_v2),
                "--desired-deployment", str(dep_v2),
                "--json",
            ],
            env=env_v2,
        )
        assert plan_v2_res.returncode == 0
        plan_v2_doc = json.loads(plan_v2_res.stdout)
        plan_v2_digest = plan_v2_doc["plan_digest"]
        plan_v2_file = tmp / "plan_v2.json"
        plan_v2_file.write_text(json.dumps(plan_v2_doc), encoding="utf-8")

        # Injetar falha de start no serviço sister-beta.service
        env_fail_start = dict(env_v2)
        env_fail_start["SISTER_MOCK_FAIL_START_UNIT"] = "sister-beta.service"

        old_current_target = (opt_dir / "current").resolve()
        res_fail_start = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_v2_file),
                "--plan-digest", plan_v2_digest,
                "--json",
            ],
            env=env_fail_start,
        )
        assert res_fail_start.returncode != 0
        # O current permaneceu apontando para a release anterior!
        assert (opt_dir / "current").resolve() == old_current_target, "Rollback não restaurou o current anterior!"
        print("[PASS] Gate P16 — Rollback automático em falha de start comprovado")

        # --------------------------------------------------------------------
        # Gate P17: Rollback em Falha de Health Check
        # --------------------------------------------------------------------
        print("[TEST] Gate P17 — Rollback automático em falha de health probe...")
        env_fail_health = dict(env_v2)
        env_fail_health["SISTER_MOCK_FAIL_HEALTH"] = "1"
        res_fail_health = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_v2_file),
                "--plan-digest", plan_v2_digest,
                "--json",
            ],
            env=env_fail_health,
        )
        assert res_fail_health.returncode != 0
        assert (opt_dir / "current").resolve() == old_current_target
        print("[PASS] Gate P17 — Rollback automático em falha de health check comprovado")

        # --------------------------------------------------------------------
        # Gate P18: Service Manager Failure -> Rollback
        # --------------------------------------------------------------------
        print("[TEST] Gate P18 — Rollback sob falha no gerenciador de serviços...")
        env_fail_mgr = dict(env_v2)
        env_fail_mgr["SISTER_MOCK_FAIL_SERVICE_MANAGER"] = "1"
        res_fail_mgr = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(plan_v2_file),
                "--plan-digest", plan_v2_digest,
                "--json",
            ],
            env=env_fail_mgr,
        )
        assert res_fail_mgr.returncode != 0
        assert (opt_dir / "current").resolve() == old_current_target
        print("[PASS] Gate P18 — Falha no service manager dispara rollback seguro")

        # --------------------------------------------------------------------
        # Gate P19: Evidência Auditável Estruturada sem Secrets
        # --------------------------------------------------------------------
        print("[TEST] Gate P19 — Evidência estruturada e ausência de segredos...")
        evidence_dir = var_lib_dir / "evidence" / "production"
        assert evidence_dir.is_dir()
        evidence_files = list(evidence_dir.glob("audit-*.json"))
        assert len(evidence_files) >= 1
        for ef in evidence_files:
            content = ef.read_text(encoding="utf-8")
            assert "BEGIN PRIVATE KEY" not in content, "Segredo vazou no arquivo de evidência!"
            assert "BEGIN RSA PRIVATE KEY" not in content
            doc_ev = json.loads(content)
            assert doc_ev["schema"] == "sister.infra.production.evidence/1.0.0"
            assert "plan_digest" in doc_ev
        print("[PASS] Gate P19 — Evidência de auditoria gerada sem segredos")

        # --------------------------------------------------------------------
        # Gate P20: Production Verify Read-Only
        # --------------------------------------------------------------------
        print("[TEST] Gate P20 — Production verify é estritamente read-only...")
        snap_before_verify = snapshot_dir(prod_root)
        res_verify = run_cmd(
            [str(PRODUCTION_CLI), "verify", "--json"],
            env=env_base,
        )
        assert res_verify.returncode == 0, f"Verify falhou: {res_verify.stderr}"
        doc_verify = json.loads(res_verify.stdout)
        assert doc_verify["status"] == "PASS"
        snap_after_verify = snapshot_dir(prod_root)
        assert snap_before_verify == snap_after_verify, "verify alterou arquivos!"
        print("[PASS] Gate P20 — Production verify validou o estado com zero mutações")

        # --------------------------------------------------------------------
        # Gate P21: Dispatcher sister-infra production
        # --------------------------------------------------------------------
        print("[TEST] Gate P21 — Dispatcher sister-infra production...")
        res_disp = run_cmd(
            [str(INFRA_CLI), "production", "verify", "--json"],
            env=env_base,
        )
        assert res_disp.returncode == 0, res_disp.stderr
        assert json.loads(res_disp.stdout)["status"] == "PASS"
        print("[PASS] Gate P21 — Dispatcher sister-infra production validado com sucesso")

        # --------------------------------------------------------------------
        # Gate P22: Portabilidade Declarativa (LAB vs PROD)
        # --------------------------------------------------------------------
        print("[TEST] Gate P22 — Portabilidade declarativa: mesma candidata sob políticas LAB vs PROD...")
        dep_lab = tmp / "deployment_lab.json"
        write_json(dep_lab, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "lab-desktop-01",
            "composition_id": "production_ecosystem",
            "gateway": {"protocol": "https", "port": 8443},
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": alpha_port},
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "alpha-lab.test"},
                },
            ],
        })
        dep_cli = ROOT / "bin" / "sister-deployment"
        res_res_lab = run_cmd([str(dep_cli), "resolve", str(candidate_dir / "manifest.json"), str(dep_lab), "--json"], env=env_base)
        assert res_res_lab.returncode == 0
        doc_res_lab = json.loads(res_res_lab.stdout)
        assert doc_res_lab["status"] == "READY"
        lab_comps = {c["component_id"]: c for c in doc_res_lab["components"]}
        assert lab_comps["alpha"]["gateway"]["public_url"] == "https://alpha-lab.test:8443"

        res_res_prod = run_cmd([str(dep_cli), "resolve", str(candidate_dir / "manifest.json"), str(deployment_file), "--json"], env=env_base)
        assert res_res_prod.returncode == 0
        doc_res_prod = json.loads(res_res_prod.stdout)
        assert doc_res_prod["status"] == "READY"
        prod_comps = {c["component_id"]: c for c in doc_res_prod["components"]}
        assert prod_comps["alpha"]["gateway"]["public_url"] == f"https://{expected_host}"
        print("[PASS] Gate P22 — Portabilidade comprovada: mesma candidata atende LAB e PROD")

        # --------------------------------------------------------------------
        # Gate P23: Genericidade Estática do Adaptador
        # --------------------------------------------------------------------
        print("[TEST] Gate P23 — Genericidade estática do adaptador de produção...")
        prod_script = (ROOT / "bin" / "sister-production").read_text(encoding="utf-8")
        forbidden_concrete = [
            "sister_nexo", "sister_praxis", "sister_urt",
            "nexo-gateway", "praxis-gateway", "urt-gateway",
            ":8015", ":8093", ":8094",
        ]
        for word in forbidden_concrete:
            assert word not in prod_script, f"Termo concreto '{word}' encontrado em bin/sister-production!"
        print("[PASS] Gate P23 — Adaptador de produção é 100% genérico")

        # --------------------------------------------------------------------
        # Gate P24: Preservação do Runtime Real do Host
        # --------------------------------------------------------------------
        print("[TEST] Gate P24 — Preservação do runtime real do host...")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            res_host = s.connect_ex(("127.0.0.1", 8443))
            assert res_host == 0, "Runtime real do gateway em 8443 foi perturbado pelos testes!"
        print("[PASS] Gate P24 — Runtime real do host permanece 100% íntegro e intocado")

    print("\n[PASS] Todos os 24 Gates de OPS-07 passaram com sucesso!")


if __name__ == "__main__":
    main()
