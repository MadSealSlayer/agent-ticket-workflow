"""Claude Code hook handlers. The adapter's settings fragment calls
`atw.py hook <stop|planmode|planproposed|guard>` with the hook payload on stdin.

Plan approval has two routes to the same stamp (ADR 0018):
  - native Claude Code: PostToolUse on a successful ExitPlanMode;
  - T3 Code, where ExitPlanMode always returns an error and PostToolUse never
    fires: PreToolUse on ExitPlanMode stamps "plan proposed", the skill asks
    AskUserQuestion (header "Plan"), and PostToolUse on AskUserQuestion turns
    an exact "Approve" answer into the approval stamp.

Safety rules, every hook:
  - No open run -> silent allow. Ordinary sessions are never affected by the
    gates. The guard's command rules and its test-marker check apply in
    every session; they only deny or ask, and never block a turn.
  - Session isolation: a hook acts only on the run of its own session, or on
    an open run that no session is bound to (`state.run_for_hook`).
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

from . import config, gates, shell, state, util
from . import guard as guard_rules

# Subcommands that change a run. `status` and `runs` are left out on purpose:
# a read-only look at another ticket must not move this session to it.
_MUTATING = {"plan", "red", "gate", "decide", "review-packet", "accept-review", "simplify-packet",
             "accept-simplify", "close", "abort", "kind"}
_TICKET = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_PYTHONS = re.compile(r"(python[0-9.]*w?|py)")
_RUNNERS = {"uv", "poetry", "pipenv", "pdm", "hatch", "rye"}


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
        # tests/lint/deps are never run here: a turn end must not wait on a
        # test suite. A missing or outdated result blocks with the refresh command.
        report = gates.evaluate_required(root, cfg, run, run_cached=False)
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
        key = state.planmode_key(root, payload.get("session_id")) if "plan" in missing else None
        proposed = bool(key) and state.pending_proposal(root, key, run) is not None
        for name in missing:
            hint = gates.FIX_HINTS.get("plan-proposed" if name == "plan" and proposed else name, "")
            if name in gates.CACHED:
                hint = f"{hint} --run {ref}"
            lines.append(f"  - {name}: {report[name]['reason']}" + (f"  ->  {hint}" if hint else ""))
        lines.append("If a decision is genuinely the user's, ask it now; that is the only reason to stop early.")
        return 0, json.dumps({"decision": "block", "reason": "\n".join(lines)})
    except Exception as e:
        print(f"atw stop hook: internal error, allowing: {e}", file=sys.stderr)
        return 0, ""


PLAN_HEADER = "Plan"
PLAN_APPROVE = "Approve"


def planmode(raw: str) -> tuple[int, str]:
    """PostToolUse on ExitPlanMode or AskUserQuestion: stamp the time the user
    really approved the plan, so `atw plan` can check it instead of trusting
    a narrated plan."""
    try:
        payload = _payload(raw)
        tool = payload.get("tool_name")
        if tool not in ("ExitPlanMode", "AskUserQuestion"):
            return 0, ""
        root = _root(payload)
        if not state.open_runs(root):
            return 0, ""
        key = state.planmode_key(root, payload.get("session_id"))
        if not key:
            return 0, ""
        if tool == "ExitPlanMode":
            state.write_approval(root, key, "exit-plan-mode")
        else:
            _plan_answer(root, key, payload)
        return 0, ""
    except Exception as e:
        print(f"atw planmode hook: internal error, allowing: {e}", file=sys.stderr)
        return 0, ""


def _plan_question(payload: dict) -> tuple[str, str | None, str | None] | None:
    """(question text, answer, notes) of the one question with header "Plan",
    or None. Answers are keyed by question text, in tool_input (filled by the
    host UI) or, failing that, in tool_response."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("questions"), list):
        return None
    question = next((q.get("question") for q in tool_input["questions"]
                     if isinstance(q, dict) and q.get("header") == PLAN_HEADER), None)
    if not isinstance(question, str):
        return None
    response = payload.get("tool_response")
    answer = notes = None
    for source in (tool_input, response if isinstance(response, dict) else {}):
        answers, annotations = source.get("answers"), source.get("annotations")
        if answer is None and isinstance(answers, dict) and isinstance(answers.get(question), str):
            answer = answers[question]
        note = annotations.get(question) if isinstance(annotations, dict) else None
        if notes is None and isinstance(note, dict) and isinstance(note.get("notes"), str):
            notes = note["notes"]
    return question, answer, notes


def _plan_answer(root: Path, key: str, payload: dict) -> None:
    """An exact "Approve" to a pending proposal writes the same approval stamp
    as ExitPlanMode. "Decline" or free text consumes the proposal: the agent
    revises the plan and proposes again."""
    found = _plan_question(payload)
    if not found or found[1] is None:
        return
    question, answer, notes = found
    run = state.run_for_hook(root, payload.get("session_id"))
    if not run or state.pending_proposal(root, key, run) is None:
        return
    detail = {"question": question, "answer": answer, **({"notes": notes} if notes else {})}
    if answer.strip() == PLAN_APPROVE:
        state.write_approval(root, key, "ask-approve", **detail)
    else:
        util.write_json(state.declined_path(root, key), {"route": "ask-decline", "ts": util.now_iso(), **detail})


def planproposed(raw: str) -> tuple[int, str]:
    """PreToolUse on ExitPlanMode: stamp "plan proposed". It fires in T3 Code
    too, before T3 rejects the call. Never blocks."""
    try:
        payload = _payload(raw)
        if payload.get("tool_name") != "ExitPlanMode":
            return 0, ""
        root = _root(payload)
        if not state.open_runs(root):
            return 0, ""
        key = state.planmode_key(root, payload.get("session_id"))
        if key:
            util.atomic_write_text(state.proposed_path(root, key), util.now_iso())
        return 0, ""
    except Exception as e:
        print(f"atw planproposed hook: internal error, allowing: {e}", file=sys.stderr)
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


def _atw_args(toks: list[str]) -> list[str] | None:
    """The arguments of an `atw` call (`atw X`, `python .atw/core/atw.py X`)."""
    if not toks:
        return None
    if toks[0] in _RUNNERS and len(toks) > 2 and toks[1] == "run":  # uv run python ..., poetry run atw ...
        toks = [shell.command_word(toks[2])] + toks[3:]
    if toks[0] in ("atw", "atw.py"):
        return toks[1:]
    if not _PYTHONS.fullmatch(toks[0]):
        return None
    i = 1
    while i < len(toks) and toks[i].startswith("-"):
        i += 2 if toks[i] in ("-X", "-W") else 1
    if i < len(toks) and shell.command_word(toks[i]) == "atw.py":
        return toks[i + 1:]
    return None


def _option(args: list[str], name: str) -> str | None:
    for j, a in enumerate(args):
        if a == name and j + 1 < len(args):
            return args[j + 1]
        if a.startswith(name + "="):
            return a[len(name) + 1:]
    return None


def bind_from_command(root: Path, session_id: str | None, command: str, powershell: bool = False) -> None:
    """Bind the session to the ticket that an `atw` command names: `start X`,
    or a mutating subcommand with `--ticket X` or `--run X/RUN_ID`. Only real
    `atw` calls count (parsed commands, not text that mentions one); a
    `start` anywhere in the line wins."""
    if not session_id or "atw" not in command:
        return
    calls = [a for a in (_atw_args(shell.normalized(seg, powershell))
                         for seg in shell.segments(command, powershell)) if a]
    ticket = next((a[1] for a in calls if a[0] == "start" and len(a) > 1), None)
    if ticket is None:
        for a in calls:
            if a[0] in _MUTATING:
                run = _option(a, "--run")
                ticket = _option(a, "--ticket") or (run.split("/")[0] if run and "/" in run else None)
                if ticket:
                    break
    if ticket and _TICKET.fullmatch(ticket):
        state.bind_session(root, session_id, ticket)


def _edit_texts(root: Path, tool: str, tool_input: dict, target: str) -> tuple[str, str]:
    """(old text, new text) of an edit. For Write, the old text is the file."""
    if tool == "Edit":
        return tool_input.get("old_string") or "", tool_input.get("new_string") or ""
    if tool == "MultiEdit":
        edits = [e for e in tool_input.get("edits") or [] if isinstance(e, dict)]
        return ("\n".join(e.get("old_string") or "" for e in edits),
                "\n".join(e.get("new_string") or "" for e in edits))
    try:
        old = (root / target).read_text(encoding="utf-8", errors="replace")
    except OSError:
        old = ""
    return old, tool_input.get("content") or ""


def added_test_marker(old: str, new: str, patterns) -> str | None:
    """The first marker pattern that the new text has more often than the old.
    Counts, not presence: one existing `.skip(` does not license another."""
    for pat in patterns or []:
        try:
            rx = re.compile(pat, re.MULTILINE)
        except re.error:
            continue
        if len(rx.findall(new)) > len(rx.findall(old)):
            return pat
    return None


def guard(raw: str) -> tuple[int, str]:
    """PreToolUse. Denies or asks on the configured command rules (guard.py),
    binds a session
    to the ticket it starts or changes, asks before an edit that disables or
    focuses a test, and asks before source or test edits while a code run's
    plan is not approved yet."""
    try:
        payload = _payload(raw)
        root = _root(payload)
        cfg = config.load(root)
        tool = payload.get("tool_name") or ""
        tool_input = payload.get("tool_input") or {}
        guards = cfg.get("guards") or {}

        if tool in ("Bash", "PowerShell"):
            command = tool_input.get("command") or ""
            powershell = tool == "PowerShell"
            try:
                bind_from_command(root, payload.get("session_id"), command, powershell)
            except Exception as e:  # a failed bind never skips the checks below
                print(f"atw guard hook: session bind failed: {e}", file=sys.stderr)
            decision = guard_rules.evaluate(root, cfg, command, powershell)
            return 0, (_decision(*decision) if decision else "")

        if tool not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            return 0, ""
        target = _target_path(root, tool_input)
        if not target:
            return 0, ""
        if tool != "NotebookEdit" and guards.get("test_markers") and guard_rules.is_test_file(cfg, target):
            marker = added_test_marker(*_edit_texts(root, tool, tool_input, target), guards["test_markers"])
            if marker:
                return 0, _decision("ask", f"this edit to {target} adds a test marker ({marker}). Disabling or "
                                           "focusing a test needs the user's OK.")
        if not guards.get("protect_before_plan", True):
            return 0, ""
        protected = list(cfg.get("protected_paths") or []) + list(cfg.get("test_paths") or [])
        if not util.under_any(target, protected):
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


HANDLERS = {"stop": stop, "planmode": planmode, "planproposed": planproposed, "guard": guard}
