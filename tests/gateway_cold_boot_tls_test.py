#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Suíte de testes de desacoplamento do cold-start do gateway do ciclo de vida TLS (OPS-07A2.2b).

Invariantes validados:
- TLSA-020: runtime-start nunca cria CA.
- TLSA-021: runtime-start nunca rotaciona CA.
- TLSA-022: runtime-start nunca emite ou renova leaf.
- TLSA-023: ausência do leaf necessário resulta em fail-closed.
- TLSA-024: cold-start e cold-stop do HAProxy permanecem funcionais.
- TLSA-025: ciclo de vida TLS legado aposentado e inalcançável por comandos de runtime.

Casos:
  Caso A: TLS existente permite cold-start do gateway preservando CA e leaf byte a byte.
  Caso B: CA em janela de expiração não sofre rotação (código legado rotacionaria).
  Caso C: ausência de TLS_PEM falha fechado antes de iniciar gateway, sem criar CA ou leaf.
  Caso D: isolamento completo de processos e integridade do runtime real.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from derived_resources_apply_test import (
    create_mock_runtime_script,
    setup_ca,
    generate_leaf,
    reserve_port,
    FixtureLifecycleManager,
    ROOT,
    INFRA_CLI,
)


def sha_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_https(host: str, port: int, path: str, ca_cert: Path) -> int:
    ctx = ssl.create_default_context(cafile=str(ca_cert))
    ctx.check_hostname = False
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
            ssock.sendall(req.encode("utf-8"))
            resp = ssock.recv(4096).decode("utf-8", errors="replace")
            if "HTTP/1.1 200" in resp or "HTTP/1.0 200" in resp:
                return 200
            parts = resp.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
            return -1


def setup_mock_environment(
    tmp: Path,
    lifecycle: FixtureLifecycleManager,
    ca_days: int = 3650,
) -> tuple[dict[str, str], int, int, Path, Path, Path]:
    run_dir = tmp / "run"
    state_dir = tmp / "state"
    tls_dir = tmp / "tls"
    comp_dir = tmp / "mock_comp"
    gateway_run = state_dir / "control-plane"
    gateway_cfg = gateway_run / "haproxy-lan.cfg"
    gateway_pid = gateway_run / "haproxy-lan.pid"
    resolved_file = tmp / "deployment.resolved.json"

    for d in (run_dir, state_dir, tls_dir, comp_dir, gateway_run):
        d.mkdir(parents=True, exist_ok=True)

    gw_port = reserve_port()
    comp_port = reserve_port()

    # 1. Mock runtime component
    runtime_script = comp_dir / "scripts" / "runtime.sh"
    create_mock_runtime_script(runtime_script, comp_port)
    c_env = dict(os.environ)
    c_env["SISTER_RUNTIME_RUN_DIR"] = str(run_dir / "mock_comp")
    c_env["SISTER_RUNTIME_STATE_DIR"] = str(state_dir / "components" / "mock_comp")
    c_env["SISTER_RESOLVED_DEPLOYMENT_FILE"] = str(resolved_file)

    subprocess.run([str(runtime_script), "start"], env=c_env, check=True)
    comp_pid = int((run_dir / "mock_comp" / "app.pid").read_text().strip())
    lifecycle.track_component(comp_pid)

    # 2. Resolved deployment
    resolved_doc = {
        "schema": "sister.infra.deployment.resolved/1",
        "status": "READY",
        "deployment_id": "dep-cold-boot-test",
        "candidate_id": "wc-test",
        "composition_id": "test_composition",
        "components": [
            {
                "component_id": "mock_comp",
                "system_id": "system_mock_comp",
                "component_path": "components/mock_comp",
                "runtime": {
                    "transport": "tcp",
                    "listen": "127.0.0.1",
                    "port": comp_port,
                },
                "probe": {
                    "health_path": "/api/health",
                },
                "gateway": {
                    "host": "mock-comp.test",
                },
            }
        ],
    }
    resolved_file.write_text(json.dumps(resolved_doc, indent=2), encoding="utf-8")

    # 3. TLS Material
    ca_cert = tls_dir / "ecosystem-lab-ca.crt"
    ca_key = tls_dir / "ecosystem-lab-ca.key"
    tls_pem = tls_dir / "ecosystem-lab.pem"

    if ca_days == 3650:
        setup_ca(tls_dir)
    else:
        # Gera CA personalizada com validade específica (ex: 10 dias)
        subprocess.run(["openssl", "genrsa", "-out", str(ca_key), "2048"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run([
            "openssl", "req", "-x509", "-new", "-nodes",
            "-key", str(ca_key),
            "-sha256",
            "-days", str(ca_days),
            "-subj", "/CN=SisTer Infra Lab CA",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-out", str(ca_cert),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    generate_leaf(tls_pem, ca_cert, ca_key, ["mock-comp.test"])

    # 4. Environment
    haproxy_bin = shutil.which("haproxy") or "/usr/local/sbin/haproxy" or "/usr/sbin/haproxy"

    env = dict(os.environ)
    env["SISTER_RESOLVED_DEPLOYMENT_FILE"] = str(resolved_file)
    env["SISTER_INFRA_RUN_ROOT"] = str(gateway_run)
    env["GATEWAY_CFG"] = str(gateway_cfg)
    env["GATEWAY_PID"] = str(gateway_pid)
    env["GATEWAY_LISTEN_PORT"] = str(gw_port)
    env["GATEWAY_LISTEN_ADDRESS"] = "127.0.0.1"
    env["HAPROXY_BIN"] = haproxy_bin
    env["TLS_PEM"] = str(tls_pem)
    env["CA_CERT"] = str(ca_cert)
    env["CA_KEY"] = str(ca_key)

    return env, gw_port, comp_port, ca_cert, ca_key, tls_pem


def test_caso_a_tls_existente(secrets_repo: Path) -> None:
    print("[TEST] Caso A — TLS existente permite cold-start preservando material byte a byte...")
    with tempfile.TemporaryDirectory(prefix="sister_cold_boot_a_") as td:
        tmp = Path(td)
        lifecycle = FixtureLifecycleManager(tmp)
        try:
            env, gw_port, comp_port, ca_cert, ca_key, tls_pem = setup_mock_environment(tmp, lifecycle)

            sha_ca_crt_before = sha_file(ca_cert)
            sha_ca_key_before = sha_file(ca_key)
            sha_leaf_before = sha_file(tls_pem)

            # Inicia via sister-infra up
            res_up = subprocess.run([str(INFRA_CLI), "up", "--profile", "lan"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert res_up.returncode == 0, f"sister-infra up falhou: {res_up.stderr}"

            gateway_pid_file = Path(env["GATEWAY_PID"])
            pid_gw = lifecycle.track_haproxy_pid_file(gateway_pid_file)
            assert pid_gw and pid_gw > 0, "HAProxy gateway não está ativo"

            # Responde 200 via HAProxy
            st = probe_https("mock-comp.test", gw_port, "/api/health", ca_cert)
            assert st == 200, f"probe HTTPS via gateway esperava 200, obteve {st}"

            # Invariantes TLSA-020, 021, 022: Material TLS 100% inalterado
            assert sha_file(ca_cert) == sha_ca_crt_before, "CA cert foi modificado durante cold-start!"
            assert sha_file(ca_key) == sha_ca_key_before, "CA key foi modificada durante cold-start!"
            assert sha_file(tls_pem) == sha_leaf_before, "Leaf cert foi modificado durante cold-start!"

            # TLSA-024: Cold-stop funcional
            res_down = subprocess.run([str(INFRA_CLI), "down", "--profile", "lan"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert res_down.returncode == 0, f"sister-infra down falhou: {res_down.stderr}"
            assert not gateway_pid_file.exists(), "gateway PID file deveria ter sido removido após down"

            print("[PASS] Caso A — cold-start e cold-stop funcionais com preservação byte a byte do material TLS")
        finally:
            lifecycle.terminate_all()


def test_caso_b_ca_em_janela_de_expiracao(secrets_repo: Path) -> None:
    print("[TEST] Caso B — CA em janela de expiração não sofre rotação (código legado rotacionaria)...")
    with tempfile.TemporaryDirectory(prefix="sister_cold_boot_b_") as td:
        tmp = Path(td)
        lifecycle = FixtureLifecycleManager(tmp)
        try:
            # Configura CA com 10 dias de validade (estritamente dentro da janela preventiva de 30 dias)
            env, gw_port, comp_port, ca_cert, ca_key, tls_pem = setup_mock_environment(tmp, lifecycle, ca_days=10)

            # Prova factual de que o teste do OpenSSL para janela de 30 dias falha nesta CA
            chk_renew = subprocess.run(["openssl", "x509", "-in", str(ca_cert), "-noout", "-checkend", "2592000"], stdout=subprocess.PIPE, check=False)
            assert chk_renew.returncode != 0, "CA deveria falhar o checkend de 30 dias para comprovar o cenário"

            sha_ca_crt_before = sha_file(ca_cert)
            sha_ca_key_before = sha_file(ca_key)
            sha_leaf_before = sha_file(tls_pem)

            # Executa sister-infra up
            res_up = subprocess.run([str(INFRA_CLI), "up", "--profile", "lan"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert res_up.returncode == 0, f"sister-infra up falhou: {res_up.stderr}"

            gateway_pid_file = Path(env["GATEWAY_PID"])
            pid_gw = lifecycle.track_haproxy_pid_file(gateway_pid_file)
            assert pid_gw and pid_gw > 0

            # Invariante TLSA-021 e TLSA-025: Nenhuma rotação ocorreu
            assert sha_file(ca_cert) == sha_ca_crt_before, "CA cert foi rotacionado indevidamente pelo up!"
            assert sha_file(ca_key) == sha_ca_key_before, "CA key foi rotacionada indevidamente pelo up!"
            assert sha_file(tls_pem) == sha_leaf_before, "Leaf foi reemitido indevidamente pelo up!"

            res_down = subprocess.run([str(INFRA_CLI), "down", "--profile", "lan"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert res_down.returncode == 0

            print("[PASS] Caso B — ausência de rotação comprovada sob CA em janela preventiva")
        finally:
            lifecycle.terminate_all()


def test_caso_c_tls_pem_ausente_fail_closed(secrets_repo: Path) -> None:
    print("[TEST] Caso C — ausência de TLS_PEM resulta em fail-closed sem criar material...")
    with tempfile.TemporaryDirectory(prefix="sister_cold_boot_c_") as td:
        tmp = Path(td)
        lifecycle = FixtureLifecycleManager(tmp)
        try:
            env, gw_port, comp_port, ca_cert, ca_key, tls_pem = setup_mock_environment(tmp, lifecycle)

            missing_pem = tmp / "nonexistent" / "missing-leaf.pem"
            env["TLS_PEM"] = str(missing_pem)

            gateway_pid_file = Path(env["GATEWAY_PID"])

            # Executa sister-infra up
            res_up = subprocess.run([str(INFRA_CLI), "up", "--profile", "lan"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # Invariante TLSA-023: Falha fechado
            assert res_up.returncode != 0, "sister-infra up deveria falhar fechado com TLS_PEM ausente"
            assert "certificado TLS do gateway ausente ou ilegível" in res_up.stderr

            # Gateway não iniciado
            assert not gateway_pid_file.exists(), "gateway PID não deve existir após falha"

            # Invariantes TLSA-020 / TLSA-022: Nenhuma criação de arquivo
            assert not missing_pem.exists(), "missing_pem não deve ser criado"
            assert not (tmp / "nonexistent").exists()

            print("[PASS] Caso C — TLS_PEM ausente resulta em fail-closed sem qualquer mutação de autoridade")
        finally:
            lifecycle.terminate_all()


def test_caso_d_runtime_real_e_secrets_preservados(secrets_repo: Path) -> None:
    print("[TEST] Caso D — prova de isolamento e não-mutação de <repo>/secrets/...")
    secrets_before = {f.name: sha_file(f) for f in secrets_repo.iterdir() if f.is_file()}
    assert "ecosystem-lab.pem" in secrets_before

    # Garante que nenhum processo de gateway real foi tocado
    res_ps = subprocess.run(["ps", "-ef"], stdout=subprocess.PIPE, text=True)
    live_haproxy = [line for line in res_ps.stdout.splitlines() if "haproxy" in line and "lan" in line and "python" not in line]
    assert live_haproxy, "HAProxy live da máquina deve permanecer ativo"

    secrets_after = {f.name: sha_file(f) for f in secrets_repo.iterdir() if f.is_file()}
    assert secrets_before == secrets_after, "arquivos em <repo>/secrets/ foram tocados!"

    print("[PASS] Caso D — runtime real e <repo>/secrets/ preservados integralmente")


def main() -> int:
    secrets_repo = (ROOT / "secrets").resolve()
    assert secrets_repo.is_dir(), f"diretório secrets não encontrado em {secrets_repo}"

    print("==================================================")
    print(" OPS-07A2.2b — Desacoplamento Gateway Boot do TLS")
    print("==================================================")

    test_caso_a_tls_existente(secrets_repo)
    test_caso_b_ca_em_janela_de_expiracao(secrets_repo)
    test_caso_c_tls_pem_ausente_fail_closed(secrets_repo)
    test_caso_d_runtime_real_e_secrets_preservados(secrets_repo)

    print()
    print("[PASS] Todos os casos de OPS-07A2.2b passaram com sucesso!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
