#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

INFRA_ROOT = Path(__file__).resolve().parents[1]
INFRA_CLI = INFRA_ROOT / "bin" / "sister-infra"
LAB_CLI = INFRA_ROOT / "bin" / "sister-lab"

def write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)

def run(cmd: list[str], env: dict[str, str], expect: int = 0) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if proc.returncode != expect:
        raise AssertionError(
            f"comando retornou {proc.returncode}, esperado {expect}\n"
            f"CMD: {cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc

def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

def main() -> int:
    assert LAB_CLI.is_file(), f"sister-lab ausente: {LAB_CLI}"

    with tempfile.TemporaryDirectory(prefix="sister-lab-ux-test-") as td:
        root = Path(td)
        cfg = root / "config"
        cfg.mkdir()
        tmp_root = root / "tmp"
        tmp_root.mkdir()
        logs = root / "logs"
        logs.mkdir()

        composition = cfg / "composition.json"
        deployment = cfg / "deployment.json"
        composition.write_text('{"schema":"fixture.composition"}\n', encoding="utf-8")
        deployment.write_text('{"schema":"fixture.deployment"}\n', encoding="utf-8")

        candidate_log = logs / "candidate.jsonl"
        reconcile_log = logs / "reconcile.jsonl"

        fake_candidate = root / "fake-candidate"
        write_exec(
            fake_candidate,
            """#!/usr/bin/env python3
import json, os
from pathlib import Path
import sys
args = sys.argv[1:]
log = Path(os.environ["OPS06_CANDIDATE_LOG"])
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"args": args}) + "\\n")
if os.environ.get("OPS06_CANDIDATE_FAIL") == "1":
    print("fixture candidate failure", file=sys.stderr)
    raise SystemExit(7)
assert args[0] == "create"
out = Path(args[args.index("--out") + 1])
out.mkdir(parents=True)
(out / "manifest.json").write_text('{"schema":"fixture.candidate"}\\n', encoding="utf-8")
print("candidate-noise-that-must-not-pollute-json")
""",
        )

        fake_reconcile = root / "fake-reconcile"
        write_exec(
            fake_reconcile,
            """#!/usr/bin/env python3
import json, os
from pathlib import Path
import sys
args = sys.argv[1:]
log = Path(os.environ["OPS06_RECONCILE_LOG"])
candidate = args[args.index("--desired-candidate") + 1]
deployment = args[args.index("--desired-deployment") + 1]
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "args": args,
        "candidate": candidate,
        "candidate_exists_during_reconcile": Path(candidate).exists(),
        "deployment": deployment,
    }) + "\\n")
print(json.dumps({
    "schema": "fixture.reconcile",
    "command": args[0],
    "candidate": candidate,
    "deployment": deployment,
}, sort_keys=True))
raise SystemExit(int(os.environ.get("OPS06_RECONCILE_RC", "0")))
""",
        )

        env = os.environ.copy()
        env.update(
            {
                "SISTER_WORKSTATION_CONFIG_ROOT": str(cfg),
                "SISTER_LAB_TMPDIR": str(tmp_root),
                "SISTER_LAB_CANDIDATE_CLI": str(fake_candidate),
                "SISTER_LAB_RECONCILE_CLI": str(fake_reconcile),
                "OPS06_CANDIDATE_LOG": str(candidate_log),
                "OPS06_RECONCILE_LOG": str(reconcile_log),
            }
        )

        res = run([str(INFRA_CLI), "lab", "plan", "--json"], env)
        parsed = json.loads(res.stdout)
        assert parsed["schema"] == "fixture.reconcile"
        rec = read_jsonl(reconcile_log)[-1]
        assert rec["args"][0] == "plan"
        assert "--mode" in rec["args"] and "lab" in rec["args"]
        assert rec["candidate_exists_during_reconcile"] is True
        assert Path(rec["deployment"]) == deployment.resolve()
        assert not Path(rec["candidate"]).exists()
        assert not list(tmp_root.iterdir())
        print("[PASS] Gate A — zero-argument lab plan + cleanup")

        res = run([str(INFRA_CLI), "lab", "apply", "--json"], env)
        parsed = json.loads(res.stdout)
        assert parsed["command"] == "apply"
        rec = read_jsonl(reconcile_log)[-1]
        assert rec["candidate_exists_during_reconcile"] is True
        assert not Path(rec["candidate"]).exists()
        assert not list(tmp_root.iterdir())
        print("[PASS] Gate B — zero-argument lab apply + cleanup")

        explicit_candidate = root / "explicit-candidate"
        explicit_candidate.mkdir()
        explicit_deployment = root / "explicit-deployment.json"
        explicit_deployment.write_text("{}\n", encoding="utf-8")

        composition.unlink()
        deployment.unlink()

        before_candidate_calls = len(read_jsonl(candidate_log))
        run(
            [
                str(INFRA_CLI),
                "lab",
                "plan",
                "--desired-candidate",
                str(explicit_candidate),
                "--desired-deployment",
                str(explicit_deployment),
                "--current-release",
                "/fixture/current",
                "--no-probe-runtime",
                "--json",
            ],
            env,
        )
        after_candidate_calls = len(read_jsonl(candidate_log))
        assert before_candidate_calls == after_candidate_calls
        rec = read_jsonl(reconcile_log)[-1]
        assert Path(rec["candidate"]) == explicit_candidate.resolve()
        assert Path(rec["deployment"]) == explicit_deployment.resolve()
        assert "--current-release" in rec["args"]
        assert "--no-probe-runtime" in rec["args"]
        print("[PASS] Gate C — overrides explícitos preservados")

        composition.write_text('{"schema":"fixture.composition"}\n', encoding="utf-8")
        before_candidate_calls = len(read_jsonl(candidate_log))
        before_reconcile_calls = len(read_jsonl(reconcile_log))
        res = run([str(INFRA_CLI), "lab", "plan"], env, expect=2)
        assert "deployment LAB canônico ausente" in res.stderr
        assert len(read_jsonl(candidate_log)) == before_candidate_calls
        assert len(read_jsonl(reconcile_log)) == before_reconcile_calls
        print("[PASS] Gate D — canonical deployment absent => fail-closed")

        deployment.write_text('{"schema":"fixture.deployment"}\n', encoding="utf-8")
        composition.unlink()
        res = run([str(INFRA_CLI), "lab", "plan"], env, expect=2)
        assert "composition LAB canônica ausente" in res.stderr
        print("[PASS] Gate E — canonical composition absent => fail-closed")

        composition.write_text('{"schema":"fixture.composition"}\n', encoding="utf-8")
        fail_env = env.copy()
        fail_env["OPS06_CANDIDATE_FAIL"] = "1"
        before_reconcile_calls = len(read_jsonl(reconcile_log))
        res = run([str(INFRA_CLI), "lab", "plan"], fail_env, expect=2)
        assert "não foi possível derivar candidata" in res.stderr
        assert len(read_jsonl(reconcile_log)) == before_reconcile_calls
        assert not list(tmp_root.iterdir())
        print("[PASS] Gate F — candidate failure propagates + cleanup")

        reconcile_fail_env = env.copy()
        reconcile_fail_env["OPS06_RECONCILE_RC"] = "9"
        run([str(INFRA_CLI), "lab", "plan"], reconcile_fail_env, expect=9)
        assert not list(tmp_root.iterdir())
        print("[PASS] Gate G — reconcile failure preserves RC + cleanup")

        composition.unlink()
        deployment.unlink()
        res = run([str(INFRA_CLI), "lab", "plan", "--help"], env)
        assert "--desired-candidate" in res.stdout
        assert "canônica" in res.stdout
        print("[PASS] Gate H — help independente de estado canônico")

        composition.write_text('{"schema":"fixture.composition"}\n', encoding="utf-8")
        deployment.write_text('{"schema":"fixture.deployment"}\n', encoding="utf-8")
        res = run([str(INFRA_CLI), "lab", "plan", "--json"], env)
        json.loads(res.stdout)
        assert "candidate-noise" not in res.stdout
        print("[PASS] Gate I — stdout JSON permanece puro")

    print("[PASS] OPS-06 LAB UX resolver")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
