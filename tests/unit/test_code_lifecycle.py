"""End-to-end: a code ticket through start -> plan -> red -> tests -> review -> close."""
from __future__ import annotations

import json
import re
import unittest

from _helpers import Project

PROOF = "tests/test_sub.py::test_sub"
TEST_SUB = ("import sys, pathlib\n"
            "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))\n\n"
            "def test_sub():\n    from calc import sub\n    assert sub(5, 3) == 2\n")


class CodeLifecycle(Project):

    def start(self) -> str:
        return self.run_ref(self.ok("start", "T-1", "--kind", "code", "--scope", "isolated"))

    def plan(self, ref: str) -> None:
        self.write("plan.md", "# Plan\nAdd sub.\n")
        self.ok("plan", "--run", ref, "--files", "src/calc.py,tests/test_sub.py",
                "--plan-file", "plan.md", "--approval", "yes, go")

    def write_report(self, packet_path: str, body: str, reviewer: str = "fresh-reviewer") -> str:
        packet = (self.root / packet_path).read_text(encoding="utf-8")
        pid = re.search(r"^packet: (\w+)", packet, re.M).group(1)
        report = re.search(r"^report: (\S+)", packet, re.M).group(1)
        self.write(report, f"packet: {pid}\nreviewer: {reviewer}\n\n{body}")
        return report

    CLEAN = "## Critical - blocks merge\n\n## Warning - blocks merge\n\n## Nit\n- [ ] naming\n"

    def test_full_happy_path(self):
        ref = self.start()
        self.refused("close", "--run", ref, contains="unmet gates")
        self.plan(ref)

        # Red must be behavioral: a missing function is a weak red.
        self.write("tests/test_sub.py", TEST_SUB)
        out = self.refused("red", "--run", ref, "--test", PROOF, contains="weak red")
        self.assertIn("ImportError", out)

        # Stub it so the assertion fails on behavior.
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return None\n")
        self.ok("red", "--run", ref, "--test", PROOF)

        # Tests gate fails while the stub is in place, passes once implemented.
        r = self.atw("gate", "--run", ref, "tests")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
        self.ok("gate", "--run", ref, "tests")

        # Audit via a clean-room packet.
        out = self.ok("review-packet", "--run", ref)
        packet = re.search(r"packet: (\S+)", out).group(1)
        packet_text = (self.root / packet).read_text(encoding="utf-8")
        self.assertIn("Add `sub(a, b)` to calc.", packet_text)  # the ticket, verbatim
        self.assertNotIn("# Plan", packet_text)                   # never the author's plan
        report = self.write_report(packet, self.CLEAN)
        self.ok("accept-review", "--run", ref, "--report", report)

        status = json.loads(self.atw("status", "--run", ref, "--json").stdout)
        self.assertEqual(status["unmet"], [])
        self.ok("close", "--run", ref, "--note", "done")
        run = json.loads(next((self.root / ".atw/runs/T-1").glob("*/run.json")).read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "closed")
        self.assertIn("T-1", (self.root / ".atw/runs/log.md").read_text(encoding="utf-8"))

    def test_red_rejects_already_passing_and_unknown_ids(self):
        ref = self.start()
        self.plan(ref)
        self.refused("red", "--run", ref, "--test", "tests/test_calc.py::test_add", contains="already passes")
        self.refused("red", "--run", ref, "--test", "tests/test_calc.py::test_nope", contains="not reported")

    def test_red_needs_plan_and_plan_needs_approval(self):
        ref = self.start()
        self.refused("red", "--run", ref, "--test", PROOF, contains="plan first")
        self.write("plan.md", "x")
        self.refused("plan", "--run", ref, "--files", "src/calc.py", "--plan-file", "plan.md",
                     contains="--approval")

    def test_coordinated_cannot_skip_plan_mode(self):
        ref = self.run_ref(self.ok("start", "T-1", "--kind", "code", "--scope", "coordinated"))
        self.refused("plan", "--run", ref, "--files", "src/calc.py", "--no-plan-mode", "--why", "small",
                     contains="coordinated")

    def test_claude_host_needs_planmode_stamp(self):
        ref = self.run_ref(self.ok("start", "T-1", "--kind", "code", "--scope", "isolated", "--host", "claude"))
        self.refused("plan", "--run", ref, "--files", "src/calc.py", contains="ExitPlanMode")
        payload = json.dumps({"tool_name": "ExitPlanMode", "session_id": "s1", "cwd": str(self.root)})
        self.ok("hook", "planmode", stdin=payload)
        self.ok("plan", "--run", ref, "--files", "src/calc.py")

    def test_edit_after_review_makes_audit_stale(self):
        ref = self.start()
        self.plan(ref)
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return None\n")
        self.write("tests/test_sub.py", TEST_SUB)
        self.ok("red", "--run", ref, "--test", PROOF)
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
        packet = re.search(r"packet: (\S+)", self.ok("review-packet", "--run", ref)).group(1)
        report = self.write_report(packet, self.CLEAN)
        self.ok("accept-review", "--run", ref, "--report", report)

        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return -(b - a)\n")
        out = self.atw("status", "--run", ref).stdout
        self.assertIn("STALE", out)
        self.refused("close", "--run", ref, contains="audit")

        # A report for an outdated packet is refused too.
        self.refused("accept-review", "--run", ref, "--report", report, contains="diff changed")

    def test_review_report_rules(self):
        ref = self.start()
        self.plan(ref)
        self.ok("red", "--run", ref, "--none", "--why", "pure refactor")
        self.write("src/calc.py", "def add(a, b):\n    return b + a\n")
        packet = re.search(r"packet: (\S+)", self.ok("review-packet", "--run", ref)).group(1)

        same = self.write_report(packet, self.CLEAN, reviewer="other-implementer")
        self.refused("accept-review", "--run", ref, "--report", same, contains="reviewer")

        no_warning = self.write_report(packet, "## Critical - blocks merge\n")
        self.refused("accept-review", "--run", ref, "--report", no_warning, contains="Warning headings")

        crit = self.write_report(packet, "## Critical - blocks merge\n- [ ] wrong sign\n## Warning - blocks merge\n")
        self.refused("accept-review", "--run", ref, "--report", crit, contains="open blocking")
        self.refused("accept-review", "--run", ref, "--report", crit, "--override", "wrong sign",
                     "--user-approved", "ok", contains="open blocking")  # Critical: never overridable

        warn = self.write_report(packet, "## Critical - blocks merge\n## Warning - blocks merge\n- [ ] long name\n")
        self.ok("accept-review", "--run", ref, "--report", warn, "--override", "long name",
                "--user-approved", "fine, keep it")
        run = json.loads(next((self.root / ".atw/runs/T-1").glob("*/run.json")).read_text(encoding="utf-8"))
        self.assertEqual(run["decisions"][-1]["verdict"], "accepted-tradeoff")

    def test_second_start_refused_and_force_aborts(self):
        self.start()
        self.refused("start", "T-1", "--kind", "code", "--scope", "isolated", contains="already has an open run")
        self.ok("start", "T-1", "--kind", "code", "--scope", "isolated", "--force")
        self.assertEqual(len([l for l in self.ok("runs", "--all").splitlines() if "aborted" in l]), 1)

    def test_kind_downgrade_is_announced(self):
        ref = self.start()
        out = self.ok("kind", "docs", "--run", ref, "--why", "only a README change")
        self.assertIn("NO LONGER REQUIRED", out)


if __name__ == "__main__":
    unittest.main()
