#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Testes de reconciliação segura de recursos derivados (OPS-04).

Valida:
1. Prova Arquitetural Principal:
   - CURRENT: alpha KEEP, beta KEEP, gamma KEEP
   - DESIRED: alpha KEEP, beta KEEP, gamma KEEP, delta ADD
   - Esperado: delta ADD, projection REFRESH, gateway RECONFIGURE
   - Após apply: PIDs alpha/beta/gamma idênticos; delta saudável;
     projection contém delta; gateway publica delta;
     current aponta TARGET; previous aponta OLD.
2. Idempotência (NO_OP consecutivo sem mutações).
3. REMOVE: retirada de gateway/projection antes de parada final;
   dados persistent-external preservados intactos.
4. Negativos:
   - ADD falhando no start
   - ADD falhando no health local
   - HAProxy validation (haproxy -c) falhando
   - Falha de verify pós-reload e Rollback gracioso sobre pid_target
   - Rotação de CA requerida (fail-closed, CA byte-identical)
   - Proxy ambiental (HTTP_PROXY / HTTPS_PROXY) não interferindo
   - Rollback sem resíduos (.old_backup, .tmp.*)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
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
WORKSTATION_CLI = ROOT / "bin" / "sister-workstation"
RECONCILE_CLI = ROOT / "bin" / "sister-reconcile"
INFRA_CLI = ROOT / "bin" / "sister-infra"


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_cmd(
    args: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            f"comando falhou ({res.returncode}): {' '.join(args)}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
    return res


def create_mock_runtime_script(
    script_path: Path,
    port: int,
    fail_on_start: bool = False,
    fail_on_health: bool = False,
    exit_after_start: bool = False,
) -> None:
    script_path.parent.mkdir(parents=True, exist_ok=True)
    fail_start_str = "1" if fail_on_start else "0"
    fail_health_str = "1" if fail_on_health else "0"
    exit_after_start_str = "1" if exit_after_start else "0"
    code = f"""#!/usr/bin/env bash
set -euo pipefail

ACTION="${{1:-health}}"

RUN_DIR="${{SISTER_RUNTIME_RUN_DIR:-${{SISTER_WORKSTATION_STATE_ROOT:-/tmp}}/run}}"
STATE_DIR="${{SISTER_RUNTIME_STATE_DIR:-${{SISTER_WORKSTATION_STATE_ROOT:-/tmp}}/components}}"

mkdir -p "$RUN_DIR" "$STATE_DIR"
PID_FILE="$RUN_DIR/app.pid"
ACTIONS_LOG="$STATE_DIR/actions.log"

echo "$ACTION $(pwd)" >> "$ACTIONS_LOG"

if [[ "$ACTION" == "start" && "{fail_start_str}" == "1" ]]; then
  echo "forced start failure" >&2
  exit 1
fi

if [[ "$ACTION" == "health" && "{fail_health_str}" == "1" ]]; then
  echo "forced health failure" >&2
  exit 1
fi

case "$ACTION" in
  start)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      exit 0
    fi
    python3 -c "
import http.server, socketserver, threading, time, os, json

exit_after = {exit_after_start_str} == 1

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{{\\"status\\":\\"UP\\"}}\\n')
            if exit_after:
                def kill_soon():
                    time.sleep(0.05)
                    os._exit(0)
                threading.Thread(target=kill_soon, daemon=True).start()
        elif self.path == '/api/ecosystem':
            proj_file = os.environ.get('SISTER_ECOSYSTEM_PROJECTION_FILE')
            systems = []
            if proj_file and os.path.isfile(proj_file):
                for line in open(proj_file, 'r', encoding='utf-8'):
                    if line.startswith('PARTICIPANT\\t'):
                        parts = line.strip().split('\\t')
                        if len(parts) >= 2:
                            systems.append({{\\"componentId\\": parts[1]}})
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({{\\"status\\":\\"UP\\",\\"systems\\":systems}}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        pass

class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True

httpd = ReusableServer(('127.0.0.1', {port}), Handler)

if exit_after:
    def shutdown_soon():
        time.sleep(0.4)
        httpd.shutdown()
    threading.Thread(target=shutdown_soon, daemon=True).start()

httpd.serve_forever()
" "$STATE_DIR" >/dev/null 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"
    sleep 0.1
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      PID="$(cat "$PID_FILE")"
      kill -9 "$PID" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
    ;;
  health)
    if curl -s "http://127.0.0.1:{port}/api/health" | grep -q "UP"; then
      exit 0
    else
      exit 1
    fi
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      exit 0
    else
      exit 1
    fi
    ;;
  *)
    exit 2
    ;;
esac
"""
    script_path.write_text(code, encoding="utf-8")
    script_path.chmod(0o755)


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


def setup_ca(tls_dir: Path, days: int = 825) -> tuple[Path, Path]:
    tls_dir.mkdir(parents=True, exist_ok=True)
    ca_key = tls_dir / "ecosystem-lab-ca.key"
    ca_cert = tls_dir / "ecosystem-lab-ca.crt"
    if ca_key.is_file() and ca_cert.is_file():
        return ca_cert, ca_key

    subprocess.run(["openssl", "genrsa", "-out", str(ca_key), "3072"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run([
        "openssl", "req", "-x509", "-new", "-nodes",
        "-key", str(ca_key),
        "-sha256",
        "-days", str(days),
        "-out", str(ca_cert),
        "-subj", "/CN=SisTer Test Lab CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return ca_cert, ca_key


def generate_leaf(tls_pem: Path, ca_cert: Path, ca_key: Path, hosts: list[str]) -> None:
    tls_pem.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        k = tdp / "gw.key"
        csr = tdp / "gw.csr"
        crt = tdp / "gw.crt"
        cnf = tdp / "openssl.cnf"
        ext = tdp / "ext.cnf"

        subprocess.run(["openssl", "genrsa", "-out", str(k), "3072"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        cnf_content = f"[req]\nprompt=no\ndistinguished_name=dn\nreq_extensions=req_ext\n[dn]\nCN={hosts[0]}\n[req_ext]\nsubjectAltName=@alt_names\n[alt_names]\n"
        for i, h in enumerate(hosts, start=1):
            cnf_content += f"DNS.{i} = {h}\n"
        cnf.write_text(cnf_content, encoding="utf-8")

        subprocess.run(["openssl", "req", "-new", "-key", str(k), "-out", str(csr), "-config", str(cnf)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        sans_str = ",".join(f"DNS:{h}" for h in hosts)
        ext.write_text(f"subjectAltName={sans_str}\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature,keyEncipherment\n", encoding="utf-8")

        subprocess.run([
            "openssl", "x509", "-req",
            "-in", str(csr),
            "-CA", str(ca_cert),
            "-CAkey", str(ca_key),
            "-CAcreateserial",
            "-out", str(crt),
            "-days", "825",
            "-sha256",
            "-extfile", str(ext),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        tls_pem.write_bytes(crt.read_bytes() + b"\n" + k.read_bytes() + b"\n")
        tls_pem.chmod(0o600)


def probe_https_gateway(host: str, port: int, path: str, ca_cert: Path) -> tuple[int, str]:
    import http.client

    class SNIHTTPSConnection(http.client.HTTPSConnection):
        def __init__(self, ip: str, port: int, server_hostname: str, context: ssl.SSLContext, timeout: float = 5.0):
            super().__init__(ip, port=port, context=context, timeout=timeout)
            self._sni_server_hostname = server_hostname

        def connect(self):
            super(http.client.HTTPSConnection, self).connect()
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self._sni_server_hostname)

    ssl_ctx = ssl.create_default_context(cafile=str(ca_cert))
    conn = SNIHTTPSConnection("127.0.0.1", port=port, server_hostname=host, context=ssl_ctx, timeout=5.0)
    conn.request("GET", path, headers={"Host": host, "Connection": "close"})
    resp = conn.getresponse()
    body = resp.read().decode("utf-8", "replace")
    status = resp.status
    conn.close()
    return status, body


class FixtureLifecycleManager:
    def __init__(self, fixture_root: Path):
        self.fixture_root = fixture_root.resolve()
        self.fixture_root_str = str(self.fixture_root)
        self.tracked_haproxy_pids: set[int] = set()
        self.tracked_component_pids: set[int] = set()

    def is_fixture_process(self, pid: int) -> bool:
        """Verifica estritamente se o PID pertence a esta fixture através de /proc/<pid>/cmdline ou /proc/<pid>/cwd.
        NUNCA retorna True para processos fora desta fixture (preserva incondicionalmente HAProxy LAB real)."""
        if pid <= 1 or pid == os.getpid():
            return False
        try:
            cmdline_path = Path(f"/proc/{pid}/cmdline")
            if cmdline_path.is_file():
                raw = cmdline_path.read_bytes()
                cmdline_str = raw.decode("utf-8", errors="replace")
                if self.fixture_root_str in cmdline_str:
                    return True

            cwd_link = Path(f"/proc/{pid}/cwd")
            if cwd_link.is_symlink():
                target = str(os.readlink(cwd_link))
                if self.fixture_root_str in target:
                    return True
        except (OSError, PermissionError):
            return False
        return False

    def track_haproxy(self, pid: int | None) -> None:
        if pid and pid > 0 and self.is_fixture_process(pid):
            self.tracked_haproxy_pids.add(pid)

    def track_component(self, pid: int | None) -> None:
        if pid and pid > 0 and self.is_fixture_process(pid):
            self.tracked_component_pids.add(pid)

    def track_haproxy_pid_file(self, pid_file: Path) -> int | None:
        if pid_file.is_file():
            try:
                pid = int(pid_file.read_text().strip())
                self.track_haproxy(pid)
                self.scan_all_fixture_processes()
                return pid
            except (ValueError, OSError):
                return None
        return None

    def scan_all_fixture_processes(self) -> set[int]:
        """Varre /proc e descobre todos os processos pertencentes exclusivamente a esta fixture."""
        found = set()
        proc = Path("/proc")
        if proc.is_dir():
            try:
                for entry in proc.iterdir():
                    if entry.name.isdigit():
                        pid = int(entry.name)
                        if self.is_fixture_process(pid):
                            found.add(pid)
            except (OSError, PermissionError):
                pass

        for p in self.tracked_haproxy_pids | self.tracked_component_pids:
            if self.is_fixture_process(p):
                found.add(p)
        return found

    def terminate_all(self, timeout_sec: float = 3.0) -> None:
        """Encerra com SIGTERM, aguarda e usa SIGKILL como fallback.
        NUNCA toca em processos fora de fixture_root."""
        all_pids = self.scan_all_fixture_processes()
        if not all_pids:
            return

        # 1. SIGTERM
        for pid in all_pids:
            if self.is_fixture_process(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass

        # 2. Aguarda encerramento gracioso
        deadline = time.monotonic() + timeout_sec
        alive = set(all_pids)
        while time.monotonic() < deadline and alive:
            still_alive = set()
            for pid in alive:
                try:
                    os.kill(pid, 0)
                    still_alive.add(pid)
                except OSError:
                    pass
            alive = still_alive
            if alive:
                time.sleep(0.05)

        # 3. SIGKILL se algum processo ainda persistir
        if alive:
            for pid in alive:
                if self.is_fixture_process(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
            time.sleep(0.1)

    def assert_zero_processes(self) -> None:
        """Prova formalmente que não existe processo cuja cmdline ou cwd contenha fixture_root."""
        lingering = self.scan_all_fixture_processes()
        assert not lingering, (
            f"Violação de isolamento: processos da fixture ainda vivos: {lingering}"
        )

    def assert_no_listeners(self, ports: list[int]) -> None:
        """Prova formalmente que nenhuma porta alocada para a fixture continua com listener ativo."""
        for port in ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("127.0.0.1", port))
                    s.listen(1)
                except OSError as exc:
                    raise AssertionError(
                        f"Porta {port} da fixture ainda possui listener ativo ou preso: {exc}"
                    )


def main() -> None:
    print("[TEST] Iniciando suite de testes de Safe Derived-Resource Reconciliation (OPS-04)...")

    haproxy_bin = shutil.which("haproxy") or "/usr/local/sbin/haproxy"
    assert os.path.isfile(haproxy_bin) and os.access(haproxy_bin, os.X_OK), "haproxy deve estar instalado"

    with tempfile.TemporaryDirectory(prefix="sister-derived-ops04-") as td:
        tmp = Path(td)
        lifecycle = FixtureLifecycleManager(tmp)

        try:
            workspace = tmp / "workspace"
            workspace.mkdir()
            home = tmp / "home"
            home.mkdir()

            infra_src = workspace / "sister-infra"
            infra_src.mkdir()
            (infra_src / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            shutil.copy2(ROOT / "README.md", infra_src / "README.md")
            git_init_commit(infra_src)

            install_root = home / ".local" / "share" / "sister"
            state_root = home / ".local" / "state" / "sister" / "workstation"
            config_root = home / ".config" / "sister" / "workstation"
            tls_dir = config_root / "tls"
            run_root = state_root / "run"

            contracts = make_contracts(tmp)

            import jsonschema
            jsonschema_site = str(Path(jsonschema.__file__).resolve().parent.parent)
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(
                part for part in (jsonschema_site, env.get("PYTHONPATH", "")) if part
            )
            env["PYTHON"] = sys.executable
            env["HOME"] = str(home)
            env["SISTER_WORKSTATION_CONTROL_PLANE_SOURCE"] = str(infra_src)
            env["SISTER_WORKSTATION_INSTALL_ROOT"] = str(install_root)
            env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(config_root)
            env["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)
            env["SISTER_CURRENT_RELEASE"] = str(install_root / "current")

            gw_port = reserve_port()
            port_alpha = reserve_port()
            port_beta = reserve_port()
            port_gamma = reserve_port()
            port_delta = reserve_port()

            # Componentes base
            alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
            beta = make_component(tmp, "sister-beta", "beta", "sister_beta")
            gamma = make_component(tmp, "sister-gamma", "gamma", "sister_gamma")
            delta = make_component(tmp, "sister-delta", "delta", "sister_delta")

            create_mock_runtime_script(alpha / "scripts" / "runtime.sh", port_alpha)
            create_mock_runtime_script(beta / "scripts" / "runtime.sh", port_beta)
            create_mock_runtime_script(gamma / "scripts" / "runtime.sh", port_gamma)
            create_mock_runtime_script(delta / "scripts" / "runtime.sh", port_delta)

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

            # Candidata Base
            cand_base = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma"],
                "cand-base",
            )
            cand_with_delta = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma", "../sister-delta"],
                "cand-delta",
            )
            cand_remove = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma"],
                "cand-remove",
            )

            dep_base_file = tmp / "dep_base.json"
            write_json(dep_base_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-base",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": gw_port, "listen": "127.0.0.1"},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                    {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
                ],
            })

            dep_delta_file = tmp / "dep_delta.json"
            write_json(dep_delta_file, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-delta",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": gw_port, "listen": "127.0.0.1"},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                    {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
                    {"system_id": "sister_delta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_delta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "delta-gateway.test"}},
                ],
            })

            ca_cert, ca_key = setup_ca(tls_dir)
            tls_pem = tls_dir / "ecosystem-lab.pem"
            generate_leaf(tls_pem, ca_cert, ca_key, ["alpha-gateway.test", "beta-gateway.test", "gamma-gateway.test"])

            gateway_dir = state_root / "control-plane" / "gateway"
            gateway_dir.mkdir(parents=True, exist_ok=True)
            gateway_cfg = gateway_dir / "haproxy-lan.cfg"
            gateway_pid = gateway_dir / "haproxy-lan.pid"
            projection_file = run_root / "ecosystem_projection.tsv"

            env["TLS_PEM"] = str(tls_pem)
            env["CA_CERT"] = str(ca_cert)
            env["CA_KEY"] = str(ca_key)
            env["GATEWAY_CFG"] = str(gateway_cfg)
            env["GATEWAY_PID"] = str(gateway_pid)
            env["GATEWAY_LISTEN_PORT"] = str(gw_port)
            env["GATEWAY_LISTEN_ADDRESS"] = "127.0.0.1"
            env["HAPROXY_BIN"] = haproxy_bin
            env["SISTER_ECOSYSTEM_PROJECTION_FILE"] = str(projection_file)

            # Cria release inicial
            res_rc = run_cmd([
                str(WORKSTATION_CLI),
                "release-create",
                "--candidate", str(cand_base),
                "--deployment", str(dep_base_file),
                "--json",
            ], env=env, check=True)
            rc_info = json.loads(res_rc.stdout)
            base_release = Path(rc_info["release_path"])

            # Comuta current
            run_cmd([str(WORKSTATION_CLI), "release-switch", "--target", str(base_release)], env=env, check=True)
            assert (install_root / "current").resolve() == base_release.resolve()

            resolved_base = base_release / "evidence" / "deployment" / "resolved.json"

            # Inicia daemons base
            for cid in ["alpha", "beta", "gamma"]:
                c_env = dict(env)
                c_env["SISTER_RUNTIME_RUN_DIR"] = str(run_root / cid)
                c_env["SISTER_RUNTIME_STATE_DIR"] = str(state_root / "components" / cid)
                c_env["SISTER_RESOLVED_DEPLOYMENT_FILE"] = str(resolved_base)
                c_env["SISTER_COMPONENT_CONFIG_FILE"] = str(config_root / f"{cid}.env")
                run_cmd([str(base_release / "components" / cid / "scripts" / "runtime.sh"), "start"], env=c_env, check=True)

            pid_alpha_orig = int((run_root / "alpha" / "app.pid").read_text().strip())
            pid_beta_orig = int((run_root / "beta" / "app.pid").read_text().strip())
            pid_gamma_orig = int((run_root / "gamma" / "app.pid").read_text().strip())
            assert pid_alpha_orig and pid_beta_orig and pid_gamma_orig
            lifecycle.track_component(pid_alpha_orig)
            lifecycle.track_component(pid_beta_orig)
            lifecycle.track_component(pid_gamma_orig)

            # Renderiza e inicia HAProxy base
            res_rend = run_cmd([
                sys.executable, str(ROOT / "bin" / "sister-gateway"), "render",
                str(resolved_base),
                "--listen-address", "127.0.0.1",
                "--listen-port", str(gw_port),
                "--tls-pem", str(tls_pem),
            ], check=True)
            gateway_cfg.write_text(res_rend.stdout, encoding="utf-8")
            run_cmd([haproxy_bin, "-D", "-f", str(gateway_cfg), "-p", str(gateway_pid)], check=True)
            time.sleep(0.3)
            pid_gw_orig = lifecycle.track_haproxy_pid_file(gateway_pid)
            assert pid_gw_orig and os.kill(pid_gw_orig, 0) is None

            # Popula arquivo de projeção base
            res_dep = json.loads(resolved_base.read_text(encoding="utf-8"))
            proj_lines = ["META\ttest_reconcile\tdep-base\tREADY"]
            for c in res_dep["components"]:
                proj_lines.append(f"PARTICIPANT\t{c['component_id']}\t{c['system_id']}\ttcp\t127.0.0.1\t{c['runtime']['port']}\t/api/health\t{c['gateway']['host']}\thttps://{c['gateway']['host']}:{gw_port}")
            projection_file.parent.mkdir(parents=True, exist_ok=True)
            projection_file.write_text("\n".join(proj_lines) + "\n", encoding="utf-8")

            # Verifica conectividade base via HAProxy
            st_alpha, _ = probe_https_gateway("alpha-gateway.test", gw_port, "/api/health", ca_cert)
            st_beta, _ = probe_https_gateway("beta-gateway.test", gw_port, "/api/health", ca_cert)
            assert st_alpha == 200 and st_beta == 200, "HAProxy base deve responder 200"

            ca_cert_hash_orig = ca_cert.read_bytes()
            ca_key_hash_orig = ca_key.read_bytes()
            # =============================================================
            # 1. PROVA ARQUITETURAL PRINCIPAL (ADD delta + KEEP alpha,beta,gamma)
            # =============================================================
            print("[TEST] Executando Prova Arquitetural Principal...")
            res_plan = run_cmd([
                str(INFRA_CLI), "lab", "plan",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_with_delta),
                "--desired-deployment", str(dep_delta_file),
                "--json",
            ], env=env, check=True)
            plan_obj = json.loads(res_plan.stdout)
            assert plan_obj["summary"]["add"] == 1
            assert plan_obj["summary"]["keep"] == 3
            assert plan_obj["gateway"]["action"] == "RECONFIGURE"
            assert plan_obj["projection"]["action"] == "REFRESH"

            res_apply = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_with_delta),
                "--desired-deployment", str(dep_delta_file),
                "--json",
            ], env=env, check=True)
            apply_obj = json.loads(res_apply.stdout)
            assert apply_obj["status"] == "SUCCESS"
            assert apply_obj["summary"]["add"] == 1
            assert apply_obj["summary"]["keep"] == 3

            # Invariante 1: PIDs de alpha, beta, gamma IDÊNTICOS (KEEP)
            assert int((run_root / "alpha" / "app.pid").read_text().strip()) == pid_alpha_orig
            assert int((run_root / "beta" / "app.pid").read_text().strip()) == pid_beta_orig
            assert int((run_root / "gamma" / "app.pid").read_text().strip()) == pid_gamma_orig

            # Invariante 2: delta iniciado e saudável
            pid_delta = int((run_root / "delta" / "app.pid").read_text().strip())
            assert pid_delta and os.kill(pid_delta, 0) is None
            lifecycle.track_component(pid_delta)

            # Invariante 3: Projection atualizada contém delta
            proj_text = projection_file.read_text(encoding="utf-8")
            assert "PARTICIPANT\tdelta\t" in proj_text

            # Invariante 4: CA byte-identical mantida
            assert ca_cert.read_bytes() == ca_cert_hash_orig
            assert ca_key.read_bytes() == ca_key_hash_orig

            # Invariante 5: HAProxy recarregado graciosamente e publica delta
            pid_gw_target = lifecycle.track_haproxy_pid_file(gateway_pid)
            assert pid_gw_target != pid_gw_orig, "HAProxy deve ter novo PID após reload"
            st_delta, _ = probe_https_gateway("delta-gateway.test", gw_port, "/api/health", ca_cert)
            assert st_delta == 200, f"delta via gateway retornou status {st_delta}"

            # Invariante 6: current -> TARGET, previous -> OLD
            assert (install_root / "current").resolve() != base_release.resolve()
            assert (install_root / "previous").resolve() == base_release.resolve()
            print("[PASS] Prova Arquitetural Principal — ADD delta + KEEP alpha/beta/gamma + Gateway + Projection")

            # =============================================================
            # 2. IDEMPOTÊNCIA (Segunda execução NO_OP)
            # =============================================================
            res_noop = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_with_delta),
                "--desired-deployment", str(dep_delta_file),
                "--json",
            ], env=env, check=True)
            noop_obj = json.loads(res_noop.stdout)
            assert noop_obj["status"] == "NO_OP"
            lifecycle.track_haproxy_pid_file(gateway_pid)
            assert noop_obj["summary"]["keep"] == 4
            assert int(gateway_pid.read_text().strip()) == pid_gw_target
            assert int((run_root / "alpha" / "app.pid").read_text().strip()) == pid_alpha_orig
            print("[PASS] Idempotência — Segunda execução consecutiva resulta em NO_OP")

            # =============================================================
            # 3. REMOVE (Ordem Segura & Preservação de Dados)
            # =============================================================
            delta_state_dir = state_root / "components" / "delta"
            delta_state_file = delta_state_dir / "persistent_data.db"
            delta_state_file.write_text("critical_database_state_123", encoding="utf-8")

            res_remove = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_remove),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ], env=env, check=True)
            rem_obj = json.loads(res_remove.stdout)
            assert rem_obj["status"] == "SUCCESS"
            assert rem_obj["summary"]["remove"] == 1
            assert rem_obj["summary"]["keep"] == 3
            pid_gw_rem = lifecycle.track_haproxy_pid_file(gateway_pid)

            # delta foi parado
            assert not os.path.exists(run_root / "delta" / "app.pid")
            # DADOS PERSISTENTES PRESERVADOS
            assert delta_state_file.is_file(), "Dados persistentes de delta foram apagados!"
            assert delta_state_file.read_text(encoding="utf-8") == "critical_database_state_123"
            # KEEP preservados
            assert int((run_root / "alpha" / "app.pid").read_text().strip()) == pid_alpha_orig
            # Projection não tem mais delta
            assert "PARTICIPANT\tdelta\t" not in projection_file.read_text(encoding="utf-8")
            print("[PASS] REMOVE — Ordem Segura e Preservação de Dados de delta")

            # =============================================================
            # 4. NEGATIVO 1: ADD falhando no start
            # =============================================================
            port_bad_s = reserve_port()
            bad_start_comp = make_component(tmp, "sister-bad-start", "bad_start", "sister_bad_start")
            create_mock_runtime_script(bad_start_comp / "scripts" / "runtime.sh", port_bad_s, fail_on_start=True)
            desc_path = bad_start_comp / ".sister" / "component.json"
            desc = json.loads(desc_path.read_text(encoding="utf-8"))
            desc["build"]["artifacts"] = [{"id": "bad-bin", "path": "scripts/runtime.sh", "executable": True}]
            write_json(desc_path, desc)
            git_init_commit(bad_start_comp)

            cand_bad_start = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma", "../sister-bad-start"],
                "cand-bad-start",
            )
            dep_bad_start = tmp / "dep_bad_start.json"
            write_json(dep_bad_start, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-bad-start",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": gw_port, "listen": "127.0.0.1"},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                    {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
                    {"system_id": "sister_bad_start", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_bad_s}, "probe": {"health_path": "/api/health"}},
                ],
            })
            current_before = (install_root / "current").resolve()
            res_fail_start = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_bad_start),
                "--desired-deployment", str(dep_bad_start),
                "--json",
            ], env=env)
            assert res_fail_start.returncode != 0
            assert "ADD falhou ao iniciar bad_start" in res_fail_start.stderr or "ADD falhou ao iniciar bad_start" in res_fail_start.stdout
            assert (install_root / "current").resolve() == current_before
            print("[PASS] Negativo 1 — ADD falhando no start aborta e preserva current")

            # =============================================================
            # 5. NEGATIVO 2: ADD falhando no health
            # =============================================================
            port_bad_h = reserve_port()
            bad_health_comp = make_component(tmp, "sister-bad-health", "bad_health", "sister_bad_health")
            create_mock_runtime_script(bad_health_comp / "scripts" / "runtime.sh", port_bad_h, fail_on_health=True)
            desc_path = bad_health_comp / ".sister" / "component.json"
            desc = json.loads(desc_path.read_text(encoding="utf-8"))
            desc["build"]["artifacts"] = [{"id": "badh-bin", "path": "scripts/runtime.sh", "executable": True}]
            write_json(desc_path, desc)
            git_init_commit(bad_health_comp)

            cand_bad_health = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma", "../sister-bad-health"],
                "cand-bad-health",
            )
            dep_bad_health = tmp / "dep_bad_health.json"
            write_json(dep_bad_health, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-bad-health",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": gw_port, "listen": "127.0.0.1"},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                    {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
                    {"system_id": "sister_bad_health", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_bad_h}, "probe": {"health_path": "/api/health"}},
                ],
            })
            res_fail_h = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_bad_health),
                "--desired-deployment", str(dep_bad_health),
                "--json",
            ], env=env)
            assert res_fail_h.returncode != 0
            assert "health check de bad_health" in res_fail_h.stderr or "health check de bad_health" in res_fail_h.stdout
            assert (install_root / "current").resolve() == current_before
            print("[PASS] Negativo 2 — ADD falhando no health aborta e reverte")

            # =============================================================
            # 6. NEGATIVO 4: HAProxy validation (haproxy -c) falhando
            # =============================================================
            dep_bad_cfg = tmp / "dep_bad_cfg.json"
            write_json(dep_bad_cfg, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-bad-cfg",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": 999999, "listen": "127.0.0.1"},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                    {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
                ],
            })
            pid_gw_before = int(gateway_pid.read_text().strip())
            res_bad_val = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_bad_cfg),
                "--json",
            ], env=env)
            assert res_bad_val.returncode != 0
            assert int(gateway_pid.read_text().strip()) == pid_gw_before, "HAProxy ativo não pode ser modificado se validação falhar!"
            print("[PASS] Negativo 4 — HAProxy validation falhando aborta antes do reload")

            # =============================================================
            # 7. NEGATIVO 6: Falha pós-reload e Rollback gracioso sobre pid_target
            # =============================================================
            port_offline = reserve_port()
            delta_offline_comp = make_component(tmp, "sister-delta-offline", "delta_offline", "sister_delta_offline")
            create_mock_runtime_script(delta_offline_comp / "scripts" / "runtime.sh", port_offline, exit_after_start=True)
            desc_path = delta_offline_comp / ".sister" / "component.json"
            desc = json.loads(desc_path.read_text(encoding="utf-8"))
            desc["build"]["artifacts"] = [{"id": "doff-bin", "path": "scripts/runtime.sh", "executable": True}]
            write_json(desc_path, desc)
            git_init_commit(delta_offline_comp)

            cand_offline = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma", "../sister-delta-offline"],
                "cand-offline",
            )
            dep_offline_gw = tmp / "dep_offline_gw.json"
            write_json(dep_offline_gw, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-offline-gw",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": gw_port, "listen": "127.0.0.1"},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                    {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
                    {"system_id": "sister_delta_offline", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_offline}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "delta-offline.test"}},
                ],
            })

            old_cfg_content = gateway_cfg.read_text(encoding="utf-8")

            res_post_reload_fail = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_offline),
                "--desired-deployment", str(dep_offline_gw),
                "--json",
            ], env=env)
            assert res_post_reload_fail.returncode != 0
            assert "verificação do gateway após reload falhou" in res_post_reload_fail.stderr or "verificação do gateway após reload falhou" in res_post_reload_fail.stdout

            # Prova que o HAProxy foi restaurado para a configuração OLD
            assert gateway_cfg.read_text(encoding="utf-8") == old_cfg_content
            st_alpha_after, _ = probe_https_gateway("alpha-gateway.test", gw_port, "/api/health", ca_cert)
            assert st_alpha_after == 200, "HAProxy deve responder na configuração OLD após rollback"
            lifecycle.track_haproxy_pid_file(gateway_pid)
            print("[PASS] Negativo 6 — Falha pós-reload executa graceful rollback sobre pid_target e restaura OLD")

            # =============================================================
            # 8. NEGATIVO 9: Rotação de CA lab requerida (Fail-Closed)
            # =============================================================
            ca_exp_dir = tmp / "ca_exp"
            setup_ca(ca_exp_dir, days=5)
            env_exp = dict(env)
            env_exp["CA_CERT"] = str(ca_exp_dir / "ecosystem-lab-ca.crt")
            env_exp["CA_KEY"] = str(ca_exp_dir / "ecosystem-lab-ca.key")

            cand_ca_rot = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma", "../sister-delta"],
                "cand-ca-rot",
            )
            res_ca_rot = run_cmd([
                str(INFRA_CLI), "lab", "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_ca_rot),
                "--desired-deployment", str(dep_delta_file),
                "--json",
            ], env=env_exp)
            assert res_ca_rot.returncode != 0
            assert "CA lab exige rotação" in res_ca_rot.stderr or "CA lab exige rotação" in res_ca_rot.stdout
            lifecycle.track_haproxy_pid_file(gateway_pid)
            print("[PASS] Negativo 9 — Rotação de CA lab requer autoridade explícita (Fail-Closed)")

            # =============================================================
            # 9. NEGATIVO 10: Isolamento de Proxy Ambiental
            # =============================================================
            env_proxy = dict(env)
            env_proxy["HTTP_PROXY"] = "http://192.0.2.1:8080"
            env_proxy["HTTPS_PROXY"] = "http://192.0.2.1:8080"
            res_proxy = run_cmd([
                str(INFRA_CLI), "lab", "plan",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ], env=env_proxy, check=True)
            assert json.loads(res_proxy.stdout)["summary"]["keep"] == 3
            print("[PASS] Negativo 10 — Proxy ambiental não interfere em probes")

            # =============================================================
            # 10. ZERO RESÍDUOS (Filesystem + Processos + Listeners)
            # =============================================================
            # Encerra ordenadamente todos os processos da fixture
            lifecycle.terminate_all(timeout_sec=3.0)

            # 1. Prova formal: nenhum processo vivo cuja cmdline ou cwd contenha o root da fixture
            lifecycle.assert_zero_processes()

            # 2. Prova formal: nenhum listener remanescente nas portas alocadas pela fixture
            lifecycle.assert_no_listeners([
                gw_port, port_alpha, port_beta, port_gamma, port_delta,
                port_bad_s, port_bad_h, port_offline,
            ])

            # 3. Prova formal: nenhum arquivo transitório residual no filesystem
            assert not list(tmp.rglob("*.old_backup")), "Nenhum backup .old_backup deve restar!"
            assert not list(tmp.rglob("*.chk.*")), "Nenhum arquivo temporário de checagem deve restar!"
            assert not list(tmp.rglob("*.tmp.*")), "Nenhum arquivo .tmp.* deve restar!"
            print("[PASS] Zero Resíduos — Filesystem, processos e listeners 100% limpos e verificados")

        finally:
            lifecycle.terminate_all(timeout_sec=3.0)
            lifecycle.assert_zero_processes()

    print("[PASS] Todos os Gates de OPS-04 passaram com sucesso!")


if __name__ == "__main__":
    main()
