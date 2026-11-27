"""Run state: one JSON file per (ticket, run id), used by every harness.

Layout under `.atw/runs/` (gitignored):
  <ticket>/<run-id>/run.json           the run
  <ticket>/<run-id>/reviews/           review packets and reports
  <ticket>/<run-id>/simplify/          simplify packets and reports
  <ticket>/<run-id>/plan.md            copy of the approved plan (non-Claude hosts)
  sessions/<session>.txt               Claude session -> ticket binding
  planmode/ticket-<ticket>.txt         plan approval stamp for a bound session
  planmode/branch-<branch>.txt         plan approval stamp, branch fallback
  planmode/<key>.json                  how that approval came (route, answer, notes)
  planmode/proposed-<key>.txt          a plan was proposed (PreToolUse ExitPlanMode)
  planmode/declined-<key>.json         the last Decline or free-text answer to a proposal
  log.md                               one line per closed or aborted run

Several runs can be open at once (parallel sessions, one branch or many).
A run is chosen explicitly (`--run TICKET/RUN_ID`, `--ticket`, $ATW_RUN), or
by elimination when exactly one run is open on the current branch.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from . import util

RUNS_DIR = ".atw/runs"
SCHEMA_VERSION = 1
TICKET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
DECIDE_VERDICTS = ("false-positive", "accepted-tradeoff", "pre-existing", "settled-question")


class RunError(Exception):
    """A user-facing refusal. The CLI prints the message and exits 1."""


def runs_dir(root: Path) -> Path:
    return root / RUNS_DIR


def run_dir(root: Path, ticket: str, run_id: str) -> Path:
    return runs_dir(root) / util.slug(ticket) / util.slug(run_id)


def run_file(root: Path, ticket: str, run_id: str) -> Path:
    return run_dir(root, ticket, run_id) / "run.json"


def validate_ticket(ticket: str) -> str:
    if not TICKET_ID.fullmatch(ticket or ""):
        raise RunError(f"ticket id '{ticket}' must be 1-64 letters, digits, '.', '_' or '-'")
    return ticket


def new_run_id(ticket: str) -> str:
    return f"{util.slug(ticket)}-{uuid.uuid4().hex[:6]}"


def new_run(root: Path, *, ticket: str, ticket_path: str, kind: str, scope: str | None,
            host: str, actor: str, run_id: str) -> dict:
    now = util.now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "ticket": ticket,
        "run_id": run_id,
        "ticket_path": ticket_path,
        "kind": kind,
        "scope": scope,
        "kind_history": [{"kind": kind, "scope": scope, "why": "initial", "ts": now}],
        "host": host,
        "actor": actor,
        "branch": util.current_branch(root),
        "baseline_ref": util.head_sha(root),
        # Files already untracked at start are never attributed to this run.
        "baseline_untracked": util.untracked_files(root),
        "started_at_epoch": util.now_epoch(),
        "status": "open",
        "planned_files": [],
        "plan": None,
        "proof_ids": [],
        # Settled ground: the review must not re-raise these. See `decide`.
        "decisions": [],
        "gates": {},
        "context_update": None,
        "consecutive_blocks": 0,
        "last_unmet_signature": None,
        "created_at": now,
        "updated_at": now,
    }


def save(root: Path, run: dict) -> None:
    run["updated_at"] = util.now_iso()
    util.write_json(run_file(root, run["ticket"], run["run_id"]), run)


def load(root: Path, ticket: str, run_id: str) -> dict | None:
    data = util.read_json(run_file(root, ticket, run_id))
    return data if isinstance(data, dict) else None


def all_runs(root: Path) -> list[dict]:
    out = []
    base = runs_dir(root)
    if not base.is_dir():
        return out
    for p in base.glob("*/*/run.json"):
        data = util.read_json(p)
        if isinstance(data, dict) and data.get("ticket") and data.get("run_id"):
            out.append(data)
    return sorted(out, key=lambda r: r.get("started_at_epoch", 0))


def open_runs(root: Path, *, ticket: str | None = None, branch: str | None = None) -> list[dict]:
    return [r for r in all_runs(root)
            if r.get("status") == "open"
            and (ticket is None or r.get("ticket") == ticket)
            and (branch is None or r.get("branch") == branch)]


def resolve(root: Path, *, run_ref: str | None = None, ticket: str | None = None,
            env_ref: str | None = None) -> dict:
    """Pick the run a command acts on, or raise RunError naming the choices."""
    ref = run_ref or env_ref
    if ref:
        if "/" not in ref:
            raise RunError(f"--run must be TICKET/RUN_ID, got '{ref}'")
        t, r = ref.split("/", 1)
        run = load(root, t, r)
        if not run:
            raise RunError(f"no run {ref}")
        return run
    if ticket:
        runs = open_runs(root, ticket=ticket)
        if len(runs) == 1:
            return runs[0]
        if not runs:
            raise RunError(f"no open run for ticket {ticket} - use `atw start {ticket} --kind <kind>`")
        raise RunError("ambiguous: several open runs for this ticket - pass --run with one of: "
                       + ", ".join(f"{r['ticket']}/{r['run_id']}" for r in runs))
    branch = util.current_branch(root)
    runs = open_runs(root, branch=branch)
    if len(runs) == 1:
        return runs[0]
    if not runs:
        raise RunError(f"no open run on branch '{branch}' - pass --run or --ticket, or `atw start` first")
    raise RunError(f"ambiguous: {len(runs)} open runs on branch '{branch}' - pass --run with one of: "
                   + ", ".join(f"{r['ticket']}/{r['run_id']}" for r in runs))


def append_decision(run: dict, item: str, verdict: str, why: str) -> bool:
    """Record a settled finding or question. Same `item` (case-insensitive)
    updates in place. Returns True for a new entry."""
    if verdict not in DECIDE_VERDICTS:
        raise RunError(f"verdict must be one of {DECIDE_VERDICTS}")
    entry = {"item": item, "verdict": verdict, "why": why, "ts": util.now_iso()}
    decisions = run.setdefault("decisions", [])
    for i, existing in enumerate(decisions):
        if existing["item"].strip().lower() == item.strip().lower():
            decisions[i] = entry
            return False
    decisions.append(entry)
    return True


def append_log(root: Path, run: dict, note: str = "") -> None:
    line = (f"- {run['ticket']} | run={run['run_id']} | kind={run['kind']}"
            f"{'/' + run['scope'] if run.get('scope') else ''} | status={run['status']}"
            f" | host={run.get('host')} | branch={run.get('branch')} | at={util.now_iso()}")
    if note:
        line += f" | {note}"
    path = runs_dir(root) / "log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Claude session binding and plan-mode stamps
# ---------------------------------------------------------------------------

def session_path(root: Path, session_id: str) -> Path:
    return runs_dir(root) / "sessions" / f"{util.slug(session_id)}.txt"


def bind_session(root: Path, session_id: str, ticket: str) -> None:
    util.atomic_write_text(session_path(root, session_id), ticket)


def session_ticket(root: Path, session_id: str | None) -> str | None:
    if not session_id:
        return None
    try:
        return session_path(root, session_id).read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def clear_session_bindings(root: Path, ticket: str) -> None:
    d = runs_dir(root) / "sessions"
    for p in d.glob("*.txt") if d.is_dir() else []:
        try:
            if p.read_text(encoding="utf-8").strip() == ticket:
                p.unlink()
        except Exception:
            continue


def planmode_ticket_path(root: Path, ticket: str) -> Path:
    return runs_dir(root) / "planmode" / f"ticket-{util.slug(ticket)}.txt"


def planmode_branch_path(root: Path, branch: str) -> Path:
    return runs_dir(root) / "planmode" / f"branch-{util.slug(branch)}.txt"


def planmode_key_path(root: Path, key: str) -> Path:
    """The approval stamp for a key from `planmode_key` ("ticket-X" / "branch-Y")."""
    return runs_dir(root) / "planmode" / f"{key}.txt"


def planmode_route_path(stamp: Path) -> Path:
    return stamp.with_suffix(".json")


def proposed_path(root: Path, key: str) -> Path:
    return runs_dir(root) / "planmode" / f"proposed-{key}.txt"


def declined_path(root: Path, key: str) -> Path:
    return runs_dir(root) / "planmode" / f"declined-{key}.json"


def planmode_key(root: Path, session_id: str | None) -> str | None:
    """Which plan stamps a hook of this session reads and writes, or None.

    A bound session uses its own ticket's stamps only: its plan mode must
    never pass the plan gate of a run that it does not drive. An unbound
    session uses the branch's stamps, and only when the branch has an open
    run that no session drives (`run_for_hook`)."""
    ticket = session_ticket(root, session_id)
    if ticket:
        return f"ticket-{util.slug(ticket)}"
    if run_for_hook(root, session_id):
        return f"branch-{util.slug(util.current_branch(root))}"
    return None


def _stamp_epoch(path: Path) -> float | None:
    try:
        return util.epoch_of_iso(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_approval(root: Path, key: str, route: str, **detail) -> None:
    """The approval stamp `atw plan` checks, plus a record of its route
    (`exit-plan-mode` or `ask-approve`). The record names the stamp it
    belongs to, so an older record is never read as the route of a newer stamp."""
    stamp = util.now_iso()
    path = planmode_key_path(root, key)
    util.write_json(planmode_route_path(path), {"route": route, "stamp": stamp, **detail})
    util.atomic_write_text(path, stamp)


def planmode_approval(root: Path, ticket: str, branch: str) -> tuple[float | None, dict]:
    """(epoch, route record) of the last plan approval for this ticket's
    session, else for the branch. A stamp without a matching record is an
    ExitPlanMode stamp from before routes were recorded."""
    for p in (planmode_ticket_path(root, ticket), planmode_branch_path(root, branch)):
        value = _stamp_epoch(p)
        if value is None:
            continue
        record = util.read_json(planmode_route_path(p), default=None)
        try:
            text = p.read_text(encoding="utf-8").strip()
        except Exception:
            text = None
        if not isinstance(record, dict) or record.get("stamp") != text:
            record = {"route": "exit-plan-mode"}
        return value, record
    return None, {}


def planmode_epoch(root: Path, ticket: str, branch: str) -> float | None:
    """Last real plan approval for this ticket's session, else for the branch."""
    return planmode_approval(root, ticket, branch)[0]


def pending_proposal(root: Path, key: str, run: dict) -> float | None:
    """The epoch of a plan proposal that waits for the user's answer: made
    after the run started, and after the last approval and the last decline
    for this key. A proposal is consumed by either answer."""
    proposed = _stamp_epoch(proposed_path(root, key))
    if proposed is None or proposed < (run.get("started_at_epoch") or 0):
        return None
    approved = _stamp_epoch(planmode_key_path(root, key))
    if approved is not None and approved >= proposed:
        return None
    declined = util.read_json(declined_path(root, key), default=None)
    declined_at = util.epoch_of_iso(str(declined.get("ts", ""))) if isinstance(declined, dict) else None
    if declined_at is not None and declined_at >= proposed:
        return None
    return proposed


def clear_session(root: Path, session_id: str) -> None:
    try:
        session_path(root, session_id).unlink()
    except Exception:
        pass


def bound_tickets(root: Path) -> set[str]:
    """Every ticket that some session is bound to. A binding file cannot tell
    whether its session is still alive, so any binding counts as live. Close
    and abort remove the bindings of their ticket, and a session that finds
    its own binding stale removes it (see `run_for_hook`)."""
    d = runs_dir(root) / "sessions"
    out: set[str] = set()
    for p in d.glob("*.txt") if d.is_dir() else []:
        try:
            value = p.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if value:
            out.add(value)
    return out


def run_for_hook(root: Path, session_id: str | None) -> dict | None:
    """The run a Claude hook acts on. Never raises.

    - A session bound to a ticket gets that ticket's newest open run. If the
      ticket has no open run, the binding is stale: it is removed and the
      result is None. It never falls back to the branch, because that would
      gate this session with a run that another session drives.
    - An unbound session gets the newest open run on the current branch whose
      ticket no session is bound to. Several sessions (for example T3 Code
      threads) can share one checkout and branch; a ticket that another
      session drives never gates this one.
    """
    try:
        bound = session_ticket(root, session_id)
        if bound:
            runs = open_runs(root, ticket=bound)
            if runs:
                return runs[-1]
            clear_session(root, session_id)
            return None
        taken = bound_tickets(root)
        runs = [r for r in open_runs(root, branch=util.current_branch(root)) if r.get("ticket") not in taken]
        return runs[-1] if runs else None
    except Exception:
        return None
