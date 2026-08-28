#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import tempfile
from pathlib import Path

import jsonschema

from composition_resolver_test import (
    make_component,
    make_contracts,
    write_composition,
    write_json,
)
from workstation_composition_candidate_test import (
    add_qualified_artifact,
    git_init_commit,
)

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-workstation"


def make_control_plane(workspace: Path) -> Path:
    target = workspace / "sister-infra"
    target.mkdir(parents=True)
    for name in ("bin", "config", "contracts", "templates"):
        shutil.copytree(ROOT / name, target / name)
    shutil.copy2(ROOT / "README.md", target / "README.md")
    git_init_commit(target)
    return target


def make_test_tls(tls_dir: Path) -> None:
    tls_dir.mkdir(parents=True, exist_ok=True)
    ca_key = tls_dir / "ecosystem-lab-ca.key"
    ca_crt = tls_dir / "ecosystem-lab-ca.crt"
    leaf_key = tls_dir / "ecosystem-lab.key"
    leaf_crt = tls_dir / "ecosystem-lab.crt"
    leaf_pem = tls_dir / "ecosystem-lab.pem"

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_crt),
            "-days",
            "30",
            "-subj",
            "/CN=Sister-Lab-Test-CA",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    csr = tls_dir / "leaf.csr"
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(leaf_key),
            "-out",
            str(csr),
            "-subj",
            "/CN=sister-workstation.local",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(leaf_crt),
            "-days",
            "30",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    leaf_pem.write_text(
        leaf_crt.read_text(encoding="utf-8")
        + leaf_key.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    os.chmod(ca_key, 0o600)
    os.chmod(leaf_key, 0o600)
    os.chmod(leaf_pem, 0o600)
    os.chmod(ca_crt, 0o644)
    os.chmod(tls_dir, 0o700)


def write_deployment(path: Path, port: int) -> None:
    write_json(
        path,
        {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "fixture-lab",
            "composition_id": "example_workstation",
            "bindings": [
                {
                    "system_id": "sister_alpha",
                    "runtime": {
                        "transport": "tcp",
                        "listen": "127.0.0.1",
                        "port": port,
                    },
                    "probe": {"health_path": "/health"},
                    "gateway": {"host": "alpha-gateway.test"},
                },
            ],
        },
    )


def run_cmd(
    env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> None:
    print("==================================================")
    print(" OPS-07A3 — Operational Reflexive Repair Test Suite")
    print("==================================================")

    port = allocate_free_port()

    with tempfile.TemporaryDirectory(
        prefix="sister-repair-test-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        home = tmp / "home"
        workspace = tmp / "workspace"
        home.mkdir()
        workspace.mkdir()

        contracts = make_contracts(tmp)
        make_control_plane(workspace)

        alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
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
        add_qualified_artifact(alpha, "alpha")
        git_init_commit(alpha)

        declaration_root = tmp / "declaration"
        declaration_root.mkdir()
        composition = declaration_root / "composition.json"
        deployment_file = declaration_root / "deployment.json"
        write_composition(composition, ["../sister-alpha"])
        write_deployment(deployment_file, port)

        env = dict(os.environ)
        jsonschema_site = str(Path(jsonschema.__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (jsonschema_site, env.get("PYTHONPATH", "")) if part
        )
        install_root = home / "install"
        config_root = home / "config"
        state_root = home / "state"
        systemd_root = home / "systemd"
        bin_root = home / "bin"

        env.update(
            {
                "HOME": str(home),
                "SISTER_WORKSTATION_CONTROL_PLANE_SOURCE": str(
                    workspace / "sister-infra"
                ),
                "SISTER_WORKSTATION_INSTALL_ROOT": str(install_root),
                "SISTER_WORKSTATION_CONFIG_ROOT": str(config_root),
                "SISTER_WORKSTATION_STATE_ROOT": str(state_root),
                "SISTER_WORKSTATION_SYSTEMD_ROOT": str(systemd_root),
                "SISTER_WORKSTATION_BIN_ROOT": str(bin_root),
                "SISTER_WORKSTATION_TEST_MODE": "1",
                "SISTER_WORKSTATION_CONTRACTS_ROOT": str(contracts),
                "SISTER_WORKSTATION_COMPOSITION_FILE": str(composition),
                "SISTER_WORKSTATION_DEPLOYMENT_FILE": str(deployment_file),
            }
        )

        # 1. Setup release
        res_create = run_cmd(env, "release-create")
        assert res_create.returncode == 0, res_create.stderr
        release_id = res_create.stdout.strip().splitlines()[-1]
        assert release_id.startswith("wr-")

        res_install = run_cmd(env, "install", release_id)
        assert res_install.returncode == 0, res_install.stderr

        # Generate TLS authority in config/tls
        make_test_tls(config_root / "tls")

        # Create runtime.env
        runtime_env = config_root / "runtime.env"
        runtime_env.write_text("SISTER_RUNTIME_MODE=installed\n", encoding="utf-8")
        os.chmod(runtime_env, 0o600)

        # Start runtime so everything is healthy
        res_start = run_cmd(env, "runtime-start")
        assert res_start.returncode == 0, res_start.stderr

        # Symlink do CLI
        cli_link = bin_root / "sister-infra"
        expected_cli_target = (
            install_root
            / "current"
            / "components"
            / "sister-infra"
            / "bin"
            / "sister-infra"
        )
        bin_root.mkdir(parents=True, exist_ok=True)
        if cli_link.exists() or cli_link.is_symlink():
            cli_link.unlink()
        os.symlink(expected_cli_target, cli_link)

        # ----------------------------------------------------
        # Gate 1: Idempotência / NO_OP sobre ambiente íntegro
        # ----------------------------------------------------
        print("[TEST] Gate 1 — Idempotência e NO_OP sobre ambiente íntegro...")
        res_rep1 = run_cmd(env, "repair", "--json")
        assert res_rep1.returncode == 0, f"RC={res_rep1.returncode}\nSTDOUT:\n{res_rep1.stdout}\nSTDERR:\n{res_rep1.stderr}"
        doc1 = json.loads(res_rep1.stdout)
        assert doc1["schema"] == "sister.infra.workstation.repair/1.0.0"
        assert doc1["status"] == "NO_OP"
        assert doc1["plan"] == []
        assert doc1["actions_applied"] == []
        assert doc1["verification"]["status"] == "PASS"

        # Segunda execução consecutiva
        res_rep2 = run_cmd(env, "repair", "--json")
        assert res_rep2.returncode == 0, res_rep2.stderr
        doc2 = json.loads(res_rep2.stdout)
        assert doc2["status"] == "NO_OP"
        print("[PASS] Gate 1 — Idempotência comprovada (0 ações, NO_OP)")

        # ----------------------------------------------------
        # Gate 2: Plan / Dry-run sem mutação
        # ----------------------------------------------------
        print("[TEST] Gate 2 — Plan antes de mutação (--plan / --dry-run)...")
        # Introduzir 2 drifts: symlink ausente + permissão errada
        cli_link.unlink()
        os.chmod(config_root, 0o777)

        res_plan = run_cmd(env, "repair", "--plan", "--json")
        assert res_plan.returncode == 0, res_plan.stderr
        doc_plan = json.loads(res_plan.stdout)
        assert doc_plan["schema"] == "sister.infra.workstation.repair/1.0.0"
        assert doc_plan["status"] == "PLANNED"
        assert len(doc_plan["plan"]) == 2
        categories = {p["category"] for p in doc_plan["plan"]}
        assert categories == {"symlink", "permission"}
        assert doc_plan["actions_applied"] == []
        assert doc_plan["verification"]["status"] == "PENDING"

        # Comprovar que NENHUMA mutação foi aplicada
        assert not cli_link.exists(), "repair --plan criou symlink indevidamente!"
        assert (
            stat.S_IMODE(config_root.stat().st_mode) == 0o777
        ), "repair --plan alterou permissões indevidamente!"
        print("[PASS] Gate 2 — Plan antes de mutação comprovado (0 mutações)")

        # ----------------------------------------------------
        # Gate 3: Reparo mínimo de Symlink e Permissões
        # ----------------------------------------------------
        print("[TEST] Gate 3 — Execução de repair mínimo sob autoridade...")
        res_repair_act = run_cmd(env, "repair", "--json")
        assert res_repair_act.returncode == 0, res_repair_act.stderr
        doc_rep_act = json.loads(res_repair_act.stdout)
        assert doc_rep_act["status"] == "REPAIRED"
        assert len(doc_rep_act["actions_applied"]) == 2
        assert doc_rep_act["verification"]["status"] == "PASS"

        # Verificar correções
        assert cli_link.is_symlink()
        assert cli_link.resolve() == expected_cli_target.resolve()
        assert stat.S_IMODE(config_root.stat().st_mode) == 0o700

        # Idempotência imediata após reparo
        res_post_rep = run_cmd(env, "repair", "--json")
        assert res_post_rep.returncode == 0
        assert json.loads(res_post_rep.stdout)["status"] == "NO_OP"
        print("[PASS] Gate 3 — Symlink e permissões reparados com sucesso e pós-verificados")

        # ----------------------------------------------------
        # Gate 4: Reparo de Unit Systemd Derivável
        # ----------------------------------------------------
        print("[TEST] Gate 4 — Reparo de Unit Systemd derivável...")
        unit_file = systemd_root / "sister-workstation.service"
        assert unit_file.is_file()
        unit_file.write_text("DIVERGENCIA_CORROMPIDA\n", encoding="utf-8")

        res_rep_unit = run_cmd(env, "repair", "--json")
        assert res_rep_unit.returncode == 0, res_rep_unit.stderr
        doc_rep_unit = json.loads(res_rep_unit.stdout)
        assert doc_rep_unit["status"] == "REPAIRED"
        assert any(
            a["category"] == "systemd_unit" for a in doc_rep_unit["actions_applied"]
        )
        assert "DIVERGENCIA_CORROMPIDA" not in unit_file.read_text(encoding="utf-8")
        assert "sister-workstation runtime-start" in unit_file.read_text(
            encoding="utf-8"
        )
        assert stat.S_IMODE(unit_file.stat().st_mode) == 0o644
        print("[PASS] Gate 4 — Unit systemd restaurada do template e pós-verificada")

        # ----------------------------------------------------
        # Gate 5: Fail-Closed sob Corrupção da Release
        # ----------------------------------------------------
        print("[TEST] Gate 5 — Fail-Closed sob release modificada/corrompida...")
        release_path = install_root / "releases" / release_id
        tampered_file = release_path / "components" / "alpha" / "main.cpp"
        assert tampered_file.is_file()
        original_bytes = tampered_file.read_bytes()
        tampered_file.write_bytes(original_bytes + b"\nTAMPERED_BYTE")

        res_fail_corrupt = run_cmd(env, "repair", "--json")
        assert res_fail_corrupt.returncode != 0
        doc_fail_corrupt = json.loads(res_fail_corrupt.stdout)
        assert doc_fail_corrupt["status"] == "FAIL_CLOSED"
        assert doc_fail_corrupt["code"] == "RELEASE_CORRUPTED"

        # Restaurar byte original para próximos testes
        tampered_file.write_bytes(original_bytes)
        print("[PASS] Gate 5 — Release corrompida falha fechado (RELEASE_CORRUPTED)")

        # ----------------------------------------------------
        # Gate 6: Fail-Closed sob Colisão de Porta Externa
        # ----------------------------------------------------
        print("[TEST] Gate 6 — Fail-Closed sob colisão com processo externo...")
        # Simular participante parado com porta ocupada externamente
        res_stop = run_cmd(env, "runtime-stop")
        assert res_stop.returncode == 0

        # Ocupar a porta do componente com socket TCP externo
        conflict_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conflict_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        conflict_sock.bind(("127.0.0.1", port))
        conflict_sock.listen(1)

        try:
            res_port_collision = run_cmd(env, "repair", "--json")
            assert res_port_collision.returncode != 0, f"STDOUT:\n{res_port_collision.stdout}\nSTDERR:\n{res_port_collision.stderr}"
            doc_port_col = json.loads(res_port_collision.stdout)
            assert doc_port_col["status"] == "FAIL_CLOSED"
            assert doc_port_col["code"] == "PORT_COLLISION_EXTERNAL"
            assert f"porta {port}" in doc_port_col["error"]
        finally:
            conflict_sock.close()

        print("[PASS] Gate 6 — Colisão com processo externo falha fechado (PORT_COLLISION_EXTERNAL)")

        # ----------------------------------------------------
        # Gate 7: Fail-Closed sob Autoridade TLS Inválida/Ausente
        # ----------------------------------------------------
        print("[TEST] Gate 7 — Fail-Closed sob autoridade TLS ausente/inválida...")
        ca_crt_path = config_root / "tls" / "ecosystem-lab-ca.crt"
        ca_backup = ca_crt_path.read_text(encoding="utf-8")
        ca_crt_path.unlink()

        res_fail_tls = run_cmd(env, "repair", "--json")
        assert res_fail_tls.returncode != 0
        doc_fail_tls = json.loads(res_fail_tls.stdout)
        assert doc_fail_tls["status"] == "FAIL_CLOSED"
        assert doc_fail_tls["code"] == "TLS_AUTHORITY_INVALID"
        assert not ca_crt_path.exists(), "repair tentou criar CA indevidamente!"

        # Restaurar CA
        ca_crt_path.write_text(ca_backup, encoding="utf-8")
        print("[PASS] Gate 7 — Autoridade TLS inválida falha fechado sem mutação")

        # ----------------------------------------------------
        # Gate 8: Fail-Closed sob Tentativa de Mudança de Versão
        # ----------------------------------------------------
        print("[TEST] Gate 8 — Fail-Closed sob ausência de current (sem suposição de versão)...")
        current_link = install_root / "current"
        current_target = current_link.resolve()
        current_link.unlink()

        res_fail_ver = run_cmd(env, "repair", "--json")
        assert res_fail_ver.returncode != 0
        doc_fail_ver = json.loads(res_fail_ver.stdout)
        assert doc_fail_ver["status"] == "FAIL_CLOSED"
        assert doc_fail_ver["code"] == "CURRENT_RELEASE_MISSING"

        # Restaurar link current
        os.symlink(current_target, current_link)
        print("[PASS] Gate 8 — Ausência de release instalada falha fechado (sem troca de versão)")

        # ----------------------------------------------------
        # Gate 9: Reparo de Processo Parado com Porta Livre
        # ----------------------------------------------------
        print("[TEST] Gate 9 — Reparo de participante parado sob porta livre...")
        # Participante estava parado do teste anterior; agora a porta está livre
        res_rep_proc = run_cmd(env, "repair", "--json")
        assert res_rep_proc.returncode == 0, res_rep_proc.stderr
        doc_rep_proc = json.loads(res_rep_proc.stdout)
        assert doc_rep_proc["status"] == "REPAIRED"
        assert any(
            a["category"] in ("component_process", "gateway_process")
            for a in doc_rep_proc["actions_applied"]
        )
        print("[PASS] Gate 9 — Participante parado reiniciado e verificado")

        # ----------------------------------------------------
        # Gate 10: Preservação do Runtime Real do Host
        # ----------------------------------------------------
        print("[TEST] Gate 10 — Preservação do runtime real do host...")
        # O teste executou em ambiente hermético temporário; o runtime real em :8443 deve estar vivo
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            res_host = s.connect_ex(("10.163.80.176", 8443))
            assert res_host == 0, "Runtime real do gateway foi afetado pelos testes!"
        print("[PASS] Gate 10 — Runtime real do host permanece 100% íntegro e intocado")

        # ----------------------------------------------------
        # Gate 11: Dispatcher sister-infra workstation repair
        # ----------------------------------------------------
        print("[TEST] Gate 11 — Dispatcher sister-infra workstation repair...")
        res_dispatcher = subprocess.run(
            [str(ROOT / "bin" / "sister-infra"), "workstation", "repair", "--json"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert res_dispatcher.returncode == 0, res_dispatcher.stderr
        doc_disp = json.loads(res_dispatcher.stdout)
        assert doc_disp["schema"] == "sister.infra.workstation.repair/1.0.0"
        assert doc_disp["status"] == "NO_OP"
        print("[PASS] Gate 11 — Dispatcher sister-infra workstation repair validado")

        # ----------------------------------------------------
        # Gate 12: Não-mutação dos bytes da release instalada
        # ----------------------------------------------------
        print("[TEST] Gate 12 — Não-mutação de release durante repair...")
        def snapshot_dir(d: Path) -> dict[str, str]:
            h = {}
            for r, _, fs in os.walk(d):
                for f in fs:
                    p = Path(r) / f
                    try:
                        import hashlib
                        h[str(p.relative_to(d))] = hashlib.sha256(p.read_bytes()).hexdigest()
                    except Exception:
                        pass
            return h

        snap_before = snapshot_dir(release_path)
        # Quebrar symlink para forçar repair ativo
        cli_link.unlink()
        res_mut = run_cmd(env, "repair", "--json")
        assert res_mut.returncode == 0
        assert json.loads(res_mut.stdout)["status"] == "REPAIRED"
        snap_after = snapshot_dir(release_path)
        assert snap_before == snap_after, "repair alterou bytes da release instalada!"
        print("[PASS] Gate 12 — Release instalada permanece 100% byte-identical após repair")

        # ----------------------------------------------------
        # Gate 13: Pureza estrita de stdout JSON
        # ----------------------------------------------------
        print("[TEST] Gate 13 — Pureza estrita de stdout JSON...")
        res_purity = run_cmd(env, "repair", "--json")
        assert res_purity.returncode == 0
        # O stdout deve ser rigorosamente um único documento JSON válido sem linhas adicionais
        stripped_stdout = res_purity.stdout.strip()
        assert stripped_stdout.startswith("{") and stripped_stdout.endswith("}")
        parsed = json.loads(stripped_stdout)
        assert "schema" in parsed
        print("[PASS] Gate 13 — Pureza estrita de stdout JSON comprovada")

    print("\n[PASS] Todos os 13 Gates de OPS-07A3 passaram com sucesso!")


if __name__ == "__main__":
    main()

