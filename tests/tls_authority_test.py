#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Teste de autoridade TLS e ausência de fallback no reconciliador (OPS-07A2.1).

Invariantes validados:
- TLSA-001: Caminho TLS explicitamente fornecido nunca é silenciosamente substituído.
- TLSA-002: Ausência de material em config_root/tls nunca causa consulta ao repositório.
- TLSA-003: Ausência de CA resulta em fail-closed, não em criação ou fallback.
- TLSA-004: O runtime corrente não é tocado.
- TLSA-005: Nenhum outro comportamento TLS é alterado neste incremento.

Casos:
  Caso A: Caminhos explícitos existentes retornam os mesmos caminhos.
  Caso B: Caminhos explícitos inexistentes retornam os mesmos caminhos (sem fallback para <repo>/secrets/).
  Caso C: Env ausente + config_root sem TLS retorna config_root/tls/* (sem fallback para <repo>/secrets/).
  Caso D: Fail-closed operacional quando reconciliação necessita de CA mas autoridade está ausente.
          (current preservado, gateway preservado, processos preservados, zero CA criada).
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
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

from composition_resolver_test import (
    make_component,
    make_contracts,
    write_json,
)
from composition_qualification_test import git_init_commit
from derived_resources_apply_test import (
    create_mock_runtime_script,
    create_qualified_candidate,
    setup_ca,
    generate_leaf,
    reserve_port,
    run_cmd,
    FixtureLifecycleManager,
    ROOT,
    CANDIDATE_CLI,
    WORKSTATION_CLI,
    RECONCILE_CLI,
    INFRA_CLI,
)

# Carrega sister-reconcile para teste unitário de get_tls_paths
loader = importlib.machinery.SourceFileLoader("sister_reconcile_mod", str(ROOT / "bin" / "sister-reconcile"))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec and spec.loader
reconcile_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconcile_mod)
get_tls_paths = reconcile_mod.get_tls_paths


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


def test_caso_a_explicit_existing(secrets_repo: Path) -> None:
    print("[TEST] Caso A — caminhos explícitos existentes...")
    with tempfile.TemporaryDirectory() as td:
        tmp_a = Path(td)
        pem = tmp_a / "custom-leaf.pem"
        ca = tmp_a / "custom-ca.crt"
        key = tmp_a / "custom-ca.key"
        pem.write_text("DUMMY_PEM", encoding="utf-8")
        ca.write_text("DUMMY_CA", encoding="utf-8")
        key.write_text("DUMMY_KEY", encoding="utf-8")

        old_env = {k: os.environ.get(k) for k in ["TLS_PEM", "CA_CERT", "CA_KEY"]}
        try:
            os.environ["TLS_PEM"] = str(pem)
            os.environ["CA_CERT"] = str(ca)
            os.environ["CA_KEY"] = str(key)

            dummy_cfg = tmp_a / "dummy_cfg"
            res_pem, res_ca, res_key = get_tls_paths(dummy_cfg)

            assert res_pem == pem.resolve(), f"esperado {pem.resolve()}, obtido {res_pem}"
            assert res_ca == ca.resolve(), f"esperado {ca.resolve()}, obtido {res_ca}"
            assert res_key == key.resolve(), f"esperado {key.resolve()}, obtido {res_key}"

            # Prova que nenhum caminho aponta para secrets do repositório
            for p in (res_pem, res_ca, res_key):
                assert not str(p).startswith(str(secrets_repo)), f"caminho {p} vazou para secrets do repo"

            print("[PASS] Caso A — caminhos explícitos existentes preservados sem mutação")
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_caso_b_explicit_nonexistent(secrets_repo: Path) -> None:
    print("[TEST] Caso B — caminhos explícitos inexistentes (rejeição de fallback)...")
    # Prova que arquivos físicos em secrets/ existem deliberadamente no repositório
    assert (secrets_repo / "ecosystem-lab.pem").is_file(), "ecosystem-lab.pem deve existir em secrets/ para validar ausência de fallback"
    assert (secrets_repo / "ecosystem-lab-ca.crt").is_file(), "ecosystem-lab-ca.crt deve existir em secrets/"
    assert (secrets_repo / "ecosystem-lab-ca.key").is_file(), "ecosystem-lab-ca.key deve existir em secrets/"

    with tempfile.TemporaryDirectory() as td:
        tmp_b = Path(td)
        missing_pem = tmp_b / "authority-that-does-not-exist" / "missing-leaf.pem"
        missing_ca = tmp_b / "authority-that-does-not-exist" / "missing-ca.crt"
        missing_key = tmp_b / "authority-that-does-not-exist" / "missing-ca.key"

        assert not missing_pem.exists()
        assert not missing_ca.exists()
        assert not missing_key.exists()

        old_env = {k: os.environ.get(k) for k in ["TLS_PEM", "CA_CERT", "CA_KEY"]}
        try:
            os.environ["TLS_PEM"] = str(missing_pem)
            os.environ["CA_CERT"] = str(missing_ca)
            os.environ["CA_KEY"] = str(missing_key)

            dummy_cfg = tmp_b / "dummy_cfg"
            res_pem, res_ca, res_key = get_tls_paths(dummy_cfg)

            # Invariante TLSA-001: caminho fornecido explicitamente NUNCA é substituído por <repo>/secrets/
            assert res_pem == missing_pem.resolve(), f"esperado {missing_pem.resolve()}, obtido {res_pem}"
            assert res_ca == missing_ca.resolve(), f"esperado {missing_ca.resolve()}, obtido {res_ca}"
            assert res_key == missing_key.resolve(), f"esperado {missing_key.resolve()}, obtido {res_key}"

            assert not str(res_pem).startswith(str(secrets_repo)), "res_pem recorreu indevidamente a <repo>/secrets/"
            assert not str(res_ca).startswith(str(secrets_repo)), "res_ca recorreu indevidamente a <repo>/secrets/"
            assert not str(res_key).startswith(str(secrets_repo)), "res_key recorreu indevidamente a <repo>/secrets/"

            print("[PASS] Caso B — caminhos explícitos inexistentes não realizam fallback para <repo>/secrets/")
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_caso_c_env_absent_config_root_without_tls(secrets_repo: Path) -> None:
    print("[TEST] Caso C — env ausente + config_root sem TLS (sem desvio para repo)...")
    with tempfile.TemporaryDirectory() as td:
        tmp_c = Path(td)
        config_root = tmp_c / "config"
        # Garante que config_root/tls não existe
        assert not (config_root / "tls").exists()

        old_env = {k: os.environ.get(k) for k in ["TLS_PEM", "CA_CERT", "CA_KEY"]}
        try:
            os.environ.pop("TLS_PEM", None)
            os.environ.pop("CA_CERT", None)
            os.environ.pop("CA_KEY", None)

            res_pem, res_ca, res_key = get_tls_paths(config_root)

            # Invariante TLSA-002: ausência de material em config_root/tls nunca causa consulta ao repositório
            exp_pem = config_root / "tls" / "ecosystem-lab.pem"
            exp_ca = config_root / "tls" / "ecosystem-lab-ca.crt"
            exp_key = config_root / "tls" / "ecosystem-lab-ca.key"

            assert res_pem == exp_pem, f"esperado {exp_pem}, obtido {res_pem}"
            assert res_ca == exp_ca, f"esperado {exp_ca}, obtido {res_ca}"
            assert res_key == exp_key, f"esperado {exp_key}, obtido {res_key}"

            assert not str(res_pem).startswith(str(secrets_repo)), "res_pem derivou para <repo>/secrets/"
            assert not str(res_ca).startswith(str(secrets_repo)), "res_ca derivou para <repo>/secrets/"
            assert not str(res_key).startswith(str(secrets_repo)), "res_key derivou para <repo>/secrets/"

            print("[PASS] Caso C — env ausente + config_root sem TLS retorna config_root/tls sem desvio para repo")
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_caso_d_fail_closed_operational(secrets_repo: Path) -> None:
    print("[TEST] Caso D — fail-closed operacional sob autoridade ausente...")
    # Registra estado inicial de <repo>/secrets/
    secrets_before = {f.name: sha_file(f) for f in secrets_repo.iterdir() if f.is_file()}

    with tempfile.TemporaryDirectory(prefix="sister_tls_auth_") as td:
        tmp = Path(td)
        lifecycle = FixtureLifecycleManager(tmp)

        try:
            contracts = make_contracts(tmp)

            install_root = tmp / "install"
            config_root = tmp / "config"
            state_root = tmp / "state"
            run_root = tmp / "run"
            bin_root = tmp / "bin"
            systemd_user = tmp / "systemd_user"
            tls_dir = config_root / "tls"

            for d in [install_root, config_root, state_root, run_root, bin_root, systemd_user, tls_dir]:
                d.mkdir(parents=True, exist_ok=True)

            gw_port = reserve_port()
            port_alpha = reserve_port()
            port_beta = reserve_port()

            # Componente Alpha
            alpha_dir = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
            create_mock_runtime_script(alpha_dir / "scripts" / "runtime.sh", port_alpha)
            desc_alpha = json.loads((alpha_dir / ".sister" / "component.json").read_text(encoding="utf-8"))
            desc_alpha["build"]["artifacts"] = [{"id": "alpha-bin", "path": "scripts/runtime.sh", "executable": True}]
            write_json(alpha_dir / ".sister" / "component.json", desc_alpha)
            git_init_commit(alpha_dir)

            # Componente Beta
            beta_dir = make_component(tmp, "sister-beta", "beta", "sister_beta")
            create_mock_runtime_script(beta_dir / "scripts" / "runtime.sh", port_beta)
            desc_beta = json.loads((beta_dir / ".sister" / "component.json").read_text(encoding="utf-8"))
            desc_beta["build"]["artifacts"] = [{"id": "beta-bin", "path": "scripts/runtime.sh", "executable": True}]
            write_json(beta_dir / ".sister" / "component.json", desc_beta)
            git_init_commit(beta_dir)

            # Candidata Base (apenas alpha)
            cand_base = create_qualified_candidate(tmp, contracts, ["../sister-alpha"], "cand-base")

            # Candidata Desired (alpha + beta)
            cand_desired = create_qualified_candidate(tmp, contracts, ["../sister-alpha", "../sister-beta"], "cand-desired")

            # Deployments
            dep_base_file = tmp / "dep_base.json"
            write_json(dep_base_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-base",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": gw_port, "listen": "127.0.0.1"},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                ],
            })

            dep_desired_file = tmp / "dep_desired.json"
            write_json(dep_desired_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-desired",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": gw_port, "listen": "127.0.0.1"},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                ],
            })

            # Gera CA inicial e leaf para Alpha
            ca_cert, ca_key = setup_ca(tls_dir)
            tls_pem = tls_dir / "ecosystem-lab.pem"
            generate_leaf(tls_pem, ca_cert, ca_key, ["alpha-gateway.test"])

            gateway_dir = state_root / "control-plane" / "gateway"
            gateway_dir.mkdir(parents=True, exist_ok=True)
            gateway_cfg = gateway_dir / "haproxy-lan.cfg"
            gateway_pid = gateway_dir / "haproxy-lan.pid"
            projection_file = run_root / "ecosystem_projection.tsv"

            haproxy_bin = shutil.which("haproxy") or "/usr/local/sbin/haproxy" or "/usr/sbin/haproxy"

            env = dict(os.environ)
            env["SISTER_WORKSTATION_INSTALL_ROOT"] = str(install_root)
            env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(config_root)
            env["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)
            env["SISTER_WORKSTATION_BIN_ROOT"] = str(bin_root)
            env["SISTER_WORKSTATION_SYSTEMD_ROOT"] = str(systemd_user)
            env["SISTER_WORKSTATION_CONTRACTS_ROOT"] = str(contracts)
            env["TLS_PEM"] = str(tls_pem)
            env["CA_CERT"] = str(ca_cert)
            env["CA_KEY"] = str(ca_key)
            env["GATEWAY_CFG"] = str(gateway_cfg)
            env["GATEWAY_PID"] = str(gateway_pid)
            env["GATEWAY_LISTEN_PORT"] = str(gw_port)
            env["GATEWAY_LISTEN_ADDRESS"] = "127.0.0.1"
            env["HAPROXY_BIN"] = haproxy_bin
            env["SISTER_ECOSYSTEM_PROJECTION_FILE"] = str(projection_file)

            # Materializa release inicial
            res_rc = run_cmd([
                str(WORKSTATION_CLI), "release-create",
                "--candidate", str(cand_base),
                "--deployment", str(dep_base_file),
                "--json",
            ], env=env, check=True)
            base_release = Path(json.loads(res_rc.stdout)["release_path"])

            run_cmd([str(WORKSTATION_CLI), "release-switch", "--target", str(base_release)], env=env, check=True)
            assert (install_root / "current").resolve() == base_release.resolve()

            # Inicia daemon Alpha
            c_env = dict(env)
            c_env["SISTER_RUNTIME_RUN_DIR"] = str(run_root / "alpha")
            c_env["SISTER_RUNTIME_STATE_DIR"] = str(state_root / "components" / "alpha")
            c_env["SISTER_RESOLVED_DEPLOYMENT_FILE"] = str(base_release / "evidence" / "deployment" / "resolved.json")
            c_env["SISTER_COMPONENT_CONFIG_FILE"] = str(config_root / "alpha.env")
            run_cmd([str(base_release / "components" / "alpha" / "scripts" / "runtime.sh"), "start"], env=c_env, check=True)

            pid_alpha = int((run_root / "alpha" / "app.pid").read_text().strip())
            lifecycle.track_component(pid_alpha)

            # Inicia HAProxy base
            resolved_base = base_release / "evidence" / "deployment" / "resolved.json"
            res_rend = run_cmd([
                sys.executable, str(ROOT / "bin" / "sister-gateway"), "render",
                str(resolved_base),
                "--listen-address", "127.0.0.1",
                "--listen-port", str(gw_port),
                "--tls-pem", str(tls_pem),
            ], check=True)
            gateway_cfg.write_text(res_rend.stdout, encoding="utf-8")
            old_gateway_cfg_content = res_rend.stdout

            run_cmd([haproxy_bin, "-D", "-f", str(gateway_cfg), "-p", str(gateway_pid)], check=True)
            time.sleep(0.3)
            pid_gw = lifecycle.track_haproxy_pid_file(gateway_pid)
            assert pid_gw and pid_gw > 0

            # Verifica gateway respondendo
            st_init = probe_https("alpha-gateway.test", gw_port, "/api/health", ca_cert)
            assert st_init == 200, f"HAProxy inicial deve responder 200 em alpha, obtido {st_init}"

            # -------------------------------------------------------------
            # AGORA O CENÁRIO DE PROVA NEGATIVA:
            # Reconciliação para cand_desired exige novo SAN (beta-gateway.test),
            # o que requer CA para reemitir o certificado leaf.
            # Mas apontamos CA_CERT e CA_KEY para caminho inexistente!
            # (Note que <repo>/secrets/ possui CA válida).
            # -------------------------------------------------------------
            absent_ca_dir = tmp / "absent_ca_authority"
            env_absent_ca = dict(env)
            env_absent_ca["CA_CERT"] = str(absent_ca_dir / "ecosystem-lab-ca.crt")
            env_absent_ca["CA_KEY"] = str(absent_ca_dir / "ecosystem-lab-ca.key")

            res_apply = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_desired),
                "--desired-deployment", str(dep_desired_file),
                "--json",
            ], env=env_absent_ca)

            # Invariante TLSA-003: Falha fechado
            assert res_apply.returncode != 0, f"lab apply com CA ausente deveria falhar fechado, mas retornou 0!\nSTDOUT: {res_apply.stdout}"
            err_output = res_apply.stderr + res_apply.stdout
            assert "CA lab exige rotação" in err_output or "CA ausente/inválida" in err_output, (
                f"Mensagem esperada de falha fechado da CA não encontrada na saída:\n{err_output}"
            )

            # Invariante TLSA-004:
            # 1. current preservado
            assert (install_root / "current").resolve() == base_release.resolve(), "current link foi alterado após falha!"

            # 2. Processo Alpha preservado e saudável
            assert (run_root / "alpha" / "app.pid").is_file(), "PID file do alpha sumiu!"
            current_alpha_pid = int((run_root / "alpha" / "app.pid").read_text().strip())
            assert current_alpha_pid == pid_alpha, f"PID do alpha mudou de {pid_alpha} para {current_alpha_pid}!"
            assert os.kill(pid_alpha, 0) is None, "processo alpha foi encerrado!"

            # 3. Gateway preservado e ativo no mesmo PID com mesma config
            assert gateway_pid.is_file(), "PID file do HAProxy sumiu!"
            current_gw_pid = int(gateway_pid.read_text().strip())
            assert current_gw_pid == pid_gw, f"HAProxy foi reiniciado indevidamente: {pid_gw} -> {current_gw_pid}"
            assert os.kill(pid_gw, 0) is None, "HAProxy foi derrubado!"
            assert gateway_cfg.read_text(encoding="utf-8") == old_gateway_cfg_content, "gateway cfg foi alterado após falha!"

            st_after = probe_https("alpha-gateway.test", gw_port, "/api/health", ca_cert)
            assert st_after == 200, f"HAProxy deve continuar respondendo 200 em alpha após falha de apply, obtido {st_after}"

            # 4. Nenhuma CA criada no caminho ausente
            assert not absent_ca_dir.exists(), "diretório absent_ca_dir foi criado indevidamente!"

            # 5. <repo>/secrets/ permaneceu 100% inalterado
            secrets_after = {f.name: sha_file(f) for f in secrets_repo.iterdir() if f.is_file()}
            assert secrets_before == secrets_after, "arquivos em <repo>/secrets/ foram tocados!"

            print("[PASS] Caso D — fail-closed operacional comprovado: current, processos e gateway preservados")

        finally:
            lifecycle.terminate_all()


def main() -> int:
    secrets_repo = (ROOT / "secrets").resolve()
    assert secrets_repo.is_dir(), f"diretório secrets não encontrado em {secrets_repo}"

    print("==================================================")
    print(" OPS-07A2.1 — Prova de Autoridade TLS & Fail-Closed")
    print("==================================================")

    test_caso_a_explicit_existing(secrets_repo)
    test_caso_b_explicit_nonexistent(secrets_repo)
    test_caso_c_env_absent_config_root_without_tls(secrets_repo)
    test_caso_d_fail_closed_operational(secrets_repo)

    print()
    print("[PASS] Todos os casos de OPS-07A2.1 passaram com sucesso!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
