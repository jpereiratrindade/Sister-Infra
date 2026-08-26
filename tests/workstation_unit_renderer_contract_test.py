#!/usr/bin/env python3

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

control = (ROOT / "bin" / "sister-workstation").read_text()

template_path = (
    ROOT
    / "templates"
    / "systemd"
    / "sister-workstation.service.in"
)

template = template_path.read_text()

assert (
    "Environment=SISTER_INFRA_RUNTIME_MODE=installed"
    in template
), "template não declara installed runtime"

assert "sister-workstation runtime-start" in template
assert "sister-workstation runtime-stop" in template

begin = control.index("render_unit() {")
end = control.index("\nsystemctl_user() {", begin)

renderer = control[begin:end]

assert (
    "components/sister-infra/templates/systemd/"
    "sister-workstation.service.in"
    in renderer
), "renderer não consome template da release"

assert 'cat > "$UNIT_FILE"' not in renderer, (
    "renderer voltou a embutir definição própria da unit"
)

for duplicated_contract in (
    "[Unit]",
    "Description=SisTer Workstation Ecosystem",
    "ExecStart=",
    "ExecStop=",
    "WantedBy=default.target",
):
    assert duplicated_contract not in renderer, (
        f"contrato systemd duplicado no renderer: "
        f"{duplicated_contract}"
    )

assert (
    "SISTER_INFRA_RUNTIME_MODE=installed"
    in renderer
), "renderer não valida installed runtime"

fixture = (
    ROOT
    / "tests"
    / "workstation_declarative_lifecycle_test.py"
).read_text()

assert (
    '"templates"' in fixture
), "fixture workstation não transporta template systemd"

print(
    "[PASS] workstation unit has a single source of truth"
)
