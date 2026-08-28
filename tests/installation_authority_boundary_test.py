#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "bin" / "sister-authority"
LIFECYCLE = ROOT / "bin" / "sister-lifecycle"
WORKSTATION = ROOT / "bin" / "sister-workstation"


def run(cmd: list[str], env: dict[str, str], expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == expect, f"{cmd}\nstdout={result.stdout}\nstderr={result.stderr}"
    return result


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def authority(env: dict[str, str], cli: Path = AUTHORITY, allow: bool = False) -> dict:
    cmd = [str(cli), "resolve", "--target", "lab"]
    if allow:
        cmd.append("--allow-missing")
    return json.loads(run(cmd, env).stdout)


def lifecycle_plan(env: dict[str, str], cli: Path = LIFECYCLE) -> dict:
    return json.loads(run([str(cli), "plan", "--target", "lab", "--json"], env).stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sister-authority-") as tmp_text:
        tmp = Path(tmp_text)
        config = tmp / "outside-repository" / "authority"
        composition = config / "composition.json"
        deployment = config / "deployment.json"
        write_json(composition, {
            "schema": "sister.infra.composition/2.0.0",
            "composition_id": "authority_test",
            "components": [],
        })
        base_deployment = {
            "schema": "sister.infra.deployment/1.0.0",
            "deployment_id": "authority-test",
            "composition_id": "authority_test",
            "gateway": {"protocol": "https", "listen": "192.0.2.10", "port": 443},
            "bindings": [{
                "system_id": "example",
                "runtime": {"transport": "tcp", "listen": "127.0.0.1", "port": 9000},
                "gateway": {"host": "a.example.test"},
            }],
        }
        write_json(deployment, base_deployment)

        env = dict(os.environ)
        for name in (
            "SISTER_WORKSTATION_COMPOSITION_FILE",
            "SISTER_WORKSTATION_DEPLOYMENT_FILE",
            "SISTER_WORKSTATION_POLICY_FILE",
        ):
            env.pop(name, None)
        env.update({
            "HOME": str(tmp / "home"),
            "SISTER_WORKSTATION_CONFIG_ROOT": str(config),
            "SISTER_WORKSTATION_INSTALL_ROOT": str(tmp / "install"),
            "SISTER_WORKSTATION_STATE_ROOT": str(tmp / "state"),
            "SISTER_WORKSTATION_SYSTEMD_ROOT": str(tmp / "systemd"),
            "SISTER_WORKSTATION_BIN_ROOT": str(tmp / "user-bin"),
            "SISTER_WORKSTATION_TEST_MODE": "1",
        })

        source_before = tree_digest(ROOT / "bin")
        plan_a = lifecycle_plan(env)
        digest_a = plan_a["authority"]["deployment"]["digest"]
        assert plan_a["authority"]["source_tree_is_authority"] is False
        assert Path(plan_a["authority"]["config_root"]) == config.resolve()
        print("[PASS] UX35/UX41 — authority externa com path/source/digest")

        changed_domain = json.loads(json.dumps(base_deployment))
        changed_domain["bindings"][0]["gateway"]["host"] = "b.example.test"
        write_json(deployment, changed_domain)
        plan_domain = lifecycle_plan(env)
        assert plan_domain["authority"]["deployment"]["digest"] != digest_a
        assert tree_digest(ROOT / "bin") == source_before
        print("[PASS] UX33/UX37 — domínio muda plano sem mudar engine")

        changed_ip = json.loads(json.dumps(changed_domain))
        changed_ip["gateway"]["listen"] = "192.0.2.99"
        write_json(deployment, changed_ip)
        plan_ip = lifecycle_plan(env)
        assert plan_ip["authority"]["deployment"]["digest"] != plan_domain["authority"]["deployment"]["digest"]
        assert tree_digest(ROOT / "bin") == source_before
        print("[PASS] UX34 — bind muda plano sem mudar engine")

        direct = authority(env)
        assert direct["composition"]["digest"] == plan_ip["authority"]["composition"]["digest"]
        assert direct["deployment"]["digest"] == plan_ip["authority"]["deployment"]["digest"]
        print("[PASS] UX40/UX44 — consumidores concordam sobre identidade")

        engine = tmp / "read-only-engine"
        (engine / "bin").mkdir(parents=True)
        shutil.copy2(AUTHORITY, engine / "bin" / "sister-authority")
        shutil.copy2(LIFECYCLE, engine / "bin" / "sister-lifecycle")
        (engine / "config" / "compositions").mkdir(parents=True)
        (engine / "config" / "deployments").mkdir(parents=True)
        write_json(engine / "config" / "compositions" / "workstation.json", {"tempting": True})
        write_json(engine / "config" / "deployments" / "workstation-lab.json", {"tempting": True})
        engine_digest = tree_digest(engine)
        for path in sorted(engine.rglob("*"), reverse=True):
            path.chmod(0o555 if path.is_dir() or path.parent.name == "bin" else 0o444)
        engine.chmod(0o555)
        try:
            readonly_plan = lifecycle_plan(env, engine / "bin" / "sister-lifecycle")
            assert readonly_plan["authority"]["deployment"]["digest"] == direct["deployment"]["digest"]
        finally:
            engine.chmod(0o755)
            for path in engine.rglob("*"):
                path.chmod(0o755 if path.is_dir() or path.parent.name == "bin" else 0o644)
        assert tree_digest(engine) == engine_digest
        print("[PASS] UX36 — source tree read-only")

        write_json(engine / "config" / "deployments" / "workstation-lab.json", {"changed": True})
        after_example = lifecycle_plan(env, engine / "bin" / "sister-lifecycle")
        assert after_example["authority"]["deployment"]["digest"] == direct["deployment"]["digest"]
        print("[PASS] UX43 — exemplo do repo não afeta instalação configurada")

        missing_env = env.copy()
        missing_env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(tmp / "missing")
        failed = run([str(engine / "bin" / "sister-lifecycle"), "plan", "--target", "lab", "--json"], missing_env, expect=2)
        error = json.loads(failed.stdout)
        assert error["failed_stage"] == "AUTHORITY"
        assert "workstation-lab.json" not in error["error"]
        print("[PASS] UX38/UX39 — missing authority falha sem repo fallback")

        before_files = {path.name: path.read_bytes() for path in (composition, deployment)}
        boot = run([str(WORKSTATION), "bootstrap"], env)
        assert "workstation bootstrap READY" in boot.stderr
        assert composition.read_bytes() == before_files["composition.json"]
        assert deployment.read_bytes() == before_files["deployment.json"]
        assert not (config / "policy.json").exists()
        assert not (config / "tls").exists()
        print("[PASS] UX42/UX45 — bootstrap não cria nem sobrescreve authority")

        empty_config = tmp / "empty-config"
        empty_env = env.copy()
        empty_env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(empty_config)
        run([str(WORKSTATION), "bootstrap"], empty_env)
        assert empty_config.is_dir()
        assert not (empty_config / "composition.json").exists()
        assert not (empty_config / "deployment.json").exists()
        assert not (empty_config / "policy.json").exists()
        assert not (empty_config / "tls").exists()

        seed_root = tmp / "seeded-config"
        seeded = json.loads(run([
            str(AUTHORITY), "seed-lab",
            "--composition-source", str(composition),
            "--deployment-source", str(deployment),
            "--config-root", str(seed_root),
        ], env).stdout)
        assert seeded["status"] == "SEEDED"
        seeded_again = json.loads(run([
            str(AUTHORITY), "seed-lab",
            "--composition-source", str(composition),
            "--deployment-source", str(deployment),
            "--config-root", str(seed_root),
        ], env).stdout)
        assert seeded_again["status"] == "NO_OP"
        assert (seed_root / "composition.json").read_bytes() == composition.read_bytes()
        assert (seed_root / "deployment.json").read_bytes() == deployment.read_bytes()
        print("[PASS] explicit seed — migração LAB idempotente e evidenciada")

        static = "\n".join((ROOT / "bin" / name).read_text(encoding="utf-8") for name in (
            "sister-workstation", "sister-lab", "sister-lifecycle", "sister-production", "sister-infra",
        ))
        assert "$CONTROL_PLANE_SOURCE/config/compositions/workstation.json" not in static
        assert "$CONTROL_PLANE_SOURCE/config/deployments/workstation-lab.json" not in static
        assert '"10.0.1.50"' not in static
        assert '"10.163.80.176"' not in static
        print("[PASS] UX42 — bootstrap vazio não inventa configuration/TLS")

    print("[PASS] OPS-09 installation authority boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
