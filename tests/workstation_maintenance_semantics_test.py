#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "sister-workstation"


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
        assert "workstation check READY" in check2.stdout
        print("[PASS] Gate F — check confirma estado convergido")

        snap1 = snapshot(tmp)
        boot2 = run(env, "bootstrap")
        snap2 = snapshot(tmp)
        assert boot2.returncode == 0, boot2.stdout + boot2.stderr
        assert "NO_OP" in boot2.stdout
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

    print("[PASS] OPS-07A0 maintenance semantics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
