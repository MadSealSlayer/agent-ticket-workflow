"""The `verify` gate: a big code change is run for real before close, next to the review."""
from __future__ import annotations

import json
import re
import unittest

from _helpers import Project, python_config
from atwlib import config, gates

PROOF = "tests/test_sub.py::test_sub"
TEST_SUB = ("import sys, pathlib\n"
            "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))\n\n"
            "def test_sub():\n    from calc import sub\n    assert sub(5, 3) == 2\n")
CLEAN_REVIEW = "## Critical - blocks merge\n\n## Warning - blocks merge\n\n## Nit\n"
CHECKED = "## Checked\n- [x] sub(5, 3) == 2 - how: ran the CLI, saw 2\n## Failed - blocks close\n## Not run\n"


def verify_cfg(**verify) -> dict:
    return python_config(verify={"when": "big", "how": "run `python -m calc` and read the output",
                                 "min_planned_files": 8, "min_proof_ids": 8, "recheck_after_rounds": 2,
                                 "ignore": [], **verify})


class Verify(Project):
    config = verify_cfg(when="always", ignore=["test-results/"])

    def implemented(self, scope: str = "isolated") -> str:
        ref = self.run_ref(self.ok("start", "T-1", "--kind", "code", "--scope", scope))
        self.write("plan.md", "# Plan\n")
        self.ok("plan", "--run", ref, "--files", "src/calc.py,tests/test_sub.py",
                "--plan-file", "plan.md", "--approval", "yes")
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return None\n")
        self.write("tests/test_sub.py", TEST_SUB)
        self.ok("red", "--run", ref, "--test", PROOF)
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
        self.ok("gate", "--run", ref, "tests")
        return ref

    def report(self, cmd_out: str, body: str, field: str, who: str = "fresh-agent") -> str:
        packet = (self.root / re.search(r"packet: +(\S+)", cmd_out).group(1)).read_text(encoding="utf-8")
        pid = re.search(r"^packet: (\w+)", packet, re.M).group(1)
        path = re.search(r"^report: (\S+)", packet, re.M).group(1)
        self.write(path, f"packet: {pid}\n{field}: {who}\n\n{body}")
        return path

    def review(self, ref: str) -> None:
        out = self.ok("review-packet", "--run", ref)
        self.ok("accept-review", "--run", ref, "--report", self.report(out, CLEAN_REVIEW, "reviewer"))

    def test_close_needs_verify_and_it_runs_next_to_the_review(self):
        ref = self.implemented()
        v_out = self.ok("verify-packet", "--run", ref)     # both packets exist at once:
        r_out = self.ok("review-packet", "--run", ref)     # neither waits for the other
        packet_text = (self.root / re.search(r"packet: +(\S+)", v_out).group(1)).read_text(encoding="utf-8")
        self.assertIn("python -m calc", packet_text)       # the project's own check
        self.assertIn("sub(5, 3) == 2", packet_text)       # the ticket, verbatim
        self.assertNotIn("# Plan", packet_text)

        self.ok("accept-review", "--run", ref, "--report", self.report(r_out, CLEAN_REVIEW, "reviewer"))
        self.refused("close", "--run", ref, contains="verify")
        # Output of the check (its own folder, or a verify.ignore path) does not make the review stale.
        self.write(re.search(r"artifacts: +(\S+)", v_out).group(1) + "/shot.png", "png")
        self.write("test-results/trace.txt", "trace")
        self.assertEqual(json.loads(self.atw("status", "--run", ref, "--json").stdout)["gates"]["audit"]["state"],
                         "passed")
        self.ok("accept-verify", "--run", ref, "--report", self.report(v_out, CHECKED, "verifier"))
        self.ok("close", "--run", ref)

    def test_report_rules(self):
        ref = self.implemented()
        out = self.ok("verify-packet", "--run", ref)
        same = self.report(out, CHECKED, "verifier", who="other-implementer")
        self.refused("accept-verify", "--run", ref, "--report", same, contains="verifier")
        self.refused("accept-verify", "--run", ref, "--report",
                     self.report(out, "## Checked\n- [x] a\n", "verifier"), contains="headings")
        failed = self.report(out, "## Checked\n## Failed - blocks close\n- [ ] sub gives 8\n## Not run\n", "verifier")
        self.refused("accept-verify", "--run", ref, "--report", failed, contains="sub gives 8")
        self.refused("accept-verify", "--run", ref, "--report", failed, "--user-approved", "ok",
                     contains="failed")                    # a failure is never accepted away
        nothing = self.report(out, "## Checked\n## Failed - blocks close\n## Not run\n", "verifier")
        self.refused("accept-verify", "--run", ref, "--report", nothing, contains="Ask the user")

    def test_not_run_needs_the_users_words(self):
        ref = self.implemented()
        out = self.ok("verify-packet", "--run", ref)
        body = "## Checked\n## Failed - blocks close\n## Not run\n- [ ] sub(5, 3) - why: no app to run\n"
        path = self.report(out, body, "verifier")
        self.refused("accept-verify", "--run", ref, "--report", path, contains="--user-approved")
        self.ok("accept-verify", "--run", ref, "--report", path, "--user-approved", "fine, it is a library")
        run = json.loads(next((self.root / ".atw/runs/T-1").glob("*/run.json")).read_text(encoding="utf-8"))
        self.assertEqual(run["decisions"][-1]["verdict"], "accepted-tradeoff")
        self.assertEqual(run["gates"]["verify"]["state"], "passed")

    def test_edit_during_the_check_refuses_the_report(self):
        ref = self.implemented()
        out = self.ok("verify-packet", "--run", ref)
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return -(b - a)\n")
        self.refused("accept-verify", "--run", ref, "--report", self.report(out, CHECKED, "verifier"),
                     contains="diff changed")

    def test_many_review_rounds_make_it_stale(self):
        ref = self.implemented()
        out = self.ok("verify-packet", "--run", ref)
        self.ok("accept-verify", "--run", ref, "--report", self.report(out, CHECKED, "verifier"))
        self.review(ref)                                    # round 1: made with the check, does not count
        for n in (2, 3):                                    # two more rounds of changes
            self.write("src/calc.py", f"def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b + 0 * {n}\n")
            self.ok("gate", "--run", ref, "tests")
            self.review(ref)
            status = json.loads(self.atw("status", "--run", ref, "--json").stdout)
            self.assertEqual(status["gates"]["verify"]["state"], "passed" if n == 2 else "stale")
        self.refused("close", "--run", ref, contains="verify")


class WhenRequired(Project):
    config = verify_cfg()

    def test_big_is_coordinated_or_a_threshold(self):
        cfg = config.load(self.root)
        run = {"kind": "code", "scope": "isolated", "planned_files": ["a"], "proof_ids": ["t"]}
        self.assertNotIn("verify", gates.required_gates(run, cfg))
        self.assertIn("verify", gates.required_gates({**run, "scope": "coordinated"}, cfg))
        self.assertIn("verify", gates.required_gates({**run, "planned_files": list("abcdefgh")}, cfg))
        self.assertIn("verify", gates.required_gates({**run, "proof_ids": list("abcdefgh")}, cfg))
        off = {**cfg, "verify": {**cfg["verify"], "when": "off"}}
        self.assertNotIn("verify", gates.required_gates({**run, "scope": "coordinated"}, off))
        self.assertNotIn("verify", gates.required_gates({**run, "kind": "docs", "scope": "coordinated"}, cfg))

    def test_plan_announces_it_when_the_plan_is_big(self):
        ref = self.run_ref(self.ok("start", "T-1", "--kind", "code", "--scope", "isolated"))
        self.write("plan.md", "# Plan\n")
        files = ",".join(f"src/m{i}.py" for i in range(8))
        out = self.ok("plan", "--run", ref, "--files", files, "--plan-file", "plan.md", "--approval", "yes")
        self.assertIn("now required: verify", out)

    def test_default_config_requires_it_for_big_runs(self):
        self.assertEqual(config.DEFAULTS["verify"]["when"], "big")
        self.assertEqual(config.validate(config.load(self.root)), [])
        bad = {**config.load(self.root), "verify": {"when": "sometimes", "how": 1, "min_planned_files": 0,
                                                    "min_proof_ids": 8, "recheck_after_rounds": 2, "ignore": "x"}}
        self.assertEqual(len([e for e in config.validate(bad) if e.startswith("verify.")]), 4)
        for hole in (["."], ["./"], ["src/"], ["src/sub/"], [""]):  # would hide the change from the review
            cfg = {**config.load(self.root), "verify": {**config.DEFAULTS["verify"], "ignore": hole}}
            self.assertTrue(any("verify.ignore" in e for e in config.validate(cfg)), hole)
        ok = {**config.load(self.root), "verify": {**config.DEFAULTS["verify"], "ignore": ["test-results/"]}}
        self.assertEqual(config.validate(ok), [])

    def test_doctor_names_the_projects_own_check(self):
        self.write(".claude/skills/check-ui/SKILL.md",
                   "---\nname: check-ui\ndescription: x\n---\nStart the dev server and drive it with Playwright.\n")
        self.write_config(verify_cfg(how=""))
        out = self.atw("doctor").stdout
        self.assertIn("verify.how is empty", out)
        self.assertIn("check-ui", out)


if __name__ == "__main__":
    unittest.main()
