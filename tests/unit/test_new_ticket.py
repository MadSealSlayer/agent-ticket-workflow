"""`atw new-ticket`: a ticket from the settled conversation, written once."""
from __future__ import annotations

import datetime
import unittest

from _helpers import Project, python_config

from atwlib import config

BODY = """## Problem / goal

Users cannot subtract.

## Settled decisions

- Negative results are allowed (the user: "keep it simple").

## Acceptance criteria

1. sub(5, 3) == 2

## Out of scope

(none)

## Open questions

(none)
"""


def cfg_with(**new) -> dict:
    cfg = python_config()
    cfg["tickets"] = {"globs": ["tickets/**/ticket-{id}.md", "tickets/**/{id}.md"],
                      "new": {"path": "tickets/{lo}-{hi}/ticket-{id}.md", "id_format": "{n:03d}",
                              "range_size": 100, **new}}
    return cfg


class NewTicket(Project):
    config = cfg_with()

    def body(self, text: str = BODY) -> str:
        self.write("scratch/body.md", text)
        return "scratch/body.md"

    def test_next_number_ignores_side_files_and_other_ids(self):
        self.write("tickets/1-100/ticket-027.md", "x\n")
        self.write("tickets/1-100/ticket-027-summary.md", "x\n")
        self.write("tickets/ABC-12.md", "x\n")
        out = self.ok("new-ticket", "--title", "Add  sub", "--body-file", self.body())
        self.assertIn("created 028 at tickets/1-100/ticket-028.md", out)
        self.assertIn("atw start 028 --kind", out)
        text = (self.root / "tickets/1-100/ticket-028.md").read_text(encoding="utf-8")
        self.assertEqual(text, f"Source: conversation {datetime.date.today().isoformat()}\n# Add sub\n\n{BODY}")
        # The new ticket can be started by its id.
        self.ok("start", "028", "--kind", "investigation")

    def test_range_bucket_rolls_over(self):
        self.write("tickets/1-100/ticket-100.md", "x\n")
        out = self.ok("new-ticket", "--title", "t", "--body-file", self.body())
        self.assertIn("tickets/101-200/ticket-101.md", out)

    def test_first_ticket_and_dry_run(self):
        out = self.ok("new-ticket", "--title", "t", "--body-file", self.body(), "--dry-run")
        self.assertIn("would create 001 at tickets/1-100/ticket-001.md", out)
        self.assertFalse((self.root / "tickets/1-100").exists())

    def test_refusals(self):
        self.refused("new-ticket", "--title", " ", "--body-file", self.body(), contains="--title")
        self.refused("new-ticket", "--title", "t", "--body-file", self.body("  \n"), contains="empty")
        self.refused("new-ticket", "--title", "t", "--body-file", self.body("# Title\n\n" + BODY),
                     contains="Source line and the title")
        self.refused("new-ticket", "--title", "t", "--body-file", self.body("## Problem / goal\n\nx\n"),
                     contains="## Acceptance criteria")
        self.refused("new-ticket", "--title", "t", "--body-file", "scratch/missing.md", contains="cannot read")

    def test_existing_file_is_never_overwritten(self):
        # A non-numeric id format is not counted, so the next path can already exist.
        self.write_config(cfg_with(path="tickets/ticket-{id}.md", id_format="N{n}"))
        self.write("tickets/ticket-N1.md", "hand written\n")
        self.refused("new-ticket", "--title", "t", "--body-file", self.body(), contains="never overwritten")
        self.refused("new-ticket", "--title", "t", "--body-file", self.body(), "--dry-run",
                     contains="never overwritten")
        self.assertEqual((self.root / "tickets/ticket-N1.md").read_text(encoding="utf-8"), "hand written\n")

    def test_path_outside_the_globs_is_refused(self):
        self.write_config(cfg_with(path="elsewhere/ticket-{id}.md"))
        self.refused("new-ticket", "--title", "t", "--body-file", self.body(), contains="not matched by tickets.globs")


class NewTicketConfig(unittest.TestCase):

    def errors(self, **new) -> list[str]:
        cfg = config._merge(config.DEFAULTS, {"tickets": {"new": new}})
        return [e for e in config.validate(cfg) if "tickets.new" in e]

    def test_defaults_are_valid(self):
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.errors(path="local_tickets/{lo:03d}-{hi:03d}/ticket-{id}.md"), [])

    def test_problems(self):
        self.assertTrue(self.errors(path="tickets/ticket.md"))           # no {id}
        self.assertTrue(self.errors(path="../tickets/ticket-{id}.md"))    # outside the project
        self.assertTrue(self.errors(path="tickets/{nope}/ticket-{id}.md"))
        self.assertTrue(self.errors(id_format="ticket"))                  # no {n}
        self.assertTrue(self.errors(id_format="{n:03d}/x"))               # not a valid id
        self.assertTrue(self.errors(range_size=0))
        self.assertTrue(self.errors(range_size=True))


class AuditConfig(unittest.TestCase):

    def errors(self, **audit) -> list[str]:
        cfg = config._merge(config.DEFAULTS, {"audit": audit})
        return [e for e in config.validate(cfg) if e.startswith("audit")]

    def test_defaults_and_t3_route_are_valid(self):
        self.assertEqual(config.DEFAULTS["audit"]["route"], "agent")
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.errors(route="t3-delegate", t3={"provider": "codex", "model": "m",
                                                              "reasoning_effort": "high"}), [])

    def test_problems(self):
        self.assertTrue(self.errors(route="codex"))
        self.assertTrue(self.errors(t3={"provider": "codex", "model": "", "reasoning_effort": "medium"}))
        self.assertTrue(self.errors(t3="codex"))


if __name__ == "__main__":
    unittest.main()
