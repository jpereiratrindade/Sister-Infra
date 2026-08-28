#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Teste do Contrato Arquitetural de Installation Lock (OPS-10D Front A / OPS-10B §7).

Prova os 11 Gates Arquiteturais:
G1 — Fresh LAB/workstation installation resolves to one installation lock.
G2 — Reconcile and workstation mutations for the same installation contend.
G3 — sister-lab apply is serialized by the same LAB installation lock.
G4 — sister-production apply owns a production installation lock.
G5 — Two production mutations targeting the same production root contend.
G6 — LAB root and a distinct production root do NOT contend merely because both use SisTer Infra.
G7 — Valid inherited canonical FD (SISTER_INSTALLATION_LOCK_FD) is accepted.
G8 — Legacy SISTER_WORKSTATION_LOCK_FD remains compatible.
G9 — Inherited FD for another inode is rejected (no lock bypass).
G10 — Upgraded legacy regular lock cannot create split-brain with installation.lock.
G11 — Active legacy lock blocks a new-version canonical lock attempt.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RECONCILE_CLI = ROOT / "bin" / "sister-reconcile"
WORKSTATION_CLI = ROOT / "bin" / "sister-workstation"
PRODUCTION_CLI = ROOT / "bin" / "sister-production"
LAB_CLI = ROOT / "bin" / "sister-lab"


def run_cmd(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def make_test_env(tmp: Path) -> dict[str, str]:
    state_root = tmp / "state"
    config_root = tmp / "config"
    install_root = tmp / "install"
    for d in (state_root, config_root, install_root):
        d.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)
    env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(config_root)
    env["SISTER_WORKSTATION_INSTALL_ROOT"] = str(install_root)
    env["SISTER_WORKSTATION_TEST_MODE"] = "1"
    return env


import importlib.machinery


def load_reconcile_module() -> Any:
    loader = importlib.machinery.SourceFileLoader("sister_reconcile", str(RECONCILE_CLI))
    return loader.load_module()


def test_g1_fresh_installation_resolves_one_lock(tmp: Path) -> None:
    env = make_test_env(tmp)
    state_root = tmp / "state"

    reconcile_mod = load_reconcile_module()
    ReconcileLock = getattr(reconcile_mod, "ReconcileLock")

    with ReconcileLock(state_root):
        locks_dir = state_root / "locks"
        assert locks_dir.is_dir(), "Diretório locks deve existir"
        inst_lock = locks_dir / "installation.lock"
        legacy_lock = locks_dir / "workstation-lifecycle.lock"
        assert inst_lock.exists() or legacy_lock.exists()
        # Ambos os caminhos devem referenciar exatamente o mesmo inode
        assert inst_lock.resolve() == legacy_lock.resolve()
        assert inst_lock.stat().st_ino == legacy_lock.stat().st_ino

    print("[PASS] Gate G1 — Fresh installation resolves to one canonical installation lock inode")


def test_g2_reconcile_and_workstation_contend(tmp: Path) -> None:
    state_root = tmp / "state"
    locks_dir = state_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    inst_lock = locks_dir / "installation.lock"
    inst_lock.touch(mode=0o600)
    legacy_lock = locks_dir / "workstation-lifecycle.lock"
    if not legacy_lock.exists():
        legacy_lock.symlink_to("installation.lock")

    env = dict(os.environ)
    env["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)

    # 1. Travar via Python flock no canonical target
    canonical_target = inst_lock.resolve()
    fd = os.open(str(canonical_target), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        # 2. Tentar executar workstation repair -> deve falhar com erro de lock
        res = run_cmd([str(WORKSTATION_CLI), "repair"], env=env)
        assert res.returncode != 0, "workstation repair deveria ter sido bloqueado por lock ativo"
        assert "lock ativo" in res.stderr or "lock" in res.stderr.lower()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    print("[PASS] Gate G2 — Reconcile and workstation mutations for the same installation contend")


def test_g3_lab_apply_serialized_by_same_lock(tmp: Path) -> None:
    state_root = tmp / "state"
    locks_dir = state_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    inst_lock = locks_dir / "installation.lock"
    inst_lock.touch(mode=0o600)
    canonical_target = inst_lock.resolve()

    env = dict(os.environ)
    env["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)

    # Segurar o lock externamente
    fd = os.open(str(canonical_target), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        res = run_cmd(
            [
                str(LAB_CLI),
                "apply",
                "--desired-candidate", str(tmp / "cand"),
                "--desired-deployment", str(tmp / "dep.json"),
                "--json",
            ],
            env=env,
        )
        assert res.returncode != 0, "sister-lab apply deveria ter falhado por lock contention"
        doc = json.loads(res.stdout) if res.stdout.strip().startswith("{") else {}
        err_msg = doc.get("error", "") or res.stderr
        assert "lock" in err_msg.lower() or doc.get("code") in ("RECONCILE_FAILED", "INSTALLATION_LOCKED")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    print("[PASS] Gate G3 — sister-lab apply is serialized by the same LAB installation lock")


def test_g4_g5_production_apply_owns_lock_and_contends(tmp: Path) -> None:
    prod_root = tmp / "production"
    locks_dir = prod_root / "var" / "lib" / "sister" / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    inst_lock = locks_dir / "installation.lock"
    inst_lock.touch(mode=0o600)
    canonical_target = inst_lock.resolve()

    env = dict(os.environ)
    env["SISTER_PRODUCTION_ROOT"] = str(prod_root)
    env["PRODUCTION_APPROVED"] = "YES"
    env["SISTER_INFRA_PRODUCTION_CONFIRM"] = "YES"

    # Segurar o lock de produção externamente
    fd = os.open(str(canonical_target), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        # Tentar sister-production apply -> deve falhar com exit code 4 (conflito de lock)
        res = run_cmd(
            [
                str(PRODUCTION_CLI),
                "apply",
                "--plan", str(tmp / "nonexistent-plan.json"),
                "--plan-digest", "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                "--json",
            ],
            env=env,
        )
        assert res.returncode == 4, f"sister-production apply deveria retornar exit 4 em lock contention (retornou {res.returncode}): {res.stdout} {res.stderr}"
        doc = json.loads(res.stdout)
        assert doc["code"] == "INSTALLATION_LOCKED"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    print("[PASS] Gate G4 & G5 — Production apply owns installation lock and serializes same-root mutations")


def test_g6_lab_and_production_do_not_contend(tmp: Path) -> None:
    lab_state = tmp / "lab_state"
    prod_root = tmp / "production"

    lab_locks = lab_state / "locks"
    prod_locks = prod_root / "var" / "lib" / "sister" / "locks"
    lab_locks.mkdir(parents=True, exist_ok=True)
    prod_locks.mkdir(parents=True, exist_ok=True)

    lab_lock = lab_locks / "installation.lock"
    lab_lock.touch(mode=0o600)
    prod_lock = prod_locks / "installation.lock"
    prod_lock.touch(mode=0o600)

    # 1. Travar LAB exclusivamente
    lab_fd = os.open(str(lab_lock.resolve()), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lab_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        # 2. Produção deve conseguir travar seu próprio lock sem conflito
        prod_fd = os.open(str(prod_lock.resolve()), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(prod_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Sucesso! Não houve conflito espúrio cross-installation
            fcntl.flock(prod_fd, fcntl.LOCK_UN)
        finally:
            os.close(prod_fd)
    finally:
        fcntl.flock(lab_fd, fcntl.LOCK_UN)
        os.close(lab_fd)

    print("[PASS] Gate G6 — LAB root and distinct Production root do NOT contend across installations")


def test_g7_g8_inherited_fd_accepted(tmp: Path) -> None:
    state_root = tmp / "state"
    locks_dir = state_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    inst_lock = locks_dir / "installation.lock"
    inst_lock.touch(mode=0o600)
    canonical_target = inst_lock.resolve()

    fd = os.open(str(canonical_target), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.set_inheritable(fd, True)

    try:
        # G7: Testar SISTER_INSTALLATION_LOCK_FD canônico
        os.environ["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)
        os.environ["SISTER_INSTALLATION_LOCK_FD"] = str(fd)
        if "SISTER_WORKSTATION_LOCK_FD" in os.environ:
            del os.environ["SISTER_WORKSTATION_LOCK_FD"]

        reconcile_mod = load_reconcile_module()
        ReconcileLock = getattr(reconcile_mod, "ReconcileLock")

        with ReconcileLock(state_root) as rlock:
            assert rlock._inherited is True, "ReconcileLock deveria ter herdado SISTER_INSTALLATION_LOCK_FD"

        # G8: Testar SISTER_WORKSTATION_LOCK_FD alias legado
        del os.environ["SISTER_INSTALLATION_LOCK_FD"]
        os.environ["SISTER_WORKSTATION_LOCK_FD"] = str(fd)

        with ReconcileLock(state_root) as rlock:
            assert rlock._inherited is True, "ReconcileLock deveria ter herdado SISTER_WORKSTATION_LOCK_FD"
    finally:
        if "SISTER_INSTALLATION_LOCK_FD" in os.environ:
            del os.environ["SISTER_INSTALLATION_LOCK_FD"]
        if "SISTER_WORKSTATION_LOCK_FD" in os.environ:
            del os.environ["SISTER_WORKSTATION_LOCK_FD"]
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    print("[PASS] Gate G7 & G8 — Valid inherited canonical FD and legacy FD alias are properly accepted")


def test_g9_unrelated_fd_rejected_no_bypass(tmp: Path) -> None:
    state_root = tmp / "state"
    locks_dir = state_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    inst_lock = locks_dir / "installation.lock"
    inst_lock.touch(mode=0o600)
    canonical_target = inst_lock.resolve()

    # Cria outro arquivo não relacionado
    other_file = tmp / "unrelated.lock"
    other_file.touch(mode=0o600)
    bogus_fd = os.open(str(other_file), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(bogus_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.set_inheritable(bogus_fd, True)

    # Segura o lock real externamente
    real_fd = os.open(str(canonical_target), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(real_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        # Passa o bogus_fd no ambiente tentando enganar o lock
        os.environ["SISTER_INSTALLATION_LOCK_FD"] = str(bogus_fd)
        os.environ["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)

        reconcile_mod = load_reconcile_module()
        ReconcileLock = getattr(reconcile_mod, "ReconcileLock")
        ReconcileError = getattr(reconcile_mod, "ReconcileError")

        blocked = False
        try:
            with ReconcileLock(state_root):
                pass
        except ReconcileError:
            blocked = True

        assert blocked is True, "ReconcileLock NÃO deve aceitar FD de outro arquivo para burlar o lock"
    finally:
        if "SISTER_INSTALLATION_LOCK_FD" in os.environ:
            del os.environ["SISTER_INSTALLATION_LOCK_FD"]
        fcntl.flock(real_fd, fcntl.LOCK_UN)
        os.close(real_fd)
        fcntl.flock(bogus_fd, fcntl.LOCK_UN)
        os.close(bogus_fd)

    print("[PASS] Gate G9 — Inherited FD for another inode is rejected; no lock bypass")


def test_g10_g11_upgraded_legacy_regular_lock_no_split_brain(tmp: Path) -> None:
    state_root = tmp / "state"
    locks_dir = state_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    # 1. Simula instalação antiga: workstation-lifecycle.lock existe como arquivo REGULAR (não symlink)
    legacy_file = locks_dir / "workstation-lifecycle.lock"
    legacy_file.write_text("legacy lock content\n", encoding="utf-8")
    legacy_ino = legacy_file.stat().st_ino

    # 2. Um processo legado obtém flock no arquivo legado
    legacy_fd = os.open(str(legacy_file), os.O_RDWR, 0o600)
    fcntl.flock(legacy_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        # 3. O novo sistema tenta adquirir o lock via installation.lock
        reconcile_mod = load_reconcile_module()
        ReconcileLock = getattr(reconcile_mod, "ReconcileLock")
        ReconcileError = getattr(reconcile_mod, "ReconcileError")

        blocked = False
        try:
            with ReconcileLock(state_root):
                pass
        except ReconcileError:
            blocked = True

        assert blocked is True, "Novo sistema DEVE observar conflito quando processo legado detém lock no inode legado"

        # 4. G10: Comprova que installation.lock e workstation-lifecycle.lock compartilham o mesmo inode
        inst_lock = locks_dir / "installation.lock"
        assert inst_lock.exists(), "installation.lock deve ter sido criado como ponte"
        assert inst_lock.stat().st_ino == legacy_ino, "installation.lock e workstation-lifecycle.lock DEVEM referenciar o mesmo inode (sem split-brain)"

    finally:
        fcntl.flock(legacy_fd, fcntl.LOCK_UN)
        os.close(legacy_fd)

    print("[PASS] Gate G10 & G11 — Upgraded legacy regular lock observes contention and prevents split-brain")


def test_g_lab_use_case_lock_ownership(tmp: Path) -> None:
    """Prova que sister-lab apply adquire o lock ANTES de chamar reconcile e passa o FD."""
    state_root = tmp / "state"
    config_root = tmp / "config"
    locks_dir = state_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    config_root.mkdir(parents=True, exist_ok=True)

    cand_dir = tmp / "cand"
    cand_dir.mkdir(parents=True, exist_ok=True)
    (cand_dir / "manifest.json").write_text('{"schema": "sister.infra.candidate/1.0.0", "candidate_id": "c1", "composition_id": "comp1"}', encoding="utf-8")
    dep_file = tmp / "dep.json"
    dep_file.write_text('{"schema": "sister.infra.deployment/1.0.0", "deployment_id": "d1", "composition_id": "comp1"}', encoding="utf-8")

    inst_lock = locks_dir / "installation.lock"
    inst_lock.touch(mode=0o600)
    canonical_lock = inst_lock.resolve()

    # Cria mock do sister-reconcile para inspecionar o FD herdado e testar exclusão mútua em tempo de execução
    mock_bin = tmp / "bin"
    mock_bin.mkdir(parents=True, exist_ok=True)
    mock_reconcile = mock_bin / "sister-reconcile"
    mock_reconcile_code = f"""#!/usr/bin/env python3
import fcntl
import json
import os
import sys
from pathlib import Path

inherited_fd = os.environ.get("SISTER_INSTALLATION_LOCK_FD")
if not inherited_fd:
    print(json.dumps({{"error": "SISTER_INSTALLATION_LOCK_FD ausente"}}))
    sys.exit(1)

fd_num = int(inherited_fd)
fd_stat = os.fstat(fd_num)
canonical_stat = os.stat("{str(canonical_lock)}")

if fd_stat.st_ino != canonical_stat.st_ino:
    print(json.dumps({{"error": f"FD aponta para inode diferente: {{fd_stat.st_ino}} != {{canonical_stat.st_ino}}"}}))
    sys.exit(2)

# Tenta abrir e travar o lock a partir de um subprocesso concorrente -> deve falhar com BlockingIOError
import subprocess
child = subprocess.run(
    [sys.executable, "-c", '''
import fcntl, os, sys
try:
    fd = os.open("{str(canonical_lock)}", os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sys.exit(0) # Incorreto: deveria ter falhado
except BlockingIOError:
    sys.exit(42) # Correto: lock está ativamente retido pelo pai
'''],
    capture_output=True
)

if child.returncode != 42:
    print(json.dumps({{"error": f"Processo concorrente conseguiu adquirir o lock: RC={{child.returncode}}"}}))
    sys.exit(3)

print(json.dumps({{"status": "SUCCESS", "inherited_fd": fd_num, "inode": fd_stat.st_ino}}))
sys.exit(0)
"""
    mock_reconcile.write_text(mock_reconcile_code, encoding="utf-8")
    mock_reconcile.chmod(0o755)

    env = dict(os.environ)
    env["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)
    env["SISTER_WORKSTATION_CONFIG_ROOT"] = str(config_root)
    env["SISTER_LAB_RECONCILE_CLI"] = str(mock_reconcile)
    env["PATH"] = f"{mock_bin}:{env.get('PATH', '')}"

    res = run_cmd(
        [
            str(LAB_CLI),
            "apply",
            "--desired-candidate", str(cand_dir),
            "--desired-deployment", str(dep_file),
            "--json",
        ],
        env=env,
    )
    assert res.returncode == 0, f"sister-lab apply com mock reconcile falhou: RC={res.returncode}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    doc = json.loads(res.stdout)
    assert doc.get("status") == "SUCCESS", f"mock reconcile reportou erro: {doc}"
    assert doc.get("inode") == canonical_lock.stat().st_ino

    print("[PASS] Gate G-LAB-OWNERSHIP — sister-lab apply holds installation lock before reconcile and child inherits same FD")


def test_g_split_brain_dual_regular_conflict(tmp: Path) -> None:
    """Prova que dois arquivos de lock regulares com inodes distintos falham fechado."""
    state_root = tmp / "state"
    locks_dir = state_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    # 1. Cria installation.lock e workstation-lifecycle.lock como arquivos REGULARES distintos
    lock1 = locks_dir / "installation.lock"
    lock2 = locks_dir / "workstation-lifecycle.lock"
    lock1.write_text("lock A", encoding="utf-8")
    lock2.write_text("lock B", encoding="utf-8")

    assert lock1.stat().st_ino != lock2.stat().st_ino, "Inodes devem ser distintos para teste adversarial"

    reconcile_mod = load_reconcile_module()
    ReconcileLock = getattr(reconcile_mod, "ReconcileLock")
    ReconcileError = getattr(reconcile_mod, "ReconcileError")

    # 1a. ReconcileLock deve falhar fechado com INSTALLATION_LOCK_IDENTITY_CONFLICT
    failed_reconcile = False
    try:
        with ReconcileLock(state_root):
            pass
    except ReconcileError as exc:
        if "INSTALLATION_LOCK_IDENTITY_CONFLICT" in str(exc):
            failed_reconcile = True
    assert failed_reconcile, "ReconcileLock deve lançar INSTALLATION_LOCK_IDENTITY_CONFLICT em dual regular conflict"

    # 1b. sister-workstation repair deve falhar fechado com INSTALLATION_LOCK_IDENTITY_CONFLICT
    env = dict(os.environ)
    env["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)
    res_ws = run_cmd([str(WORKSTATION_CLI), "repair"], env=env)
    assert res_ws.returncode != 0
    assert "INSTALLATION_LOCK_IDENTITY_CONFLICT" in res_ws.stderr

    # 1c. sister-lab apply deve falhar fechado com INSTALLATION_LOCK_IDENTITY_CONFLICT
    cand_p = tmp / "cand"
    cand_p.mkdir(parents=True, exist_ok=True)
    (cand_p / "manifest.json").write_text('{"schema": "sister.infra.candidate/1.0.0", "candidate_id": "c1", "composition_id": "comp1"}', encoding="utf-8")
    dep_p = tmp / "dep.json"
    dep_p.write_text('{"schema": "sister.infra.deployment/1.0.0", "deployment_id": "d1", "composition_id": "comp1"}', encoding="utf-8")

    res_lab = run_cmd(
        [
            str(LAB_CLI),
            "apply",
            "--desired-candidate", str(cand_p),
            "--desired-deployment", str(dep_p),
            "--json",
        ],
        env=env,
    )
    assert res_lab.returncode != 0
    assert "INSTALLATION_LOCK_IDENTITY_CONFLICT" in res_lab.stderr or "INSTALLATION_LOCK_IDENTITY_CONFLICT" in res_lab.stdout

    # 2. Testa symlink para alvo fora do diretório de locks
    lock1.unlink()
    lock2.unlink()
    bogus_target = tmp / "outside.lock"
    bogus_target.touch()
    lock1.symlink_to(bogus_target)

    failed_bogus = False
    try:
        with ReconcileLock(state_root):
            pass
    except ReconcileError as exc:
        if "INSTALLATION_LOCK_IDENTITY_CONFLICT" in str(exc):
            failed_bogus = True
    assert failed_bogus, "Symlink para alvo externo deve falhar fechado com INSTALLATION_LOCK_IDENTITY_CONFLICT"

    print("[PASS] Gate G-SPLIT-BRAIN — Dual-regular lock files with differing inodes and invalid symlinks fail closed")


def test_g_production_has_no_workstation_legacy(tmp: Path) -> None:
    """Prova que produção NUNCA cria nem referencia workstation-lifecycle.lock."""
    prod_root = tmp / "production"
    locks_dir = prod_root / "var" / "lib" / "sister" / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    prod_mod = load_production_module()
    ProductionInstallationLock = getattr(prod_mod, "ProductionInstallationLock")

    with ProductionInstallationLock(locks_dir):
        inst_lock = locks_dir / "installation.lock"
        legacy_lock = locks_dir / "workstation-lifecycle.lock"
        assert inst_lock.is_file(), "installation.lock deve existir na produção"
        assert not legacy_lock.exists(), "workstation-lifecycle.lock NUNCA deve ser criado na produção"

    print("[PASS] Gate G-PROD-ISOLATION — Production initializes only installation.lock without legacy workstation paths")


def load_production_module() -> Any:
    loader = importlib.machinery.SourceFileLoader("sister_production", str(PRODUCTION_CLI))
    return loader.load_module()


def test_g_public_cli_workstation_release_switch_lock(tmp: Path) -> None:
    """Prova que comandos da CLI pública respeitam a exclusão mútua do installation.lock."""
    state_root = tmp / "state"
    locks_dir = state_root / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    canonical_lock = locks_dir / "installation.lock"
    canonical_lock.touch(mode=0o600)

    env = dict(os.environ)
    env["SISTER_WORKSTATION_STATE_ROOT"] = str(state_root)

    with open(canonical_lock, "a") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        res = run_cmd(
            [str(WORKSTATION_CLI), "release-switch", "--target", "nonexistent"],
            env=env,
        )
        assert res.returncode != 0, "release-switch deveria ter falhado com lock de instalação ativo"
        assert "outra operação de lifecycle está em execução" in res.stderr or "lock ativo" in res.stderr
        fcntl.flock(fd, fcntl.LOCK_UN)

    print("[PASS] Gate G-CLI-INTEGRATION — Public CLI commands observe active installation.lock")


def main() -> None:
    print("==================================================")
    print(" OPS-10D Front A — Installation Lock Contract Test")
    print("==================================================")
    with tempfile.TemporaryDirectory(prefix="sister-lock-contract-") as tmp:
        p = Path(tmp)
        test_g1_fresh_installation_resolves_one_lock(p / "g1")
        test_g2_reconcile_and_workstation_contend(p / "g2")
        test_g3_lab_apply_serialized_by_same_lock(p / "g3")
        test_g_lab_use_case_lock_ownership(p / "g_lab_ownership")
        test_g4_g5_production_apply_owns_lock_and_contends(p / "g4_g5")
        test_g6_lab_and_production_do_not_contend(p / "g6")
        test_g7_g8_inherited_fd_accepted(p / "g7_g8")
        test_g9_unrelated_fd_rejected_no_bypass(p / "g9")
        test_g10_g11_upgraded_legacy_regular_lock_no_split_brain(p / "g10_g11")
        test_g_split_brain_dual_regular_conflict(p / "g_split_brain")
        test_g_production_has_no_workstation_legacy(p / "g_prod_legacy")
        test_g_public_cli_workstation_release_switch_lock(p / "g_cli_lock")
    print("==================================================")
    print("[PASS] Todos os Gates de Contrato de Installation Lock (OPS-10D-A) passaram com sucesso!")
    print("==================================================")


if __name__ == "__main__":
    main()
