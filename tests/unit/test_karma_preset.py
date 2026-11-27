"""The Karma preset: spec-to-project mapping, the inline JUnit reporter, and
detection. The Node parts need `node` on PATH; they never need Angular."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _helpers import CORE

from atwlib import detect, junit

KARMA = CORE / "presets" / "karma"
NODE = shutil.which("node")

ANGULAR = {
    "version": 1,
    "projects": {
        "app-a": {"root": "projects/app-a", "sourceRoot": "projects/app-a/src",
                  "architect": {"test": {"builder": "@angular-devkit/build-angular:karma",
                                         "options": {"tsConfig": "projects/app-a/tsconfig.spec.json"}}}},
        "app-b": {"root": "projects/app-b", "sourceRoot": "projects/app-b/src",
                  "architect": {"test": {"builder": "@angular/build:karma",
                                         "options": {"tsConfig": "projects/app-b/tsconfig.spec.json"}}}},
        "shared": {"root": "projects/shared", "architect": {"build": {"builder": "x"}}},
    },
}


class Workspace(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="atw-karma-"))
        self.write("angular.json", json.dumps(ANGULAR))
        # JSONC with a comment and a trailing comma, include inherited through `extends`.
        self.write("projects/app-a/tsconfig.base.json", '{\n  // base\n  "include": ["src/**/*.spec.ts",],\n}\n')
        self.write("projects/app-a/tsconfig.spec.json", '{"extends": "./tsconfig.base.json"}\n')
        self.write("projects/app-b/tsconfig.spec.json", '{"files": ["src/only.spec.ts"]}\n')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def node(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        import os
        return subprocess.run([NODE, *args], cwd=self.root, capture_output=True, text=True,
                              env={**os.environ, **(env or {})})

    @unittest.skipUnless(NODE, "node is not installed")
    def test_dry_run_maps_specs_and_skips_the_ones_no_target_runs(self):
        r = self.node(str(KARMA / "karma-run.cjs"), "--dry-run",
                      "projects/app-a/src/app/calc.spec.ts", "projects/app-a/src/x/y.spec.ts",
                      "projects/app-a/e2e/flow.spec.ts", "projects/app-b/src/only.spec.ts",
                      "projects/app-b/src/other.spec.ts", "projects/shared/util.spec.ts",
                      "projects/app-a/src/app/calc.ts")
        self.assertEqual(r.returncode, 0, r.stderr)
        plan = json.loads(r.stdout)
        self.assertEqual(plan["projects"], {
            "app-a": ["projects/app-a/src/app/calc.spec.ts", "projects/app-a/src/x/y.spec.ts"],
            "app-b": ["projects/app-b/src/only.spec.ts"]})
        skipped = {s["file"]: s["why"] for s in plan["skipped"]}
        self.assertEqual(set(skipped), {"projects/app-a/e2e/flow.spec.ts", "projects/app-b/src/other.spec.ts",
                                        "projects/shared/util.spec.ts"})
        self.assertIn("tsconfig.spec.json", skipped["projects/app-a/e2e/flow.spec.ts"])
        self.assertIn("no angular.json project", skipped["projects/shared/util.spec.ts"])
        self.assertIn("not a spec file", r.stderr)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_reporter_writes_junit_that_proof_ids_match(self):
        self.write("projects/app-a/src/app/calc.spec.ts", "describe('Calc', () => { it('subtracts', () => {}); });\n")
        self.write("projects/app-a/src/app/other.spec.ts", "describe(\"Other\", () => {});\n")
        out = self.root / "out" / "junit.xml"
        script = (
            "const R = require(process.argv[1]).AtwJunitReporter;"
            "const r = new R(function () {});"
            "r.onSpecComplete(null, {suite: ['Calc'], description: 'subtracts', success: false,"
            " log: ['Expected 8 to be 2.'], time: 5});"
            "r.onSpecComplete(null, {suite: ['Other', 'inner'], description: 'works & <ok>', success: true});"
            "r.onSpecComplete(null, {suite: ['Other'], description: 'later', success: true, skipped: true});"
            "r.onRunComplete();")
        specs = ["projects/app-a/src/app/other.spec.ts", "projects/app-a/src/app/calc.spec.ts"]
        r = self.node("-e", script, str(KARMA / "karma.atw.cjs"),
                      env={"ATW_JUNIT": str(out), "ATW_SPEC_FILES": json.dumps(specs)})
        self.assertEqual(r.returncode, 0, r.stderr)
        text = out.read_text(encoding="utf-8")
        self.assertIn('file="projects/app-a/src/app/calc.spec.ts"', text)
        res = junit.check(text, ["projects/app-a/src/app/calc.spec.ts::Calc subtracts"], "red", "name")
        self.assertTrue(res["passed"], res)
        res = junit.check(text, ["projects/app-a/src/app/other.spec.ts::Other inner works & <ok>"], "green", "name")
        self.assertTrue(res["passed"], res)
        res = junit.check(text, ["Other later"], "green", "name")
        self.assertEqual(res["verdicts"]["Other later"]["outcome"], "skipped")

    def test_detect_suggests_karma_and_tsc(self):
        self.write("tsconfig.json", "{}\n")
        report = detect.detect(self.root)
        matched = {m["preset"] for m in report["stack"]["presets_matched"]}
        self.assertTrue({"karma", "tsc"} <= matched, matched)
        karma = {a["project"]: a["karma"] for a in report["stack"]["angular"]}
        self.assertEqual(karma, {"app-a": True, "app-b": True, "shared": False})
        self.assertIn("karma preset", detect.render(report))


if __name__ == "__main__":
    unittest.main()
