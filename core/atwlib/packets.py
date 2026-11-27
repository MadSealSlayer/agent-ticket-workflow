"""Clean-room review and simplify packets.

The reviewer must not inherit the author's reasoning. A packet carries only:
  - the diff since the run's baseline (as a patch file),
  - the ticket's requirements (the ticket file, verbatim),
  - the settled decisions (what is closed and why the human chose it),
  - on round 2+, the previous report's open items (delta mode).
It never carries the plan, the author's notes, or a claim that tests pass.

Each packet is bound to the diff's hash. A report is accepted only for a
packet whose diff still matches the working tree, so any edit after the
review makes it stale by construction.

Report format (markdown), checked by `parse_report`:
    packet: <packet id>
    reviewer: <reviewer id, different from the implementer>
    ## Critical - blocks merge
    - [ ] ...            (open)      - [x] ...  (fixed)
    ## Warning - blocks merge
    ## Nit
Both Critical and Warning headings must be present, even when empty, so an
empty report can never be mistaken for a clean one.

The verification packet (`verify` gate) is bound the same way, but its agent
RUNS the change (integration, browser, end-to-end) instead of reading it:
    packet: <packet id>
    verifier: <id, different from the implementer>
    ## Checked                     - [x] <criterion> - how: <what ran, what was seen>
    ## Failed - blocks close       - [ ] <criterion> - <what happened instead>
    ## Not run                     - [ ] <criterion> - why: <reason>
Open Failed items block. Open Not-run items block unless the user accepts
them in their own words. The verifier writes only into its own folder, so
the review of the same diff can run at the same time.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from . import gates, state, util

_SECTION = re.compile(r"^#{2,6}\s+(.*)$", re.MULTILINE)
_OPEN = re.compile(r"^\s*-\s*\[\s\]\s*(.*)$", re.MULTILINE)
_DONE = re.compile(r"^\s*-\s*\[[xX]\]", re.MULTILINE)
_FIELD = re.compile(r"^\s*(packet|reviewer|agent|verifier)\s*:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)


def fields(text: str) -> dict:
    return {k.lower(): v for k, v in _FIELD.findall(text)}


def parse_report(text: str) -> dict:
    sections = _sections(text)

    def find(label):
        for title, body in sections.items():
            if label in title:
                return body
        return None

    out = {"fields": fields(text)}
    for label in ("critical", "warning", "nit"):
        body = find(label)
        out[f"{label}_present"] = body is not None
        out[f"{label}_open"] = [s.strip() for s in _OPEN.findall(body or "")]
        out[f"{label}_done"] = len(_DONE.findall(body or ""))
    return out


def _dir(root: Path, run: dict, sub: str) -> Path:
    d = state.run_dir(root, run["ticket"], run["run_id"]) / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ticket_text(root: Path, run: dict) -> str:
    try:
        return (root / run["ticket_path"]).read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return f"(ticket file {run.get('ticket_path')} could not be read)"


def _decisions_md(run: dict) -> str:
    items = run.get("decisions") or []
    if not items:
        return "_None._"
    return "\n".join(f"- **{d['verdict']}**: {d['item']} - {d['why']}" for d in items)


# --------------------------------------------------------------------------- review

def _require_gates_before_review(root: Path, cfg: dict, run: dict, what: str) -> None:
    report = gates.evaluate_required(root, cfg, run)
    blocking = [n for n in ("plan", "red", "tests", "lint", "deps", "simplify")
                if n in report and report[n]["state"] != "passed"]
    if blocking:
        raise state.RunError(f"{what} refused - these gates must pass first: "
                             + "; ".join(f"{n} ({report[n]['reason']})" for n in blocking))


def _sections(text: str) -> dict:
    out = {}
    matches = list(_SECTION.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[m.group(1).strip().lower()] = text[m.end():end]
    return out


def review_packet(root: Path, cfg: dict, run: dict) -> dict:
    if run.get("kind") != "code":
        raise state.RunError("a clean-room review applies to code runs only")
    _require_gates_before_review(root, cfg, run, "review")
    rounds = run.setdefault("review_rounds", [])
    n = len(rounds) + 1
    d = _dir(root, run, "reviews")
    patch = gates.diff_text(root, cfg, run)
    sha = util.sha256_bytes(patch.encode("utf-8"))
    packet_id = uuid.uuid4().hex[:12]
    patch_path = d / f"review-{n}.diff.patch"
    packet_path = d / f"review-{n}.packet.md"
    report_path = d / f"review-{n}.report.md"
    patch_path.write_text(patch, encoding="utf-8", newline="\n")

    delta = ""
    if rounds:
        prev = rounds[-1]
        prev_open = prev.get("open_items") or []
        delta = (
            "\n## Delta mode (round {n})\n\n"
            "Review ONLY: (1) whether each open item below is resolved, and (2) the lines that changed "
            "since the previous round (compare with `{prev_patch}`).\n\nOpen items from round {p}:\n{items}\n"
        ).format(n=n, p=prev["round"], prev_patch=util.rel(root, d / f"review-{prev['round']}.diff.patch"),
                 items="\n".join(f"- {i}" for i in prev_open) or "- (none recorded)")

    body = f"""packet: {packet_id}
ticket: {run['ticket']}
run: {run['run_id']}
round: {n}
implementer: {run.get('actor')}
diff_sha256: {sha}
patch: {util.rel(root, patch_path)}
report: {util.rel(root, report_path)}

# Clean-room review packet

You are reviewing a change you did not write. Use only this packet, the patch
file, and the repository itself. Do not ask for, or read, the author's plan or
reasoning. Follow the ticket-audit skill for the five checks and the report format.

## Requirements (ticket, verbatim)

{_ticket_text(root, run)}

## Settled decisions (do not re-raise)

{_decisions_md(run)}
{delta}
## Report

Write the report to `{util.rel(root, report_path)}`. Its first lines must be:

    packet: {packet_id}
    reviewer: <your reviewer id - not "{run.get('actor')}">

and it must contain `## Critical - blocks merge`, `## Warning - blocks merge`
and `## Nit` headings (keep a heading even when it has no items), with each
finding as a `- [ ]` checkbox.
"""
    packet_path.write_text(body, encoding="utf-8", newline="\n")
    rounds.append({"round": n, "packet_id": packet_id, "diff_sha": sha, "created_at": util.now_iso(),
                   "packet": util.rel(root, packet_path), "report": util.rel(root, report_path)})
    state.save(root, run)
    return {"round": n, "packet_id": packet_id, "packet": util.rel(root, packet_path),
            "report": util.rel(root, report_path), "patch": util.rel(root, patch_path), "diff_sha": sha}


def accept_review(root: Path, cfg: dict, run: dict, report_path: Path,
                  override_items: str | None = None, user_approval: str | None = None) -> dict:
    if not report_path.is_file():
        raise state.RunError(f"report not found: {report_path}")
    text = report_path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_report(text)
    pid = parsed["fields"].get("packet")
    rnd = next((r for r in run.get("review_rounds") or [] if r["packet_id"] == pid), None)
    if not rnd:
        raise state.RunError("the report's `packet:` line does not match any packet of this run")
    reviewer = parsed["fields"].get("reviewer")
    if not reviewer or reviewer == run.get("actor"):
        raise state.RunError("the report needs a `reviewer:` line naming a reviewer other than the implementer")
    if not (parsed["critical_present"] and parsed["warning_present"]):
        raise state.RunError("the report must keep both the Critical and the Warning headings - "
                             "an unreadable report is never treated as clean")
    if rnd["diff_sha"] != gates.diff_sha(root, cfg, run):
        raise state.RunError("the diff changed after this packet was made - run `atw review-packet` again")
    open_items = [f"Critical: {i}" for i in parsed["critical_open"]] + [f"Warning: {i}" for i in parsed["warning_open"]]
    rnd["open_items"] = open_items
    rnd["reviewer"] = reviewer
    evidence = {"report": util.rel(root, report_path), "packet_id": pid, "round": rnd["round"],
                "reviewer": reviewer, "diff_sha": rnd["diff_sha"], "nit_open": len(parsed["nit_open"])}
    if open_items and parsed["critical_open"]:
        override_items = None  # a Critical item is never overridable
    if open_items and not (override_items and user_approval):
        run.setdefault("gates", {})["audit"] = {"state": "failed", "by": "script", "ts": util.now_iso(),
                                                "reason": f"{len(open_items)} open blocking item(s)",
                                                "evidence": evidence}
        state.save(root, run)
        raise state.RunError("review has open blocking items - fix them, then make a new packet:\n  "
                             + "\n  ".join(open_items))
    reason = f"clean per review round {rnd['round']} ({len(parsed['nit_open'])} nit open)"
    if open_items:
        reason = f"open Warning(s) accepted by the user: {override_items}"
        evidence["override"] = {"items": override_items, "user_approval": user_approval}
        state.append_decision(run, override_items, "accepted-tradeoff", f"user approved: {user_approval}")
    run.setdefault("gates", {})["audit"] = {"state": "passed", "by": "script", "ts": util.now_iso(),
                                            "reason": reason, "evidence": evidence}
    state.save(root, run)
    return {"reason": reason, **evidence}


# --------------------------------------------------------------------------- simplify

def simplify_packet(root: Path, cfg: dict, run: dict) -> dict:
    if run.get("kind") != "code":
        raise state.RunError("simplify applies to code runs only")
    rounds = run.setdefault("simplify_rounds", [])
    n = len(rounds) + 1
    d = _dir(root, run, "simplify")
    patch = gates.diff_text(root, cfg, run)
    packet_id = uuid.uuid4().hex[:12]
    patch_path = d / f"simplify-{n}.diff.patch"
    packet_path = d / f"simplify-{n}.packet.md"
    report_path = d / f"simplify-{n}.report.md"
    patch_path.write_text(patch, encoding="utf-8", newline="\n")
    packet_path.write_text(f"""packet: {packet_id}
ticket: {run['ticket']}
run: {run['run_id']}
implementer: {run.get('actor')}
patch: {util.rel(root, patch_path)}
report: {util.rel(root, report_path)}

# Simplify packet

Read the patch and propose simplifications that keep behavior identical: less
code, fewer abstractions, clearer names, reuse of existing helpers. Do not
propose new features. Write `{util.rel(root, report_path)}` starting with

    packet: {packet_id}
    agent: <your id - not "{run.get('actor')}">

then `## Recommendations` with one `- [ ] R<n>: <location> - <proposal> - <why behavior is preserved>`
per item (or the line `- none`). The implementer then ticks each box and
appends `applied` or `declined: <reason>`.
""", encoding="utf-8", newline="\n")
    rounds.append({"round": n, "packet_id": packet_id, "report": util.rel(root, report_path)})
    state.save(root, run)
    return {"round": n, "packet_id": packet_id, "packet": util.rel(root, packet_path),
            "report": util.rel(root, report_path)}


def accept_simplify(root: Path, run: dict, report_path: Path) -> dict:
    if not report_path.is_file():
        raise state.RunError(f"report not found: {report_path}")
    text = report_path.read_text(encoding="utf-8", errors="replace")
    f = fields(text)
    rnd = next((r for r in run.get("simplify_rounds") or [] if r["packet_id"] == f.get("packet")), None)
    if not rnd:
        raise state.RunError("the report's `packet:` line does not match any simplify packet of this run")
    if not f.get("agent") or f["agent"] == run.get("actor"):
        raise state.RunError("the report needs an `agent:` line naming a simplifier other than the implementer")
    if not re.search(r"^#{2,6}\s+Recommendations", text, re.MULTILINE | re.IGNORECASE):
        raise state.RunError("the report needs a `## Recommendations` section")
    open_items = _OPEN.findall(text)
    if open_items:
        raise state.RunError("every recommendation needs a decision - tick it and add `applied` or "
                             "`declined: <reason>`:\n  " + "\n  ".join(open_items))
    run.setdefault("gates", {})["simplify"] = {
        "state": "passed", "by": "script", "ts": util.now_iso(),
        "reason": f"simplify round {rnd['round']} dispositioned",
        "evidence": {"report": util.rel(root, report_path), "packet_id": rnd["packet_id"], "agent": f["agent"]}}
    state.save(root, run)
    return run["gates"]["simplify"]


# --------------------------------------------------------------------------- verify

NO_CHECK = ("_No realistic check is configured for this project._ Look for one the repository already "
            "has (a skill, an e2e or integration script, a documented way to run the app) and use it. If "
            "there is none, or it cannot run here, put every criterion under `## Not run` with the reason. "
            "The user decides whether that is acceptable.")


def verify_packet(root: Path, cfg: dict, run: dict) -> dict:
    if run.get("kind") != "code":
        raise state.RunError("realistic verification applies to code runs only")
    _require_gates_before_review(root, cfg, run, "verification")
    rounds = run.setdefault("verify_rounds", [])
    n = len(rounds) + 1
    d = _dir(root, run, "verify")
    out_dir = util.rel(root, _dir(root, run, f"verify/verify-{n}"))
    sha = gates.diff_sha(root, cfg, run)
    packet_id = uuid.uuid4().hex[:12]
    packet_path = d / f"verify-{n}.packet.md"
    report_path = util.rel(root, d / f"verify-{n}.report.md")
    how = ((cfg.get("verify") or {}).get("how") or "").strip() or NO_CHECK
    packet_path.write_text(f"""packet: {packet_id}
ticket: {run['ticket']}
run: {run['run_id']}
round: {n}
implementer: {run.get('actor')}
diff_sha256: {sha}
artifacts: {out_dir}
report: {report_path}

# Realistic verification packet

Unit tests and a static review cover this change already. Your job is different: run the changed
behavior **for real**, the way a user or a calling system meets it (integration, browser,
end-to-end, whatever this project has), and report what you saw for each acceptance criterion.
You did not write this change. Do not read or ask for the author's plan or reasoning.

## How this project checks a change for real

{how}

## Rules

- You share the author's checkout. Do not edit, create or delete project files, and never change
  the code to make a check pass: report the failure instead.
- Write screenshots, traces, logs and any other output only under `{out_dir}/`. A file left
  anywhere else changes the diff and invalidates the code review that runs at the same time.
- Do not run `atw` or anything under `.atw/core/`. Do not start sub-agents.
- Stop every server and browser you start before you finish.
- Never copy secrets, tokens or credentials into the report.

## Requirements (ticket, verbatim)

{_ticket_text(root, run)}

## Report

Every acceptance criterion gets exactly one line, in one of the three sections below. Write
`{report_path}` as your last action. Its first lines must be:

    packet: {packet_id}
    verifier: <your id - not "{run.get('actor')}">

then these three headings, kept even when empty:

    ## Checked
    - [x] <criterion> - how: <what you ran and what you saw; name the artifact file>
    ## Failed - blocks close
    - [ ] <criterion> - <what happened instead>
    ## Not run
    - [ ] <criterion> - why: <why it could not be checked for real>
""", encoding="utf-8", newline="\n")
    rounds.append({"round": n, "packet_id": packet_id, "diff_sha": sha, "created_at": util.now_iso(),
                   "review_rounds": len(run.get("review_rounds") or []),
                   "packet": util.rel(root, packet_path), "report": report_path})
    state.save(root, run)
    return {"round": n, "packet_id": packet_id, "packet": util.rel(root, packet_path),
            "report": report_path, "artifacts": out_dir}


def accept_verify(root: Path, cfg: dict, run: dict, report_path: Path, user_approval: str | None = None) -> dict:
    if not report_path.is_file():
        raise state.RunError(f"report not found: {report_path}")
    text = report_path.read_text(encoding="utf-8", errors="replace")
    f = fields(text)
    rnd = next((r for r in run.get("verify_rounds") or [] if r["packet_id"] == f.get("packet")), None)
    if not rnd:
        raise state.RunError("the report's `packet:` line does not match any verification packet of this run")
    verifier = f.get("verifier")
    if not verifier or verifier == run.get("actor"):
        raise state.RunError("the report needs a `verifier:` line naming an agent other than the implementer")
    sections = _sections(text)

    def section(label):
        return next((body for title, body in sections.items() if title.startswith(label)), None)

    checked, failed, not_run = section("checked"), section("failed"), section("not run")
    if checked is None or failed is None or not_run is None:
        raise state.RunError("the report must keep the `## Checked`, `## Failed - blocks close` and `## Not run` "
                             "headings - an unreadable report is never treated as clean")
    if rnd["diff_sha"] != gates.diff_sha(root, cfg, run):
        raise state.RunError("the diff changed after this verification packet was made - "
                             "run `atw verify-packet` again")
    failed_open = [i.strip() for i in _OPEN.findall(failed)]
    not_run_open = [i.strip() for i in _OPEN.findall(not_run)]
    n_checked = len(_DONE.findall(checked))
    evidence = {"report": util.rel(root, report_path), "packet_id": rnd["packet_id"], "round": rnd["round"],
                "verifier": verifier, "diff_sha": rnd["diff_sha"], "review_rounds": rnd["review_rounds"],
                "checked": n_checked}
    unrun = bool(not_run_open) or not n_checked

    def refuse(reason: str, message: str):
        run.setdefault("gates", {})["verify"] = {"state": "failed", "by": "script", "ts": util.now_iso(),
                                                 "reason": reason, "evidence": evidence}
        state.save(root, run)
        raise state.RunError(message)

    if failed_open:
        refuse(f"{len(failed_open)} criterion line(s) failed",
               "the realistic check failed - fix it, then make a new packet:\n  " + "\n  ".join(failed_open))
    if unrun and not user_approval:
        refuse("not run for real", "nothing or not everything was run for real. Ask the user; if they accept "
               "it, re-run with --user-approved \"<their words>\":\n  "
               + "\n  ".join(not_run_open or ["(no line under ## Checked)"]))
    reason = f"realistic check round {rnd['round']}: {n_checked} criterion line(s) checked"
    if unrun:
        reason += f", {len(not_run_open)} not run (accepted by the user)"
        evidence.update(not_run=not_run_open, user_approval=user_approval)
        state.append_decision(run, "not run for real: " + "; ".join(not_run_open or ["(nothing checked)"]),
                              "accepted-tradeoff", f"user approved: {user_approval}")
    run.setdefault("gates", {})["verify"] = {"state": "passed", "by": "script", "ts": util.now_iso(),
                                             "reason": reason, "evidence": evidence}
    state.save(root, run)
    return {"reason": reason, **evidence}
