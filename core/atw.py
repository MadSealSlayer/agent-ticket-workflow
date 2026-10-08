#!/usr/bin/env python3
"""atw - the agent ticket workflow core. Host-neutral; Python 3 stdlib only.

Lifecycle (every harness):
    atw start <TICKET> --kind <kind> [--scope isolated|coordinated] [--host claude|codex|other]
    atw plan --files "a,b" [--plan-file P --approval "..."] [--no-plan-mode --why "..."]   (code)
    atw red --test "<id>" [--test ...]   |   atw red --none --why "..."                     (code)
    atw gate tests lint deps
    atw review-packet  ->  fresh reviewer  ->  atw accept-review --report <path>           (code)
    atw status
    atw close [--context updated|no-op --why "..."] [--note "..."]

Pick a run with --run TICKET/RUN_ID, --ticket TICKET, or $ATW_RUN. With none,
the single open run on the current branch is used.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atwlib import config, gates, junit, packets, state, util  # noqa: E402

VERSION_FILE_CANDIDATES = ("VERSION", "../VERSION")


def version() -> str:
    here = Path(__file__).resolve().parent
    for cand in VERSION_FILE_CANDIDATES:
        p = (here / cand).resolve()
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return "unknown"


def out(msg: str = "") -> None:
    print(msg)


# --------------------------------------------------------------------------- helpers

def _select(root: Path, args) -> dict:
    return state.resolve(root, run_ref=getattr(args, "run", None), ticket=getattr(args, "ticket", None),
                         env_ref=os.environ.get("ATW_RUN"))


def _ref(run: dict) -> str:
    return f"{run['ticket']}/{run['run_id']}"


def _detect_host() -> str:
    if os.environ.get("ATW_HOST"):
        return os.environ["ATW_HOST"]
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if any(k.startswith("CODEX_") for k in os.environ):
        return "codex"
    return "other"


def _find_ticket_file(root: Path, cfg: dict, ticket: str) -> list[Path]:
    hits: list[Path] = []
    for pattern in cfg["tickets"]["globs"]:
        pat = pattern.replace("{id}", ticket)
        hits += [p for p in root.glob(pat) if p.is_file()]
    return sorted(set(hits))


def _split_files(raw: str) -> list[str]:
    files = []
    for name in (raw or "").split(","):
        name = name.strip()
        if not name:
            continue
        p = Path(name)
        if p.is_absolute() or ".." in p.parts:
            raise state.RunError(f"planned file must be repository-relative: {name}")
        files.append(util.posix(p))
    if len(files) != len(set(files)):
        raise state.RunError("planned files must not repeat")
    return files


def _print_report(report: dict) -> None:
    for name, r in report.items():
        mark = "OK" if r["state"] == "passed" else r["state"].upper()
        out(f"  [{mark:7}] {name}: {r['reason']}")


# --------------------------------------------------------------------------- lifecycle

def cmd_start(root: Path, cfg: dict, args) -> int:
    ticket = state.validate_ticket(args.ticket_id)
    enabled = cfg["kinds"]["enabled"]
    if args.kind not in enabled:
        raise state.RunError(f"kind '{args.kind}' is not enabled for this project (enabled: {', '.join(enabled)})")
    if args.kind == "code" and args.scope not in ("isolated", "coordinated"):
        raise state.RunError("a code run needs --scope isolated|coordinated. Coordinated = changes a public "
                             "API or event contract, a schema or migration, cross-service behavior, "
                             "infrastructure, or spans sessions.")
    if args.kind != "code" and args.scope:
        raise state.RunError("--scope applies to code runs only")
    if args.ticket_file:
        tpath = root / args.ticket_file
        if not tpath.is_file():
            raise state.RunError(f"ticket file not found: {args.ticket_file}")
    else:
        hits = _find_ticket_file(root, cfg, ticket)
        if not hits:
            raise state.RunError(f"no ticket file for '{ticket}' (searched: {', '.join(cfg['tickets']['globs'])}). "
                                 "Save the ticket as a markdown file there, or pass --ticket-file.")
        if len(hits) > 1:
            raise state.RunError("several ticket files match - pass --ticket-file: "
                                 + ", ".join(util.rel(root, h) for h in hits))
        tpath = hits[0]
    existing = state.open_runs(root, ticket=ticket)
    if existing and not args.force:
        raise state.RunError(f"ticket {ticket} already has an open run ({_ref(existing[-1])}). "
                             "Continue it with --run, or pass --force to abort it and start over.")
    for old in existing:
        old["status"] = "aborted"
        state.save(root, old)
        state.append_log(root, old, "aborted by start --force")
    host = args.host or _detect_host()
    run_id = args.run_id or state.new_run_id(ticket)
    if args.run_id and not state.RUN_ID.fullmatch(args.run_id):
        raise state.RunError("--run-id must be 3-64 letters, digits, '.', '_' or '-'")
    run = state.new_run(root, ticket=ticket, ticket_path=util.rel(root, tpath), kind=args.kind,
                        scope=args.scope, host=host, actor=args.actor or f"{host}-implementer", run_id=run_id)
    state.save(root, run)
    req = gates.required_gates(run, cfg)
    out(f"started {_ref(run)} kind={run['kind']}{'/' + run['scope'] if run['scope'] else ''} "
        f"host={host} branch={run['branch']}")
    out(f"run: {_ref(run)}   (pass --run {_ref(run)} to later commands, or set ATW_RUN)")
    out(f"required gates: {', '.join(req) or '(none)'}")
    if run["kind"] == "spike":
        out("NEXT: spikes use the experimental spike workflow (see its skill). No gates are armed.")
    elif run["kind"] == "code":
        if host == "claude":
            out("NEXT: call EnterPlanMode now. Ask the open questions there. After ExitPlanMode: atw plan --files \"...\"")
        else:
            out("NEXT: plan with your host's planning mode, save the plan to a file, get the user's explicit approval, "
                "then: atw plan --files \"...\" --plan-file <path> --approval \"<the user's words>\"")
    else:
        folder = (cfg.get("placement") or {}).get(run["kind"])
        named = " (put the ticket id in the file name)" if run["kind"] in ("investigation", "comms") else ""
        out(f"NEXT: produce the deliverable under {folder}/{named}, then: atw gate {' '.join(req)}")
    return 0


def cmd_kind(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    if args.new_kind not in cfg["kinds"]["enabled"]:
        raise state.RunError(f"kind '{args.new_kind}' is not enabled for this project")
    if args.new_kind == "code" and args.scope not in ("isolated", "coordinated"):
        raise state.RunError("re-kinding to code needs --scope isolated|coordinated")
    before = set(gates.required_gates(run, cfg))
    old = run["kind"]
    run["kind"], run["scope"] = args.new_kind, (args.scope if args.new_kind == "code" else None)
    after = set(gates.required_gates(run, cfg))
    run.setdefault("kind_history", []).append({"kind": run["kind"], "scope": run["scope"], "why": args.why,
                                               "ts": util.now_iso(), "gates_gained": sorted(after - before),
                                               "gates_lost": sorted(before - after)})
    state.save(root, run)
    out(f"{_ref(run)}: kind {old} -> {run['kind']} ({args.why})")
    if after - before:
        out(f"  + now required: {', '.join(sorted(after - before))}")
    if before - after:
        out(f"  ! NO LONGER REQUIRED: {', '.join(sorted(before - after))} - tell the user about this downgrade")
    return 0


def cmd_plan(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    if run["kind"] != "code":
        raise state.RunError("the plan gate applies to code runs")
    files = _split_files(args.files)
    if not files:
        raise state.RunError('plan needs --files "a,b" - the files this ticket will touch')
    evidence: dict = {"files": files}
    if args.no_plan_mode:
        if run.get("scope") == "coordinated":
            raise state.RunError("a coordinated change always needs a real, approved plan")
        if not args.why:
            raise state.RunError("--no-plan-mode needs --why \"<why a plan round-trip would be theater here>\"")
        evidence["plan_mode_skipped"] = args.why
    elif run.get("host") == "claude" and not args.plan_file:
        stamp = state.planmode_epoch(root, run["ticket"], run.get("branch") or util.current_branch(root))
        if stamp is None or stamp < run["started_at_epoch"]:
            raise state.RunError("no ExitPlanMode was recorded after this run started. Call EnterPlanMode, "
                                 "design the change with the user, then ExitPlanMode, then re-run this.")
        evidence["planmode_at"] = stamp
    else:
        if not args.plan_file or not args.approval:
            raise state.RunError("this host needs --plan-file <path> and --approval \"<the user's approval, "
                                 "in their words>\". Planning without the user's explicit yes does not count.")
        src = (root / args.plan_file) if not Path(args.plan_file).is_absolute() else Path(args.plan_file)
        if not src.is_file():
            raise state.RunError(f"plan file not found: {args.plan_file}")
        copy = state.run_dir(root, run["ticket"], run["run_id"]) / "plan.md"
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, copy)
        evidence.update({"plan_source": util.rel(root, src), "plan_copy": util.rel(root, copy),
                         "plan_hash": util.sha256_file(copy), "approval": args.approval})
    run["planned_files"] = files
    run["gates"]["plan"] = {"state": "passed", "by": "recorded", "ts": util.now_iso(),
                            "reason": f"approved ({len(files)} planned files)", "evidence": evidence}
    state.save(root, run)
    out(f"{_ref(run)}: plan recorded ({len(files)} planned files)")
    out("NEXT: write the proof tests (one per acceptance criterion), stub new code so they fail on behavior, "
        "then: atw red --test \"<id>\" ...")
    return 0


def cmd_red(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    if run["kind"] != "code":
        raise state.RunError("red applies to code runs")
    if (run["gates"].get("plan") or {}).get("state") != "passed":
        raise state.RunError("record the plan first (atw plan)")
    if args.none:
        if not args.why:
            raise state.RunError("red --none needs --why \"<why no test can fail on this change, e.g. a pure refactor>\"")
        run["gates"]["red"] = {"state": "passed", "by": "recorded", "ts": util.now_iso(),
                               "reason": f"no proof set: {args.why}",
                               "evidence": {"none": args.why, "proof_ids": run.get("proof_ids", [])}}
        state.save(root, run)
        out(f"{_ref(run)}: red recorded with no proof set ({args.why})")
        return 0
    ids = [t.strip() for t in args.test or [] if t.strip()]
    if not ids:
        raise state.RunError('red needs --test "<id>" (repeatable), or --none --why "..."')
    result = junit.run_and_check(root, cfg, ids, "red", root / ".atw" / "tmp")
    for tid, v in result["verdicts"].items():
        out(f"  [{'RED' if v['ok'] else 'NOT RED':7}] {tid}: {v['outcome']} {v['detail']}".rstrip())
    if not result["passed"]:
        out(f"  command: {result.get('command')}")
        if result.get("summary"):
            out(f"  runner: {result['summary']}")
        raise state.RunError("red refused - every proof id must fail on behavior before the change")
    proof = list(dict.fromkeys([*run.get("proof_ids", []), *ids]))
    prev = ((run["gates"].get("red") or {}).get("evidence") or {}).get("verdicts", {})
    run["proof_ids"] = proof
    run["gates"]["red"] = {"state": "passed", "by": "recorded", "ts": util.now_iso(),
                           "reason": f"{len(proof)} proof id(s) failed on behavior",
                           "evidence": {"proof_ids": proof, "verdicts": {**prev, **result["verdicts"]},
                                        "command": result["command"]}}
    state.save(root, run)
    out(f"{_ref(run)}: red recorded - proof set is {len(proof)} id(s). Implement, then: atw gate tests")
    return 0


def cmd_gate(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    ok = True
    for name in args.names:
        if name in gates.LIVE:
            r = gates.evaluate_live(root, cfg, run, name)
        elif name in gates.RECORDED:
            r = gates.eval_recorded(root, cfg, run, name)
        else:
            out(f"[??] {name}: unknown gate (known: {', '.join(gates.LIVE + gates.RECORDED)})")
            ok = False
            continue
        out(f"[{'PASS' if r['state'] == 'passed' else r['state'].upper()}] {name}: {r['reason']}")
        ok = ok and r["state"] == "passed"
    state.save(root, run)
    return 0 if ok else 1


def cmd_decide(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    new = state.append_decision(run, args.item, args.verdict, args.why)
    state.save(root, run)
    out(f"{_ref(run)}: decision {'recorded' if new else 'updated'} ({args.verdict}): {args.item}")
    return 0


def cmd_review_packet(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    info = packets.review_packet(root, cfg, run)
    out(f"{_ref(run)}: review round {info['round']} packet written")
    out(f"  packet: {info['packet']}")
    out(f"  patch:  {info['patch']}")
    out(f"  report: {info['report']}  (the reviewer writes this)")
    out("NEXT: hand ONLY the packet path to a FRESH agent with no memory of this session (a subagent with "
        "no conversation context, or a new session). It follows the ticket-audit skill. Then: "
        f"atw accept-review --report {info['report']}")
    return 0


def cmd_accept_review(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    if bool(args.override) != bool(args.user_approved):
        raise state.RunError("--override and --user-approved go together")
    res = packets.accept_review(root, cfg, run, root / args.report, args.override, args.user_approved)
    out(f"{_ref(run)}: audit passed - {res['reason']}")
    return 0


def cmd_simplify_packet(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    info = packets.simplify_packet(root, cfg, run)
    out(f"{_ref(run)}: simplify round {info['round']} packet: {info['packet']}")
    out(f"NEXT: a fresh agent writes {info['report']}; disposition every item; then: "
        f"atw accept-simplify --report {info['report']}")
    return 0


def cmd_accept_simplify(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    g = packets.accept_simplify(root, run, root / args.report)
    out(f"{_ref(run)}: simplify passed - {g['reason']}")
    return 0


def cmd_status(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    report = gates.evaluate_required(root, cfg, run)
    state.save(root, run)
    missing = gates.unmet(report)
    if args.json:
        print(json.dumps({"run": _ref(run), "kind": run["kind"], "scope": run.get("scope"),
                          "status": run["status"], "gates": report, "unmet": missing}, indent=2))
        return 0 if not missing else 1
    out(f"{_ref(run)} | kind={run['kind']}{'/' + run['scope'] if run.get('scope') else ''} | "
        f"status={run['status']} | host={run.get('host')} | branch={run.get('branch')}")
    out(f"  ticket: {run['ticket_path']}")
    if run.get("planned_files"):
        out(f"  planned files: {', '.join(run['planned_files'])}")
    if run.get("proof_ids"):
        out(f"  proof set: {', '.join(run['proof_ids'])}")
    _print_report(report)
    for name in missing:
        out(f"  -> {name}: {gates.FIX_HINTS.get(name, '')}")
    out("ALL GATES MET - ready for atw close" if not missing else f"UNMET: {', '.join(missing)}")
    return 0 if not missing else 1


def cmd_close(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    if run["status"] != "open":
        raise state.RunError(f"{_ref(run)} is {run['status']}")
    report = gates.evaluate_required(root, cfg, run)
    missing = gates.unmet(report)
    if missing:
        state.save(root, run)
        _print_report({k: v for k, v in report.items() if k in missing})
        raise state.RunError(f"cannot close {_ref(run)}: unmet gates -> {', '.join(missing)}")
    if run["kind"] == "code" and (cfg.get("context") or {}).get("enabled"):
        if args.context not in ("updated", "no-op"):
            raise state.RunError("this project keeps a context index: close needs --context updated|no-op "
                                 "(run the project-context-updating skill first)")
        if args.context == "no-op" and not args.why:
            raise state.RunError("--context no-op needs --why (the significance filter's reason)")
        run["context_update"] = {"result": args.context, "why": args.why, "ts": util.now_iso()}
    run["status"] = "closed"
    run["closed_at"] = util.now_iso()
    state.save(root, run)
    state.append_log(root, run, args.note or "")
    state.clear_session_bindings(root, run["ticket"])
    out(f"{_ref(run)} closed. Evidence: {util.rel(root, state.run_file(root, run['ticket'], run['run_id']))}")
    return 0


def cmd_abort(root: Path, cfg: dict, args) -> int:
    run = _select(root, args)
    if run["status"] == "closed":
        raise state.RunError("a closed run cannot be aborted")
    run["status"] = "aborted"
    run["abort_reason"] = args.why
    state.save(root, run)
    state.append_log(root, run, f"aborted: {args.why}")
    state.clear_session_bindings(root, run["ticket"])
    out(f"{_ref(run)} aborted; its gates are disarmed")
    return 0


def cmd_runs(root: Path, cfg: dict, args) -> int:
    runs = state.all_runs(root) if args.all else state.open_runs(root)
    if not runs:
        out("no runs" if args.all else "no open runs")
    for r in runs:
        out(f"{_ref(r):40} {r['status']:8} {r['kind']:13} {r.get('host', ''):7} {r.get('branch', '')}")
    return 0


# --------------------------------------------------------------------------- setup side

def cmd_hook(root: Path, cfg: dict, args) -> int:
    from atwlib import hooks
    code, text = hooks.HANDLERS[args.name](sys.stdin.read())
    if text:
        print(text)
    return code


def cmd_detect(root: Path, cfg: dict, args) -> int:
    from atwlib import detect
    report = detect.detect(root, our_names=args.names.split(",") if args.names else None)
    print(json.dumps(report, indent=2) if args.json else detect.render(report))
    return 0


def cmd_doctor(root: Path, cfg: dict, args) -> int:
    from atwlib import doctor
    return doctor.run(root, run_commands=args.run_commands)


def cmd_apply(root: Path, cfg: dict, args) -> int:
    from atwlib import install
    return install.apply(root, Path(args.plan), dry_run=args.dry_run,
                         payload=Path(args.payload) if args.payload else None)


def cmd_hygiene(root: Path, cfg: dict, args) -> int:
    from atwlib import doctor
    return doctor.hygiene(root, cfg)


def cmd_version(root: Path, cfg: dict, args) -> int:
    out(version())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="atw", description="agent ticket workflow core")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, select=True, **kw):
        s = sub.add_parser(name, **kw)
        if select:
            s.add_argument("--run", help="TICKET/RUN_ID")
            s.add_argument("--ticket", help="ticket id (when it has exactly one open run)")
        s.set_defaults(fn=fn)
        return s

    s = add("start", cmd_start, select=False, help="open a run for a ticket")
    s.add_argument("ticket_id")
    s.add_argument("--kind", required=True, choices=config.ALL_KINDS)
    s.add_argument("--scope", choices=("isolated", "coordinated"))
    s.add_argument("--host", choices=config.HOSTS)
    s.add_argument("--actor")
    s.add_argument("--run-id")
    s.add_argument("--ticket-file")
    s.add_argument("--force", action="store_true", help="abort this ticket's open run and start over")

    s = add("kind", cmd_kind, help="re-kind the run honestly")
    s.add_argument("new_kind", choices=config.ALL_KINDS)
    s.add_argument("--scope", choices=("isolated", "coordinated"))
    s.add_argument("--why", required=True)

    s = add("plan", cmd_plan, help="record the approved plan (code)")
    s.add_argument("--files", required=True)
    s.add_argument("--plan-file")
    s.add_argument("--approval")
    s.add_argument("--no-plan-mode", action="store_true")
    s.add_argument("--why")

    s = add("red", cmd_red, help="prove the proof set fails on behavior (code)")
    s.add_argument("--test", action="append", help="a proof test id (repeatable)")
    s.add_argument("--none", action="store_true")
    s.add_argument("--why")

    s = add("gate", cmd_gate, help="check gates now")
    s.add_argument("names", nargs="+")

    s = add("decide", cmd_decide, help="record a settled question or finding")
    s.add_argument("--item", required=True)
    s.add_argument("--verdict", required=True, choices=state.DECIDE_VERDICTS)
    s.add_argument("--why", required=True)

    add("review-packet", cmd_review_packet, help="write a clean-room review packet (code)")
    s = add("accept-review", cmd_accept_review, help="accept a review report")
    s.add_argument("--report", required=True)
    s.add_argument("--override", help="open Warning items the user accepts")
    s.add_argument("--user-approved", help="the user's approval, in their words")
    add("simplify-packet", cmd_simplify_packet, help="write a simplify packet (code)")
    s = add("accept-simplify", cmd_accept_simplify, help="accept a simplify report")
    s.add_argument("--report", required=True)

    s = add("status", cmd_status, help="show gates for a run")
    s.add_argument("--json", action="store_true")
    s = add("close", cmd_close, help="re-check every gate and close")
    s.add_argument("--note", default="")
    s.add_argument("--context", choices=("updated", "no-op"))
    s.add_argument("--why")
    s = add("abort", cmd_abort, help="abandon a run")
    s.add_argument("--why", required=True)
    s = add("runs", cmd_runs, select=False, help="list runs")
    s.add_argument("--all", action="store_true")

    s = add("hook", cmd_hook, select=False, help="Claude Code hook entry (stdin payload)")
    s.add_argument("name", choices=("stop", "planmode", "guard"))
    s = add("detect", cmd_detect, select=False, help="read-only brownfield discovery")
    s.add_argument("--json", action="store_true")
    s.add_argument("--names", help="comma-separated skill names to check for clashes")
    s = add("doctor", cmd_doctor, select=False, help="check the installation")
    s.add_argument("--run-commands", action="store_true", help="also dry-run the configured commands")
    s = add("apply", cmd_apply, select=False, help="apply an approved install plan")
    s.add_argument("--plan", required=True)
    s.add_argument("--payload", help="package folder to install from (default: the staged payload)")
    s.add_argument("--dry-run", action="store_true")
    add("hygiene", cmd_hygiene, select=False, help="report misplaced files (read-only)")
    add("version", cmd_version, select=False, help="print the version")
    return p


def main(argv: list[str] | None = None) -> int:
    # Gate output quotes test runners (✔, accented names). A Windows console code page cannot
    # encode all of it, and a crash while printing must never hide a gate result.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    root = util.project_root()
    cfg = config.load(root)
    try:
        return args.fn(root, cfg, args)
    except state.RunError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
