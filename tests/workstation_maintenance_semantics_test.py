#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-workstation"

sys.path.insert(0, str(ROOT / "tests"))
import jsonschema
from composition_resolver_test import make_component, make_contracts, write_composition
from workstation_composition_candidate_test import add_qualified_artifact, git_init_commit
from workstation_declarative_lifecycle_test import deployment, make_control_plane


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def snapshot(root: Path) -> tuple[tuple[str, str, int, str], ...]:
    items: list[tuple[str, str, int, str]] = []
    if not root.exists():
        return tuple()

    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            items.append((rel, "symlink", 0, os.readlink(path)))
        elif path.is_dir():
            items.append((rel, "dir", path.stat().st_mode & 0o7777, ""))
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            items.append((rel, "file", path.stat().st_mode & 0o7777, digest))
        else:
            items.append((rel, "other", path.stat().st_mode & 0o7777, ""))
    return tuple(items)


def function_block(source: str, name: str) -> str:
    start = source.index(f"{name}() {{")
    next_pos = source.find("\n}\n", start)
    if next_pos < 0:
        raise AssertionError(f"fim de função não encontrado: {name}")
    return source[start : next_pos + 3]


def make_env(base: Path) -> tuple[dict[str, str], dict[str, Path]]:
    home = base / "home"
    control = base / "control-plane"
    composition = control / "config" / "compositions" / "workstation.json"
    deployment = control / "config" / "deployments" / "workstation-lab.json"

    composition.parent.mkdir(parents=True)
    deployment.parent.mkdir(parents=True)
    composition.write_text("{}\n", encoding="utf-8")
    deployment.write_text("{}\n", encoding="utf-8")
    home.mkdir(parents=True)

    paths = {
        "install": home / "install",
        "config": home / "config",
        "state": home / "state",
        "systemd": home / "systemd",
        "bin": home / "bin",
        "control": control,
        "composition": composition,
        "deployment": deployment,
    }

    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "SISTER_WORKSTATION_INSTALL_ROOT": str(paths["install"]),
            "SISTER_WORKSTATION_CONFIG_ROOT": str(paths["config"]),
            "SISTER_WORKSTATION_STATE_ROOT": str(paths["state"]),
            "SISTER_WORKSTATION_SYSTEMD_ROOT": str(paths["systemd"]),
            "SISTER_WORKSTATION_BIN_ROOT": str(paths["bin"]),
            "SISTER_WORKSTATION_CONTROL_PLANE_SOURCE": str(control),
            "SISTER_WORKSTATION_COMPOSITION_FILE": str(composition),
            "SISTER_WORKSTATION_DEPLOYMENT_FILE": str(deployment),
            "SISTER_WORKSTATION_TEST_MODE": "1",
        }
    )
    return env, paths


def main() -> int:
    source = CLI.read_text(encoding="utf-8")

    for name in (
        "workstation_check",
        "doctor",
        "cmd_client_env",
        "cmd_hosts_line",
        "candidate_verify",
        "release_list",
    ):
        block = function_block(source, name)
        assert "materialize_layout" not in block, (
            f"{name} voltou a materializar layout"
        )
    print("[PASS] Gate A — fronteiras read-only não materializam layout")

    lowered = source.lower()
    for forbidden in (
        "sister_nexo",
        "sister-nexo",
        "sister_praxis",
        "sister-praxis",
        "sister_urt",
        "sister-urt",
        "sister_atmos",
        "sister-atmos",
        "8015",
        "8093",
        "8094",
    ):
        assert forbidden not in lowered, (
            f"maintenance boundary contém conhecimento concreto: {forbidden}"
        )
    print("[PASS] Gate B — maintenance boundary sem participantes concretos")

    materializer = function_block(source, "materialize_layout")
    assert "COMPOSITION_FILE" not in materializer
    assert "DEPLOYMENT_FILE" not in materializer
    assert "CONTROL_PLANE_SOURCE" not in materializer
    assert "layout_preflight" in materializer

    bootstrap_preflight = function_block(
        source, "workstation_bootstrap_preflight"
    )
    assert "COMPOSITION_FILE" in bootstrap_preflight
    assert "DEPLOYMENT_FILE" in bootstrap_preflight
    assert "CONTROL_PLANE_SOURCE" in bootstrap_preflight

    bootstrap_block = function_block(source, "workstation_bootstrap")
    assert "workstation_bootstrap_preflight" in bootstrap_block
    assert "materialize_layout" in bootstrap_block

    print(
        "[PASS] Gate B2 — materialização local desacoplada da autoridade "
        "de bootstrap"
    )

    with tempfile.TemporaryDirectory(
        prefix="sister-maintenance-semantics-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        env, paths = make_env(tmp)

        before = snapshot(tmp)
        check = run(env, "check")
        after = snapshot(tmp)
        assert check.returncode != 0
        assert before == after, "check alterou filesystem"
        print("[PASS] Gate C — check é read-only em falha")

        before = snapshot(tmp)
        doctor = run(env, "doctor")
        after = snapshot(tmp)
        assert before == after, "doctor alterou filesystem"
        print("[PASS] Gate D — doctor é read-only")

        boot = run(env, "bootstrap")
        assert boot.returncode == 0, boot.stdout + boot.stderr

        expected_dirs = {
            paths["install"],
            paths["install"] / "releases",
            paths["install"] / "candidates",
            paths["config"],
            paths["state"],
            paths["systemd"],
            paths["bin"],
        }
        for path in expected_dirs:
            assert path.is_dir(), f"bootstrap não criou {path}"
        print("[PASS] Gate E — bootstrap materializa pré-condições locais")

        check2 = run(env, "check")
        assert check2.returncode == 0, check2.stdout + check2.stderr
        assert "workstation check READY" in (check2.stdout + check2.stderr)
        print("[PASS] Gate F — check confirma estado convergido")

        snap1 = snapshot(tmp)
        boot2 = run(env, "bootstrap")
        snap2 = snapshot(tmp)
        assert boot2.returncode == 0, boot2.stdout + boot2.stderr
        assert "NO_OP" in (boot2.stdout + boot2.stderr)
        assert snap1 == snap2, "segundo bootstrap alterou estado material"
        print("[PASS] Gate G — bootstrap repetido produz NO_OP")

    with tempfile.TemporaryDirectory(
        prefix="sister-maintenance-failclosed-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        env, paths = make_env(tmp)

        paths["config"].write_text("collision\n", encoding="utf-8")
        before = snapshot(tmp)
        blocked = run(env, "bootstrap")
        after = snapshot(tmp)

        assert blocked.returncode != 0
        assert "não é diretório" in blocked.stderr
        assert before == after, "bootstrap alterou estado após preflight falhar"
        assert not paths["install"].exists(), (
            "bootstrap criou layout parcial antes de detectar divergência"
        )
        print("[PASS] Gate H — divergência existente falha fechado sem mutação")

    with tempfile.TemporaryDirectory(
        prefix="sister-maintenance-authority-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        env, paths = make_env(tmp)
        paths["deployment"].unlink()

        before = snapshot(tmp)
        blocked = run(env, "bootstrap")
        after = snapshot(tmp)

        assert blocked.returncode != 0
        assert "deployment canônico ausente" in blocked.stderr
        assert before == after
        assert not paths["install"].exists()
        print("[PASS] Gate I — bootstrap exige declaração canônica antes de agir")

    # Gate J: Pureza de stdout JSON em operações declarativas (OPS-07A0-FIX)
    # Caso 1: release-create --json produz exatamente um documento JSON válido em stdout
    # Caso 2: Segunda criação (idempotência / NO_OP em materialize_layout) preserva stdout JSON puro
    # Caso 3: Diagnósticos permitidos em stderr sem invalidar o contrato JSON
    # Teste adicional: release-verify --json preserva stdout JSON puro com diagnósticos em stderr
    with tempfile.TemporaryDirectory(
        prefix="sister-maintenance-json-contract-"
    ) as tmp_text:
        tmp = Path(tmp_text)
        home = tmp / "home"
        workspace = tmp / "workspace"
        home.mkdir()
        workspace.mkdir()

        contracts = make_contracts(tmp)
        make_control_plane(workspace)

        alpha = make_component(tmp, "sister-alpha", "alpha", "sister_alpha")
        beta = make_component(tmp, "sister-beta", "beta", "sister_beta")
        add_qualified_artifact(alpha, "alpha")
        add_qualified_artifact(beta, "beta")
        git_init_commit(alpha)
        git_init_commit(beta)

        decl_dir = tmp / "decl"
        decl_dir.mkdir()
        comp_file = decl_dir / "composition.json"
        dep_file = decl_dir / "deployment.json"
        write_composition(comp_file, ["../sister-alpha", "../sister-beta"])
        deployment(dep_file)

        jsonschema_site = str(Path(jsonschema.__file__).resolve().parent.parent)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (jsonschema_site, env.get("PYTHONPATH", "")) if part
        )
        env.update(
            {
                "HOME": str(home),
                "SISTER_WORKSTATION_CONTROL_PLANE_SOURCE": str(
                    workspace / "sister-infra"
                ),
                "SISTER_WORKSTATION_INSTALL_ROOT": str(home / "install"),
                "SISTER_WORKSTATION_CONFIG_ROOT": str(home / "config"),
                "SISTER_WORKSTATION_STATE_ROOT": str(home / "state"),
                "SISTER_WORKSTATION_SYSTEMD_ROOT": str(home / "systemd"),
                "SISTER_WORKSTATION_BIN_ROOT": str(home / "bin"),
                "SISTER_WORKSTATION_TEST_MODE": "1",
                "SISTER_WORKSTATION_CONTRACTS_ROOT": str(contracts),
                "SISTER_WORKSTATION_COMPOSITION_FILE": str(comp_file),
                "SISTER_WORKSTATION_DEPLOYMENT_FILE": str(dep_file),
            }
        )

        cand_dir1 = tmp / "candidate1"
        res_cand1 = subprocess.run(
            [
                str(ROOT / "bin" / "sister-candidate"),
                "create",
                str(comp_file),
                "--out",
                str(cand_dir1),
                "--contracts-root",
                str(contracts),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert res_cand1.returncode == 0, res_cand1.stderr

        # Caso 1: release-create --json (primeira criação com materialização de layout)
        res_rc1 = run(
            env,
            "release-create",
            "--candidate",
            str(cand_dir1),
            "--deployment",
            str(dep_file),
            "--json",
        )
        assert res_rc1.returncode == 0, res_rc1.stdout + res_rc1.stderr
        assert "[PASS]" not in res_rc1.stdout, "linha [PASS] vazou para stdout"
        assert "[INFO]" not in res_rc1.stdout, "linha [INFO] vazou para stdout"
        payload1 = json.loads(res_rc1.stdout)
        assert payload1.get("status") == "READY"
        assert "release_id" in payload1
        assert "release_path" in payload1
        release1_path = Path(payload1["release_path"])

        # Caso 3: diagnóstico permitido em stderr
        assert "[PASS]" in res_rc1.stderr, "mensagens diagnósticas esperadas em stderr"

        # Prepara candidata 2 para testar Caso 2 (layout já convergido / NO_OP em materialize_layout)
        (alpha / "main.cpp").write_text("int main() { return 0; }\n// v2\n")
        subprocess.run(["git", "-C", str(alpha), "add", "main.cpp"], check=True)
        subprocess.run(["git", "-C", str(alpha), "commit", "-q", "-m", "v2"], check=True)
        add_qualified_artifact(alpha, "alpha")
        git_init_commit(alpha)

        cand_dir2 = tmp / "candidate2"
        res_cand2 = subprocess.run(
            [
                str(ROOT / "bin" / "sister-candidate"),
                "create",
                str(comp_file),
                "--out",
                str(cand_dir2),
                "--contracts-root",
                str(contracts),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert res_cand2.returncode == 0, res_cand2.stderr

        # Caso 2: idempotência / NO_OP em layout
        res_rc2 = run(
            env,
            "release-create",
            "--candidate",
            str(cand_dir2),
            "--deployment",
            str(dep_file),
            "--json",
        )
        assert res_rc2.returncode == 0, res_rc2.stdout + res_rc2.stderr
        assert "[PASS]" not in res_rc2.stdout
        assert "[INFO]" not in res_rc2.stdout
        payload2 = json.loads(res_rc2.stdout)
        assert payload2.get("status") == "READY"
        assert "NO_OP" in res_rc2.stderr, "diagnóstico NO_OP deve estar em stderr"

        # Verificação do contrato JSON para release-verify --json
        res_ver = run(env, "release-verify", str(release1_path), "--json")
        assert res_ver.returncode == 0, res_ver.stdout + res_ver.stderr
        assert "[PASS]" not in res_ver.stdout
        assert "[INFO]" not in res_ver.stdout
        payload_ver = json.loads(res_ver.stdout)
        assert payload_ver.get("status") == "VALID"
        assert payload_ver.get("release_id") == payload1["release_id"]

        print("[PASS] Gate J — pureza de stdout JSON em operações declarativas")

    print("[PASS] OPS-07A0 maintenance semantics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
