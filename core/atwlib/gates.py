"""Gates: which ones each kind needs, and how each one is checked.

Two styles, as in the original harness:
  LIVE      recomputed fresh on every call, nothing cached to go stale:
            nocode, placement, provenance, tests, lint, deps.
  RECORDED  written by a CLI command after a real check, then re-validated:
            plan   (plan-mode stamp or approved plan file; stale if the plan copy changes)
            red    (the proof set failed on behavior; `tests` re-proves it green)
            simplify (an accepted simplify report bound to a packet)
            audit  (an accepted review report; stale once the diff changes)

A gate that verifies nothing is worse than none: every check here reads the
repo, a command result, or a hash, never the agent's say-so.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import deps as deps_mod
from . import junit, runner, util

LIVE = ("nocode", "placement", "provenance", "tests", "lint", "deps")
RECORDED = ("plan", "red", "simplify", "audit")
NONCODE_KINDS = ("investigation", "comms", "docs", "tooling")
RELEASE_VALVE = 3


def _cmd(cfg: dict, name: str) -> dict | None:
    return (cfg.get("commands") or {}).get(name) or None


def required_gates(run: dict, cfg: dict) -> list[str]:
    kind = run.get("kind")
    lint = ["lint"] if _cmd(cfg, "lint") else []
    deps = ["deps"] if _cmd(cfg, "deps") else []
    if kind == "code":
        simplify = ["simplify"] if cfg.get("simplify") == "gate" else []
        return ["plan", "red", "tests", *lint, *deps, *simplify, "audit"]
    if kind == "tooling":
        return ["nocode", "placement", *lint, *deps]
    if kind in ("investigation", "docs"):
        return ["nocode", "placement", "provenance"]
    if kind == "comms":
        return ["nocode", "placement"]
    return []  # spike: handed to the experimental spike workflow, never armed


def _changed(root: Path, run: dict) -> list[str]:
    return util.changed_files(root, run.get("baseline_ref"), run.get("baseline_untracked"))


def _ok(reason: str, **evidence) -> dict:
    return {"state": "passed", "reason": reason, "evidence": evidence}


def _fail(reason: str, **evidence) -> dict:
    return {"state": "failed", "reason": reason, "evidence": evidence}


# --------------------------------------------------------------------------- nocode

def eval_nocode(root: Path, cfg: dict, run: dict) -> dict:
    hits = [f for f in _changed(root, run) if util.under_any(f, cfg.get("protected_paths"))]
    if hits:
        more = " ..." if len(hits) > 5 else ""
        return _fail(f"kind '{run['kind']}' changed {len(hits)} protected file(s): {', '.join(hits[:5])}{more}. "
                     f"If a code change is really needed, re-kind honestly: atw kind code --why \"...\"",
                     files=hits)
    return _ok("no protected source touched")


# --------------------------------------------------------------------------- placement

def _id_in_name(path: str, ticket: str) -> bool:
    return ticket.lower() in path.rsplit("/", 1)[-1].lower()


def _deliverables(root: Path, cfg: dict, run: dict, kind: str) -> list[str]:
    folder = (cfg.get("placement") or {}).get(kind)
    if not folder:
        return []
    changed = [f for f in _changed(root, run) if util.under_any(f, [folder])]
    written = util.files_written_since(root, folder, run.get("started_at_epoch", 0))
    files = sorted(set(changed) | set(written))
    if kind in ("investigation", "comms"):
        # The folder is shared by every ticket; mtime alone cannot tell whose
        # file it is, so the ticket id must be in the file name.
        files = [f for f in files if _id_in_name(f, run["ticket"])]
    return files


def eval_placement(root: Path, cfg: dict, run: dict) -> dict:
    kind = run["kind"]
    placement = cfg.get("placement") or {}
    folder = placement.get(kind)
    if not folder:
        return _ok(f"no placement rule for kind '{kind}'")
    docs_dir = placement.get("docs")
    if kind in ("investigation", "comms") and docs_dir and docs_dir != folder:
        stray = [f for f in _changed(root, run)
                 if util.under_any(f, [docs_dir]) and not util.under_any(f, [folder])]
        if stray:
            return _fail(f"'{kind}' wrote into the committed docs folder {docs_dir}/: {', '.join(stray[:5])} "
                         f"- its deliverable belongs in {folder}/", files=stray)
    found = _deliverables(root, cfg, run, kind)
    if found:
        return _ok(f"deliverable found under {folder}/: {', '.join(found[:3])}", files=found)
    need_id = " with the ticket id in the file name" if kind in ("investigation", "comms") else ""
    return _fail(f"no deliverable under {folder}/{need_id} for kind '{kind}'")


# --------------------------------------------------------------------------- provenance

_SOURCES_HEADING = re.compile(r"^\s*#{2,3}\s*Sources\s*$", re.IGNORECASE | re.MULTILINE)
_HEADING = re.compile(r"^\s*#{1,6}\s", re.MULTILINE)
_SOURCE_ID = re.compile(r"^\s*-\s*\[([\w-]+)\]", re.MULTILINE)
_CLAIM_TAG = re.compile(r"\b(measured|inferred)\b", re.IGNORECASE)
_BRACKET_REF = re.compile(r"\[([\w-]+)\]")


def provenance_problems(text: str) -> list[str]:
    """A `## Sources` section of `- [id] ...` entries, and every claim line
    tagged measured/inferred cites one of those ids."""
    m = _SOURCES_HEADING.search(text)
    if not m:
        return ["no '## Sources' section"]
    rest = text[m.end():]
    nxt = _HEADING.search(rest)
    block = rest[: nxt.start()] if nxt else rest
    ids = set(_SOURCE_ID.findall(block))
    if not ids:
        return ["'Sources' section has no `- [id] ...` entries"]
    body = text[: m.start()] + (rest[nxt.start():] if nxt else "")
    claims = [l for l in body.splitlines() if _CLAIM_TAG.search(l)]
    if not claims:
        return ["no claim tagged measured/inferred"]
    return [f"claim without a valid [id] source: {l.strip()[:100]}"
            for l in claims if not (set(_BRACKET_REF.findall(l)) & ids)]


def eval_provenance(root: Path, cfg: dict, run: dict) -> dict:
    kind = run["kind"]
    candidates = [f for f in _deliverables(root, cfg, run, kind) if f.endswith(".md")]
    if kind == "docs":
        # A reference doc may have no derived figures; working notes under
        # the investigation folder can carry the sources instead.
        candidates += [f for f in _deliverables(root, cfg, run, "investigation") if f.endswith(".md")]
    if not candidates:
        return _fail(f"no markdown deliverable found for kind '{kind}'")
    problems = []
    for f in candidates:
        found = provenance_problems((root / f).read_text(encoding="utf-8", errors="ignore"))
        if not found:
            return _ok(f"Sources present and claims cite them ({f})", file=f)
        problems += [f"{f}: {p}" for p in found]
    return _fail("; ".join(problems[:5]), problems=problems)


# --------------------------------------------------------------------------- tests

def _related_tests(root: Path, cfg: dict, changed: list[str]) -> list[str]:
    tests = _cmd(cfg, "tests") or {}
    scope = tests.get("scope", "all")
    test_globs = tests.get("test_globs") or ["test_*.py", "*_test.py", "*.test.*", "*.spec.*", "*_test.go"]
    direct = [f for f in changed if util.glob_match(f, test_globs) and (root / f).is_file()]
    if scope == "changed-tests":
        return sorted(direct)
    # stem-match: also any test file whose text names a changed source file's stem.
    source_globs = tests.get("source_globs") or []
    sources = [f for f in changed if f not in direct and (
        util.glob_match(f, source_globs) if source_globs else util.under_any(f, cfg.get("protected_paths")))]
    stems = {Path(f).stem.split(".")[0] for f in sources}
    stems = {s for s in stems if len(s) > 2 and s not in ("index", "main", "init", "__init__", "utils")}
    related = set(direct)
    if stems:
        roots = cfg.get("test_paths") or ["."]
        pattern = re.compile(r"\b(" + "|".join(re.escape(s) for s in sorted(stems)) + r")\b")
        for base in roots:
            for p in (root / base).rglob("*"):
                rp = util.rel(root, p)
                if (not p.is_file() or rp in related or "node_modules/" in rp
                        or not util.glob_match(rp, test_globs)):
                    continue
                try:
                    if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
                        related.add(rp)
                except Exception:
                    continue
    return sorted(related)


def eval_tests(root: Path, cfg: dict, run: dict) -> dict:
    tests = _cmd(cfg, "tests")
    if not tests:
        return _fail("commands.tests is not configured - run /ticket-setup")
    timeout = (cfg.get("timeouts") or {}).get("command_seconds", 600)
    scope = tests.get("scope", "all")
    files = None if scope == "all" else _related_tests(root, cfg, _changed(root, run))
    if files == []:
        summary, ev = "no test file in scope for this diff", {"command": None}
    else:
        res = runner.run(root, runner.render(tests["run"], files=files, python=cfg.get("python")), timeout)
        summary = res["error"] or runner.tail(res["output"]) or f"exit {res['returncode']}"
        ev = {"command": res["command"], "returncode": res["returncode"], "files": files}
        if res["returncode"] != 0:
            return _fail(f"tests failed: {summary}", **ev)
    if run.get("kind") != "code":
        return _ok(summary, **ev)
    red = (run.get("gates") or {}).get("red") or {}
    if red.get("state") != "passed":
        return _fail("no red recorded yet - run: atw red --test \"<id>\" (or --none --why \"...\")", **ev)
    ids = run.get("proof_ids") or []
    if not ids:
        return _ok(f"{summary}; no proof set (red --none: {red.get('evidence', {}).get('none', '')})", **ev)
    proof = junit.run_and_check(root, cfg, ids, "green", root / ".atw" / "tmp")
    not_green = [i for i, v in proof["verdicts"].items() if not v["ok"]]
    if not proof["passed"]:
        return _fail(f"proof id(s) not green: {', '.join(not_green) or proof['summary']}", **ev, proof=proof)
    return _ok(f"{summary}; proof set green ({len(ids)} id(s))", **ev, proof=proof)


# --------------------------------------------------------------------------- lint

def _json_payload(text: str):
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0], default=-1)
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except Exception:
        return None


def _lint_findings(root: Path, output: str, fmt: str) -> list[dict] | None:
    data = _json_payload(output)
    if data is None:
        return None
    findings = []
    if fmt == "ruff-json":
        for item in data if isinstance(data, list) else []:
            findings.append({"file": util.rel(root, Path(item.get("filename", ""))),
                             "line": (item.get("location") or {}).get("row"),
                             "message": f"{item.get('code')}: {item.get('message')}"})
    elif fmt == "eslint-json":
        for item in data if isinstance(data, list) else []:
            for msg in item.get("messages") or []:
                if msg.get("severity", 2) >= 2:
                    findings.append({"file": util.rel(root, Path(item.get("filePath", ""))),
                                     "line": msg.get("line"),
                                     "message": f"{msg.get('ruleId')}: {msg.get('message')}"})
    return findings


def eval_lint(root: Path, cfg: dict, run: dict) -> dict:
    lint = _cmd(cfg, "lint")
    if not lint:
        return _ok("lint not configured")
    globs = lint.get("file_globs") or ["*"]
    files = [f for f in _changed(root, run) if util.glob_match(f, globs) and (root / f).is_file()]
    if not files:
        return _ok("no changed files to lint")
    timeout = (cfg.get("timeouts") or {}).get("command_seconds", 600)
    res = runner.run(root, runner.render(lint["run"], files=files, python=cfg.get("python")), timeout)
    if res["error"]:
        return _fail(f"lint could not run: {res['error']}", command=res["command"])
    fmt = lint.get("output", "exit-code")
    if fmt == "exit-code":
        if res["returncode"] == 0:
            return _ok("clean", command=res["command"])
        return _fail(f"lint failed: {runner.tail(res['output'], 3)}", command=res["command"])
    findings = _lint_findings(root, res["stdout"], fmt)
    if findings is None:
        if res["returncode"] == 0:
            return _ok("clean", command=res["command"])
        return _fail(f"lint output was not {fmt}: {runner.tail(res['output'], 3)}", command=res["command"])
    if lint.get("changed_lines_only", True):
        # Pre-existing findings on untouched lines are not this run's problem.
        ranges = util.changed_line_ranges(root, run.get("baseline_ref"), files)
        findings = [x for x in findings if x["file"] not in ranges or x["line"] in ranges[x["file"]]]
    if findings:
        first = "; ".join(f"{x['file']}:{x['line']} {x['message']}" for x in findings[:3])
        return _fail(f"{len(findings)} lint finding(s) on changed lines: {first}",
                     command=res["command"], findings=findings)
    return _ok("clean on changed lines", command=res["command"])


# --------------------------------------------------------------------------- deps

def eval_deps(root: Path, cfg: dict, run: dict) -> dict:
    spec = _cmd(cfg, "deps")
    if not spec:
        return _ok("deps not configured")
    files = _changed(root, run)
    if spec.get("run"):
        timeout = (cfg.get("timeouts") or {}).get("command_seconds", 600)
        res = runner.run(root, runner.render(spec["run"], files=files, python=cfg.get("python")), timeout)
        if res["returncode"] == 0:
            return _ok("deps check passed", command=res["command"])
        return _fail(f"deps check failed: {res['error'] or runner.tail(res['output'], 3)}", command=res["command"])
    result = deps_mod.check(root, files, spec)
    if result.get("error"):
        return _fail(result["error"])
    if not result["passed"]:
        first = "; ".join(f"{m['module']} in {m['file']} -> {m['manifest']}" for m in result["missing"][:3])
        return _fail(f"{len(result['missing'])} undeclared import(s): {first}", **result)
    return _ok("no undeclared imports", **result)


LIVE_EVALUATORS = {
    "nocode": eval_nocode, "placement": eval_placement, "provenance": eval_provenance,
    "tests": eval_tests, "lint": eval_lint, "deps": eval_deps,
}


def evaluate_live(root: Path, cfg: dict, run: dict, name: str) -> dict:
    try:
        result = LIVE_EVALUATORS[name](root, cfg, run)
    except Exception as e:  # a crashing gate is a failing gate, never a pass
        result = _fail(f"gate '{name}' crashed: {e}")
    run.setdefault("gates", {})[name] = {"state": result["state"], "by": "script", "ts": util.now_iso(),
                                         "reason": result["reason"]}
    return result


# --------------------------------------------------------------------------- recorded gates

def review_exclude(cfg: dict) -> list[str]:
    """Paths whose change does not make a review stale: the workflow's own
    folder and the project-context index (updated after the review)."""
    ex = [".atw/"]
    index = (cfg.get("context") or {}).get("index")
    if (cfg.get("context") or {}).get("enabled") and index:
        parent = util.posix(Path(index).parent)
        ex.append(parent + "/" if parent not in ("", ".") else index)
    return ex


def diff_text(root: Path, cfg: dict, run: dict) -> str:
    return util.unified_diff(root, run.get("baseline_ref"), run.get("baseline_untracked"), review_exclude(cfg))


def diff_sha(root: Path, cfg: dict, run: dict) -> str:
    return util.sha256_bytes(diff_text(root, cfg, run).encode("utf-8"))


def eval_recorded(root: Path, cfg: dict, run: dict, name: str) -> dict:
    gate = (run.get("gates") or {}).get(name)
    if not gate or gate.get("state") != "passed":
        hint = {"plan": "not approved yet", "red": "not recorded yet",
                "simplify": "no accepted simplify report", "audit": "no accepted review report"}[name]
        return {"state": "pending", "reason": hint}
    ev = gate.get("evidence") or {}
    if name == "plan" and ev.get("plan_copy"):
        if util.sha256_file(root / ev["plan_copy"]) != ev.get("plan_hash"):
            return {"state": "stale", "reason": "the approved plan copy changed after approval - re-approve"}
    if name == "audit" and ev.get("diff_sha") and ev["diff_sha"] != diff_sha(root, cfg, run):
        return {"state": "stale", "reason": "the diff changed after the review - run a new review round"}
    return {"state": "passed", "reason": gate.get("reason") or "recorded"}


def evaluate_required(root: Path, cfg: dict, run: dict) -> dict:
    report = {}
    for name in required_gates(run, cfg):
        if name in LIVE:
            r = evaluate_live(root, cfg, run, name)
            report[name] = {"state": r["state"], "reason": r["reason"]}
        else:
            report[name] = eval_recorded(root, cfg, run, name)
    return report


def unmet(report: dict) -> list[str]:
    return [n for n, r in report.items() if r["state"] != "passed"]


def record_block(run: dict, unmet_names: list[str]) -> bool:
    """True when the release valve fires: the same unmet set blocked the turn
    RELEASE_VALVE times in a row, so a broken gate can never wedge a session."""
    sig = sorted(unmet_names)
    if run.get("last_unmet_signature") == sig:
        run["consecutive_blocks"] = run.get("consecutive_blocks", 0) + 1
    else:
        run["consecutive_blocks"] = 1
        run["last_unmet_signature"] = sig
    return run["consecutive_blocks"] >= RELEASE_VALVE


def record_progress(run: dict) -> None:
    run["consecutive_blocks"] = 0
    run["last_unmet_signature"] = None


FIX_HINTS = {
    "plan": "plan in plan mode (Claude) or write the plan and get approval, then: atw plan --files \"a,b\" ...",
    "red": "write proof tests (stub new code first), then: atw red --test \"<id>\" [--test ...]",
    "tests": "atw gate tests",
    "lint": "atw gate lint",
    "deps": "declare the import in its manifest, then: atw gate deps",
    "simplify": "atw simplify-packet, run a fresh simplifier, then: atw accept-simplify --report <path>",
    "audit": "atw review-packet, run the clean-room review in a FRESH agent, then: atw accept-review --report <path>",
    "nocode": "revert the protected change, or re-kind: atw kind code --why \"...\"",
    "placement": "write the deliverable where its kind requires (see atw status)",
    "provenance": "add '## Sources' with '- [id] ...' entries; tag claims measured/inferred with an [id]",
}
