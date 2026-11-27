"""Session isolation: several sessions (for example T3 Code threads) share one
checkout and branch. A hook acts only on its own session's run, or on an open
run that no session drives."""
from __future__ import annotations

import json
import unittest

from _helpers import Project

from atwlib import hooks, state


class SessionIsolation(Project):

    def setUp(self):
        super().setUp()
        self.write("tickets/T-2.md", "# T-2\n\nA second ticket.\n")

    def payload(self, session: str, **kw) -> str:
        return json.dumps({"session_id": session, "cwd": str(self.root), **kw})

    def bash(self, session: str, command: str) -> str:
        return self.ok("hook", "guard", stdin=self.payload(session, tool_name="Bash",
                                                            tool_input={"command": command}))

    def bound(self, session: str) -> str | None:
        p = self.root / ".atw/runs/sessions" / f"{session}.txt"
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def test_unbound_session_skips_a_run_bound_to_another_session(self):
        self.bash("sess-A", "python .atw/core/atw.py start T-1 --kind comms")
        self.ok("start", "T-1", "--kind", "comms")
        # sess-B is an ordinary thread on the same branch: T-1 is not its run.
        self.assertEqual(self.ok("hook", "stop", stdin=self.payload("sess-B")).strip(), "")
        # sess-A still gets its own gate.
        out = json.loads(self.ok("hook", "stop", stdin=self.payload("sess-A")))
        self.assertEqual(out["decision"], "block")

    def test_unbound_session_still_falls_back_to_an_unbound_run(self):
        self.ok("start", "T-1", "--kind", "comms")
        out = json.loads(self.ok("hook", "stop", stdin=self.payload("sess-B")))
        self.assertEqual(out["decision"], "block")
        self.assertIn("T-1/", out["reason"])

    def test_fallback_picks_the_newest_unbound_run(self):
        self.bash("sess-A", "atw start T-2 --kind comms")
        self.ok("start", "T-1", "--kind", "comms")
        self.ok("start", "T-2", "--kind", "comms")
        run = state.run_for_hook(self.root, "sess-B")
        self.assertEqual(run["ticket"], "T-1")

    def test_stale_binding_is_cleared_and_never_falls_back(self):
        self.ok("start", "T-1", "--kind", "comms")  # an open, unbound run on the branch
        self.write(".atw/runs/sessions/sess-A.txt", "T-9")  # bound to a ticket with no open run
        self.assertEqual(self.ok("hook", "stop", stdin=self.payload("sess-A")).strip(), "")
        self.assertIsNone(self.bound("sess-A"))

    def test_guard_skips_run_checks_for_another_sessions_run(self):
        self.bash("sess-A", "atw start T-1 --kind code --scope isolated")
        self.ok("start", "T-1", "--kind", "code", "--scope", "isolated")
        edit = {"tool_name": "Edit", "tool_input": {"file_path": "src/calc.py", "old_string": "a", "new_string": "b"}}
        ask = json.loads(self.ok("hook", "guard", stdin=self.payload("sess-A", **edit)))
        self.assertEqual(ask["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertEqual(self.ok("hook", "guard", stdin=self.payload("sess-B", **edit)).strip(), "")

    def test_binds_on_mutating_subcommands_with_ticket_or_run(self):
        self.bash("s1", "python .atw/core/atw.py gate tests lint --ticket T-1")
        self.assertEqual(self.bound("s1"), "T-1")
        self.bash("s2", 'py -3 .atw/core/atw.py accept-review --run "T-2/T-2-abc123" --report r.md')
        self.assertEqual(self.bound("s2"), "T-2")
        self.bash("s3", "python .atw/core/atw.py decide --ticket=T-1 --item x --verdict settled-question --why y")
        self.assertEqual(self.bound("s3"), "T-1")

    def test_read_only_and_other_commands_do_not_bind(self):
        self.bash("s1", "python .atw/core/atw.py status --ticket T-1")
        self.bash("s1", "python .atw/core/atw.py runs")
        self.bash("s1", "pytest --run T-1/x")
        self.assertIsNone(self.bound("s1"))

    def test_status_does_not_move_a_bound_session(self):
        self.bash("s1", "atw start T-1 --kind comms")
        self.bash("s1", "atw status --ticket T-2")
        self.assertEqual(self.bound("s1"), "T-1")

    def test_chained_command_binds_only_from_the_mutating_one(self):
        self.bash("s1", "atw gate tests --run T-1/abc && atw status --ticket T-2")
        self.assertEqual(self.bound("s1"), "T-1")

    def test_planmode_of_a_bound_session_does_not_stamp_the_branch(self):
        self.bash("sess-A", "atw start T-2 --kind comms")
        ref = self.run_ref(self.ok("start", "T-1", "--kind", "code", "--scope", "isolated", "--host", "claude"))
        self.ok("start", "T-2", "--kind", "comms")
        self.ok("hook", "planmode", stdin=self.payload("sess-A", tool_name="ExitPlanMode"))
        # sess-A drives T-2; its plan mode must not pass T-1's plan gate.
        self.refused("plan", "--run", ref, "--files", "src/calc.py", contains="ExitPlanMode")
        self.ok("hook", "planmode", stdin=self.payload("sess-B", tool_name="ExitPlanMode"))
        self.ok("plan", "--run", ref, "--files", "src/calc.py")


class BindFromCommand(unittest.TestCase):

    def test_start_wins_and_quotes_are_accepted(self):
        seen = []
        orig = state.bind_session
        state.bind_session = lambda root, sid, ticket: seen.append(ticket)
        try:
            hooks.bind_from_command(None, "s", "python .atw/core/atw.py start 'T-3' --kind comms")
            hooks.bind_from_command(None, "s", 'atw.py" kind code --scope isolated --why x --run T-4/r1')
            hooks.bind_from_command(None, None, "atw start T-5 --kind comms")  # no session: no bind
        finally:
            state.bind_session = orig
        self.assertEqual(seen, ["T-3", "T-4"])


if __name__ == "__main__":
    unittest.main()
