#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

infra = (ROOT / "bin/sister-infra").read_text()
common = (ROOT / "config/common.env").read_text()

assert 'NEXO_ADDRESS="127.0.0.1"' in common
assert "# SISTER-INFRA-NEXO-LOOPBACK-BOUNDARY" in infra
assert 'export NEXO_HOST="$NEXO_ADDRESS"' in infra

start = infra.index("start_nexo() {")
end = infra.index("start_sister() {", start)
block = infra[start:end]

assert 'export NEXO_HOST="$NEXO_ADDRESS"' in block
assert './scripts/run.sh' in block

print("[PASS] sister-infra forces managed Nexo to loopback")
