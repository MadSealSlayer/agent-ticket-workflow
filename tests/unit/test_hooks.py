"""Claude Code hook handlers through the CLI (stdin JSON in, JSON out)."""
from __future__ import annotations

import json
import unittest

from _helpers import Project


class Hooks(Project):

    def payload(self, **kw) -> str:
        return json.dumps({"session_id": "sess-1", "cwd": str(self.root), **kw})

    def test_no_run_means_silent_allow(self):
        for name in ("stop", "guard", "planmode"):
            r = self.atw("hook", name, stdin=self.payload(tool_name="Edit", tool_input={"file_path": "src/calc.py"}))
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_garbage_payload_fails_open(self):
        r = self.atw("hook", "stop", stdin="{not json")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        self.assertIn("internal error", r.stderr)

    def test_stop_blocks_then_release_valve(self):
        self.ok("start", "T-1", "--kind", "comms")
        outs = [json.loads(self.ok("hook", "stop", stdin=self.payload())) for _ in range(3)]
        self.assertEqual(outs[0]["decision"], "block")
        self.assertIn("placement", outs[0]["reason"])
        self.assertEqual(outs[1]["decision"], "block")
        self.assertNotIn("decision", outs[2])
        self.assertIn("allowing the turn", outs[2]["systemMessage"])

    def test_stop_allows_when_gates_met(self):
        self.ok("start", "T-1", "--kind", "comms")
        self.write("docs/agent-notes/comms/T-1.md", "ok\n")
        self.assertEqual(self.ok("hook", "stop", stdin=self.payload()).strip(), "")

    def test_guard_denies_history_rewrite_and_asks_push(self):
        deny = json.loads(self.ok("hook", "guard", stdin=self.payload(
            tool_name="Bash", tool_input={"command": "git reset --hard HEAD~1"})))
        self.assertEqual(deny["hookSpecificOutput"]["permissionDecision"], "deny")
        ask = json.loads(self.ok("hook", "guard", stdin=self.payload(
            tool_name="Bash", tool_input={"command": "git push origin main"})))
        self.assertEqual(ask["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertEqual(self.ok("hook", "guard", stdin=self.payload(
            tool_name="Bash", tool_input={"command": "git status"})).strip(), "")

    def test_guard_asks_before_source_edit_until_plan(self):
        self.ok("start", "T-1", "--kind", "code", "--scope", "isolated")
        edit = self.payload(tool_name="Edit", tool_input={"file_path": str(self.root / "src" / "calc.py")})
        out = json.loads(self.ok("hook", "guard", stdin=edit))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        self.ok("plan", "--files", "src/calc.py", "--no-plan-mode", "--why", "one-liner")
        self.assertEqual(self.ok("hook", "guard", stdin=edit).strip(), "")
        # Non-protected files are never asked about.
        other = self.payload(tool_name="Write", tool_input={"file_path": "README.md"})
        self.assertEqual(self.ok("hook", "guard", stdin=other).strip(), "")

    def test_guard_binds_session_on_start(self):
        self.ok("hook", "guard", stdin=self.payload(
            tool_name="Bash", tool_input={"command": "python .atw/core/atw.py start T-1 --kind comms"}))
        bound = (self.root / ".atw/runs/sessions/sess-1.txt").read_text(encoding="utf-8")
        self.assertEqual(bound, "T-1")


if __name__ == "__main__":
    unittest.main()
