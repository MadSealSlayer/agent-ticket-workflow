"""deps builtins, config validation and lint/simplify wiring."""
from __future__ import annotations

import json
import re
import unittest

from _helpers import PY, Project, python_config
from atwlib import config


class PythonDeps(Project):
    config = python_config(commands={**python_config()["commands"], "deps": {"builtin": "python-imports"}})

    def setUp(self):
        super().setUp()
        self.write("src/requirements.txt", "requests==2.32\nPyYAML>=6\n")

    def gate(self, source: str) -> str:
        self.ok("start", "T-1", "--kind", "tooling")
        self.write("src/svc.py", source)  # after start: files untracked at start are not this run's
        return self.atw("gate", "deps").stdout

    def test_declared_stdlib_and_first_party_pass(self):
        self.assertIn("[PASS]", self.gate("import os, json\nimport requests\nimport yaml\nimport calc\n"))

    def test_undeclared_import_fails(self):
        out = self.gate("import httpx\n")
        self.assertIn("httpx", out)
        self.assertIn("src/requirements.txt", out)


class NodeDeps(Project):
    config = python_config(commands={**python_config()["commands"], "deps": {"builtin": "node-imports"}})

    def test_node(self):
        self.write("web/package.json", json.dumps({"name": "web", "dependencies": {"react": "18"},
                                                  "devDependencies": {"@types/node": "20"}}))
        self.write("web/a.ts", "import React from 'react'\nimport fs from 'node:fs'\nimport x from './x'\n"
                               "import y from '@/y'\nimport type { T } from '@types/node'\n")
        self.ok("start", "T-1", "--kind", "tooling")
        self.assertIn("[PASS]", self.atw("gate", "deps").stdout)
        self.write("web/b.ts", "import _ from 'lodash/fp'\n")
        out = self.atw("gate", "deps").stdout
        self.assertIn("lodash", out)


class Lint(Project):
    def setUp(self):
        self.config = python_config(commands={
            **python_config()["commands"],
            # exit 1 when any given file contains "TODO"
            "lint": {"run": f'"{PY}" -c "import sys; sys.exit(any(\'TODO\' in open(f).read() for f in sys.argv[1:]))" {{files}}',
                     "file_globs": ["*.py"]}})
        super().setUp()

    def test_lint_gate(self):
        self.ok("start", "T-1", "--kind", "tooling")
        self.write("scripts/T-1.py", "print('ok')\n")
        self.ok("gate", "lint")
        self.write("scripts/T-1.py", "print('ok')  # TODO\n")
        self.assertEqual(self.atw("gate", "lint").returncode, 1)


class Simplify(Project):
    def setUp(self):
        self.config = python_config(simplify="gate")
        super().setUp()

    def test_simplify_gate_required_and_accepted(self):
        ref = self.run_ref(self.ok("start", "T-1", "--kind", "code", "--scope", "isolated"))
        self.ok("plan", "--files", "src/calc.py", "--no-plan-mode", "--why", "tiny")
        self.ok("red", "--none", "--why", "refactor")
        self.write("src/calc.py", "def add(a, b):\n    return b + a\n")
        self.refused("review-packet", contains="simplify")
        out = self.ok("simplify-packet")
        packet = (self.root / re.search(r"packet: (\S+)", out).group(1)).read_text(encoding="utf-8")
        pid = re.search(r"^packet: (\w+)", packet, re.M).group(1)
        report = re.search(r"^report: (\S+)", packet, re.M).group(1)
        self.write(report, f"packet: {pid}\nagent: simplifier\n\n## Recommendations\n- [ ] R1: swap back\n")
        self.refused("accept-simplify", "--report", report, contains="needs a decision")
        self.write(report, f"packet: {pid}\nagent: simplifier\n\n## Recommendations\n- [x] R1: swap back - declined: same\n")
        self.ok("accept-simplify", "--report", report)
        self.ok("review-packet", "--run", ref)


class ConfigValidation(unittest.TestCase):

    def test_defaults_need_project_answers(self):
        errs = config.validate(config.load(__import__("pathlib").Path("/nonexistent")))
        self.assertTrue(any("commands.proof" in e for e in errs))
        self.assertTrue(any("protected_paths" in e for e in errs))

    def test_python_fixture_config_is_valid(self):
        self.assertEqual(config.validate(config._merge(config.DEFAULTS, python_config())), [])

    def test_placeholders_checked(self):
        cfg = config._merge(config.DEFAULTS, python_config())
        cfg["commands"]["proof"]["run"] = "pytest {ids}"
        cfg["commands"]["tests"]["run"] = "pytest"
        errs = config.validate(cfg)
        self.assertTrue(any("{junit}" in e for e in errs))
        self.assertTrue(any("{files}" in e for e in errs))


if __name__ == "__main__":
    unittest.main()


class PathPrefixes(unittest.TestCase):
    def test_dot_folders_keep_their_dot(self):
        from atwlib.util import under_any
        self.assertTrue(under_any(".github/workflows/ci.yml", [".github/workflows/"]))
        self.assertFalse(under_any("github/workflows/ci.yml", [".github/"]))
        self.assertTrue(under_any(".atw/runs/x/run.json", [".atw/runs/"]))
        self.assertFalse(under_any("atw/runs/x", [".atw/runs/"]))
        self.assertTrue(under_any("./src/a.ts", ["src"]))
        self.assertTrue(under_any("src/a.ts", ["./src/"]))
        self.assertTrue(under_any("anything", ["."]))
