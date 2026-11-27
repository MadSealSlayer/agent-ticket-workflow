"""Plan approval on Claude Code, natively and inside T3 Code (ADR 0018).

In T3 Code, ExitPlanMode always returns an error, so its PostToolUse never
fires. PreToolUse on ExitPlanMode stamps "plan proposed"; an exact "Approve"
to the AskUserQuestion with header "Plan" then writes the approval stamp."""
from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta

from _helpers import REPO, Project

from atwlib import doctor, hooks, install, state, util

QUESTION = "Approve this plan?"


def ask(answer=None, header="Plan", question=QUESTION, notes=None, response=None) -> dict:
    tool_input = {"questions": [{"question": question, "header": header, "multiSelect": False, "options": [
        {"label": "Approve", "description": "Start implementing this plan"},
        {"label": "Decline", "description": "Don't implement; tell me what to change"}]}]}
    if answer is not None:
        tool_input["answers"] = {question: answer}
    if notes:
        tool_input["annotations"] = {question: {"notes": notes}}
    payload = {"tool_name": "AskUserQuestion", "tool_input": tool_input}
    if response is not None:
        payload["tool_response"] = response
    return payload


class PlanApproval(Project):

    def setUp(self):
        super().setUp()
        self.ref = self.run_ref(self.ok("start", "T-1", "--kind", "code", "--scope", "isolated", "--host", "claude"))

    def hook(self, name: str, session: str = "s1", **kw) -> str:
        return self.ok("hook", name, stdin=json.dumps({"session_id": session, "cwd": str(self.root), **kw}))

    def propose(self, session: str = "s1") -> None:
        self.assertEqual(self.hook("planproposed", session, tool_name="ExitPlanMode", tool_input={"plan": "x"}), "")

    def answer(self, session: str = "s1", **kw) -> None:
        self.assertEqual(self.hook("planmode", session, **ask(**kw)), "")

    def plan_evidence(self) -> dict:
        ticket, run_id = self.ref.split("/")
        return state.load(self.root, ticket, run_id)["gates"]["plan"]["evidence"]

    def refused_plan(self) -> None:
        self.refused("plan", "--run", self.ref, "--files", "src/calc.py", contains="AskUserQuestion")

    # --- the two routes

    def test_native_exit_plan_mode_still_stamps(self):
        self.propose()
        self.hook("planmode", tool_name="ExitPlanMode", tool_response={"plan": "x"})
        self.ok("plan", "--run", self.ref, "--files", "src/calc.py")
        self.assertEqual(self.plan_evidence()["route"], "exit-plan-mode")

    def test_t3_proposal_then_approve_stamps(self):
        self.propose()
        self.refused_plan()
        self.answer(answer="Approve", notes="keep it small")
        self.ok("plan", "--run", self.ref, "--files", "src/calc.py")
        ev = self.plan_evidence()
        self.assertEqual((ev["route"], ev["answer"], ev["notes"]), ("ask-approve", "Approve", "keep it small"))

    def test_answer_in_tool_response_counts(self):
        self.propose()
        payload = ask(response={"answers": {QUESTION: "Approve"}})
        self.hook("planmode", **payload)
        self.ok("plan", "--run", self.ref, "--files", "src/calc.py")

    # --- no stamp

    def test_decline_consumes_the_proposal(self):
        self.propose()
        self.answer(answer="Decline")
        self.refused_plan()
        record = json.loads(state.declined_path(self.root, "branch-main").read_text(encoding="utf-8"))
        self.assertEqual((record["route"], record["answer"]), ("ask-decline", "Decline"))
        # A later "Approve" without a new proposal does not approve the declined plan.
        self.answer(answer="Approve")
        self.refused_plan()
        self.propose()
        self.answer(answer="Approve")
        self.ok("plan", "--run", self.ref, "--files", "src/calc.py")

    def test_free_text_is_a_decline(self):
        self.propose()
        self.answer(answer="Approve, but rename the function first")
        self.refused_plan()
        self.answer(answer="Approve")
        self.refused_plan()

    def test_multi_select_answer_is_not_an_approve(self):
        self.propose()
        self.answer(answer="Approve, Decline")
        self.refused_plan()

    def test_approve_without_a_proposal(self):
        self.answer(answer="Approve")
        self.refused_plan()

    def test_proposal_older_than_the_run(self):
        old = (datetime.now() - timedelta(hours=1)).isoformat(timespec="microseconds")
        util.atomic_write_text(state.proposed_path(self.root, "branch-main"), old)
        self.answer(answer="Approve")
        self.refused_plan()

    def test_question_with_another_header(self):
        self.propose()
        self.answer(answer="Approve", header="Scope")
        self.refused_plan()

    def test_no_answer_records_nothing(self):
        self.propose()
        self.answer()
        self.assertFalse(state.declined_path(self.root, "branch-main").exists())
        self.answer(answer="Approve")
        self.ok("plan", "--run", self.ref, "--files", "src/calc.py")

    # --- session isolation

    def test_bound_session_approves_only_its_own_ticket(self):
        self.write("tickets/T-2.md", "# T-2\n\nA second ticket.\n")
        self.hook("guard", "sess-A", tool_name="Bash", tool_input={"command": "atw start T-2 --kind comms"})
        self.ok("start", "T-2", "--kind", "comms")
        self.propose("sess-A")
        self.answer("sess-A", answer="Approve")
        # sess-A drives T-2; its approval must not pass T-1's plan gate.
        self.refused_plan()
        self.assertTrue(state.planmode_key_path(self.root, "ticket-T-2").is_file())
        self.propose("sess-B")
        self.answer("sess-B", answer="Approve")
        self.ok("plan", "--run", self.ref, "--files", "src/calc.py")

    # --- Stop hint

    def plan_line(self, session: str = "s1") -> str:
        reason = json.loads(self.hook("stop", session))["reason"]
        return next(line for line in reason.splitlines() if line.strip().startswith("- plan:"))

    def test_stop_hint_while_a_proposal_waits(self):
        self.assertIn("EnterPlanMode", self.plan_line())
        self.propose()
        line = self.plan_line()
        self.assertIn("ask the user Approve/Decline with AskUserQuestion (header `Plan`)", line)
        self.assertNotIn("EnterPlanMode", line)

    def test_stop_hint_after_a_decline(self):
        # Two Stop calls per test: a third identical block would fire the release valve.
        self.propose()
        self.answer(answer="Decline")
        self.assertIn("EnterPlanMode", self.plan_line())

    # --- fail open

    def test_malformed_payloads_fail_open(self):
        self.propose()
        bad = [
            {"tool_name": "AskUserQuestion"},
            {"tool_name": "AskUserQuestion", "tool_input": "x"},
            {"tool_name": "AskUserQuestion", "tool_input": {"questions": "x", "answers": []}},
            {"tool_name": "AskUserQuestion", "tool_input": {"questions": [None, 3, {"header": "Plan"}]}},
            {"tool_name": "AskUserQuestion", "tool_input": {"questions": [{"header": "Plan", "question": QUESTION}],
                                                            "answers": {QUESTION: ["Approve"]},
                                                            "annotations": "x"}, "tool_response": "Approve"},
        ]
        for payload in bad:
            payload.update({"session_id": "s1", "cwd": str(self.root)})
            self.assertEqual(hooks.planmode(json.dumps(payload)), (0, ""))
        for name in ("planmode", "planproposed"):
            r = self.atw("hook", name, stdin="[1, 2")
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
            self.assertIn("internal error", r.stderr)
        self.refused_plan()


class NoRun(Project):

    def test_planproposed_without_a_run_is_silent(self):
        payload = json.dumps({"tool_name": "ExitPlanMode", "session_id": "s1", "cwd": str(self.root)})
        self.assertEqual(self.ok("hook", "planproposed", stdin=payload).strip(), "")
        self.assertFalse((self.root / ".atw/runs/planmode").exists())


class HookRegistration(unittest.TestCase):

    FRAGMENT = install.hook_fragment((REPO / "adapters/claude-code/settings.fragment.json").read_text(encoding="utf-8"),
                                     "python")

    def old_settings(self) -> dict:
        """Our entries as 0.3.0 wrote them, plus one entry of the user's."""
        new = copy.deepcopy(self.FRAGMENT)
        hooks_ = new["hooks"]
        hooks_["PreToolUse"] = hooks_["PreToolUse"][:1]
        hooks_["PostToolUse"][0]["matcher"] = "ExitPlanMode"
        theirs = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo theirs"}]}
        hooks_["PreToolUse"].insert(0, theirs)
        return new

    def test_fragment_registers_the_plan_hooks(self):
        hooks_ = self.FRAGMENT["hooks"]
        pre = [(e["matcher"], e["hooks"][0]["args"][-1]) for e in hooks_["PreToolUse"]]
        self.assertIn(("ExitPlanMode", "planproposed"), pre)
        post = [(e["matcher"], e["hooks"][0]["args"][-1]) for e in hooks_["PostToolUse"]]
        self.assertEqual(post, [("ExitPlanMode|AskUserQuestion", "planmode")])
        self.assertEqual(doctor.missing_hook_coverage(self.FRAGMENT), [])

    def test_upgrade_replaces_old_entries(self):
        old = self.old_settings()
        self.assertEqual(doctor.missing_hook_coverage(old), ["PreToolUse:ExitPlanMode", "PostToolUse:AskUserQuestion"])
        merged, _ = install.merge_settings(old, self.FRAGMENT)
        self.assertEqual(doctor.missing_hook_coverage(merged), [])
        pre = merged["hooks"]["PreToolUse"]
        self.assertEqual(pre[0]["hooks"][0]["command"], "echo theirs")  # theirs kept, first
        self.assertEqual(len(pre), 3)
        self.assertEqual([e["matcher"] for e in merged["hooks"]["PostToolUse"]], ["ExitPlanMode|AskUserQuestion"])


if __name__ == "__main__":
    unittest.main()
