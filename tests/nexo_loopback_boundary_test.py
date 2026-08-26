#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
deployment_file = ROOT / "config/deployments/workstation-lab.json"

assert deployment_file.exists(), "workstation-lab.json ausente"
data = json.loads(deployment_file.read_text(encoding="utf-8"))

bindings = {b["system_id"]: b for b in data.get("bindings", [])}
assert "sister_nexo" in bindings, "binding sister_nexo ausente no deployment"

nexo_runtime = bindings["sister_nexo"]["runtime"]
assert nexo_runtime.get("transport") == "tcp"
assert nexo_runtime.get("listen") == "127.0.0.1", "Nexo não está restrito a loopback"
assert nexo_runtime.get("port") == 8015

for system_id, b in bindings.items():
    rt = b["runtime"]
    if rt.get("transport") == "tcp":
        assert rt.get("listen") in ("127.0.0.1", "localhost"), (
            f"{system_id} exposto fora do loopback: {rt.get('listen')}"
        )

print("[PASS] declarative deployment enforces loopback isolation for managed subsystems")
