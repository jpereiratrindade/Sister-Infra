#!/usr/bin/env python3

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "sister-infra"
TEMPLATE = ROOT / "gateway" / "haproxy.cfg.in"


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


script = SCRIPT.read_text()
template = TEMPLATE.read_text()

start = script.find("render_gateway() {")
if start < 0:
    fail("função render_gateway não encontrada")

end = script.find("\npid_alive() {", start)
if end < 0:
    fail("fim da função render_gateway não encontrado")

renderer = script[start:end]

template_placeholders = set(
    re.findall(r"__[A-Z0-9_]+__", template)
)

rendered_placeholders = set(
    re.findall(
        r's\|(__[A-Z0-9_]+__)\|',
        renderer,
    )
)

missing = sorted(template_placeholders - rendered_placeholders)

if missing:
    fail(
        "placeholders do template sem renderização: "
        + ", ".join(missing)
    )

required_urt = {
    "__URT_HOST__",
    "__URT_ADDRESS__",
    "__URT_PORT__",
    "__URT_HEALTH_PATH__",
}

missing_urt = sorted(required_urt - rendered_placeholders)

if missing_urt:
    fail(
        "renderização URT incompleta: "
        + ", ".join(missing_urt)
    )

if "grep -Eq '__[A-Z0-9_]+__' \"$GATEWAY_CFG\"" not in renderer:
    fail("gate contra placeholders residuais ausente")

print(
    "[PASS] gateway renderer cobre todos os placeholders "
    f"({len(template_placeholders)} encontrados)"
)
print("[PASS] contrato de renderização URT completo")
print("[PASS] gate contra placeholders residuais presente")
