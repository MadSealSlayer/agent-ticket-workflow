"""Run state: one JSON file per (ticket, run id), used by every harness.

Layout under `.atw/runs/` (gitignored):
  <ticket>/<run-id>/run.json           the run
  <ticket>/<run-id>/reviews/           review packets and reports
  <ticket>/<run-id>/simplify/          simplify packets and reports
  <ticket>/<run-id>/plan.md            copy of the approved plan (non-Claude hosts)
  sessions/<session>.txt               Claude session -> ticket binding
  planmode/ticket-<ticket>.txt         ExitPlanMode stamp for a bound session
  planmode/branch-<branch>.txt         ExitPlanMode stamp, branch fallback
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


def planmode_epoch(root: Path, ticket: str, branch: str) -> float | None:
    """Last real ExitPlanMode for this ticket's session, else for the branch."""
    for p in (planmode_ticket_path(root, ticket), planmode_branch_path(root, branch)):
        try:
            value = util.epoch_of_iso(p.read_text(encoding="utf-8"))
        except Exception:
            value = None
        if value is not None:
            return value
    return None


def run_for_hook(root: Path, session_id: str | None) -> dict | None:
    """The run a Claude hook acts on: this session's bound ticket first, else
    the most recently started open run on the current branch. Never raises."""
    try:
        bound = session_ticket(root, session_id)
        if bound:
            runs = open_runs(root, ticket=bound)
            return runs[-1] if runs else None
        runs = open_runs(root, branch=util.current_branch(root))
        return runs[-1] if runs else None
    except Exception:
        return None
