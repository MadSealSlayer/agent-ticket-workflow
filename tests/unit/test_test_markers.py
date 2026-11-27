"""Guard: an edit that adds a skip or focus marker to a test file asks first."""
from __future__ import annotations

import json
import unittest

from _helpers import Project

from atwlib import config, hooks

MARKERS = config.DEFAULTS["guards"]["test_markers"]


class Detection(unittest.TestCase):

    def added(self, old: str, new: str) -> bool:
        return hooks.added_test_marker(old, new, MARKERS) is not None

    def test_js_markers(self):
        for new in ("xit('a', () => {})", "fit('a', () => {})", "xdescribe('S', () => {})",
                    "fdescribe('S', () => {})", "it.skip('a', f)", "describe.only('S', f)",
                    "test.skip.each([1])('a', f)", "it.only (\"a\", f)", "context.skip('c', f)"):
            self.assertTrue(self.added("", new), new)

    def test_python_markers(self):
        for new in ("@pytest.mark.skip(reason='x')", "@pytest.mark.xfail", "@pytest.mark.skipif(True, reason='')",
                    "    pytest.skip('later')", "@unittest.skip('x')", "@unittest.expectedFailure"):
            self.assertTrue(self.added("", new), new)

    def test_ordinary_code_is_not_a_marker(self):
        for new in ("it('fits', () => {})", "this.fit(x)", "obs.pipe(skip(1))", "list.skip(2)",
                    "const outfit = profit(3)", "submit(a)", "describe('only one', f)"):
            self.assertFalse(self.added("", new), new)

    def test_counts_not_presence(self):
        old = "it.skip('a', f)\n"
        self.assertFalse(self.added(old, old.replace("'a'", "'b'")))
        self.assertTrue(self.added(old, old + "it.skip('c', f)\n"))
        self.assertFalse(self.added(old, ""))  # removing a marker is fine


class Guard(Project):

    def guard(self, tool: str, **tool_input) -> str:
        return self.ok("hook", "guard", stdin=json.dumps(
            {"session_id": "s", "cwd": str(self.root), "tool_name": tool, "tool_input": tool_input}))

    def decision(self, out: str) -> str:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else ""

    def test_asks_without_any_run(self):
        out = self.guard("Edit", file_path=str(self.root / "tests/test_calc.py"),
                         old_string="def test_add():", new_string="@pytest.mark.skip\ndef test_add():")
        self.assertEqual(self.decision(out), "ask")
        self.assertIn("user's OK", out)

    def test_write_compares_with_the_file_on_disk(self):
        self.write("tests/test_x.py", "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    pass\n")
        same = (self.root / "tests/test_x.py").read_text(encoding="utf-8") + "\ndef test_b():\n    pass\n"
        self.assertEqual(self.decision(self.guard("Write", file_path="tests/test_x.py", content=same)), "")
        more = same + "\n@pytest.mark.xfail\ndef test_c():\n    pass\n"
        self.assertEqual(self.decision(self.guard("Write", file_path="tests/test_x.py", content=more)), "ask")

    def test_multiedit_and_test_globs_outside_test_paths(self):
        out = self.guard("MultiEdit", file_path="web/app.spec.ts",
                         edits=[{"old_string": "it('a'", "new_string": "it('a'"},
                                {"old_string": "describe('S'", "new_string": "fdescribe('S'"}])
        self.assertEqual(self.decision(out), "ask")

    def test_non_test_files_are_not_checked(self):
        out = self.guard("Edit", file_path="README.md", old_string="x", new_string="it.only(")
        self.assertEqual(self.decision(out), "")

    def test_can_be_turned_off(self):
        cfg = json.loads((self.root / ".atw/atw.config.json").read_text(encoding="utf-8"))
        cfg["guards"] = {"test_markers": []}
        self.write_config(cfg)
        out = self.guard("Edit", file_path="tests/test_calc.py", old_string="a", new_string="@pytest.mark.skip")
        self.assertEqual(self.decision(out), "")


class MarkerConfig(unittest.TestCase):

    def test_invalid_regex_is_reported(self):
        cfg = config._merge(config.DEFAULTS, {"guards": {"test_markers": ["(unclosed"]}})
        self.assertTrue(any("guards.test_markers" in e for e in config.validate(cfg)))


if __name__ == "__main__":
    unittest.main()
