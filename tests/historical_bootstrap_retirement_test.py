#!/usr/bin/env python3

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "setup_sister_infra.sh"


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


if LEGACY.exists():
    fail("setup_sister_infra.sh voltou à árvore operacional")

proc = subprocess.run(
    [
        "git",
        "-C",
        str(ROOT),
        "grep",
        "-n",
        "-E",
        r"gateway-lab\.pem|ca-lab\.crt|SisTer/\.run/gateway|migrate_existing_lab_tls",
        "--",
        "bin",
        "config",
        "contracts",
        "templates",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    check=False,
)

if proc.returncode not in (0, 1):
    fail(f"git grep falhou: {proc.stderr.strip()}")

if proc.stdout.strip():
    fail(
        "fronteira operacional ainda referencia TLS legado:\n"
        + proc.stdout.strip()
    )

print("[PASS] historical bootstrap retired from operational tree")
