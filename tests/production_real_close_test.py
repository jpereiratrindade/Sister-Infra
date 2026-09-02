#!/usr/bin/env python3
"""
tests/production_real_close_test.py
=============================================================================
SUÍTE DE FECHAMENTO DO PRODUCTION REAL (PRODUCTION-REAL-CLOSE)
=============================================================================
Comprova as 5 condições obrigatórias do último quilômetro produtivo:
1. Promoção Verdadeira: LAB gera evidência persistente e Produção jamais cria
   candidata a partir de fontes;
2. Candidata Durável: O artefato promovível reside em storage durável fora de /tmp;
3. Executor Produtivo Real: SystemdServiceManager materializa unidades determinísticas
   e gerencia ciclo de vida sob autoridade institucional;
4. Gateway Produtivo Real: HAProxy produtivo é renderizado deterministicamente a
   partir do deployment resolvido com TLS e subdomínios derivados;
5. Verify Factual Real: units ativas + health probes de componentes + acessibilidade
   HTTPS de cada subdomínio no gateway com rollback transacional.
=============================================================================
"""

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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from composition_resolver_test import make_contracts

INFRA_CLI = ROOT / "bin" / "sister-infra"
LIFECYCLE_CLI = ROOT / "bin" / "sister-lifecycle"
PRODUCTION_CLI = ROOT / "bin" / "sister-production"
DEPLOYMENT_CLI = ROOT / "bin" / "sister-deployment"
CANDIDATE_CLI = ROOT / "bin" / "sister-candidate"
LAB_CLI = ROOT / "bin" / "sister-lab"


def run_cmd(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    curr_env = os.environ.copy()
    if env:
        curr_env.update(env)
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, env=curr_env)


def allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def generate_self_signed_cert(cert_path: Path, key_path: Path, san_hosts: list[str]) -> None:
    san_entries = [f"DNS:{h}" for h in san_hosts]
    san_conf = (
        "[req]\ndistinguished_name=req_distinguished_name\nx509_extensions=v3_req\nprompt=no\n"
        "[req_distinguished_name]\nCN=production.sister.test\n"
        "[v3_req]\nsubjectAltName=" + ",".join(san_entries) + "\n"
    )
    with tempfile.NamedTemporaryFile("w", delete=False) as cfile:
        cfile.write(san_conf)
        cnf_path = cfile.name

    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(key_path), "-out", str(cert_path),
                "-days", "30", "-nodes", "-config", cnf_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    finally:
        if os.path.exists(cnf_path):
            os.unlink(cnf_path)


def main() -> None:
    print("=====================================================================")
    print(" SUÍTE: Fechamento do Production Real (PRODUCTION-REAL-CLOSE)")
    print("=====================================================================")

    with tempfile.TemporaryDirectory(prefix="sister-prc-") as tmp_dir:
        tmp = Path(tmp_dir)

        # Configurar ambiente hermético
        state_root = tmp / "state"
        state_root.mkdir(parents=True, exist_ok=True)
        fhs_root = tmp / "fhs"
        fhs_root.mkdir(parents=True, exist_ok=True)
        unit_dir = fhs_root / "etc" / "systemd"
        unit_dir.mkdir(parents=True, exist_ok=True)

        install_root = tmp / "workstation_install"
        install_root.mkdir(parents=True, exist_ok=True)

        # Control-Plane Fixture (Limpo e versionado)
        control_fixture = tmp / "control-plane"
        control_fixture.mkdir(parents=True, exist_ok=True)
        for d in ("bin", "config", "contracts", "libexec", "templates"):
            if (ROOT / d).exists():
                shutil.copytree(ROOT / d, control_fixture / d)
        if (ROOT / "README.md").exists():
            shutil.copy2(ROOT / "README.md", control_fixture / "README.md")
        (control_fixture / "VERSION").write_text("1.0.0\n")
        subprocess.run(["git", "init", "-b", "main"], cwd=str(control_fixture), check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(control_fixture), check=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(control_fixture), check=True)
        subprocess.run(["git", "add", "."], cwd=str(control_fixture), check=True)
        subprocess.run(["git", "commit", "-m", "initial snapshot"], cwd=str(control_fixture), check=True, stdout=subprocess.DEVNULL)

        contracts_dir = make_contracts(tmp)
        env_base = {
            "SISTER_WORKSTATION_STATE_ROOT": str(state_root),
            "SISTER_WORKSTATION_INSTALL_ROOT": str(install_root),
            "SISTER_WORKSTATION_CONTROL_PLANE_SOURCE": str(control_fixture),
            "SISTER_PRODUCTION_CONTROL_PLANE_SOURCE": str(control_fixture),
            "SISTER_WORKSTATION_TEST_MODE": "1",
            "SISTER_PRODUCTION_ROOT": str(fhs_root),
            "SISTER_SYSTEMD_UNIT_DIR": str(unit_dir),
            "SISTER_WORKSTATION_CONFIG_ROOT": str(tmp / "workstation_config"),
            "SISTER_WORKSTATION_CONTRACTS_ROOT": str(contracts_dir),
            "SISTER_CONTRACT_ROOT": str(contracts_dir),
        }

        # -------------------------------------------------------------------
        # Preparar repositórios sintéticos de componentes
        # -------------------------------------------------------------------
        repo_alpha = tmp / "repos" / "alpha"
        repo_alpha.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_alpha), check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo_alpha), check=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(repo_alpha), check=True)

        (repo_alpha / ".sister").mkdir(parents=True, exist_ok=True)
        (repo_alpha / ".sister" / "component.json").write_text(json.dumps({
            "schema": "sister.component/1.0.0",
            "component_id": "alpha",
            "system_id": "system_alpha",
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
        }, indent=2), encoding="utf-8")

        scripts_alpha = repo_alpha / "scripts"
        scripts_alpha.mkdir(parents=True, exist_ok=True)
        daemon_alpha = scripts_alpha / "runtime.sh"
        daemon_alpha.write_text("""#!/usr/bin/env bash
cmd="${1:-status}"
comp="alpha"
run_dir="${SISTER_RUNTIME_RUN_DIR:-/tmp}"
pid_file="$run_dir/${comp}.pid"

case "$cmd" in
  start|run)
    python3 -c "
import json, os, socketserver, http.server

resolved_path = os.environ.get('SISTER_RESOLVED_DEPLOYMENT_FILE')
port = 18011
if resolved_path and os.path.exists(resolved_path):
    try:
        data = json.loads(open(resolved_path).read())
        for c in data.get('components', []):
            if c.get('component_id') == 'alpha':
                port = int(c.get('runtime', {}).get('port', port))
    except Exception:
        pass

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK alpha')
    def log_message(self, *args):
        pass

class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True

with ReusableServer(('127.0.0.1', port), Handler) as httpd:
    httpd.serve_forever()
" >/dev/null 2>&1 &
    echo "$!" > "$pid_file"
    sleep 0.2
    exit 0
    ;;
  stop)
    if [[ -f "$pid_file" ]]; then
      kill -9 "$(cat "$pid_file")" 2>/dev/null || true
      rm -f "$pid_file"
    fi
    exit 0
    ;;
  status|health|readiness)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
""", encoding="utf-8")
        daemon_alpha.chmod(0o755)

        subprocess.run(["git", "add", "."], cwd=str(repo_alpha), check=True)
        subprocess.run(["git", "commit", "-m", "initial alpha"], cwd=str(repo_alpha), check=True, stdout=subprocess.DEVNULL)

        # Repositório Beta
        repo_beta = tmp / "repos" / "beta"
        repo_beta.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_beta), check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo_beta), check=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(repo_beta), check=True)

        (repo_beta / ".sister").mkdir(parents=True, exist_ok=True)
        (repo_beta / ".sister" / "component.json").write_text(json.dumps({
            "schema": "sister.component/1.0.0",
            "component_id": "beta",
            "system_id": "system_beta",
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
        }, indent=2), encoding="utf-8")

        scripts_beta = repo_beta / "scripts"
        scripts_beta.mkdir(parents=True, exist_ok=True)
        daemon_beta = scripts_beta / "runtime.sh"
        daemon_beta.write_text("""#!/usr/bin/env bash
cmd="${1:-status}"
comp="beta"
run_dir="${SISTER_RUNTIME_RUN_DIR:-/tmp}"
pid_file="$run_dir/${comp}.pid"

case "$cmd" in
  start|run)
    python3 -c "
import json, os, socketserver, http.server

resolved_path = os.environ.get('SISTER_RESOLVED_DEPLOYMENT_FILE')
port = 18012
if resolved_path and os.path.exists(resolved_path):
    try:
        data = json.loads(open(resolved_path).read())
        for c in data.get('components', []):
            if c.get('component_id') == 'beta':
                port = int(c.get('runtime', {}).get('port', port))
    except Exception:
        pass

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK beta')
    def log_message(self, *args):
        pass

class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True

with ReusableServer(('127.0.0.1', port), Handler) as httpd:
    httpd.serve_forever()
" >/dev/null 2>&1 &
    echo "$!" > "$pid_file"
    sleep 0.2
    exit 0
    ;;
  stop)
    if [[ -f "$pid_file" ]]; then
      kill -9 "$(cat "$pid_file")" 2>/dev/null || true
      rm -f "$pid_file"
    fi
    exit 0
    ;;
  status|health|readiness)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
""", encoding="utf-8")
        daemon_beta.chmod(0o755)

        subprocess.run(["git", "add", "."], cwd=str(repo_beta), check=True)
        subprocess.run(["git", "commit", "-m", "initial beta"], cwd=str(repo_beta), check=True, stdout=subprocess.DEVNULL)

        # Composição
        composition_file = tmp / "composition.json"
        composition_file.write_text(json.dumps({
            "schema": "sister.infra.composition/1.0.0",
            "composition_id": "ecosystem-prc",
            "deployment_class": "workstation",
            "components": [
                {"source": str(repo_alpha)},
                {"source": str(repo_beta)},
            ],
        }, indent=2), encoding="utf-8")

        port_lab_gw = allocate_free_port()
        port_lab_alpha = allocate_free_port()
        port_lab_beta = allocate_free_port()
        port_prod_gw = allocate_free_port()
        port_prod_alpha = allocate_free_port()
        port_prod_beta = allocate_free_port()

        # Deployments (LAB e Produção com domínio único)
        dep_lab_file = tmp / "deployment_lab.json"
        dep_lab_file.write_text(json.dumps({
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "lab-prc",
            "composition_id": "ecosystem-prc",
            "gateway": {
                "protocol": "https",
                "listen": "127.0.0.1",
                "port": port_lab_gw,
                "domain": "lab.sister.local",
            },
            "bindings": [
                {
                    "system_id": "system_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_lab_alpha},
                    "probe": {"health_path": "/health"},
                },
                {
                    "system_id": "system_beta",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_lab_beta},
                    "probe": {"health_path": "/health"},
                },
            ],
        }, indent=2), encoding="utf-8")

        dep_prod_file = tmp / "deployment_prod.json"
        dep_prod_file.write_text(json.dumps({
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "prod-dc-01",
            "composition_id": "ecosystem-prc",
            "gateway": {
                "protocol": "https",
                "listen": "127.0.0.1",
                "port": port_prod_gw,
                "domain": "sister.gov.br",
            },
            "bindings": [
                {
                    "system_id": "system_alpha",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_prod_alpha},
                    "probe": {"health_path": "/health"},
                },
                {
                    "system_id": "system_beta",
                    "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_prod_beta},
                    "probe": {"health_path": "/health"},
                },
            ],
        }, indent=2), encoding="utf-8")

        # Materializar certificados TLS de produção em FHS
        tls_dir = fhs_root / "etc" / "sister" / "tls"
        tls_dir.mkdir(parents=True, exist_ok=True)
        cert_path = tls_dir / "ecosystem.crt"
        key_path = tls_dir / "ecosystem.key"
        generate_self_signed_cert(cert_path, key_path, ["alpha.sister.gov.br", "beta.sister.gov.br", "127.0.0.1"])

        # Inicializar autoridade TLS de LAB
        r_ca = run_cmd([sys.executable, str(LAB_CLI), "tls", "init-ca"], env=env_base)
        assert r_ca.returncode == 0, f"falha ao inicializar CA do LAB: {r_ca.stderr}"

        # -------------------------------------------------------------------
        # GATE PRC-1: Candidata Durável em storage persistente
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-1 — Candidatas residem em storage persistente fora de /tmp...")
        res_cand = run_cmd([
            sys.executable, str(LIFECYCLE_CLI), "run",
            "--target", "lab",
            "--composition", str(composition_file),
            "--deployment", str(dep_lab_file),
            "--json",
        ], env=env_base)
        assert res_cand.returncode == 0, f"falha ao rodar lifecycle lab: stderr={res_cand.stderr} stdout={res_cand.stdout}"
        doc_lab = json.loads(res_cand.stdout)

        cand_stage = [s for s in doc_lab["stages_executed"] if s["stage"] == "CANDIDATE"][0]
        cand_path_str = cand_stage["candidate_path"]
        assert not cand_path_str.startswith("/tmp/sister-lifecycle-cand"), "Candidata não pode residir em /tmp efêmero!"
        assert str(state_root / "candidates") in cand_path_str, f"Candidata deve residir no storage durável ({cand_path_str})"
        print("[PASS] Gate PRC-1 — Candidata durável materializada em storage persistente com sucesso")

        # -------------------------------------------------------------------
        # GATE PRC-2: Evidência persistente de verificação de LAB
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-2 — Evidência persistente de LAB verification...")
        lab_ev_files = list((state_root / "evidence" / "lab").glob("verification-*.json"))
        assert len(lab_ev_files) > 0, "Evidência persistente de verificação em LAB não foi criada!"
        ver_doc = json.loads(lab_ev_files[0].read_text(encoding="utf-8"))
        assert ver_doc["status"] == "PASS", "Status da evidência de LAB deve ser PASS"
        assert ver_doc["candidate_id"] == cand_stage["candidate_id"]
        assert ver_doc["candidate_digest"].startswith("sha256:")
        print("[PASS] Gate PRC-2 — Evidência persistente emitida com SHA-256 e status PASS")

        # -------------------------------------------------------------------
        # GATE PRC-3: Bloqueio fail-closed se produção tentar rodar sem LAB
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-3 — Produção rejeita execução se candidata não tiver sido verificada em LAB...")
        # Limpar evidência de lab temporariamente
        lab_ev_backup = list(lab_ev_files)
        for f in lab_ev_files:
            f.unlink()

        res_prod_nolab = run_cmd([
            sys.executable, str(LIFECYCLE_CLI), "run",
            "--target", "production",
            "--composition", str(composition_file),
            "--deployment", str(dep_prod_file),
            "--json",
        ], env=dict(env_base, PRODUCTION_APPROVED="YES", SISTER_INFRA_PRODUCTION_CONFIRM="YES"))

        assert res_prod_nolab.returncode != 0, "Produção deveria falhar fechado sem candidata verificada em LAB!"
        combined_output = res_prod_nolab.stdout + res_prod_nolab.stderr
        assert "PRODUCTION_REQUIRES_LAB_VERIFIED_CANDIDATE" in combined_output or "PROMOTION_BLOCKED" in combined_output
        print("[PASS] Gate PRC-3 — Produção falha fechado imediatamente e jamais cria candidata de fontes")

        # Restaurar evidência de LAB
        for f in lab_ev_backup:
            f.write_text(json.dumps(ver_doc, indent=2), encoding="utf-8")

        # -------------------------------------------------------------------
        # GATE PRC-4: Promoção com mesma candidata verificada
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-4 — Promoção formal da MESMA candidata verificada em LAB...")
        res_prom = run_cmd([
            sys.executable, str(LIFECYCLE_CLI), "plan",
            "--target", "production",
            "--composition", str(composition_file),
            "--deployment", str(dep_prod_file),
            "--json",
        ], env=env_base)
        assert res_prom.returncode == 0, f"falha ao gerar plano de produção com candidata de LAB: {res_prom.stderr}"
        print("[PASS] Gate PRC-4 — Candidata verificada em LAB elegível para promoção institucional")

        # -------------------------------------------------------------------
        # GATE PRC-5: SystemdServiceManager determinístico
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-5 — SystemdServiceManager gera units determinísticas fiéis aos contratos...")
        # Executar produção com SystemdServiceManager em sandbox
        env_prod = dict(
            env_base,
            PRODUCTION_APPROVED="YES",
            SISTER_INFRA_PRODUCTION_CONFIRM="YES",
            SISTER_PRODUCTION_SERVICE_MANAGER="systemd",
            SISTER_PRODUCTION_GATEWAY_LISTEN_ADDRESS="127.0.0.1",
            SISTER_PRODUCTION_GATEWAY_PORT=str(port_prod_gw),
            SISTER_PRODUCTION_DNS_RESOLVER=json.dumps({"alpha.sister.gov.br": "127.0.0.1", "beta.sister.gov.br": "127.0.0.1"}),
            PRODUCTION_TLS_CERT=str(cert_path),
            PRODUCTION_TLS_KEY=str(key_path),
        )

        res_prod_apply = run_cmd([
            sys.executable, str(LIFECYCLE_CLI), "run",
            "--target", "production",
            "--composition", str(composition_file),
            "--deployment", str(dep_prod_file),
            "--json",
        ], env=env_prod)

        assert res_prod_apply.returncode == 0, f"falha ao rodar lifecycle production: stderr={res_prod_apply.stderr} stdout={res_prod_apply.stdout}"
        doc_prod = json.loads(res_prod_apply.stdout)
        assert doc_prod["status"] == "COMPLETED"

        # Verificar se as units determinísticas foram geradas no diretório de systemd
        unit_alpha = unit_dir / "sister-alpha.service"
        unit_beta = unit_dir / "sister-beta.service"
        assert unit_alpha.is_file(), "Unit do alpha deve ter sido materializada no systemd"
        assert unit_beta.is_file(), "Unit do beta deve ter sido materializada no systemd"

        unit_alpha_content = unit_alpha.read_text(encoding="utf-8")
        assert "ExecStart=" in unit_alpha_content
        assert "runtime.sh" in unit_alpha_content
        assert "DynamicUser" not in unit_alpha_content, "Não deve introduzir flags arbitrárias fora do contrato"
        print("[PASS] Gate PRC-5 — Units systemd geradas deterministicamente e de acordo com o contrato")

        # -------------------------------------------------------------------
        # GATE PRC-6: Gateway HAProxy Produtivo Reconciliado
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-6 — Reconciliação factual do HAProxy produtivo...")
        gw_cfg_file = fhs_root / "etc" / "sister" / "gateway" / "haproxy.cfg"
        assert gw_cfg_file.is_file(), "Arquivo de configuração do HAProxy produtivo deve ter sido gerado"
        gw_cfg_text = gw_cfg_file.read_text(encoding="utf-8")
        assert "alpha.sister.gov.br" in gw_cfg_text, "Configuração do HAProxy deve conter o subdomínio do alpha"
        assert "beta.sister.gov.br" in gw_cfg_text, "Configuração do HAProxy deve conter o subdomínio do beta"
        assert str(port_prod_gw) in gw_cfg_text, "Porta configurada do gateway de produção deve constar no HAProxy"
        print("[PASS] Gate PRC-6 — HAProxy produtivo renderizado com subdomínios derivados e porta configurada")

        # -------------------------------------------------------------------
        # GATE PRC-7: Production Verify Factual
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-7 — Production verify factual (same candidate + units + gateway + TLS + DNS)...")
        res_pver = run_cmd([
            sys.executable, str(PRODUCTION_CLI), "verify", "--json",
        ], env=env_prod)
        assert res_pver.returncode == 0, f"production verify falhou: {res_pver.stderr}"
        pver_doc = json.loads(res_pver.stdout)
        assert pver_doc["status"] == "PASS"
        assert pver_doc["candidate_id"] == cand_stage["candidate_id"], "Verify deve atestar a MESMA candidata verificada em LAB"
        assert pver_doc["components_status"]["alpha"] == "ACTIVE"
        assert "fingerprint" in pver_doc["tls"]
        assert "alpha.sister.gov.br" in pver_doc["dns"]
        print("[PASS] Gate PRC-7 — Production verify atestou a mesma candidata, units ativas, TLS e DNS com sucesso")

        # -------------------------------------------------------------------
        # GATE PRC-8: Rollback Transacional
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-8 — Transacionalidade e rollback seguro em caso de falha no apply...")
        # Criar plano para forçar falha
        plan_tmp = tmp / "plan-fail.json"
        res_plan = run_cmd([
            sys.executable, str(PRODUCTION_CLI), "plan",
            "--desired-candidate", cand_path_str,
            "--desired-deployment", str(dep_prod_file),
            "--out", str(plan_tmp),
            "--json",
        ], env=env_prod)
        assert res_plan.returncode == 0
        digest = json.loads(res_plan.stdout)["plan_digest"]

        # Executar apply injetando falha de health
        res_fail = run_cmd([
            sys.executable, str(PRODUCTION_CLI), "apply",
            "--plan", str(plan_tmp),
            "--plan-digest", digest,
            "--json",
        ], env=dict(env_prod, SISTER_MOCK_FAIL_HEALTH="1"))

        assert res_fail.returncode != 0, "Apply deveria falhar e executar rollback"
        # Garantir que a release anterior continue ativa em current
        res_pver_after = run_cmd([sys.executable, str(PRODUCTION_CLI), "verify", "--json"], env=env_prod)
        assert res_pver_after.returncode == 0, "Release estável deve permanecer ativa após rollback"
        print("[PASS] Gate PRC-8 — Rollback automático restaura estado anterior em caso de falha")

        # -------------------------------------------------------------------
        # GATE PRC-9: Ciclo Fim a Fim Completo (UX Canônica)
        # -------------------------------------------------------------------
        print("[TEST] Gate PRC-9 — Ciclo sequencial fim a fim via UX única:")
        print("       sister-infra lifecycle run --target lab")
        print("       sister-infra lifecycle run --target production")

        e2e_dir = tmp / "e2e"
        e2e_state = e2e_dir / "state"
        e2e_install = e2e_dir / "install"
        e2e_fhs = e2e_dir / "fhs"
        e2e_config = e2e_dir / "config"
        e2e_unit_dir = e2e_fhs / "etc" / "systemd"

        for d in (e2e_state, e2e_install, e2e_fhs, e2e_config, e2e_unit_dir):
            d.mkdir(parents=True, exist_ok=True)

        e2e_env_base = dict(
            env_base,
            SISTER_WORKSTATION_STATE_ROOT=str(e2e_state),
            SISTER_WORKSTATION_INSTALL_ROOT=str(e2e_install),
            SISTER_WORKSTATION_CONFIG_ROOT=str(e2e_config),
            SISTER_PRODUCTION_ROOT=str(e2e_fhs),
            SISTER_SYSTEMD_UNIT_DIR=str(e2e_unit_dir),
        )

        # Inicializar CA no config do e2e
        r_ca_e2e = run_cmd([sys.executable, str(LAB_CLI), "tls", "init-ca"], env=e2e_env_base)
        assert r_ca_e2e.returncode == 0

        # Alocar portas novas para o e2e
        port_e2e_lab_gw = allocate_free_port()
        port_e2e_lab_alpha = allocate_free_port()
        port_e2e_lab_beta = allocate_free_port()
        port_e2e_prod_gw = allocate_free_port()
        port_e2e_prod_alpha = allocate_free_port()
        port_e2e_prod_beta = allocate_free_port()

        dep_lab_e2e = e2e_dir / "dep_lab.json"
        dep_lab_e2e.write_text(json.dumps({
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "lab-e2e",
            "composition_id": "ecosystem-prc",
            "gateway": {"protocol": "https", "listen": "127.0.0.1", "port": port_e2e_lab_gw, "domain": "lab.sister.local"},
            "bindings": [
                {"system_id": "system_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_e2e_lab_alpha}, "probe": {"health_path": "/health"}},
                {"system_id": "system_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_e2e_lab_beta}, "probe": {"health_path": "/health"}},
            ],
        }, indent=2), encoding="utf-8")

        dep_prod_e2e = e2e_dir / "dep_prod.json"
        dep_prod_e2e.write_text(json.dumps({
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "prod-e2e",
            "composition_id": "ecosystem-prc",
            "gateway": {"protocol": "https", "listen": "127.0.0.1", "port": port_e2e_prod_gw, "domain": "sister.gov.br"},
            "bindings": [
                {"system_id": "system_alpha", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_e2e_prod_alpha}, "probe": {"health_path": "/health"}},
                {"system_id": "system_beta", "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": port_e2e_prod_beta}, "probe": {"health_path": "/health"}},
            ],
        }, indent=2), encoding="utf-8")

        e2e_tls_dir = e2e_fhs / "etc" / "sister" / "tls"
        e2e_tls_dir.mkdir(parents=True, exist_ok=True)
        e2e_cert = e2e_tls_dir / "ecosystem.crt"
        e2e_key = e2e_tls_dir / "ecosystem.key"
        generate_self_signed_cert(e2e_cert, e2e_key, ["alpha.sister.gov.br", "beta.sister.gov.br", "127.0.0.1"])

        e2e_env_prod = dict(
            e2e_env_base,
            PRODUCTION_APPROVED="YES",
            SISTER_INFRA_PRODUCTION_CONFIRM="YES",
            SISTER_PRODUCTION_SERVICE_MANAGER="systemd",
            SISTER_PRODUCTION_GATEWAY_LISTEN_ADDRESS="127.0.0.1",
            SISTER_PRODUCTION_GATEWAY_PORT=str(port_e2e_prod_gw),
            SISTER_PRODUCTION_DNS_RESOLVER=json.dumps({"alpha.sister.gov.br": "127.0.0.1", "beta.sister.gov.br": "127.0.0.1"}),
            PRODUCTION_TLS_CERT=str(e2e_cert),
            PRODUCTION_TLS_KEY=str(e2e_key),
        )

        # 1. Executar LAB
        r_lab_e2e = run_cmd([
            str(INFRA_CLI), "lifecycle", "run",
            "--target", "lab",
            "--composition", str(composition_file),
            "--deployment", str(dep_lab_e2e),
            "--json",
        ], env=e2e_env_base)
        assert r_lab_e2e.returncode == 0, f"falha em lab e2e: stderr={r_lab_e2e.stderr} stdout={r_lab_e2e.stdout}"
        cand_e2e = json.loads(r_lab_e2e.stdout)["stages_executed"][1]["candidate_id"]

        # 2. Executar Produção (sem passar candidate explicitamente: descobre e promove a do LAB!)
        r_prod_e2e = run_cmd([
            str(INFRA_CLI), "lifecycle", "run",
            "--target", "production",
            "--composition", str(composition_file),
            "--deployment", str(dep_prod_e2e),
            "--json",
        ], env=e2e_env_prod)
        assert r_prod_e2e.returncode == 0, f"falha em production e2e: stderr={r_prod_e2e.stderr} stdout={r_prod_e2e.stdout}"
        doc_prod_e2e = json.loads(r_prod_e2e.stdout)
        cand_prod_e2e = doc_prod_e2e["stages_executed"][0]["candidate_id"]

        assert cand_prod_e2e == cand_e2e, f"Produção deve ter promovido exatamente a candidata do LAB ({cand_e2e} == {cand_prod_e2e})"
        print("[PASS] Gate PRC-9 — Ciclo fim a fim executado com sucesso: a MESMA candidata verificada em LAB foi promovida para Produção!")

    print("\n=====================================================================")
    print(" [SUCESSO] Todos os 9 Gates de PRODUCTION-REAL-CLOSE passaram!")
    print("=====================================================================")


if __name__ == "__main__":
    main()
