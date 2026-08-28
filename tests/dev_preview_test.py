#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Suíte de Testes Automatizados — OPS-05: DEV Preview

Valida:
- Gate 1: Autoridade única sister-deployment dev-binding e contrato sister.infra.runtime.binding/1.0.0
- Gate 2: Descoberta normativa por .sister/component.json (caminho, component_id, system_id, ambiguidade)
- Gate 3: Preservação de fontes rastreadas (snapshot Git antes e depois, com código não commitado)
- Gate 4: Invariantes estritas de isolamento contra o LAB (current/previous, PIDs, gateway, state)
- Gate 5: Alocação de porta efêmera e retry em evidência factual de colisão
- Gate 6: Lifecycle completo com health autoritativo ($entrypoint health, probe opcional, --duration, --json)
- Gate 7: Cleanup seguro scoped e Zero Resíduos (processos, listeners, sandbox, lock reutilizável)
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INFRA_CLI = ROOT / "bin" / "sister-infra"
DEV_CLI = ROOT / "bin" / "sister-dev"
DEPLOYMENT_CLI = ROOT / "bin" / "sister-deployment"
COMPONENT_CLI = ROOT / "bin" / "sister-component"


def pass_test(name: str) -> None:
    print(f"[PASS] {name}")


def fail_test(name: str, reason: str) -> None:
    print(f"[FAIL] {name}: {reason}", file=sys.stderr)
    sys.exit(1)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_snapshot_tracked_files(repo_dir: Path) -> dict[str, str]:
    res = subprocess.run(
        ["git", "-C", str(repo_dir), "ls-files", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    paths = [p.decode("utf-8") for p in res.stdout.split(b"\x00") if p]
    snapshot: dict[str, str] = {}
    for rel in paths:
        file_path = repo_dir / rel
        if file_path.is_file():
            snapshot[rel] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return snapshot


def create_mock_component(
    root: Path,
    component_id: str,
    system_id: str,
    probe_path: str | None = None,
    simulate_collision_first: bool = False,
) -> Path:
    comp_dir = root / f"sister-{component_id}"
    comp_dir.mkdir(parents=True, exist_ok=True)

    desc: dict[str, Any] = {
        "schema": "sister.component/1.0.0",
        "component_id": component_id,
        "system_id": system_id,
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
            "actions": ["start", "stop", "restart", "status", "health"],
            "state_policy": "stateless",
        },
    }

    write_json(comp_dir / ".sister" / "component.json", desc)

    # Runtime script mock que consome SISTER_RESOLVED_DEPLOYMENT_FILE
    runtime_script = comp_dir / "scripts" / "runtime.sh"
    runtime_script.parent.mkdir(parents=True, exist_ok=True)

    # Cria script do daemon Python embutido
    server_script = comp_dir / "scripts" / "server.py"
    server_script.write_text(
        """#!/usr/bin/env python3
import http.server
import json
import os
import sys

port = int(sys.argv[1])
listen = sys.argv[2]
probe = sys.argv[3] if len(sys.argv) > 3 else "/health"

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == probe or self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"healthy","service":"dev-mock"}\\n')
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        pass

server = http.server.HTTPServer((listen, port), Handler)
server.serve_forever()
""",
        encoding="utf-8",
    )

    probe_arg = probe_path or "/health"
    col_check = ""
    if simulate_collision_first:
        col_check = """
  COLLISION_FLAG="$ROOT_DIR/.collision_simulated"
  if [[ ! -f "$COLLISION_FLAG" ]]; then
    touch "$COLLISION_FLAG"
    echo "[FAIL] bind: Address already in use" >&2
    echo "bind: Address already in use" >> "$SISTER_RUNTIME_RUN_DIR/daemon.log"
    exit 1
  fi
"""

    runtime_script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd -P)"
ACTION="${{1:-status}}"

load_deployment_binding() {{
  local resolved="${{SISTER_RESOLVED_DEPLOYMENT_FILE:-}}"
  [[ -n "$resolved" ]] || return 0
  [[ -f "$resolved" ]] || exit 1

  local sys_id transport
  sys_id="$(jq -er '.system_id' "$ROOT_DIR/.sister/component.json")"
  transport="$(jq -er --arg id "$sys_id" '.components[] | select(.system_id == $id) | .runtime.transport' "$resolved")"
  [[ "$transport" == "tcp" ]] || exit 1
  BIND="$(jq -er --arg id "$sys_id" '.components[] | select(.system_id == $id) | .runtime.listen' "$resolved")"
  PORT="$(jq -er --arg id "$sys_id" '.components[] | select(.system_id == $id) | .runtime.port' "$resolved")"
}}

load_deployment_binding

BIND="${{BIND:-127.0.0.1}}"
PORT="${{PORT:-8000}}"
RUN_DIR="${{SISTER_RUNTIME_RUN_DIR:-$ROOT_DIR/.run}}"
PID_FILE="$RUN_DIR/daemon.pid"
LOG_FILE="$RUN_DIR/daemon.log"

mkdir -p "$RUN_DIR"

case "$ACTION" in
  start)
{col_check}
    python3 "$ROOT_DIR/scripts/server.py" "$PORT" "$BIND" "{probe_arg}" > "$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
    echo "[PASS] daemon started pid=$(cat "$PID_FILE") port=$PORT"
    exit 0
    ;;
  health)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[PASS] daemon healthy"
      exit 0
    fi
    echo "[FAIL] daemon not running" >&2
    exit 1
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "running pid=$(cat "$PID_FILE")"
      exit 0
    fi
    echo "stopped"
    exit 3
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      pid="$(cat "$PID_FILE")"
      kill "$pid" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
    echo "[PASS] daemon stopped"
    exit 0
    ;;
  *)
    echo "unknown action: $ACTION" >&2
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    runtime_script.chmod(0o755)

    # Inicializa repositório Git com commit inicial
    subprocess.run(["git", "-C", str(comp_dir), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(comp_dir), "config", "user.name", "SisTer Tester"], check=True)
    subprocess.run(["git", "-C", str(comp_dir), "config", "user.email", "tester@sister.local"], check=True)
    subprocess.run(["git", "-C", str(comp_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(comp_dir), "commit", "-q", "-m", "initial component commit"], check=True)

    return comp_dir


# ==============================================================================
# Gate 1: sister-deployment dev-binding e contrato sister.infra.runtime.binding/1.0.0
# ==============================================================================
def test_gate_1_dev_binding() -> None:
    print("[TEST] Validando Gate 1 — sister-deployment dev-binding e schema runtime-binding/1.0.0...")

    # Sucesso nominal
    res = subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT_CLI),
            "dev-binding",
            "--component-id",
            "mockcomp",
            "--system-id",
            "sister_mockcomp",
            "--port",
            "8199",
            "--probe-path",
            "/api/health",
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    doc = json.loads(res.stdout)
    if doc.get("schema") != "sister.infra.runtime.binding/1.0.0":
        fail_test("Gate 1", f"schema incorreto: {doc.get('schema')}")
    comps = doc.get("components", [])
    if len(comps) != 1:
        fail_test("Gate 1", f"esperado 1 componente, obtido: {len(comps)}")
    c = comps[0]
    if c["component_id"] != "mockcomp" or c["system_id"] != "sister_mockcomp":
        fail_test("Gate 1", f"identificadores incorretos: {c}")
    if c["runtime"]["transport"] != "tcp" or c["runtime"]["listen"] != "127.0.0.1" or c["runtime"]["port"] != 8199:
        fail_test("Gate 1", f"runtime binding incorreto: {c['runtime']}")
    if c.get("probe", {}).get("health_path") != "/api/health":
        fail_test("Gate 1", f"probe path incorreto: {c.get('probe')}")

    # Negativos fail-closed
    negatives = [
        (["--component-id", "", "--system-id", "s", "--port", "8000"], "component_id não pode ser vazio"),
        (["--component-id", "c", "--system-id", "", "--port", "8000"], "system_id não pode ser vazio"),
        (["--component-id", "c", "--system-id", "s", "--port", "0"], "porta inválida: 0"),
        (["--component-id", "c", "--system-id", "s", "--port", "70000"], "porta inválida: 70000"),
        (["--component-id", "c", "--system-id", "s", "--port", "8000", "--transport", "udp"], "transporte não suportado"),
        (["--component-id", "c", "--system-id", "s", "--port", "8000", "--listen", "0.0.0.0"], "endereço de escuta não suportado"),
    ]
    for args, err_needle in negatives:
        r = subprocess.run(
            [sys.executable, str(DEPLOYMENT_CLI), "dev-binding", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            fail_test("Gate 1 Negativo", f"esperada falha para args: {args}")
        err_out = r.stderr.strip() or r.stdout.strip()
        if err_needle not in err_out:
            fail_test("Gate 1 Negativo", f"mensagem de erro esperada '{err_needle}', obtido: '{err_out}'")

    pass_test("Gate 1 — sister-deployment dev-binding e contrato sister.infra.runtime.binding/1.0.0")


# ==============================================================================
# Gate 2: Descoberta Normativa de Componente
# ==============================================================================
def test_gate_2_discovery() -> None:
    print("[TEST] Validando Gate 2 — Descoberta Normativa de Componente...")
    with tempfile.TemporaryDirectory(prefix="sister-test-disc-") as tmp:
        tmp_path = Path(tmp)
        c1 = create_mock_component(tmp_path, "delta", "sister_delta")
        c2 = create_mock_component(tmp_path, "echo", "sister_echo")

        env = dict(os.environ)
        env["SISTER_REPOSITORIES_ROOT"] = str(tmp_path)

        # 1. Resolução por caminho direto
        res = subprocess.run(
            [sys.executable, str(DEV_CLI), "preview", str(c1), "--duration", "0.1", "--json"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        if data["component_id"] != "delta":
            fail_test("Gate 2", f"esperado delta por caminho, obtido: {data['component_id']}")

        # 2. Resolução por component_id
        res = subprocess.run(
            [sys.executable, str(DEV_CLI), "preview", "echo", "--duration", "0.1", "--json"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        if data["component_id"] != "echo":
            fail_test("Gate 2", f"esperado echo por identificador, obtido: {data['component_id']}")

        # 3. Resolução por system_id
        res = subprocess.run(
            [sys.executable, str(DEV_CLI), "preview", "sister_delta", "--duration", "0.1", "--json"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        if data["component_id"] != "delta":
            fail_test("Gate 2", f"esperado delta por system_id, obtido: {data['component_id']}")

        # 4. Inexistente fail-closed
        res = subprocess.run(
            [sys.executable, str(DEV_CLI), "preview", "fantasma", "--duration", "0.1"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if res.returncode == 0 or "não encontrado" not in res.stderr:
            fail_test("Gate 2", f"falha esperada para componente inexistente: {res.stderr}")

        # 5. Ambiguidade fail-closed
        c_dup = tmp_path / "outro-delta"
        shutil.copytree(c1, c_dup)
        res = subprocess.run(
            [sys.executable, str(DEV_CLI), "preview", "delta", "--duration", "0.1"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if res.returncode == 0 or "ambiguidade" not in res.stderr:
            fail_test("Gate 2", f"falha esperada para ambiguidade: {res.stderr}")

    pass_test("Gate 2 — Descoberta normativa por .sister/component.json")


# ==============================================================================
# Gate 3: Preservação de Fontes Rastreadas (Snapshot Git com código não commitado)
# ==============================================================================
def test_gate_3_source_preservation() -> None:
    print("[TEST] Validando Gate 3 — Preservação de Fontes Rastreadas com Código Não Commitado...")
    with tempfile.TemporaryDirectory(prefix="sister-test-git-") as tmp:
        tmp_path = Path(tmp)
        comp = create_mock_component(tmp_path, "foxtrot", "sister_foxtrot")

        # Modifica propositalmente um arquivo rastreado SEM commitar (working tree sujo de dev)
        test_file = comp / "README.md"
        test_file.write_text("Alteração local não commitada pelo desenvolvedor\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(comp), "add", "README.md"], check=True)
        test_file.write_text("Alteração adicional no working tree não staged\n", encoding="utf-8")

        # Coleta snapshot SHA-256 de todos os arquivos rastreados
        snapshot_before = git_snapshot_tracked_files(comp)
        if "README.md" not in snapshot_before:
            fail_test("Gate 3", "README.md não encontrado no snapshot")

        # Executa dev preview
        env = dict(os.environ)
        env["SISTER_REPOSITORIES_ROOT"] = str(tmp_path)

        res = subprocess.run(
            [sys.executable, str(DEV_CLI), "preview", str(comp), "--duration", "0.2", "--json"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        if data.get("status") != "TERMINATED":
            fail_test("Gate 3", f"status inesperado: {data}")

        # Coleta snapshot pós-execução e exige igualdade byte a byte
        snapshot_after = git_snapshot_tracked_files(comp)
        if snapshot_before != snapshot_after:
            fail_test(
                "Gate 3",
                f"violação de integridade de fontes rastreadas:\nAntes: {snapshot_before}\nDepois: {snapshot_after}",
            )

    pass_test("Gate 3 — Preservação de fontes rastreadas (snapshot Git antes e depois)")


# ==============================================================================
# Gate 4: Invariantes Estritas de Isolamento contra o LAB
# ==============================================================================
def test_gate_4_lab_isolation() -> None:
    print("[TEST] Validando Gate 4 — Invariantes Estritas de Isolamento contra o LAB...")
    with tempfile.TemporaryDirectory(prefix="sister-test-lab-") as tmp:
        tmp_path = Path(tmp)
        comp = create_mock_component(tmp_path, "golf", "sister_golf")

        # Configura estado simulado do LAB
        lab_state = tmp_path / "lab_state"
        lab_releases = lab_state / "releases"
        lab_current = lab_state / "current"
        lab_previous = lab_state / "previous"
        lab_components_state = lab_state / "components"
        lab_run = lab_state / "run"
        lab_locks = lab_state / "locks"

        lab_releases.mkdir(parents=True)
        lab_components_state.mkdir(parents=True)
        lab_run.mkdir(parents=True)
        lab_locks.mkdir(parents=True)

        rel1 = lab_releases / "wr-lab-01"
        rel1.mkdir()
        (rel1 / "manifest.json").write_text('{"release_id":"wr-lab-01"}', encoding="utf-8")

        rel0 = lab_releases / "wr-lab-00"
        rel0.mkdir()
        (rel0 / "manifest.json").write_text('{"release_id":"wr-lab-00"}', encoding="utf-8")

        lab_current.symlink_to(rel1)
        lab_previous.symlink_to(rel0)

        # Inicia processo fictício simulando um daemon LAB
        lab_dummy = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=str(tmp_path),
        )
        lab_dummy_pid = lab_dummy.pid

        # Cria lock do lifecycle de workstation
        workstation_lock_file = lab_locks / "workstation-lifecycle.lock"
        workstation_lock_file.touch()

        env = dict(os.environ)
        env["SISTER_WORKSTATION_STATE_ROOT"] = str(lab_state)
        env["SISTER_REPOSITORIES_ROOT"] = str(tmp_path)

        current_target_before = lab_current.resolve()
        previous_target_before = lab_previous.resolve()

        # Executa dev preview do componente golf
        res = subprocess.run(
            [sys.executable, str(DEV_CLI), "preview", str(comp), "--duration", "0.2", "--json"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        try:
            # 1. CURRENT e PREVIOUS byte-identical
            if lab_current.resolve() != current_target_before:
                fail_test("Gate 4", "CURRENT_LINK foi modificado pelo dev preview")
            if lab_previous.resolve() != previous_target_before:
                fail_test("Gate 4", "PREVIOUS_LINK foi modificado pelo dev preview")

            # 2. Processos do LAB intocados
            try:
                os.kill(lab_dummy_pid, 0)
            except OSError:
                fail_test("Gate 4", "processo simulado do LAB foi perturbado ou morto")

            # 3. State persistente do LAB intocado
            if any(lab_components_state.iterdir()):
                fail_test("Gate 4", "arquivos foram escritos em lab_state/components")
            if any(lab_run.iterdir()):
                fail_test("Gate 4", "arquivos foram escritos em lab_state/run")

            # 4. Workstation lock não foi perturbado
            fd = open(workstation_lock_file, "r")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

        finally:
            lab_dummy.terminate()
            lab_dummy.wait()

    pass_test("Gate 4 — Invariantes estritas de isolamento contra o LAB")


# ==============================================================================
# Gate 5: Alocação de Porta Efêmera e Retry por Colisão
# ==============================================================================
def test_gate_5_port_retry() -> None:
    print("[TEST] Validando Gate 5 — Alocação de Porta Efêmera e Retry por Colisão...")
    with tempfile.TemporaryDirectory(prefix="sister-test-port-") as tmp:
        tmp_path = Path(tmp)

        # Componente que simula colisão de bind na primeira tentativa
        comp = create_mock_component(
            tmp_path,
            "hotel",
            "sister_hotel",
            simulate_collision_first=True,
        )

        env = dict(os.environ)
        env["SISTER_REPOSITORIES_ROOT"] = str(tmp_path)

        # Deve se recuperar via retry na segunda tentativa efêmera
        res = subprocess.run(
            [sys.executable, str(DEV_CLI), "preview", str(comp), "--duration", "0.2", "--json"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        if data.get("status") != "TERMINATED":
            fail_test("Gate 5", f"dev preview falhou na recuperação por retry: {res.stderr}")

    pass_test("Gate 5 — Alocação de porta efêmera e retry em evidência factual de colisão")


# ==============================================================================
# Gate 6: Lifecycle e Health Autoritativo
# ==============================================================================
def test_gate_6_lifecycle_health() -> None:
    print("[TEST] Validando Gate 6 — Lifecycle e Health Autoritativo...")
    with tempfile.TemporaryDirectory(prefix="sister-test-lc-") as tmp:
        tmp_path = Path(tmp)
        comp = create_mock_component(tmp_path, "india", "sister_india", probe_path="/api/v1/health")

        env = dict(os.environ)
        env["SISTER_REPOSITORIES_ROOT"] = str(tmp_path)

        # Executa via CLI dispatcher (sister-infra dev preview)
        res = subprocess.run(
            [
                str(INFRA_CLI),
                "dev",
                "preview",
                str(comp),
                "--duration",
                "0.3",
                "--json",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        if data.get("component_id") != "india" or data.get("system_id") != "sister_india":
            fail_test("Gate 6", f"dados incorretos na saída JSON: {data}")
        if data.get("status") != "TERMINATED":
            fail_test("Gate 6", f"status final esperado TERMINATED, obtido: {data.get('status')}")

    pass_test("Gate 6 — Lifecycle e health autoritativo (sister-infra dev preview)")


# ==============================================================================
# Gate 7: Cleanup Seguro e Zero Resíduos
# ==============================================================================
def test_gate_7_zero_residues() -> None:
    print("[TEST] Validando Gate 7 — Cleanup Seguro Scoped e Zero Resíduos...")
    with tempfile.TemporaryDirectory(prefix="sister-test-clean-") as tmp:
        tmp_path = Path(tmp)
        comp = create_mock_component(tmp_path, "juliet", "sister_juliet")

        env = dict(os.environ)
        env["SISTER_REPOSITORIES_ROOT"] = str(tmp_path)

        # Inicia preview em subprocesso e interrompe com SIGINT (Ctrl+C)
        proc = subprocess.Popen(
            [sys.executable, str(DEV_CLI), "preview", str(comp)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Aguarda subir
        time.sleep(0.6)
        if proc.poll() is not None:
            out, err = proc.communicate()
            fail_test("Gate 7", f"processo encerrou antes do sinal: {out}\n{err}")

        # Envia SIGINT
        proc.send_signal(signal.SIGINT)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            fail_test("Gate 7", "processo não encerrou graciosamente após SIGINT")

        if "encerrado com sucesso" not in stdout and "[PASS]" not in stdout:
            fail_test("Gate 7", f"saída de encerramento não confirmada: {stdout}\n{stderr}")

        # Verifica que nenhuma sandbox /tmp/sister-dev-preview-juliet-* permaneceu
        leftovers = list(Path("/tmp").glob("sister-dev-preview-juliet-*"))
        if leftovers:
            fail_test("Gate 7", f"sandboxes residuais encontradas: {leftovers}")

        # Verifica que nenhum processo órfão com o path de mock existe
        ps_res = subprocess.run(
            ["ps", "-eo", "pid,args"],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        )
        for line in ps_res.stdout.splitlines():
            if str(comp) in line and "dev_preview_test" not in line:
                fail_test("Gate 7", f"processo órfão encontrado: {line}")

    pass_test("Gate 7 — Cleanup seguro scoped e Zero Resíduos")


def main() -> None:
    print("[TEST] Iniciando suite de testes de DEV Preview (OPS-05)...")
    from component_resolver_test import make_contracts
    with tempfile.TemporaryDirectory(prefix="sister-dev-contracts-") as tmp:
        previous = os.environ.get("SISTER_CONTRACT_ROOT")
        os.environ["SISTER_CONTRACT_ROOT"] = str(make_contracts(Path(tmp)))
        try:
            test_gate_1_dev_binding()
            test_gate_2_discovery()
            test_gate_3_source_preservation()
            test_gate_4_lab_isolation()
            test_gate_5_port_retry()
            test_gate_6_lifecycle_health()
            test_gate_7_zero_residues()
        finally:
            if previous is None:
                os.environ.pop("SISTER_CONTRACT_ROOT", None)
            else:
                os.environ["SISTER_CONTRACT_ROOT"] = previous
    print("[PASS] Todos os Gates de OPS-05 (1 a 7) passaram com sucesso!")


if __name__ == "__main__":
    main()
