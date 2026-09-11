#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "libexec" / "sister-infra" / "runtime-gateway"
text = path.read_text(encoding="utf-8")


verify_start = text.find("cmd_verify() {")
verify_end = text.find("\ncmd_client_env() {", verify_start)

if verify_start < 0 or verify_end < 0:
    raise SystemExit("FAIL: cmd_verify boundaries not found")

verify_body = text[verify_start:verify_end]

if "verify_gateway_materialization" not in verify_body:
    raise SystemExit(
        "FAIL: verify does not validate gateway materialization"
    )

if "verify_public_navigation" not in verify_body:
    raise SystemExit(
        "FAIL: verify does not observe active public navigation"
    )

if "\n  render_gateway\n" in verify_body:
    raise SystemExit(
        "FAIL: verify still materializes gateway configuration"
    )


material_start = text.find("verify_gateway_materialization() {")
material_end = text.find("\npid_alive() {", material_start)

if material_start < 0 or material_end < 0:
    raise SystemExit(
        "FAIL: verify_gateway_materialization boundaries not found"
    )

material_body = text[material_start:material_end]

if 'cmp -s "$expected" "$GATEWAY_CFG"' not in material_body:
    raise SystemExit(
        "FAIL: expected/materialized gateway comparison absent"
    )


navigation_start = text.find("verify_public_navigation() {")
navigation_end = text.find("\npid_alive() {", navigation_start)

if navigation_start < 0 or navigation_end < 0:
    raise SystemExit(
        "FAIL: verify_public_navigation boundaries not found"
    )

navigation_body = text[navigation_start:navigation_end]

for required in (
    "/_sister/open/$component_id",
    "%{http_code}",
    "%{redirect_url}",
    '"302"',
):
    if required not in navigation_body:
        raise SystemExit(
            f"FAIL: factual navigation witness missing: {required}"
        )

print("runtime gateway verify read-only contract ok")
