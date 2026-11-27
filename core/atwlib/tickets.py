"""Create a local ticket from a settled conversation (`atw new-ticket`).

The agent drafts the ticket from what the user agreed to and shows it. Only
after the user's explicit yes does it write the body to a file and call this
module. The ticket text never goes on a command line, where it could reach a
shell.

The file gets the next free number among the existing tickets, is written
once (exclusive create) and is never changed by the workflow afterwards. Line
1 marks where it came from, like the `Jira:` line of an imported ticket:

    Source: conversation <YYYY-MM-DD>
    # <title>

    <body: ## Problem / goal, ## Settled decisions, ## Acceptance criteria,
     ## Out of scope, ## Open questions>
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from . import jira, state, util

SOURCE_PREFIX = "Source: conversation"
REQUIRED_SECTIONS = ("Problem / goal", "Settled decisions", "Acceptance criteria", "Out of scope",
                     "Open questions")


class NewTicketError(Exception):
    """A refusal with a message for the user."""


def _glob_regex(glob: str) -> re.Pattern:
    """`tickets/**/ticket-{id}.md` -> a regex whose group 1 is the id."""
    out, i = "", 0
    g = util.posix(glob)
    while i < len(g):
        if g.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif g.startswith("{id}", i):
            out, i = out + "([^/]+)", i + 4
        elif g[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif g[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(g[i]), i + 1
    return re.compile(out)


def existing_numbers(root: Path, globs) -> set[int]:
    """Numeric ids of the ticket files that `tickets.globs` finds. Other ids
    (Jira keys, `T-1`) and side files (`ticket-027-summary.md`) are ignored."""
    numbers: set[int] = set()
    for g in globs or ():
        rx = _glob_regex(g)
        for p in root.glob(util.posix(g).replace("{id}", "*")):
            if not p.is_file():
                continue
            m = rx.fullmatch(util.rel(root, p))
            if m and m.group(1).isdigit():
                numbers.add(int(m.group(1)))
    return numbers


def plan_path(root: Path, cfg: dict) -> tuple[str, str]:
    """(ticket id, repo-relative path) for the next new ticket."""
    new = cfg["tickets"]["new"]
    n = max(existing_numbers(root, cfg["tickets"]["globs"]), default=0) + 1
    size = new["range_size"]
    lo = (n - 1) // size * size + 1
    ticket_id = new["id_format"].format(n=n)
    state.validate_ticket(ticket_id)
    rel_path = util.posix(new["path"].format(id=ticket_id, n=n, lo=lo, hi=lo + size - 1))
    return ticket_id, rel_path


def check_body(body: str) -> None:
    if not body.strip():
        raise NewTicketError("the ticket body is empty")
    first = next((line for line in body.splitlines() if line.strip()), "")
    if first.startswith(SOURCE_PREFIX) or re.match(r"#\s", first):
        raise NewTicketError("the body starts at `## Problem / goal`: new-ticket writes the Source line and "
                             "the title itself")
    headings = {h.strip().lower() for h in re.findall(r"^##\s+(.+?)\s*$", body, re.MULTILINE)}
    missing = [s for s in REQUIRED_SECTIONS if s.lower() not in headings]
    if missing:
        raise NewTicketError("the body is missing these sections: " + ", ".join(f"## {s}" for s in missing)
                             + ' (write "(none)" under a section that has nothing)')


def render(title: str, body: str, today: date | None = None) -> str:
    return f"{SOURCE_PREFIX} {(today or date.today()).isoformat()}\n# {title}\n\n{body.strip()}\n"


def create(root: Path, cfg: dict, title: str, body: str, dry_run: bool = False) -> tuple[str, str]:
    """Write the ticket (unless `dry_run`) and return (id, repo-relative path)."""
    title = " ".join((title or "").split())
    if not title:
        raise NewTicketError("--title must not be empty")
    check_body(body)
    ticket_id, rel_path = plan_path(root, cfg)
    if not jira.matched_by_globs(rel_path, cfg["tickets"]["globs"], ticket_id):
        raise NewTicketError(f"{rel_path} is not matched by tickets.globs, so `atw start {ticket_id}` would not "
                             "find it - fix tickets.new.path or tickets.globs")
    path = root / rel_path
    if dry_run:
        if path.exists():
            raise NewTicketError(f"{rel_path} already exists - it is never overwritten")
        return ticket_id, rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as f:
            f.write(render(title, body))
    except FileExistsError:
        raise NewTicketError(f"{rel_path} already exists - it is never overwritten")
    return ticket_id, rel_path
