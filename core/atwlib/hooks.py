"""Claude Code hook handlers. The adapter's settings fragment calls
`atw.py hook <stop|planmode|guard>` with the hook payload on stdin.

Safety rules, all three hooks:
  - No open run -> silent allow. Ordinary sessions are never affected.
  - Fail open: any exception -> message on stderr, allow. A bug in a hook
    must never trap a session.
  - The Stop hook has a release valve: after 3 identical blocks it allows the
    turn with a warning, so a broken gate can never wedge a session.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from . import config, gates, state, util

_START = re.compile(r"atw(?:\.py)?[\"']?\s+start\s+[\"']?([A-Za-z0-9][A-Za-z0-9_.-]*)")


def _payload(raw: str) -> dict:
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("hook payload must be a JSON object")
    return data


def _root(payload: dict) -> Path:
    cwd = payload.get("cwd")
    return util.project_root(Path(cwd)) if cwd and Path(cwd).is_dir() else util.project_root()


def stop(raw: str) -> tuple[int, str]:
    try:
        payload = _payload(raw)
        root = _root(payload)
        run = state.run_for_hook(root, payload.get("session_id"))
        if not run:
            return 0, ""
        cfg = config.load(root)
        report = gates.evaluate_required(root, cfg, run)
        missing = gates.unmet(report)
        if not missing:
            gates.record_progress(run)
            state.save(root, run)
            return 0, ""
        released = gates.record_block(run, missing)
        state.save(root, run)
        ref = f"{run['ticket']}/{run['run_id']}"
        if released:
            return 0, json.dumps({"systemMessage": (
                f"{ref}: gates still unmet after {gates.RELEASE_VALVE} blocks, allowing the turn to end - "
                f"{', '.join(missing)}. Run `atw status --run {ref}` for details.")})
        lines = [f"{ref} ({run['kind']}) is not done yet - unmet gate(s):"]
        for name in missing:
            hint = gates.FIX_HINTS.get(name, "")
            lines.append(f"  - {name}: {report[name]['reason']}" + (f"  ->  {hint}" if hint else ""))
        lines.append("If a decision is genuinely the user's, ask it now; that is the only reason to stop early.")
        return 0, json.dumps({"decision": "block", "reason": "\n".join(lines)})
    except Exception as e:
        print(f"atw stop hook: internal error, allowing: {e}", file=sys.stderr)
        return 0, ""


def planmode(raw: str) -> tuple[int, str]:
    """PostToolUse on ExitPlanMode: stamp the time plan mode really ended, so
    `atw plan` can check it instead of trusting a narrated plan."""
    try:
        payload = _payload(raw)
        if payload.get("tool_name") != "ExitPlanMode":
            return 0, ""
        root = _root(payload)
        if not state.open_runs(root):
            return 0, ""
        stamp = util.now_iso()
        util.atomic_write_text(state.planmode_branch_path(root, util.current_branch(root)), stamp)
        ticket = state.session_ticket(root, payload.get("session_id"))
        if ticket:
            util.atomic_write_text(state.planmode_ticket_path(root, ticket), stamp)
        return 0, ""
    except Exception as e:
        print(f"atw planmode hook: internal error, allowing: {e}", file=sys.stderr)
        return 0, ""


def _decision(kind: str, reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": kind, "permissionDecisionReason": reason}})


def _target_path(root: Path, tool_input: dict) -> str | None:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    if not raw:
        return None
    p = Path(raw)
    return util.rel(root, p if p.is_absolute() else root / p)


def guard(raw: str) -> tuple[int, str]:
    """PreToolUse. Denies or asks on configured shell patterns, binds a session
    to the ticket it starts, and asks before source or test edits while a code
    run's plan is not approved yet."""
    try:
        payload = _payload(raw)
        root = _root(payload)
        cfg = config.load(root)
        tool = payload.get("tool_name") or ""
        tool_input = payload.get("tool_input") or {}
        guards = cfg.get("guards") or {}

        if tool in ("Bash", "PowerShell"):
            command = tool_input.get("command") or ""
            m = _START.search(command)
            if m and payload.get("session_id"):
                state.bind_session(root, payload["session_id"], m.group(1))
            for pat in guards.get("deny") or []:
                if re.search(pat, command):
                    return 0, _decision("deny", f"blocked by the ticket workflow guard ({pat}). "
                                                "This command is the developer's call: ask them to run it.")
            for pat in guards.get("ask") or []:
                if re.search(pat, command):
                    return 0, _decision("ask", f"the ticket workflow asks before this command ({pat})")
            return 0, ""

        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") and guards.get("protect_before_plan", True):
            target = _target_path(root, tool_input)
            protected = list(cfg.get("protected_paths") or []) + list(cfg.get("test_paths") or [])
            if not target or not util.under_any(target, protected):
                return 0, ""
            run = state.run_for_hook(root, payload.get("session_id"))
            if run and run.get("kind") == "code" and (run.get("gates") or {}).get("plan", {}).get("state") != "passed":
                return 0, _decision("ask", f"{run['ticket']}: the plan is not approved yet, and {target} is "
                                           "protected source or test code. Finish planning first (atw plan).")
            if run and run.get("kind") in gates.NONCODE_KINDS:
                return 0, _decision("ask", f"{run['ticket']} is a '{run['kind']}' run, and {target} is protected "
                                           "source. If a code change is needed, re-kind honestly first.")
        return 0, ""
    except Exception as e:
        print(f"atw guard hook: internal error, allowing: {e}", file=sys.stderr)
        return 0, ""


HANDLERS = {"stop": stop, "planmode": planmode, "guard": guard}
