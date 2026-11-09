#!/usr/bin/env python3
"""Selective candidate updates preserve the exact qualified bytes of KEEP participants."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin/sister-candidate"


def fixture(root, revision):
    components, reports = [], []
    for cid in ("alpha", "beta"):
        path = root / "components" / cid / "build/service"
        path.parent.mkdir(parents=True)
        path.write_text(f"#!/bin/sh\necho {cid}-{revision}\n")
        path.chmod(0o700)
        artifacts = [dict(id="service", path="build/service", executable=True,
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest())]
        component = dict(component_id=cid, system_id=f"sister_{cid}",
                         path=f"components/{cid}", commit=revision * 40, artifacts=artifacts)
        components.append(component)
        reports.append(dict(component_id=cid, qualification=dict(status="PASS",
                            source=dict(clean=True, commit=component["commit"]), artifacts=artifacts)))
    evidence = root / "evidence/composition/qualification.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps(dict(status="PASS", components=reports)))
    manifest = dict(schema="sister.infra.candidate/1", candidate_id=f"cand-{revision}",
                    created_at_utc="20261109T000000Z",
                    composition=dict(composition_id="test", schema="sister.infra.composition.qualification/1"),
                    qualification=dict(status="PASS", evidence="evidence/composition/qualification.json",
                                       sha256=hashlib.sha256(evidence.read_bytes()).hexdigest()),
                    deployment=dict(status="PENDING_BINDINGS"), components=components)
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


class CandidateSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base, self.qualified, self.output = [self.root / part for part in ("base", "qualified", "out")]
        self.base_manifest = fixture(self.base, "a")
        self.new_manifest = fixture(self.qualified, "b")

    def select(self, *extra):
        return subprocess.run([str(CLI), "select", "--base", str(self.base),
                               "--qualified", str(self.qualified), "--component", "beta",
                               "--out", str(self.output), "--json", *extra],
                              capture_output=True, text=True)

    def test_only_selected_component_changes_and_provenance_is_preserved(self):
        before = (self.base / "manifest.json").read_bytes()
        result = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["components"][0], self.base_manifest["components"][0])
        self.assertEqual(manifest["components"][1], self.new_manifest["components"][1])
        for cid, source in [("alpha", self.base), ("beta", self.qualified)]:
            relative = f"components/{cid}/build/service"
            self.assertEqual((self.output / relative).read_bytes(), (source / relative).read_bytes())
        self.assertEqual(before, (self.base / "manifest.json").read_bytes())
        self.assertTrue((self.output / "evidence/selection/base-qualification.json").exists())
        self.assertTrue((self.output / "evidence/selection/qualified-qualification.json").exists())
        check = subprocess.run([str(CLI), "verify", str(self.output)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_unknown_component_is_refused_without_partial_candidate(self):
        result = self.select("--component", "unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_tampered_reused_artifact_is_refused(self):
        (self.base / "components/alpha/build/service").write_text("tampered")
        self.assertNotEqual(self.select().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_refuses_inconsistent_qualification_even_with_valid_evidence_hash(self):
        evidence = self.qualified / "evidence/composition/qualification.json"
        report = json.loads(evidence.read_text())
        report["components"][1]["qualification"]["source"]["commit"] = "c" * 40
        evidence.write_text(json.dumps(report))
        manifest = self.new_manifest
        manifest["qualification"]["sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
        (self.qualified / "manifest.json").write_text(json.dumps(manifest))
        self.assertNotEqual(self.select().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_output_cannot_modify_an_input(self):
        self.output = self.base / "nested"
        self.assertNotEqual(self.select().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_existing_destination_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_text("preserve")
        self.assertNotEqual(self.select().returncode, 0)
        self.assertEqual(sentinel.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
