#!/usr/bin/env python3

from __future__ import annotations

import runpy
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECONCILE = ROOT / "bin" / "sister-reconcile"


namespace = runpy.run_path(str(RECONCILE))

compute_plan = namespace.get("compute_plan")
if not callable(compute_plan):
    raise SystemExit(
        "FAIL: sister-reconcile did not expose compute_plan"
    )


def materialize_control_plane(
    base: Path,
    *,
    gateway: str,
    runtime_gateway: str,
) -> dict:
    root = base / "components" / "sister-infra"

    gateway_path = root / "bin" / "sister-gateway"
    runtime_path = (
        root
        / "libexec"
        / "sister-infra"
        / "runtime-gateway"
    )

    gateway_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)

    gateway_path.write_text(gateway, encoding="utf-8")
    runtime_path.write_text(runtime_gateway, encoding="utf-8")

    return {
        "control_plane": {
            "component_id": "infra",
            "path": "components/sister-infra",
            "commit": "fixture",
        }
    }


def resolved() -> dict:
    return {
        "gateway": {
            "protocol": "http",
            "exposure": "ip-ports",
            "listen": "10.0.0.1",
        },
        "components": [],
    }


with tempfile.TemporaryDirectory(
    prefix="sister-gateway-control-identity-"
) as temporary:
    tmp = Path(temporary)

    current_root = tmp / "current"
    desired_root = tmp / "desired"

    current_manifest = materialize_control_plane(
        current_root,
        gateway="gateway-v1\n",
        runtime_gateway="runtime-v1\n",
    )
    desired_manifest = materialize_control_plane(
        desired_root,
        gateway="gateway-v1\n",
        runtime_gateway="runtime-v1\n",
    )

    current = {
        "current_dir": str(current_root),
        "manifest": current_manifest,
        "components": {},
        "resolved_deployment": resolved(),
        "release_id": "current",
    }

    desired = {
        "candidate_dir": str(desired_root),
        "candidate_manifest": desired_manifest,
        "components": {},
        "resolved_deployment": resolved(),
        "candidate_id": "desired",
    }

    same = compute_plan(
        current,
        desired,
        mode="lab",
        probe_runtime=False,
    )

    assert same["gateway"]["action"] == "KEEP", same["gateway"]

    (
        desired_root
        / "components"
        / "sister-infra"
        / "bin"
        / "sister-gateway"
    ).write_text(
        "gateway-v2\n",
        encoding="utf-8",
    )

    renderer_changed = compute_plan(
        current,
        desired,
        mode="lab",
        probe_runtime=False,
    )

    assert (
        renderer_changed["gateway"]["action"] == "RECONFIGURE"
    ), renderer_changed["gateway"]

    # Restore renderer, then mutate runtime adapter.
    (
        desired_root
        / "components"
        / "sister-infra"
        / "bin"
        / "sister-gateway"
    ).write_text(
        "gateway-v1\n",
        encoding="utf-8",
    )

    (
        desired_root
        / "components"
        / "sister-infra"
        / "libexec"
        / "sister-infra"
        / "runtime-gateway"
    ).write_text(
        "runtime-v2\n",
        encoding="utf-8",
    )

    runtime_changed = compute_plan(
        current,
        desired,
        mode="lab",
        probe_runtime=False,
    )

    assert (
        runtime_changed["gateway"]["action"] == "RECONFIGURE"
    ), runtime_changed["gateway"]

print("gateway control identity reconcile contract ok")
