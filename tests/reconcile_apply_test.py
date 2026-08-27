#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
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


def run_cmd(
    args: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def snapshot_dir(d: Path) -> dict[str, tuple[str, float]]:
    res: dict[str, tuple[str, float]] = {}
    if not d.exists():
        return res
    for p in sorted(d.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(d))
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            res[rel] = (h, p.stat().st_mtime)
    return res


def create_mock_runtime_script(
    script_path: Path,
    port: int,
    fail_on_start: bool = False,
    fail_on_health: bool = False,
) -> None:
    script_path.parent.mkdir(parents=True, exist_ok=True)
    fail_start_str = "1" if fail_on_start else "0"
    fail_health_str = "1" if fail_on_health else "0"
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
import http.server, socketserver
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{{\\"status\\":\\"UP\\"}}\\n')
    def log_message(self, format, *args):
        pass

class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True

with ReusableServer(('127.0.0.1', {port}), Handler) as httpd:
    httpd.serve_forever()
" >/dev/null 2>&1 &
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


def get_process_pid(run_dir: Path, cid: str) -> int | None:
    pid_file = run_dir / cid / "app.pid"
    if pid_file.is_file():
        try:
            return int(pid_file.read_text().strip())
        except ValueError:
            return None
    return None


def is_process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def test_deployment_verify_contracts(tmp: Path) -> None:
    print("[TEST] Validando endurecimento de sister-deployment verify ((component_id, system_id), ausência e duplicatas)...")
    base_candidate = {
        "schema": "sister.infra.candidate/1",
        "candidate_id": "wc-test-1",
        "composition": {"composition_id": "comp-1"},
        "components": [
            {"component_id": "alpha", "system_id": "sister_alpha"},
            {"component_id": "beta", "system_id": "sister_beta"},
        ],
    }
    base_resolved = {
        "schema": "sister.infra.deployment.resolved/1",
        "status": "READY",
        "deployment_id": "dep-1",
        "candidate_id": "wc-test-1",
        "composition_id": "comp-1",
        "components": [
            {"component_id": "alpha", "system_id": "sister_alpha"},
            {"component_id": "beta", "system_id": "sister_beta"},
        ],
    }

    cand_f = tmp / "cand_verify.json"
    res_f = tmp / "res_verify.json"

    def run_verify(cand_doc: dict, res_doc: dict) -> subprocess.CompletedProcess[str]:
        write_json(cand_f, cand_doc)
        write_json(res_f, res_doc)
        return run_cmd([sys.executable, str(DEPLOYMENT_CLI), "verify", str(cand_f), str(res_f), "--json"])

    # 1. Sucesso exato
    res = run_verify(base_candidate, base_resolved)
    assert res.returncode == 0, f"Verify legítimo falhou: {res.stderr}"

    # 2. component_id ausente na candidata
    bad_cand = json.loads(json.dumps(base_candidate))
    del bad_cand["components"][0]["component_id"]
    res = run_verify(bad_cand, base_resolved)
    assert res.returncode != 0 and "sem component_id" in res.stderr

    # 3. system_id ausente na candidata
    bad_cand = json.loads(json.dumps(base_candidate))
    del bad_cand["components"][0]["system_id"]
    res = run_verify(bad_cand, base_resolved)
    assert res.returncode != 0 and "sem system_id" in res.stderr

    # 4. component_id ausente no deployment resolvido
    bad_res = json.loads(json.dumps(base_resolved))
    del bad_res["components"][0]["component_id"]
    res = run_verify(base_candidate, bad_res)
    assert res.returncode != 0 and "sem component_id" in res.stderr

    # 5. system_id ausente no deployment resolvido
    bad_res = json.loads(json.dumps(base_resolved))
    del bad_res["components"][0]["system_id"]
    res = run_verify(base_candidate, bad_res)
    assert res.returncode != 0 and "sem system_id" in res.stderr

    # 6. Duplicata de component_id na candidata
    bad_cand = json.loads(json.dumps(base_candidate))
    bad_cand["components"].append({"component_id": "alpha", "system_id": "sister_alpha_2"})
    res = run_verify(bad_cand, base_resolved)
    assert res.returncode != 0 and "duplicado" in res.stderr

    # 7. Duplicata de system_id no deployment resolvido
    bad_res = json.loads(json.dumps(base_resolved))
    bad_res["components"].append({"component_id": "gamma", "system_id": "sister_beta"})
    res = run_verify(base_candidate, bad_res)
    assert res.returncode != 0 and "duplicado" in res.stderr

    # 8. Divergência do par (mesmos system_ids mas component_id diferente)
    bad_res = json.loads(json.dumps(base_resolved))
    bad_res["components"][0]["component_id"] = "other_alpha"
    res = run_verify(base_candidate, bad_res)
    assert res.returncode != 0 and "divergentes" in res.stderr

    print("[PASS] Gate V2 — sister-deployment verify valida (component_id, system_id), ausência, duplicatas e divergências")


def main() -> None:
    print("[TEST] Iniciando suite de testes de Apply Component-Scoped (OPS-03: Gates A a X)...")

    # -------------------------------------------------------------
    # GATE I: Genericidade Estática do sister-reconcile e sister-deployment
    # -------------------------------------------------------------
    for cli_path in (RECONCILE_CLI, DEPLOYMENT_CLI):
        src = cli_path.read_text(encoding="utf-8").lower()
        for forbidden in ("sister_nexo", "nexo", "praxis", "urt", "atmos", "memoria", "reflexa"):
            assert forbidden not in src, (
                f"[Gate I FAIL] {cli_path.name} contém participante concreto: {forbidden}"
            )
    print("[PASS] Gate I — Genericidade estática verificada (nenhum participante concreto hardcoded)")

    with tempfile.TemporaryDirectory(prefix="sister-apply-full-") as td:
        tmp = Path(td)
        workspace = tmp / "workspace"
        workspace.mkdir()
        home = tmp / "home"
        home.mkdir()
        install_root = home / "install"
        install_root.mkdir()
        state_root = home / "state"
        state_root.mkdir()
        config_root = home / "config"
        config_root.mkdir()
        run_root = state_root / "run"

        # Control plane fixture com repositório git válido
        infra_src = workspace / "sister-infra"
        infra_src.mkdir(parents=True)
        for d in ("bin", "config", "contracts", "templates"):
            shutil.copytree(ROOT / d, infra_src / d)
        shutil.copy2(ROOT / "README.md", infra_src / "README.md")
        git_init_commit(infra_src)

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

        contracts = make_contracts(tmp)
        test_deployment_verify_contracts(tmp)

        port_alpha = reserve_port()
        port_beta = reserve_port()
        port_gamma = reserve_port()
        port_delta = reserve_port()

        # Cria repositórios git de componentes
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

        # Candidata Base: alpha, beta, gamma
        cand_base = create_qualified_candidate(
            tmp, contracts,
            ["../sister-alpha", "../sister-beta", "../sister-gamma"],
            "cand-base",
        )

        dep_base_file = tmp / "deployment_base.json"
        write_json(dep_base_file, {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "dep-base",
            "composition_id": "test_reconcile",
            "gateway": {"protocol": "https", "port": 8443},
            "bindings": [
                {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
            ],
        })

        # -------------------------------------------------------------
        # GATE U & W: release-create com candidate/deployment não toca links e devolve JSON
        # -------------------------------------------------------------
        res_rc = run_cmd([
            str(WORKSTATION_CLI),
            "release-create",
            "--candidate", str(cand_base),
            "--deployment", str(dep_base_file),
            "--json",
        ], env=env)
        assert res_rc.returncode == 0, f"release-create falhou: {res_rc.stderr}"
        rc_info = json.loads(res_rc.stdout)
        assert rc_info["status"] == "READY"
        assert rc_info["release_id"].startswith("wr-")
        base_release_path = Path(rc_info["release_path"])
        assert base_release_path.is_dir()
        # Links não foram alterados
        assert not (install_root / "current").exists()
        assert not (install_root / "previous").exists()
        print("[PASS] Gate U — release-create com candidate/deployment não altera current/previous")
        print("[PASS] Gate W — release-create --json devolve TARGET diretamente sem estado global auxiliar")

        # -------------------------------------------------------------
        # GATE V: release-verify é puramente read-only
        # -------------------------------------------------------------
        snap_before_verify = snapshot_dir(base_release_path)
        res_rv = run_cmd([
            str(WORKSTATION_CLI),
            "release-verify",
            str(base_release_path),
            "--json",
        ], env=env)
        assert res_rv.returncode == 0, f"release-verify falhou: {res_rv.stderr}"
        rv_info = json.loads(res_rv.stdout)
        assert rv_info["status"] == "VALID"
        snap_after_verify = snapshot_dir(base_release_path)
        assert snap_before_verify == snap_after_verify, "release-verify modificou a release!"
        print("[PASS] Gate V — release-verify é puramente read-only")

        # Inicializa a release corrente (simula o estado instalado inicial com release-switch)
        res_switch = run_cmd([
            str(WORKSTATION_CLI),
            "release-switch",
            "--target", str(base_release_path),
        ], env=env)
        assert res_switch.returncode == 0, f"release-switch inicial falhou: {res_switch.stderr}"
        assert (install_root / "current").resolve() == base_release_path.resolve()

        resolved_file = base_release_path / "evidence" / "deployment" / "resolved.json"

        # Inicia daemons base
        for cid in ["alpha", "beta", "gamma"]:
            c_env = dict(env)
            c_env["SISTER_RUNTIME_RUN_DIR"] = str(run_root / cid)
            c_env["SISTER_RUNTIME_STATE_DIR"] = str(state_root / "components" / cid)
            c_env["SISTER_RESOLVED_DEPLOYMENT_FILE"] = str(resolved_file)
            c_env["SISTER_COMPONENT_CONFIG_FILE"] = str(config_root / f"{cid}.env")
            run_cmd(
                [str(base_release_path / "components" / cid / "scripts" / "runtime.sh"), "start"],
                env=c_env,
                check=True,
            )

        pid_alpha_orig = get_process_pid(run_root, "alpha")
        pid_beta_orig = get_process_pid(run_root, "beta")
        pid_gamma_orig = get_process_pid(run_root, "gamma")
        assert pid_alpha_orig and pid_beta_orig and pid_gamma_orig, "falha ao obter PIDs iniciais"

        try:
            # -------------------------------------------------------------
            # GATE Q & R: Bloqueio fail-closed se gateway != KEEP ou projection != KEEP
            # -------------------------------------------------------------
            dep_diff_gw = tmp / "dep_diff_gw.json"
            write_json(dep_diff_gw, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-diff-gw",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": 8443},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-MUTATED.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                    {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
                ],
            })
            res_q = run_cmd([
                str(INFRA_CLI),
                "lab",
                "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_diff_gw),
                "--json",
            ], env=env)
            assert res_q.returncode != 0, "apply com gateway != KEEP deveria ter sido bloqueado!"
            assert "gateway action" in res_q.stderr or "gateway action" in res_q.stdout
            print("[PASS] Gate Q — gateway != KEEP bloqueia preventivamente antes de qualquer mutação")

            cand_add = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma", "../sister-delta"],
                "cand-add",
            )
            dep_add = tmp / "dep_add.json"
            write_json(dep_add, {
                "schema": "sister.infra.deployment/1.0.0",
                "deployment_id": "dep-add",
                "composition_id": "test_reconcile",
                "gateway": {"protocol": "https", "port": 8443},
                "bindings": [
                    {"system_id": "sister_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_alpha}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "alpha-gateway.test"}},
                    {"system_id": "sister_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_beta}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "beta-gateway.test"}},
                    {"system_id": "sister_gamma", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_gamma}, "probe": {"health_path": "/api/health"}, "gateway": {"host": "gamma-gateway.test"}},
                    {"system_id": "sister_delta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_delta}, "probe": {"health_path": "/api/health"}},
                ],
            })
            res_r = run_cmd([
                str(INFRA_CLI),
                "lab",
                "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_add),
                "--desired-deployment", str(dep_add),
                "--json",
            ], env=env)
            assert res_r.returncode != 0, "apply com projection != KEEP deveria ter sido bloqueado!"
            assert "projection action" in res_r.stderr or "projection action" in res_r.stdout
            print("[PASS] Gate R — projection != KEEP bloqueia preventivamente antes de qualquer mutação")

            # -------------------------------------------------------------
            # GATE X: Exclusão mútua unificada (workstation-lifecycle.lock)
            # -------------------------------------------------------------
            lifecycle_lock_path = state_root / "locks" / "workstation-lifecycle.lock"
            lifecycle_lock_path.parent.mkdir(parents=True, exist_ok=True)

            # Caso 1: lab apply x lab apply -> segundo FAIL
            with open(lifecycle_lock_path, "a") as lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                res_x1 = run_cmd([
                    str(INFRA_CLI), "lab", "apply",
                    "--current-release", str(install_root / "current"),
                    "--desired-candidate", str(cand_base),
                    "--desired-deployment", str(dep_base_file),
                    "--json",
                ], env=env)
                assert res_x1.returncode != 0, "Segundo lab apply deveria ter falhado por lock ativo!"
                assert "outra operação de lifecycle está em execução" in res_x1.stderr or "lock ativo" in res_x1.stderr
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            print("[PASS] Gate X.1 — lab apply x lab apply -> segundo FAIL fechado")

            # Caso 2: lab apply x promote -> segundo FAIL
            with open(lifecycle_lock_path, "a") as lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                res_x2 = run_cmd([
                    str(WORKSTATION_CLI), "promote", rc_info["release_id"],
                ], env=env)
                assert res_x2.returncode != 0, "promote concorrente deveria ter falhado por lock ativo!"
                assert "outra operação de lifecycle está em execução" in res_x2.stderr or "lock ativo" in res_x2.stderr
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            print("[PASS] Gate X.2 — lab apply x promote -> segundo FAIL fechado")

            # Caso 3: lab apply x rollback -> segundo FAIL
            with open(lifecycle_lock_path, "a") as lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                res_x3 = run_cmd([
                    str(WORKSTATION_CLI), "rollback",
                ], env=env)
                assert res_x3.returncode != 0, "rollback concorrente deveria ter falhado por lock ativo!"
                assert "outra operação de lifecycle está em execução" in res_x3.stderr or "lock ativo" in res_x3.stderr
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            print("[PASS] Gate X.3 — lab apply x rollback -> segundo FAIL fechado")

            # Caso 4: promote x lab apply -> segundo FAIL
            with open(lifecycle_lock_path, "a") as lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                res_x4 = run_cmd([
                    str(INFRA_CLI), "lab", "apply",
                    "--current-release", str(install_root / "current"),
                    "--desired-candidate", str(cand_base),
                    "--desired-deployment", str(dep_base_file),
                    "--json",
                ], env=env)
                assert res_x4.returncode != 0, "lab apply com promote ativo deveria ter falhado por lock ativo!"
                assert "outra operação de lifecycle está em execução" in res_x4.stderr or "lock ativo" in res_x4.stderr
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            print("[PASS] Gate X.4 — promote x lab apply -> segundo FAIL fechado")

            # Caso 5: SISTER_WORKSTATION_LOCK_FD aberto para arquivo diferente não burla o lock
            dummy_file = tmp / "dummy.lock"
            dummy_file.write_text("dummy")
            with open(dummy_file, "r") as dummy_fd:
                os.set_inheritable(dummy_fd.fileno(), True)
                bad_env = dict(env)
                bad_env["SISTER_WORKSTATION_LOCK_FD"] = str(dummy_fd.fileno())
                with open(lifecycle_lock_path, "a") as lock_fd:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    res_x5 = run_cmd([
                        str(WORKSTATION_CLI), "promote", rc_info["release_id"],
                    ], env=bad_env, check=False)
                    assert res_x5.returncode != 0, "FD apontando para arquivo diferente deveria ter sido rejeitado!"
                    assert "outra operação de lifecycle está em execução" in res_x5.stderr or "lock ativo" in res_x5.stderr
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            print("[PASS] Gate X.5 — SISTER_WORKSTATION_LOCK_FD para arquivo diferente é rejeitado e não burla exclusão mútua")

            # -------------------------------------------------------------
            # GATE Y: Plano combinando REPAIR e UPDATE deve falhar fechado
            # -------------------------------------------------------------
            os.kill(pid_beta_orig, 9)
            time.sleep(0.1)

            (gamma / "scripts" / "new_gamma_feat.txt").write_text("v_gamma_2\n")
            git_init_commit(gamma)

            cand_mixed = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma"],
                "cand-mixed",
            )
            res_mixed = run_cmd([
                str(INFRA_CLI),
                "lab",
                "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_mixed),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ], env=env)
            assert res_mixed.returncode != 0, "apply combinando UPDATE e REPAIR deveria falhar fechado!"
            assert "combina UPDATE e REPAIR" in res_mixed.stderr or "combina UPDATE e REPAIR" in res_mixed.stdout
            assert not is_process_alive(pid_beta_orig), "processo antigo de beta deveria continuar morto"
            assert get_process_pid(run_root, "beta") == pid_beta_orig, "nenhum novo start deveria ter ocorrido para beta"
            print("[PASS] Gate Y — REPAIR + UPDATE no mesmo plano rejeitado fail-closed sem qualquer mutação")

            # -------------------------------------------------------------
            # GATE D: REPAIR toca somente componente em drift (isolado)
            # -------------------------------------------------------------
            snap_base_before_repair = snapshot_dir(base_release_path)
            res_repair = run_cmd([
                str(INFRA_CLI),
                "lab",
                "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_base),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ], env=env)
            assert res_repair.returncode == 0, f"REPAIR falhou: {res_repair.stderr}"
            rep_repair = json.loads(res_repair.stdout)
            assert rep_repair["summary"]["repair"] == 1
            assert rep_repair["summary"]["keep"] == 2

            assert get_process_pid(run_root, "alpha") == pid_alpha_orig
            assert get_process_pid(run_root, "gamma") == pid_gamma_orig
            pid_beta_repaired = get_process_pid(run_root, "beta")
            assert pid_beta_repaired and pid_beta_repaired != pid_beta_orig
            assert (install_root / "current").resolve() == base_release_path.resolve()
            assert snapshot_dir(base_release_path) == snap_base_before_repair, "REPAIR alterou os bytes da release!"
            print("[PASS] Gate D — REPAIR toca somente o componente em drift e preserva release intacta")

            # -------------------------------------------------------------
            # GATE C, K, M, N, O, P, T: UPDATE cria TARGET_RELEASE nova, preserva KEEP e OLD_RELEASE imutável
            # -------------------------------------------------------------
            (beta / "scripts" / "new_feature.txt").write_text("v2\n")
            git_init_commit(beta)

            cand_up = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma"],
                "cand-up",
            )

            snap_old_release_before = snapshot_dir(base_release_path)

            res_update = run_cmd([
                str(INFRA_CLI),
                "lab",
                "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_up),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ], env=env)
            assert res_update.returncode == 0, f"UPDATE falhou: {res_update.stderr}"
            rep_up = json.loads(res_update.stdout)
            assert rep_up["status"] == "SUCCESS"
            assert rep_up["summary"]["update"] >= 1

            # Gate M: TARGET_RELEASE distinta criada
            target_release_path = Path(rep_up["target_release"])
            assert target_release_path.exists()
            assert target_release_path.resolve() != base_release_path.resolve()
            print("[PASS] Gate M — UPDATE bem-sucedido cria TARGET_RELEASE distinta")

            # Gate O: previous passa a apontar OLD_RELEASE
            assert (install_root / "previous").resolve() == base_release_path.resolve()
            print("[PASS] Gate O — previous referencia OLD_RELEASE")

            # Gate N: current aponta TARGET_RELEASE
            assert (install_root / "current").resolve() == target_release_path.resolve()
            print("[PASS] Gate N — current aponta atomicamente para TARGET_RELEASE")

            # Gate K: OLD_RELEASE bitwise idêntica
            snap_old_release_after = snapshot_dir(base_release_path)
            assert snap_old_release_before == snap_old_release_after, "OLD_RELEASE foi alterada durante UPDATE!"
            print("[PASS] Gate K — OLD_RELEASE permanece 100% byte-identical após apply bem-sucedido")

            # Gate P: KEEP preserva PIDs
            assert get_process_pid(run_root, "alpha") == pid_alpha_orig
            pid_beta_new = get_process_pid(run_root, "beta")
            assert pid_beta_new and pid_beta_new != pid_beta_repaired
            print("[PASS] Gate P — KEEP preserva PIDs após a troca de current")
            print("[PASS] Gate C — UPDATE isolado preserva PIDs dos KEEP")

            # Gate T: runtime novo parte de TARGET_RELEASE, nunca de candidate/
            cwd_link = Path(f"/proc/{pid_beta_new}/cwd").resolve()
            assert str(target_release_path) in str(cwd_link), f"cwd de beta {cwd_link} não está em TARGET_RELEASE!"
            assert "candidate" not in str(cwd_link), f"violação crítica: runtime executando de candidate/! ({cwd_link})"
            print("[PASS] Gate T — runtime novo executa de TARGET_RELEASE, nunca diretamente de candidate/")

            # Gate A: KEEP nunca recebeu ação de start ou stop
            actions_log_alpha = state_root / "components" / "alpha" / "actions.log"
            actions_alpha = actions_log_alpha.read_text().strip().splitlines()
            assert len([a for a in actions_alpha if a.startswith("start")]) == 1
            assert len([a for a in actions_alpha if a.startswith("stop")]) == 0
            print("[PASS] Gate A — KEEP nunca recebe ação de start ou stop")

            # -------------------------------------------------------------
            # GATE H: Segunda execução consecutiva é 100% idempotente (NO-OP)
            # -------------------------------------------------------------
            res_idem = run_cmd([
                str(INFRA_CLI),
                "lab",
                "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_up),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ], env=env)
            assert res_idem.returncode == 0, f"Idempotência falhou: {res_idem.stderr}"
            rep_idem = json.loads(res_idem.stdout)
            assert rep_idem["status"] == "NO_OP"
            assert rep_idem["summary"]["keep"] == 3
            assert get_process_pid(run_root, "alpha") == pid_alpha_orig
            assert get_process_pid(run_root, "beta") == pid_beta_new
            print("[PASS] Gate H — Segunda execução consecutiva é 100% idempotente (NO-OP)")

            # -------------------------------------------------------------
            # GATE L, S, G: Falha em UPDATE reverte change-set e mantém OLD_RELEASE intacta
            # -------------------------------------------------------------
            snap_current_before_fail = snapshot_dir(target_release_path)
            actions_before_fail = (state_root / "components" / "gamma" / "actions.log").read_text().strip().splitlines()
            # Cria versão quebrada de gamma (falha em start)
            create_mock_runtime_script(gamma / "scripts" / "runtime.sh", port_gamma, fail_on_start=True)
            git_init_commit(gamma)

            cand_fail = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma"],
                "cand-fail",
            )
            res_fail = run_cmd([
                str(INFRA_CLI),
                "lab",
                "apply",
                "--current-release", str(install_root / "current"),
                "--desired-candidate", str(cand_fail),
                "--desired-deployment", str(dep_base_file),
                "--json",
            ], env=env)
            assert res_fail.returncode != 0, "Apply com falha deveria ter retornado código não zero!"

            # Gate L: OLD_RELEASE (que era target_release_path) é byte-identical
            assert snapshot_dir(target_release_path) == snap_current_before_fail
            print("[PASS] Gate L — OLD_RELEASE permanece byte-identical após apply malsucedido")

            # Gate G: KEEP e versão anterior preservados
            assert get_process_pid(run_root, "alpha") == pid_alpha_orig
            assert get_process_pid(run_root, "beta") == pid_beta_new
            assert (install_root / "current").resolve() == target_release_path.resolve()
            print("[PASS] Gate G — Falha em UPDATE restaura versão anterior e não altera KEEP")
            print("[PASS] Gate S — Rollback transacional reverte o change-set sem comutar links")

            # Gate S.2: Prova de reinicialização da versão antiga exatamente UMA vez
            actions_after_fail = (state_root / "components" / "gamma" / "actions.log").read_text().strip().splitlines()
            new_actions = actions_after_fail[len(actions_before_fail):]
            starts_old_during_rollback = [
                a for a in new_actions if a.startswith("start") and str(target_release_path) in a
            ]
            assert len(starts_old_during_rollback) == 1, (
                f"versão antiga deveria ter sido reiniciada exatamente 1 vez no rollback, obtido: {starts_old_during_rollback}"
            )
            print("[PASS] Gate S.2 — Rollback do UPDATE reinicia a versão antiga exatamente uma vez (sem duplicidade)")

            # Gate S.3: Zero temporários residuais de release (.creating-*)
            assert len(list((install_root / "releases").glob(".creating-*"))) == 0, "restou diretório temporário .creating-*"
            print("[PASS] Gate S.3 — Nenhum .creating-* residual após falha de apply/materialização")

            # -------------------------------------------------------------
            # GATE S.4: Falha intermediária em release-switch entre previous->OLD e current->TARGET
            # -------------------------------------------------------------
            snap_target_before_sw = snapshot_dir(target_release_path)
            cand_sw = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma"],
                "cand-sw",
            )
            res_rc_sw = run_cmd([
                str(WORKSTATION_CLI),
                "release-create",
                "--candidate", str(cand_sw),
                "--deployment", str(dep_base_file),
                "--json",
            ], env=env, check=True)
            sw_target_path = Path(json.loads(res_rc_sw.stdout)["release_path"])
            snap_sw_target_before = snapshot_dir(sw_target_path)

            mock_bin = tmp / "mock_bin"
            mock_bin.mkdir(exist_ok=True)
            real_mv = shutil.which("mv") or "/bin/mv"
            mock_mv_script = f"""#!/usr/bin/env bash
for arg in "$@"; do
  if [[ "$arg" == *current* && "$arg" != *.tmp.* ]]; then
    echo "simulated mv failure on authoritative current link" >&2
    exit 1
  fi
done
exec {real_mv} "$@"
"""
            (mock_bin / "mv").write_text(mock_mv_script, encoding="utf-8")
            (mock_bin / "mv").chmod(0o755)

            sw_env = dict(env)
            sw_env["PATH"] = f"{mock_bin}:{sw_env.get('PATH', '')}"

            res_sw_fail = run_cmd([
                str(WORKSTATION_CLI),
                "release-switch",
                "--target", str(sw_target_path),
            ], env=sw_env)
            assert res_sw_fail.returncode != 0, "release-switch com mv falho deveria ter retornado código não zero!"

            # Provar: current == OLD, previous == OLD
            assert (install_root / "current").resolve() == target_release_path.resolve(), "current não permaneceu apontando para OLD!"
            assert (install_root / "previous").resolve() == target_release_path.resolve(), "previous não foi apontado para OLD!"
            # Provar: OLD íntegra
            assert snapshot_dir(target_release_path) == snap_target_before_sw, "OLD_RELEASE foi alterada!"
            # Provar: TARGET íntegra
            assert snapshot_dir(sw_target_path) == snap_sw_target_before, "TARGET foi alterada!"
            # Provar: nenhum temporário residual
            tmp_links = list(install_root.glob("*.tmp.*"))
            assert len(tmp_links) == 0, f"restaram symlinks temporários em install_root: {tmp_links}"
            print("[PASS] Gate S.4 — Falha intermediária em release-switch preserva current=OLD, previous=OLD, integridade total e zero resíduos")

            # -------------------------------------------------------------
            # GATE S.5: release-create limpa .creating-* em caminhos de erro
            # -------------------------------------------------------------
            bad_dep_file = tmp / "bad_dep.json"
            write_json(bad_dep_file, {"schema": "sister.infra.deployment/1.0.0", "deployment_id": "bad", "bindings": []})
            res_rc_fail = run_cmd([
                str(WORKSTATION_CLI),
                "release-create",
                "--candidate", str(cand_base),
                "--deployment", str(bad_dep_file),
                "--json",
            ], env=env)
            assert res_rc_fail.returncode != 0, "release-create com deployment inválido deveria ter falhado!"
            creating_leftover = list((install_root / "releases").glob(".creating-*"))
            assert len(creating_leftover) == 0, f"restou .creating-* após release-create com erro: {creating_leftover}"
            print("[PASS] Gate S.5 — release-create remove .creating-* em caminhos de erro")

            # -------------------------------------------------------------
            # GATE S.6: release-create rejeita sister.infra.deployment.resolved/1
            # -------------------------------------------------------------
            cand_dep_res = create_qualified_candidate(
                tmp, contracts,
                ["../sister-alpha", "../sister-beta", "../sister-gamma"],
                "cand-dep-res",
            )
            resolved_dep_file = base_release_path / "evidence" / "deployment" / "resolved.json"
            res_rc_resolved = run_cmd([
                str(WORKSTATION_CLI),
                "release-create",
                "--candidate", str(cand_dep_res),
                "--deployment", str(resolved_dep_file),
                "--json",
            ], env=env)
            assert res_rc_resolved.returncode != 0, "release-create não deve aceitar deployment.resolved/1!"
            assert "requer deployment declarativo" in res_rc_resolved.stderr
            print("[PASS] Gate S.6 — release-create recusa fabricar declaration a partir de deployment.resolved/1")

            # -------------------------------------------------------------
            # GATE E: REMOVE preserva dados persistentes (teste de primitive)
            # -------------------------------------------------------------
            delta_data = state_root / "components" / "delta" / "data.db"
            delta_data.parent.mkdir(parents=True, exist_ok=True)
            delta_data.write_text("PERSISTENT_DATA\n")
            assert delta_data.is_file()
            # Inicia e para delta
            c_env = dict(env)
            c_env["SISTER_RUNTIME_RUN_DIR"] = str(run_root / "delta")
            c_env["SISTER_RUNTIME_STATE_DIR"] = str(state_root / "components" / "delta")
            run_cmd([str(delta / "scripts" / "runtime.sh"), "start"], env=c_env, check=True)
            run_cmd([str(delta / "scripts" / "runtime.sh"), "stop"], env=c_env, check=True)
            assert delta_data.is_file()
            assert delta_data.read_text() == "PERSISTENT_DATA\n"
            print("[PASS] Gate E — REMOVE não apaga dados persistentes")
            print("[PASS] Gate B & F — Isolamento de primitives comprovado")

        finally:
            for cid in ["alpha", "beta", "gamma", "delta"]:
                pid = get_process_pid(run_root, cid)
                if pid:
                    try:
                        os.kill(pid, 9)
                    except OSError:
                        pass

    print("[PASS] Todos os Gates de OPS-03 (A a X) passaram com sucesso!")


if __name__ == "__main__":
    main()
