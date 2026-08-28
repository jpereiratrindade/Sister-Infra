#!/usr/bin/env python3
"""Acceptance gate for OPS-10C — Public CLI Surface & Operator UX Contract."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "bin" / "sister-infra"
WORKSTATION = ROOT / "bin" / "sister-workstation"
RUNTIME_GATEWAY = ROOT / "libexec" / "sister-infra" / "runtime-gateway"


def assert_help_exposes_canonical_namespaces() -> None:
    for flag in ("--help", "-h", "help"):
        res = subprocess.run(
            [str(INFRA), flag],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"{flag} returned {res.returncode}"
        out = res.stdout

        # Canonical namespaces
        for namespace in ("dev", "lab", "production", "lifecycle", "workstation", "authority"):
            assert f"sister-infra {namespace}" in out, f"missing namespace {namespace} in help ({flag})"

        # Must not expose legacy commands or options in help
        for forbidden in (
            "sister-infra <comando> [--profile",
            "up --profile",
            "down --profile",
            "status --profile",
            "--profile dev|lan",
            "sister-infra candidate",
            "\n  candidate",
            "client-env",
            "hosts-line",
            "\n  hosts",
            "\n  up ",
            "\n  down ",
        ):
            assert forbidden not in out, f"help ({flag}) exposes forbidden legacy term: {forbidden!r}"


def assert_no_args_exits_usage_code_2() -> None:
    res = subprocess.run(
        [str(INFRA)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert res.returncode == 2, f"expected returncode 2 on empty invocation, got {res.returncode}"
    assert "sister-infra dev" in res.stderr or "sister-infra dev" in res.stdout


def assert_production_fail_closed(root: Path) -> None:
    for cmd in ("up", "down"):
        run_root = root / cmd
        env = dict(os.environ)
        env["SISTER_INFRA_RUN_ROOT"] = str(run_root)
        env["PRODUCTION_APPROVED"] = "YES"
        env["SISTER_INFRA_PRODUCTION_CONFIRM"] = "YES"
        env["PRODUCTION_GATE_CMD"] = "true"
        res = subprocess.run(
            [str(INFRA), cmd, "--profile", "production"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        assert res.returncode == 2, f"production {cmd} must fail with code 2"
        assert "foi retirado pelo OPS-10" in res.stderr
        assert "production plan" in res.stderr
        assert "production apply" in res.stderr
        assert not run_root.exists(), f"production {cmd} mutated filesystem before failing"


def assert_production_verify_forwarding(root: Path) -> None:
    fixture = root / "forward"
    bin_dir = fixture / "bin"
    bin_dir.mkdir(parents=True)
    infra = bin_dir / "sister-infra"
    production = bin_dir / "sister-production"
    shutil.copy2(INFRA, infra)
    production.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'forwarded:%s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    production.chmod(0o755)

    res = subprocess.run(
        [str(infra), "verify", "--profile", "production"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout == "forwarded:verify\n"
    assert "[DEPRECATED]" in res.stderr
    assert "production verify" in res.stderr


def assert_legacy_lan_runtime_deprecation(root: Path) -> None:
    # client-env produces clean stdout and deprecation warning on stderr
    fixture_resolved = root / "resolved.json"
    fixture_resolved.write_text(
        '{"schema":"sister.infra.deployment.resolved/1","status":"READY","gateway":{"listen":"127.0.0.1","port":8443},"components":[{"component_id":"test","system_id":"sister_test","runtime":{"transport":"tcp","listen":"127.0.0.1","port":8090},"gateway":{"host":"test.localhost"}}]}',
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["SISTER_RESOLVED_DEPLOYMENT_FILE"] = str(fixture_resolved)

    res = subprocess.run(
        [str(INFRA), "client-env"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "export NO_PROXY=" in res.stdout
    assert "[DEPRECATED]" in res.stderr
    assert "comando histórico" in res.stderr


def assert_runtime_boundaries_and_docs() -> None:
    infra_source = INFRA.read_text(encoding="utf-8")
    workstation_source = WORKSTATION.read_text(encoding="utf-8")

    assert RUNTIME_GATEWAY.is_file() and os.access(RUNTIME_GATEWAY, os.X_OK)
    assert "render_gateway()" not in infra_source
    assert 'RUNTIME_GATEWAY="$INFRA_ROOT/libexec/sister-infra/runtime-gateway"' in infra_source

    begin = workstation_source.index("declarative_gateway_action() {")
    end = workstation_source.index("\nruntime_start() {", begin)
    gateway_adapter = workstation_source[begin:end]
    assert "/libexec/sister-infra/runtime-gateway" in gateway_adapter
def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sister-ops10c-public-") as tmp:
        root = Path(tmp)
        assert_help_exposes_canonical_namespaces()
        assert_no_args_exits_usage_code_2()
        assert_production_fail_closed(root)
        assert_production_verify_forwarding(root)
        assert_legacy_lan_runtime_deprecation(root)
        assert_runtime_boundaries_and_docs()
    print("[PASS] OPS-10C public CLI surface contract validation")


if __name__ == "__main__":
    main()
