"""tests/lint/deps results are cached by a fingerprint of the change; the Stop
hook only reads them, `status` reuses them, `gate` and `close` recompute."""
from __future__ import annotations

import json
import unittest

from _helpers import PY, Project, git, python_config

from atwlib import util

# Lint that counts its own runs in an ignored file, so counting never changes the diff.
COUNTING_LINT = ('"' + PY + '" -c "import pathlib, sys; p = pathlib.Path(\'.atw/tmp/lint-runs\'); '
                 'p.parent.mkdir(parents=True, exist_ok=True); '
                 'p.write_text(str(int(p.read_text() or 0) + 1) if p.exists() else \'1\'); '
                 'sys.exit(any(\'TODO\' in open(f).read() for f in sys.argv[1:]))" {files}')


def lint_config(run: str = COUNTING_LINT) -> dict:
    cfg = python_config()
    cfg["commands"]["lint"] = {"run": run, "output": "exit-code", "file_globs": ["*.py"]}
    return cfg


class CachedGates(Project):
    config = lint_config()

    def payload(self) -> str:
        return json.dumps({"session_id": "sess-1", "cwd": str(self.root)})

    def lint_runs(self) -> int:
        p = self.root / ".atw/tmp/lint-runs"
        return int(p.read_text()) if p.exists() else 0

    def start_tooling(self) -> str:
        ref = self.run_ref(self.ok("start", "T-1", "--kind", "tooling"))
        self.write("scripts/T-1_tool.py", "print('hi')\n")
        return ref

    def test_stop_hook_never_runs_lint_and_blocks_with_refresh_command(self):
        ref = self.start_tooling()
        out = json.loads(self.ok("hook", "stop", stdin=self.payload()))
        self.assertEqual(out["decision"], "block")
        self.assertIn("lint: no result for the current change", out["reason"])
        self.assertIn(f"atw gate lint --run {ref}", out["reason"])
        self.assertEqual(self.lint_runs(), 0)

    def test_fresh_result_is_reused_until_the_change_moves(self):
        ref = self.start_tooling()
        self.ok("gate", "--run", ref, "lint")
        self.assertEqual(self.lint_runs(), 1)
        self.assertEqual(self.ok("hook", "stop", stdin=self.payload()).strip(), "")
        self.ok("status", "--run", ref)
        self.assertEqual(self.lint_runs(), 1)  # status reused the cached result

        self.write("scripts/T-1_tool.py", "print('hi again')\n")
        out = json.loads(self.ok("hook", "stop", stdin=self.payload()))
        self.assertIn("lint: no result for the current change", out["reason"])
        self.assertEqual(self.lint_runs(), 1)

    def test_a_cached_failure_is_reported_as_failed(self):
        ref = self.start_tooling()
        self.write("scripts/T-1_tool.py", "# TODO\n")
        self.assertEqual(self.atw("gate", "--run", ref, "lint").returncode, 1)
        out = json.loads(self.ok("hook", "stop", stdin=self.payload()))
        self.assertIn("lint: lint failed", out["reason"])

    def test_config_change_makes_the_result_stale(self):
        ref = self.start_tooling()
        self.ok("gate", "--run", ref, "lint")
        cfg = lint_config()
        cfg["commands"]["lint"]["file_globs"] = ["*.py", "*.pyi"]
        self.write_config(cfg)
        out = json.loads(self.ok("hook", "stop", stdin=self.payload()))
        self.assertIn("lint: no result for the current change", out["reason"])

    def test_close_always_recomputes(self):
        ref = self.start_tooling()
        self.ok("gate", "--run", ref, "lint")
        self.ok("close", "--run", ref)
        self.assertEqual(self.lint_runs(), 2)


class ChangedLineRanges(Project):

    def test_deletion_only_diff_has_no_changed_lines(self):
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef old():\n    return 1\n")
        git(self.root, "commit", "-qam", "add old")
        base = util.head_sha(self.root)
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n")
        self.assertEqual(util.changed_line_ranges(self.root, base, ["src/calc.py"]), {"src/calc.py": set()})

    def test_untracked_file_has_no_entry(self):
        self.write("src/new.py", "x = 1\n")
        self.assertEqual(util.changed_line_ranges(self.root, util.head_sha(self.root), ["src/new.py"]), {})


if __name__ == "__main__":
    unittest.main()
