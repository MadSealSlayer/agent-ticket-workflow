"""Behavioral RED/GREEN checks for a run's proof set, from JUnit XML.

A proof set is a list of test ids, one per acceptance criterion. RED means
each id currently fails because the behavior is wrong, not because the code
under test is missing. A failure whose message matches a "weak" pattern
(import error, undefined name, missing function) is not a red: stub the code
first (e.g. `def f(x): return None`) so the assertion itself fails.
GREEN means each id ran and passed.

An id that the runner never reported (typo, collection error, deselected) is
always a failure, never a pass.

Id styles:
  pytest  `path/test_x.py::Class::test_y[p]`, matched exactly the way pytest
          writes classname/name into JUnit.
  name    `path/to/file.test.ts::full test name` or just `full test name`.
          Matches a testcase whose name equals the title or ends with it after
          a separator (` `, ` > `, ` › `). When a path is given, the testcase's
          file or classname must contain that file's name. Two matches are an
          error: use a more specific title.
"""
from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import runner

PY_WEAK = [
    r"^(\w+\.)*(ImportError|ModuleNotFoundError|NameError|NotImplementedError|SyntaxError|IndentationError)\b",
    r"^AttributeError: (module '[^']*' has no attribute|<module '[^']*'.*> does not have the attribute)",
]
JS_WEAK = [
    r"Cannot find module",
    r"Failed to (resolve|load) (import|url)",
    r"does not provide an export named",
    r"is not a function",
    r"is not a constructor",
    r"is not defined",
    r"^SyntaxError\b",
    r"^ReferenceError\b",
]
GO_WEAK = [r"undefined: ", r"cannot find package", r"\[build failed\]", r"\[setup failed\]"]
DEFAULT_WEAK = PY_WEAK + JS_WEAK + GO_WEAK


def nodeid_to_case(nodeid: str) -> tuple[str, str]:
    """`a/b/test_x.py::Cls::test_y[p]` -> ("a.b.test_x.Cls", "test_y[p]")."""
    parts = nodeid.replace("\\", "/").split("::")
    module = parts[0][:-3] if parts[0].endswith(".py") else parts[0]
    classname = ".".join([module.replace("/", "."), *parts[1:-1]])
    return classname, parts[-1]


def parse_cases(junit_text: str) -> list[ET.Element]:
    if not (junit_text or "").strip():
        return []
    try:
        return list(ET.fromstring(junit_text).iter("testcase"))
    except ET.ParseError:
        return []


def _find_pytest(cases, test_id):
    key = nodeid_to_case(test_id)
    hits = [c for c in cases if (c.get("classname", ""), c.get("name", "")) == key]
    return hits


_SEPARATORS = (" > ", " › ", " ")


def _find_by_name(cases, test_id):
    path, _, title = test_id.replace("\\", "/").rpartition("::")
    title = title.strip()
    file_name = path.rsplit("/", 1)[-1] if path else ""
    hits = []
    for c in cases:
        name = (c.get("name") or "").strip()
        if not (name == title or any(name.endswith(sep + title) for sep in _SEPARATORS)):
            continue
        if file_name:
            where = (c.get("file") or "") + " " + (c.get("classname") or "")
            if file_name not in where.replace("\\", "/"):
                continue
        hits.append(c)
    return hits


def find_case(cases, test_id: str, id_style: str):
    hits = _find_pytest(cases, test_id) if id_style == "pytest" else _find_by_name(cases, test_id)
    if len(hits) > 1:
        return None, "ambiguous: more than one test matches this id - use a more specific title"
    return (hits[0] if hits else None), None


def weak_reason(message: str, patterns) -> str | None:
    first = (message or "").strip()
    for pat in patterns:
        if re.search(pat, first, re.MULTILINE):
            return pat
    return None


def _failure_message(el: ET.Element) -> str:
    msg = el.get("message") or ""
    body = (el.text or "").strip()
    return (msg + "\n" + body).strip() if body and body not in msg else msg


def verdict(case, mode: str, patterns, problem: str | None = None) -> dict:
    if problem:
        return {"ok": False, "outcome": "ambiguous", "detail": problem}
    if case is None:
        return {"ok": False, "outcome": "missing",
                "detail": "not reported by the test runner (typo, collection error, or deselected)"}
    for tag in ("error", "skipped"):
        el = case.find(tag)
        if el is not None:
            return {"ok": False, "outcome": tag, "detail": _failure_message(el)[:300]}
    failure = case.find("failure")
    if failure is None:
        if mode == "green":
            return {"ok": True, "outcome": "passed", "detail": ""}
        return {"ok": False, "outcome": "passed", "detail": "already passes - the change is not proven"}
    message = _failure_message(failure)
    if mode == "green":
        return {"ok": False, "outcome": "failed", "detail": message[:300]}
    # The message attribute names the exception. The body is a traceback that
    # can quote unrelated source, so it is only used when there is no message.
    weak = weak_reason(failure.get("message") or (failure.text or ""), patterns)
    if weak:
        return {"ok": False, "outcome": "failed",
                "detail": f"weak red (matches {weak!r}) - stub the code so the test fails on behavior: {message[:300]}"}
    return {"ok": True, "outcome": "failed", "detail": message[:300]}


def check(junit_text: str, ids: list[str], mode: str, id_style: str = "pytest", patterns=None) -> dict:
    """Classify each id as a valid `mode` ("red"|"green") result. The set passes
    only if it is non-empty and every id is ok."""
    patterns = DEFAULT_WEAK if patterns is None else patterns
    cases = parse_cases(junit_text)
    verdicts = {}
    for tid in ids:
        case, problem = find_case(cases, tid, id_style)
        verdicts[tid] = verdict(case, mode, patterns, problem)
    return {"passed": bool(ids) and all(v["ok"] for v in verdicts.values()), "verdicts": verdicts}


def run_and_check(root: Path, cfg: dict, ids: list[str], mode: str, work_dir: Path | None = None) -> dict:
    """Run exactly `ids` with the configured proof command and check() them."""
    proof = (cfg.get("commands") or {}).get("proof") or {}
    if not proof.get("run"):
        return {"passed": False, "verdicts": {}, "command": None,
                "summary": "commands.proof is not configured - run /ticket-setup"}
    if work_dir:
        work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(work_dir) if work_dir else None) as tmp:
        junit = Path(tmp) / "junit.xml"
        cmd = runner.render(proof["run"], ids=ids, junit=junit, python=cfg.get("python"))
        env = {k: runner.render(v, junit=junit).strip('"') for k, v in (proof.get("env") or {}).items()}
        res = runner.run(root, cmd, timeout=(cfg.get("timeouts") or {}).get("command_seconds", 600), env=env)
        text = junit.read_text(encoding="utf-8", errors="ignore") if junit.exists() else ""
    patterns = proof.get("weak_patterns") or DEFAULT_WEAK
    result = check(text, ids, mode, proof.get("id_style", "pytest"), patterns)
    result["command"] = cmd
    result["summary"] = res["error"] or runner.tail(res["output"])
    if not text:
        result["summary"] = (result["summary"] + " | no JUnit XML was written - check commands.proof.run").strip(" |")
    return result
