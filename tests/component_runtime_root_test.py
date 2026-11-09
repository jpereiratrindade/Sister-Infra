#!/usr/bin/env python3
"""KEEP lifecycle actions retain factual process ownership with qualified equivalence."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
owner_root = runpy.run_path(str(ROOT / "libexec/sister-infra/component-runtime-root"))["owner_root"]


class RuntimeRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.releases = Path(self.tmp.name) / "releases"
        self.old, self.current = self.releases / "old", self.releases / "current"
        self.body = b"qualified artifact"
        self.artifact = dict(id="app", path="build/app", executable=True,
                             sha256=hashlib.sha256(self.body).hexdigest())
        for release in (self.old, self.current):
            app = release / "components/alpha/build/app"
            app.parent.mkdir(parents=True)
            app.write_bytes(self.body)
            manifest = dict(deployment=dict(evidence="resolved.json"), components=[dict(
                component_id="alpha", system_id="sister_alpha", path="components/alpha",
                commit="a" * 40, artifacts=[self.artifact])])
            (release / "manifest.json").write_text(json.dumps(manifest))
            (release / "resolved.json").write_text(json.dumps(dict(components=[dict(
                component_id="alpha", runtime=dict(transport="tcp", listen="127.0.0.1", port=12345),
                probe=dict(health_path="/health"))])))
        self.exe = self.old / "components/alpha/build/app"
        self.running_exe = Path(self.tmp.name) / "running-image"
        self.running_exe.write_bytes(self.body)

    def resolve(self):
        return owner_root(self.current, "alpha", self.releases, self.exe, self.running_exe)

    def test_equivalent_keep_returns_factual_root_without_mutation(self):
        before = {p: p.read_bytes() for p in self.releases.rglob("*") if p.is_file()}
        self.assertEqual(self.resolve(), self.old / "components/alpha")
        self.assertEqual(before, {p: p.read_bytes() for p in self.releases.rglob("*") if p.is_file()})

    def test_current_release_uses_its_native_entrypoint(self):
        self.exe = self.current / "components/alpha/build/app"
        self.assertEqual(self.resolve(), self.current / "components/alpha")

    def test_different_commit_is_refused(self):
        path = self.old / "manifest.json"
        data = json.loads(path.read_text())
        data["components"][0]["commit"] = "b" * 40
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.resolve()

    def test_different_artifact_on_disk_is_refused(self):
        self.exe.write_bytes(b"modified")
        with self.assertRaises(ValueError): self.resolve()

    def test_different_running_image_is_refused(self):
        self.running_exe.write_bytes(b"modified")
        with self.assertRaises(ValueError): self.resolve()

    def test_different_binding_is_refused(self):
        path = self.old / "resolved.json"
        data = json.loads(path.read_text())
        data["components"][0]["runtime"]["port"] += 1
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.resolve()

    def test_undeclared_executable_is_refused(self):
        self.exe = self.old / "components/alpha/build/other-app"
        with self.assertRaises(ValueError): self.resolve()

    def test_external_release_is_refused(self):
        self.exe = Path(self.tmp.name) / "external-app"
        with self.assertRaises(ValueError): self.resolve()


if __name__ == "__main__":
    unittest.main()
