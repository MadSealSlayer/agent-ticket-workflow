"""Non-code kinds: nocode, placement, provenance."""
from __future__ import annotations

import unittest

from _helpers import Project

GOOD = """# T-1 investigation

Average latency is 120 ms (measured) [q1].
The spike likely comes from cold starts (inferred) [q1].

## Sources
- [q1] logs query, 2026-10-01..03
"""


class Investigation(Project):

    def start(self) -> str:
        return self.run_ref(self.ok("start", "T-1", "--kind", "investigation"))

    def test_good_investigation_closes(self):
        ref = self.start()
        self.write("docs/agent-notes/investigations/T-1-latency.md", GOOD)
        self.ok("close", "--run", ref)

    def test_touching_source_fails_nocode(self):
        ref = self.start()
        self.write("docs/agent-notes/investigations/T-1-latency.md", GOOD)
        self.write("src/calc.py", "def add(a, b):\n    return 0\n")
        out = self.refused("close", "--run", ref, contains="nocode")
        self.assertIn("src/calc.py", out)

    def test_needs_ticket_id_in_filename(self):
        ref = self.start()
        self.write("docs/agent-notes/investigations/latency.md", GOOD)
        self.refused("close", "--run", ref, contains="placement")

    def test_wrong_folder_under_docs(self):
        ref = self.start()
        self.write("docs/agent-notes/investigations/T-1-latency.md", GOOD)
        self.write("docs/T-1-notes.md", GOOD)
        self.refused("close", "--run", ref, contains="committed docs folder")

    def test_untagged_or_uncited_claims_fail_provenance(self):
        ref = self.start()
        self.write("docs/agent-notes/investigations/T-1-latency.md",
                   "# x\nLatency is 120 ms (measured).\n\n## Sources\n- [q1] logs\n")
        self.refused("close", "--run", ref, contains="provenance")

    def test_preexisting_untracked_file_is_not_attributed(self):
        self.write("src/scratch.py", "x = 1\n")  # untracked before start
        ref = self.start()
        self.write("docs/agent-notes/investigations/T-1-latency.md", GOOD)
        self.ok("close", "--run", ref)


class Comms(Project):

    def test_comms_needs_only_placement(self):
        ref = self.run_ref(self.ok("start", "T-1", "--kind", "comms"))
        self.refused("close", "--run", ref, contains="placement")
        self.write("docs/agent-notes/comms/T-1-reply.md", "Hi, short answer: yes.\n")
        self.ok("close", "--run", ref)


class KindsConfig(Project):

    def test_disabled_kind_is_refused(self):
        self.refused("start", "T-1", "--kind", "spike", contains="not enabled")

    def test_missing_ticket_file(self):
        self.refused("start", "T-404", "--kind", "comms", contains="no ticket file")


if __name__ == "__main__":
    unittest.main()


class ConsoleEncoding(Project):
    """A Windows console code page cannot print everything gate output quotes."""

    def test_output_survives_a_narrow_console_encoding(self):
        self.ok("start", "T-1", "--kind", "tooling")
        r = self.atw("decide", "--item", "✔ ok ś", "--verdict", "settled-question", "--why", "test",
                     env={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
