#!/usr/bin/env python3
"""
tests/documentation_contract_alignment_test.py
=============================================================================
SUÍTE DE CONFORMIDADE E ALINHAMENTO DOCUMENTAL (FACTUAL CONTRACTUAL GATE)
=============================================================================
Garante que a documentação (README.md, docs/, contracts/) e o código do
ecossistema permaneçam em estrita convergência factual, prevenindo:
- Drift de contratos (ex: documentar gateway em bindings quando o código rejeita)
- Ambiguidade de campos canônicos (ex: domain vs base_domain)
- Exemplos operacionais desatualizados ou quebrados
- Menções a testes inexistentes no README
=============================================================================
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_gate_d1_no_gateway_in_documentation_bindings():
    """Gate D1: Nenhum documento ativo instrui participantes a declarar gateway em bindings."""
    print("[TEST] Gate D1 — Verificando ausência de exemplos com 'gateway' em bindings...")
    doc_paths = [ROOT / "README.md"]
    doc_paths.extend((ROOT / "docs").rglob("*.md"))
    doc_paths.extend((ROOT / "contracts").rglob("*.md"))

    pattern = re.compile(r'"gateway"\s*:\s*\{\s*"host"', re.MULTILINE)

    violations = []
    for path in doc_paths:
        content = path.read_text(encoding="utf-8")
        if pattern.search(content):
            violations.append(str(path.relative_to(ROOT)))

    assert not violations, (
        f"Violação no Gate D1: Documentos ativos ensinam participantes a declarar gateway: {violations}"
    )
    print("[PASS] Gate D1 — Zero exemplos incorretos de gateway em bindings na documentação")


def test_gate_d2_contract_unification_gateway_domain():
    """Gate D2: O schema e o README do contrato de deployment unificam exclusivamente em gateway.domain."""
    print("[TEST] Gate D2 — Validando unificação canônica de gateway.domain nos contratos...")
    schema_file = ROOT / "contracts" / "deployment" / "1.0.0" / "deployment.schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))

    gw_props = schema.get("properties", {}).get("gateway", {}).get("properties", {})
    assert "domain" in gw_props, "Propriedade 'domain' deve existir no gateway do deployment schema"
    assert "base_domain" not in gw_props, "Propriedade ambígua 'base_domain' não deve existir no deployment schema"

    readme_file = ROOT / "contracts" / "deployment" / "1.0.0" / "README.md"
    readme_content = readme_file.read_text(encoding="utf-8")
    assert "gateway.domain" in readme_content, "contracts/deployment/1.0.0/README.md deve documentar gateway.domain"
    assert "base_domain" not in readme_content, "contracts/deployment/1.0.0/README.md não deve citar base_domain"

    print("[PASS] Gate D2 — Contrato de deployment unificado exclusivamente sobre gateway.domain")


def test_gate_d3_canonical_deployment_alignment():
    """Gate D3: workstation-lab.json publica HTTP por IP/portas e mantém bindings puros."""
    print("[TEST] Gate D3 — Validando conformidade factual de workstation-lab.json...")
    dep_file = ROOT / "config" / "deployments" / "workstation-lab.json"
    doc = json.loads(dep_file.read_text(encoding="utf-8"))

    gw = doc.get("gateway", {})
    assert gw.get("protocol") == "http", "LAB deve publicar HTTP sem autoridade TLS"
    assert gw.get("exposure") == "ip-ports", "LAB deve usar exposição ip-ports"
    assert "domain" not in gw, "LAB ip-ports não deve depender de DNS"
    assert gw.get("listen") == "10.163.80.176", (
        "gateway.listen do LAB deve publicar na interface LAN institucional"
    )
    assert "port" not in gw, "LAB ip-ports deriva a porta pública de cada binding"
    assert "base_domain" not in gw, "workstation-lab.json não deve conter base_domain"

    for binding in doc.get("bindings", []):
        sys_id = binding.get("system_id")
        assert "gateway" not in binding, f"Binding '{sys_id}' em workstation-lab.json contém gateway!"
        for forbidden in ("domain", "proxy", "certificate", "tls"):
            assert forbidden not in binding, f"Binding '{sys_id}' contém chave proibida '{forbidden}'"

    assert [b["runtime"]["port"] for b in doc["bindings"]] == [8000, 8015, 8093, 8094, 8095]
    print("[PASS] Gate D3 — workstation-lab.json publica HTTP/IP por portas institucionais")


def test_gate_d4_readme_test_references_exist():
    """Gate D4: Todos os arquivos de teste referenciados no README.md existem no repositório."""
    print("[TEST] Gate D4 — Verificando existência física de testes listados no README.md...")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    test_matches = re.findall(r'(?:python3|bash)\s+(tests/[a-zA-Z0-9_\-\.]+)', readme)
    assert len(test_matches) >= 10, f"Poucos testes encontrados no README: {len(test_matches)}"

    missing_tests = []
    for test_rel in test_matches:
        test_path = ROOT / test_rel
        if not test_path.is_file():
            missing_tests.append(test_rel)

    assert not missing_tests, f"Testes documentados no README não existem no disco: {missing_tests}"
    print(f"[PASS] Gate D4 — Todos os {len(test_matches)} testes documentados no README existem no disco")


def test_gate_d5_operational_status_alignment():
    """Gate D5: Documentação operacional (docs/operations/lab.md) não declara como indisponíveis comandos prontos."""
    print("[TEST] Gate D5 — Validando alinhamento factual de interfaces operacionais...")
    lab_md = (ROOT / "docs" / "operations" / "lab.md").read_text(encoding="utf-8")

    assert "A interface reconciliada de produção ainda permanece no roadmap" not in lab_md, (
        "lab.md afirma que production apply está no roadmap, mas ela já está implementada (OPS-07)"
    )
    assert "sister-infra production plan/apply/verify" in lab_md or "OPS-07" in lab_md

    print("[PASS] Gate D5 — Alinhamento de status de interfaces operacionais comprovado")


def main() -> int:
    print("=====================================================================")
    print(" SUÍTE: Alinhamento Factual e Conformidade Documental (OPS-DOC-01)")
    print("=====================================================================")
    try:
        test_gate_d1_no_gateway_in_documentation_bindings()
        test_gate_d2_contract_unification_gateway_domain()
        test_gate_d3_canonical_deployment_alignment()
        test_gate_d4_readme_test_references_exist()
        test_gate_d5_operational_status_alignment()
        print("\n=====================================================================")
        print(" [SUCESSO] Todos os Gates de Alinhamento Documental passaram!")
        print("=====================================================================")
        return 0
    except AssertionError as exc:
        print(f"\n[FALHA] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
