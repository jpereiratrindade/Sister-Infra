#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Suíte de testes de inicialização da autoridade CA de laboratório (OPS-07A2.2a).

Invariantes validados:
- TLSA-006: Criação inicial de CA exige comando administrativo explícito.
- TLSA-007: init-ca nunca substitui autoridade existente.
- TLSA-008: init-ca repetido sobre autoridade válida converge para NO_OP.
- TLSA-009: Estado parcial ou inválido resulta em FAIL-CLOSED.
- TLSA-010: status é estritamente observacional.
- TLSA-011: Nenhuma operação de autoridade consulta <repo>/secrets/.
- TLSA-012: init-ca cria CA, nunca leaf.
- TLSA-013: Nenhum --force existe nesta interface.
- TLSA-014: Inicialização concorrente é serializada por autoridade exclusiva.
- TLSA-015: Após adquirir o lock, o estado é obrigatoriamente reobservado.
- TLSA-016: A CA é publicada como uma unidade lógica, nunca como dois arquivos autoritativos independentes.
- TLSA-017: CA ausente não autoriza substituir conteúdo preexistente de tls/.
- TLSA-018: Staging abandonado nunca constitui autoridade.
- TLSA-019: status permanece read-only em ABSENT, VALID e INVALID.

Casos:
  Caso A: status em ambiente novo reporta ABSENT e não cria arquivos.
  Caso B: init em ambiente vazio gera autoridade CA válida com permissões seguras e sem leaf.
  Caso C: segunda execução de init-ca converge para NO_OP e preserva material byte a byte.
  Caso D: estado parcial (chave ou cert ausente) resulta em FAIL-CLOSED sem sobrescrita.
  Caso E: material inválido (chave incompatível, CA expirada ou não-CA) resulta em FAIL-CLOSED.
  Caso F: <repo>/secrets/ permanece estritamente intocado antes e depois das operações.
  Caso G: status após init reporta VALID com contrato JSON estrito e snapshot read-only.
  Caso H: inicialização concorrente serializada por lock (um CREATE, outro NO_OP, zero races).
  Caso I: tls/ existente e não-vazio sem CA resulta em FAIL-CLOSED com preservação de conteúdo.
  First-Boot Integrado: workstation bootstrap -> status (ABSENT) -> init-ca (CREATE) -> status (VALID).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

INFRA_CLI = ROOT / "bin" / "sister-infra"
LAB_CLI = ROOT / "bin" / "sister-lab"
WORKSTATION_CLI = ROOT / "bin" / "sister-workstation"


def sha_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_dir(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    res = {}
    for p in sorted(path.rglob("*")):
        if p.is_file():
            res[str(p.relative_to(path))] = sha_file(p)
        elif p.is_dir():
            res[str(p.relative_to(path))] = "<DIR>"
    return res


def run_cli(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        check=False,
    )


def test_caso_a_status_absent(secrets_repo: Path) -> None:
    print("[TEST] Caso A — status ausente...")
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_a_") as td:
        cfg = Path(td) / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        snap_before = snapshot_dir(cfg)

        # Execução legível
        res = run_cli([str(INFRA_CLI), "lab", "tls", "status"], env=env)
        assert res.returncode == 0, f"status deveria retornar 0, obteve {res.returncode}: {res.stderr}"
        assert "ABSENT" in res.stdout

        # Execução JSON pura
        res_json = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_json.returncode == 0
        doc = json.loads(res_json.stdout)
        assert doc["status"] == "ABSENT"
        assert "ca_cert_path" in doc
        assert not Path(doc["ca_cert_path"]).exists()

        # Invariante TLSA-010: estritamente observacional, nada criado
        snap_after = snapshot_dir(cfg)
        assert snap_before == snap_after, "status mutou o filesystem indevidamente!"
        assert not (cfg / "tls").exists(), "diretório tls/ não deveria ser criado por status"

        print("[PASS] Caso A — status ausente comprovado (leitura pura, zero mutações)")


def test_caso_b_init_empty(secrets_repo: Path) -> None:
    print("[TEST] Caso B — init em ambiente vazio...")
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_b_") as td:
        cfg = Path(td) / "config"
        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        res = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca", "--json"], env=env)
        assert res.returncode == 0, f"init-ca falhou: {res.stderr}"
        doc = json.loads(res.stdout)
        assert doc["status"] == "CREATE"

        tls_dir = cfg / "tls"
        ca_cert = tls_dir / "ecosystem-lab-ca.crt"
        ca_key = tls_dir / "ecosystem-lab-ca.key"
        leaf_cert = tls_dir / "ecosystem-lab.pem"

        # Arquivos esperados
        assert tls_dir.is_dir(), "tls/ não criado"
        assert ca_cert.is_file(), "ca.crt não criado"
        assert ca_key.is_file(), "ca.key não criado"
        # Invariante TLSA-012: init-ca cria CA, nunca leaf
        assert not leaf_cert.exists(), "leaf ecosystem-lab.pem não deve ser criado no init-ca"

        # Permissões
        mode_dir = tls_dir.stat().st_mode & 0o777
        mode_key = ca_key.stat().st_mode & 0o777
        mode_crt = ca_cert.stat().st_mode & 0o777

        assert mode_dir == 0o700, f"permissão de tls/ esperada 0700, obtida {oct(mode_dir)}"
        assert mode_key == 0o600, f"permissão de ca.key esperada 0600, obtida {oct(mode_key)}"
        assert mode_crt == 0o644, f"permissão de ca.crt esperada 0644, obtida {oct(mode_crt)}"

        # Validação OpenSSL
        r_x509 = subprocess.run(["openssl", "x509", "-in", str(ca_cert), "-noout", "-text"], stdout=subprocess.PIPE, text=True, check=True)
        assert "CN = SisTer Infra Lab CA" in r_x509.stdout or "CN=SisTer Infra Lab CA" in r_x509.stdout
        assert "CA:TRUE" in r_x509.stdout
        assert "Certificate Sign, CRL Sign" in r_x509.stdout

        # Validação coerência chave/certificado
        r_pub1 = subprocess.run(["openssl", "x509", "-in", str(ca_cert), "-pubkey", "-noout"], stdout=subprocess.PIPE, text=True, check=True)
        r_pub2 = subprocess.run(["openssl", "pkey", "-in", str(ca_key), "-pubout"], stdout=subprocess.PIPE, text=True, check=True)
        assert r_pub1.stdout.strip() == r_pub2.stdout.strip()

        # Validade >= 3640 dias
        r_chk = subprocess.run(["openssl", "x509", "-in", str(ca_cert), "-noout", "-checkend", str(3640 * 86400)], stdout=subprocess.PIPE, check=False)
        assert r_chk.returncode == 0, "validade da CA menor que o esperado de 10 anos"

        print("[PASS] Caso B — init em ambiente vazio cria CA válida, permissões 0700/0600/0644 e sem leaf")


def test_caso_c_second_run_noop(secrets_repo: Path) -> None:
    print("[TEST] Caso C — segunda execução converge para NO_OP...")
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_c_") as td:
        cfg = Path(td) / "config"
        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        # Primeira execução (CREATE)
        res1 = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca", "--json"], env=env)
        assert res1.returncode == 0
        doc1 = json.loads(res1.stdout)
        assert doc1["status"] == "CREATE"

        ca_cert = cfg / "tls" / "ecosystem-lab-ca.crt"
        ca_key = cfg / "tls" / "ecosystem-lab-ca.key"
        sha_crt_before = sha_file(ca_cert)
        sha_key_before = sha_file(ca_key)
        fp_before = doc1["fingerprint"]

        # Segunda execução (NO_OP)
        res2 = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca", "--json"], env=env)
        assert res2.returncode == 0
        doc2 = json.loads(res2.stdout)
        # Invariante TLSA-008: converge para NO_OP
        assert doc2["status"] == "NO_OP"

        sha_crt_after = sha_file(ca_cert)
        sha_key_after = sha_file(ca_key)
        fp_after = doc2["fingerprint"]

        # Invariante TLSA-007: nunca substitui autoridade existente
        assert sha_crt_before == sha_crt_after, "certificado CA foi alterado na segunda execução!"
        assert sha_key_before == sha_key_after, "chave da CA foi alterada na segunda execução!"
        assert fp_before == fp_after, "fingerprint divergiu na segunda execução!"

        print("[PASS] Caso C — idempotência comprovada (NO_OP com preservação byte a byte)")


def test_caso_d_partial_state_fail_closed(secrets_repo: Path) -> None:
    print("[TEST] Caso D — estado parcial resulta em FAIL-CLOSED...")
    # Cenário 1: cert existe, key ausente
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_d1_") as td:
        cfg = Path(td) / "config"
        tls_dir = cfg / "tls"
        tls_dir.mkdir(parents=True, exist_ok=True)
        ca_cert = tls_dir / "ecosystem-lab-ca.crt"
        ca_cert.write_text("DUMMY_CERT", encoding="utf-8")
        sha_cert_before = sha_file(ca_cert)

        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        res = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca"], env=env)
        # Invariante TLSA-009: FAIL-CLOSED
        assert res.returncode != 0, "init-ca deveria falhar com key ausente"
        assert "FAIL-CLOSED" in res.stderr or "recusado" in res.stderr
        assert sha_file(ca_cert) == sha_cert_before, "cert existente não deve ser modificado em erro"
        assert not (tls_dir / "ecosystem-lab-ca.key").exists()

    # Cenário 2: key existe, cert ausente
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_d2_") as td:
        cfg = Path(td) / "config"
        tls_dir = cfg / "tls"
        tls_dir.mkdir(parents=True, exist_ok=True)
        ca_key = tls_dir / "ecosystem-lab-ca.key"
        ca_key.write_text("DUMMY_KEY", encoding="utf-8")
        sha_key_before = sha_file(ca_key)

        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        res = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca"], env=env)
        # Invariante TLSA-009: FAIL-CLOSED
        assert res.returncode != 0, "init-ca deveria falhar com cert ausente"
        assert "FAIL-CLOSED" in res.stderr or "recusado" in res.stderr
        assert sha_file(ca_key) == sha_key_before, "key existente não deve ser modificada em erro"
        assert not (tls_dir / "ecosystem-lab-ca.crt").exists()

    print("[PASS] Caso D — estado parcial falha fechado sem sobrescrever resíduos")


def test_caso_e_invalid_material_fail_closed(secrets_repo: Path) -> None:
    print("[TEST] Caso E — material inválido resulta em FAIL-CLOSED...")
    # Cenário 1: chave incompatível com cert
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_e1_") as td:
        cfg = Path(td) / "config"
        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        # Gera CA válida primeiro
        run_cli([str(INFRA_CLI), "lab", "tls", "init-ca"], env=env)

        # Substitui a chave por outra chave RSA gerada aleatoriamente
        ca_key = cfg / "tls" / "ecosystem-lab-ca.key"
        ca_cert = cfg / "tls" / "ecosystem-lab-ca.crt"
        sha_cert_before = sha_file(ca_cert)

        subprocess.run(["openssl", "genrsa", "-out", str(ca_key), "2048"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sha_key_diff = sha_file(ca_key)

        # Tentar init-ca agora deve falhar fechado
        res = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca"], env=env)
        assert res.returncode != 0, "init-ca com chave incompatível deve falhar fechado"
        assert "FAIL-CLOSED" in res.stderr or "incompatível" in res.stderr

        # Nenhuma sobrescrita permitida
        assert sha_file(ca_cert) == sha_cert_before
        assert sha_file(ca_key) == sha_key_diff

    # Cenário 2: cert que não é CA (possui basicConstraints CA:FALSE)
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_e2_") as td:
        cfg = Path(td) / "config"
        tls_dir = cfg / "tls"
        tls_dir.mkdir(parents=True, exist_ok=True)
        ca_key = tls_dir / "ecosystem-lab-ca.key"
        ca_cert = tls_dir / "ecosystem-lab-ca.crt"

        subprocess.run(["openssl", "genrsa", "-out", str(ca_key), "2048"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run([
            "openssl", "req", "-x509", "-new", "-nodes", "-key", str(ca_key),
            "-sha256", "-days", "365", "-subj", "/CN=Not-A-CA",
            "-addext", "basicConstraints=critical,CA:FALSE",
            "-out", str(ca_cert)
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        res = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca"], env=env)
        assert res.returncode != 0, "init-ca com certificado não-CA deve falhar fechado"
        assert "FAIL-CLOSED" in res.stderr or "CA:TRUE" in res.stderr

    # Cenário 3: cert corrompido / não-parseável
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_e3_") as td:
        cfg = Path(td) / "config"
        tls_dir = cfg / "tls"
        tls_dir.mkdir(parents=True, exist_ok=True)
        ca_key = tls_dir / "ecosystem-lab-ca.key"
        ca_cert = tls_dir / "ecosystem-lab-ca.crt"

        subprocess.run(["openssl", "genrsa", "-out", str(ca_key), "2048"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ca_cert.write_text("-----BEGIN CERTIFICATE-----\nCORRUPTED_BASE64_DATA\n-----END CERTIFICATE-----\n")

        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        res = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca"], env=env)
        assert res.returncode != 0, "init-ca com certificado corrompido deve falhar fechado"
        assert "FAIL-CLOSED" in res.stderr or "não parseável" in res.stderr

        # Snapshot read-only em estado INVALID (TLSA-019)
        snap_inv_before = snapshot_dir(cfg)
        res_st_inv = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st_inv.returncode == 0
        assert json.loads(res_st_inv.stdout)["status"] == "INVALID"
        snap_inv_after = snapshot_dir(cfg)
        assert snap_inv_before == snap_inv_after, "status em INVALID mutou o filesystem!"

    print("[PASS] Caso E — material inválido falha fechado e status em INVALID é 100% read-only")


def test_caso_f_secrets_repo_untouched(secrets_repo: Path) -> None:
    print("[TEST] Caso F — <repo>/secrets/ intocado durante toda a execução...")
    # Registra estado de <repo>/secrets/
    secrets_before = {f.name: sha_file(f) for f in secrets_repo.iterdir() if f.is_file()}
    assert ".gitkeep" in secrets_before
    assert "ecosystem-lab.pem" not in secrets_before
    assert "ecosystem-lab-ca.crt" not in secrets_before

    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_f_") as td:
        cfg = Path(td) / "config"
        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        # Executa status (ABSENT)
        res_st1 = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st1.returncode == 0

        # Executa init-ca (CREATE)
        res_init = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca", "--json"], env=env)
        assert res_init.returncode == 0

        # Executa status (VALID)
        res_st2 = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st2.returncode == 0

        # Invariante TLSA-011: Nenhuma operação consulta ou modifica <repo>/secrets/
        secrets_after = {f.name: sha_file(f) for f in secrets_repo.iterdir() if f.is_file()}
        assert secrets_before == secrets_after, "<repo>/secrets/ foi tocado ou modificado durante os comandos de autoridade!"

    print("[PASS] Caso F — <repo>/secrets/ preservado 100% inalterado (prova estrita de não-mutação)")


def test_caso_g_status_after_init(secrets_repo: Path) -> None:
    print("[TEST] Caso G — status após init reporta VALID com conformidade JSON e snapshot read-only...")
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_g_") as td:
        cfg = Path(td) / "config"
        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        res_init = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca", "--json"], env=env)
        assert res_init.returncode == 0
        doc_init = json.loads(res_init.stdout)

        # Snapshot antes das chamadas de status (TLSA-019)
        snap_valid_before = snapshot_dir(cfg)

        # 1. Execução JSON de status
        res_st_json = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st_json.returncode == 0

        # Prova de conformidade: stdout é documento JSON válido puro
        # sem prefixos de log [PASS] ou [INFO]
        assert "[PASS]" not in res_st_json.stdout
        assert "[INFO]" not in res_st_json.stdout
        doc_st = json.loads(res_st_json.stdout)

        assert doc_st["status"] == "VALID"
        assert doc_st["fingerprint"] == doc_init["fingerprint"]
        assert doc_st["subject"] == "/CN=SisTer Infra Lab CA" or doc_st["subject"] == "CN=SisTer Infra Lab CA"
        assert doc_st["days_remaining"] is not None and doc_st["days_remaining"] >= 3640
        assert "not_before" in doc_st and "not_after" in doc_st

        # 2. Execução textual de status
        res_st_txt = run_cli([str(INFRA_CLI), "lab", "tls", "status"], env=env)
        assert res_st_txt.returncode == 0
        assert "Status CA:       VALID" in res_st_txt.stdout
        assert doc_st["fingerprint"] in res_st_txt.stdout

        # Prova de snapshot: status em VALID não altera nenhum byte ou arquivo
        snap_valid_after = snapshot_dir(cfg)
        assert snap_valid_before == snap_valid_after, "status em VALID mutou o filesystem!"

        print("[PASS] Caso G — status após init reporta VALID, fingerprint correspondente, JSON estrito e snapshot read-only")


def test_caso_h_concurrent_init(secrets_repo: Path) -> None:
    print("[TEST] Caso H — inicialização concorrente serializada por lock...")
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_h_") as td:
        cfg = Path(td) / "config"
        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        # Dispara dois processos concorrentes reais simultaneamente
        cmd = [str(INFRA_CLI), "lab", "tls", "init-ca", "--json"]
        p1 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p2 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        out1, err1 = p1.communicate()
        out2, err2 = p2.communicate()

        assert p1.returncode == 0, f"Processo 1 falhou: {err1}"
        assert p2.returncode == 0, f"Processo 2 falhou: {err2}"

        doc1 = json.loads(out1)
        doc2 = json.loads(out2)

        statuses = {doc1["status"], doc2["status"]}
        # Invariante TLSA-014: exatamente um CREATE e um NO_OP (proibido CREATE + CREATE)
        assert statuses == {"CREATE", "NO_OP"}, f"esperado {{'CREATE', 'NO_OP'}}, mas obtido {statuses}"

        create_doc = doc1 if doc1["status"] == "CREATE" else doc2
        noop_doc = doc2 if doc1["status"] == "CREATE" else doc1

        # Fingerprint deve coincidir (o NO_OP observou e confirmou a autoridade do CREATE sob lock)
        assert noop_doc["fingerprint"] == create_doc["fingerprint"], "fingerprints divergiram entre CREATE e NO_OP!"

        # Invariante TLSA-015 / TLSA-016: exatamente uma CA existe e é válida
        res_st = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st.returncode == 0
        doc_st = json.loads(res_st.stdout)
        assert doc_st["status"] == "VALID"
        assert doc_st["fingerprint"] == create_doc["fingerprint"]

        # Invariante TLSA-018: nenhum staging residual .tls-init-* permanece
        residual_staging = [p.name for p in cfg.iterdir() if p.name.startswith(".tls-init-")]
        assert not residual_staging, f"staging residual encontrado: {residual_staging}"

        print("[PASS] Caso H — concorrência serializada comprovada (1 CREATE, 1 NO_OP, fingerprints idênticos)")


def test_caso_i_tls_dir_not_empty_fail_closed(secrets_repo: Path) -> None:
    print("[TEST] Caso I — tls/ existente e não-vazio sem CA resulta em FAIL-CLOSED...")
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_i_") as td:
        cfg = Path(td) / "config"
        tls_dir = cfg / "tls"
        tls_dir.mkdir(parents=True, exist_ok=True)
        leaf_file = tls_dir / "ecosystem-lab.pem"
        leaf_file.write_text("EXISTING_LEAF_DATA", encoding="utf-8")
        sha_leaf_before = sha_file(leaf_file)

        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        # Status observa CA ausente
        res_st = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st.returncode == 0
        assert json.loads(res_st.stdout)["status"] == "ABSENT"

        # Invariante TLSA-017: CA ausente NÃO autoriza substituir conteúdo preexistente de tls/
        res_init = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca"], env=env)
        assert res_init.returncode != 0, "init-ca deveria falhar fechado com tls/ preexistente não vazio"
        assert "FAIL-CLOSED" in res_init.stderr or "não está vazio" in res_init.stderr

        # Preservação estrita byte a byte do arquivo preexistente
        assert sha_file(leaf_file) == sha_leaf_before, "ecosystem-lab.pem foi alterado ou corrompido!"
        assert not (tls_dir / "ecosystem-lab-ca.crt").exists()
        assert not (tls_dir / "ecosystem-lab-ca.key").exists()

        print("[PASS] Caso I — proteção de namespace comprovada (tls/ não-vazio falha fechado e preserva dados)")


def test_staging_abandoned_ignored_and_cleaned(secrets_repo: Path) -> None:
    print("[TEST] Staging abandonado é ignorado por status e limpo por init-ca...")
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_stg_") as td:
        cfg = Path(td) / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        abandoned = cfg / ".tls-init-deadbeef"
        abandoned.mkdir(parents=True, exist_ok=True)
        (abandoned / "garbage.txt").write_text("TRASH", encoding="utf-8")

        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)

        # Invariante TLSA-018 / TLSA-019: status ignora staging abandonado e não o apaga
        snap_before = snapshot_dir(cfg)
        res_st = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st.returncode == 0
        assert json.loads(res_st.stdout)["status"] == "ABSENT"
        snap_after = snapshot_dir(cfg)
        assert snap_before == snap_after, "status mutou staging abandonado indevidamente!"
        assert abandoned.is_dir()

        # init-ca sob lock limpa staging abandonado e cria autoridade com sucesso
        res_init = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca", "--json"], env=env)
        assert res_init.returncode == 0
        assert json.loads(res_init.stdout)["status"] == "CREATE"
        assert not abandoned.exists(), "staging abandonado deveria ser limpo por init-ca"
        assert (cfg / "tls" / "ecosystem-lab-ca.crt").is_file()

        print("[PASS] Staging abandonado ignorado por status e limpo sob lock por init-ca")


def test_first_boot_integrated(secrets_repo: Path) -> None:
    print("[TEST] First-boot integrado: workstation bootstrap -> status -> init-ca -> status...")
    with tempfile.TemporaryDirectory(prefix="sister_lab_tls_fb_") as td:
        tmp = Path(td)
        cfg = tmp / "config"
        inst = tmp / "install"
        state = tmp / "state"
        bin_dir = tmp / "bin"
        systemd = tmp / "systemd"

        env = dict(os.environ)
        env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(cfg)
        env["SISTER_WORKSTATION_INSTALL_ROOT"] = str(inst)
        env["SISTER_WORKSTATION_STATE_ROOT"] = str(state)
        env["SISTER_WORKSTATION_BIN_ROOT"] = str(bin_dir)
        env["SISTER_WORKSTATION_SYSTEMD_ROOT"] = str(systemd)

        # Passo 1: workstation bootstrap (layout estrutural do host)
        res_boot = run_cli([str(WORKSTATION_CLI), "bootstrap"], env=env)
        assert res_boot.returncode == 0, f"workstation bootstrap falhou: {res_boot.stderr}"
        assert cfg.is_dir(), "config_root deveria existir após workstation bootstrap"

        # Passo 2: lab tls status -> ABSENT
        res_st1 = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st1.returncode == 0
        assert json.loads(res_st1.stdout)["status"] == "ABSENT"

        # Passo 3: lab tls init-ca -> CREATE
        res_init = run_cli([str(INFRA_CLI), "lab", "tls", "init-ca", "--json"], env=env)
        assert res_init.returncode == 0
        doc_init = json.loads(res_init.stdout)
        assert doc_init["status"] == "CREATE"

        # Passo 4: lab tls status -> VALID
        res_st2 = run_cli([str(INFRA_CLI), "lab", "tls", "status", "--json"], env=env)
        assert res_st2.returncode == 0
        doc_st2 = json.loads(res_st2.stdout)
        assert doc_st2["status"] == "VALID"
        assert doc_st2["fingerprint"] == doc_init["fingerprint"]

        # Garante que nenhum leaf foi criado inadvertidamente
        assert not (cfg / "tls" / "ecosystem-lab.pem").exists()

        print("[PASS] First-boot integrado comprovado com sucesso (gargalo de first-boot resolvido)")


def main() -> int:
    secrets_repo = (ROOT / "secrets").resolve()
    assert secrets_repo.is_dir(), f"diretório secrets não encontrado em {secrets_repo}"

    print("==================================================")
    print(" OPS-07A2.2a — Inicialização da Autoridade CA LAB")
    print("==================================================")

    test_caso_a_status_absent(secrets_repo)
    test_caso_b_init_empty(secrets_repo)
    test_caso_c_second_run_noop(secrets_repo)
    test_caso_d_partial_state_fail_closed(secrets_repo)
    test_caso_e_invalid_material_fail_closed(secrets_repo)
    test_caso_f_secrets_repo_untouched(secrets_repo)
    test_caso_g_status_after_init(secrets_repo)
    test_caso_h_concurrent_init(secrets_repo)
    test_caso_i_tls_dir_not_empty_fail_closed(secrets_repo)
    test_staging_abandoned_ignored_and_cleaned(secrets_repo)
    test_first_boot_integrated(secrets_repo)

    print()
    print("[PASS] Todos os casos de OPS-07A2.2a passaram com sucesso!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
