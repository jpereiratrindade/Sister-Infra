#!/usr/bin/env python3
"""Gates iniciais do OPS-10C — caminhos operacionais canônicos."""

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


def run_legacy(command: str, run_root: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["SISTER_INFRA_RUN_ROOT"] = str(run_root)
    env["PRODUCTION_APPROVED"] = "YES"
    env["SISTER_INFRA_PRODUCTION_CONFIRM"] = "YES"
    env["PRODUCTION_GATE_CMD"] = "true"
    return subprocess.run(
        [str(INFRA), command, "--profile", "production"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def assert_retired(command: str, root: Path) -> None:
    run_root = root / command
    result = run_legacy(command, run_root)
    assert result.returncode == 2, (
        f"{command} de produção histórico deveria falhar com código 2; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "foi retirado pelo OPS-10" in result.stderr
    assert "production plan" in result.stderr
    assert "production apply" in result.stderr
    assert not run_root.exists(), (
        f"guard deve falhar antes de materializar estado operacional: {run_root}"
    )


def assert_production_verify_forwards(root: Path) -> None:
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

    result = subprocess.run(
        [str(infra), "verify", "--profile", "production"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "forwarded:verify\n"
    assert "[DEPRECATED]" in result.stderr
    assert "production verify" in result.stderr


def assert_runtime_boundary() -> None:
    infra_source = INFRA.read_text(encoding="utf-8")
    workstation_source = WORKSTATION.read_text(encoding="utf-8")

    assert RUNTIME_GATEWAY.is_file() and os.access(RUNTIME_GATEWAY, os.X_OK)
    assert "render_gateway()" not in infra_source
    assert 'RUNTIME_GATEWAY="$INFRA_ROOT/libexec/sister-infra/runtime-gateway"' in infra_source

    begin = workstation_source.index("declarative_gateway_action() {")
    end = workstation_source.index("\nruntime_start() {", begin)
    gateway_adapter = workstation_source[begin:end]
    assert "/libexec/sister-infra/runtime-gateway" in gateway_adapter
    assert '/bin/sister-infra" "$action"' not in gateway_adapter


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sister-ops10-surface-") as tmp:
        root = Path(tmp)
        assert_retired("up", root)
        assert_retired("down", root)
        assert_production_verify_forwards(root)
        assert_runtime_boundary()
    print("[PASS] OPS-10C canonical production and runtime boundaries")


if __name__ == "__main__":
    main()
