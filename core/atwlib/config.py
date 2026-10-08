"""Project configuration: `.atw/atw.config.json`.

`/ticket-setup` writes this file from the interview. Everything that is
project-specific lives here and nowhere in the core: ticket locations,
protected paths, deliverable folders, and the commands the gates run.
"""
from __future__ import annotations

import copy
from pathlib import Path

from . import util

CONFIG_PATH = ".atw/atw.config.json"
SCHEMA_VERSION = 1

ALL_KINDS = ("code", "investigation", "comms", "docs", "tooling", "spike")
HOSTS = ("claude", "codex", "other")
SIMPLIFY_MODES = ("off", "advisory", "gate")
LINT_OUTPUTS = ("exit-code", "ruff-json", "eslint-json")
TEST_SCOPES = ("all", "changed-tests", "stem-match")
DEPS_BUILTINS = ("python-imports", "node-imports")
ID_STYLES = ("pytest", "name")

DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "python": "python",
    "tickets": {
        # `{id}` is replaced with the ticket id given to `atw start`.
        "globs": ["tickets/**/{id}.md", "tickets/**/ticket-{id}.md", "tickets/{id}.md"],
    },
    "kinds": {"enabled": ["code", "investigation", "comms", "docs", "tooling"]},
    # Source that only a `code` run may change. Non-code runs fail `nocode` if
    # they touch these, and the guard asks before edits here until `plan` passes.
    "protected_paths": [],
    "test_paths": [],
    "placement": {
        "investigation": "docs/agent-notes/investigations",
        "comms": "docs/agent-notes/comms",
        "docs": "docs",
        "tooling": "scripts",
    },
    "plan_dir": ".atw/plans",
    "commands": {
        "proof": None,   # {"run": "... {ids}|{id_files} ... {junit}", "env": {...}, "id_style": "pytest"|"name", "weak_patterns": [...]}
        "tests": None,   # {"run": "...", "scope": "all"|"changed-tests"|"stem-match", "test_globs": [...], "source_globs": [...]}
        "lint": None,    # {"run": "... {files}", "output": "exit-code"|"ruff-json"|"eslint-json", "file_globs": [...], "changed_lines_only": true}
        "deps": None,    # {"builtin": "python-imports"|"node-imports"} or {"run": "..."}
    },
    "timeouts": {"command_seconds": 600},
    "simplify": "off",
    "audit": {"model": "opus"},
    "context": {"enabled": False, "index": "docs/agent-context/INDEX.md"},
    "guards": {
        "deny": [
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+push\b[^\n]*\s(--force|-f)(\s|$)",
            r"\bgit\s+push\b[^\n]*--force-with-lease",
            r"\bgit\s+commit\b[^\n]*--amend",
            r"\bgit\s+clean\b[^\n]*\s-[a-zA-Z]*f",
            r"\bgit\s+rebase\b",
        ],
        "ask": [r"\bgit\s+push\b"],
        "protect_before_plan": True,
    },
    "ste": {"enabled": False},
    # Free-form pointers for investigation tickets: the project's own data
    # tools and where their credentials come from. Read by the skill only.
    "investigation": {"tools": [], "notes": ""},
    "names": {},  # skill renames chosen at setup, e.g. {"ticket": "atw-ticket"}
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def config_path(root: Path) -> Path:
    return root / CONFIG_PATH


def load(root: Path) -> dict:
    """Defaults merged with the project's file. A missing or unreadable file
    gives the defaults, so hooks keep working; `atw doctor` reports it."""
    raw = util.read_json(config_path(root), default={})
    return _merge(DEFAULTS, raw if isinstance(raw, dict) else {})


def exists(root: Path) -> bool:
    return config_path(root).is_file()


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def validate(cfg: dict) -> list[str]:
    """Return human-readable problems. Empty list means valid."""
    errs: list[str] = []
    if cfg.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(cfg.get("python"), str) or not cfg["python"].strip():
        errs.append("python must be a non-empty command string")
    globs = (cfg.get("tickets") or {}).get("globs")
    if not _is_str_list(globs) or not globs or not all("{id}" in g for g in globs):
        errs.append("tickets.globs must be a non-empty list of patterns that contain {id}")
    enabled = (cfg.get("kinds") or {}).get("enabled")
    if not _is_str_list(enabled) or not enabled:
        errs.append("kinds.enabled must be a non-empty list")
    else:
        bad = [k for k in enabled if k not in ALL_KINDS]
        if bad:
            errs.append(f"kinds.enabled has unknown kinds: {bad}")
    for key in ("protected_paths", "test_paths"):
        if not _is_str_list(cfg.get(key)):
            errs.append(f"{key} must be a list of strings")
    if "code" in (enabled or []) and not cfg.get("protected_paths"):
        errs.append("protected_paths is empty: non-code runs could change source unnoticed")
    placement = cfg.get("placement") or {}
    for kind in ("investigation", "comms", "docs", "tooling"):
        if kind in (enabled or []) and not isinstance(placement.get(kind), str):
            errs.append(f"placement.{kind} must be a folder path")
    if cfg.get("simplify") not in SIMPLIFY_MODES:
        errs.append(f"simplify must be one of {SIMPLIFY_MODES}")

    cmds = cfg.get("commands") or {}
    proof, tests, lint, deps = (cmds.get(k) for k in ("proof", "tests", "lint", "deps"))
    if "code" in (enabled or []):
        if not proof:
            errs.append("commands.proof is required when kind 'code' is enabled")
        if not tests:
            errs.append("commands.tests is required when kind 'code' is enabled")
    if proof:
        run = proof.get("run", "")
        env_values = " ".join(str(v) for v in (proof.get("env") or {}).values())
        if "{ids}" not in run and "{id_files}" not in run:
            errs.append("commands.proof.run must contain {ids} or {id_files}")
        if "{junit}" not in run + " " + env_values:
            errs.append("commands.proof must write JUnit XML to {junit} (in run, or in an env value)")
        if proof.get("id_style", "pytest") not in ID_STYLES:
            errs.append(f"commands.proof.id_style must be one of {ID_STYLES}")
        if "weak_patterns" in proof and not _is_str_list(proof["weak_patterns"]):
            errs.append("commands.proof.weak_patterns must be a list of regex strings")
    if tests:
        if not isinstance(tests.get("run"), str) or not tests["run"].strip():
            errs.append("commands.tests.run must be a command string")
        if tests.get("scope", "all") not in TEST_SCOPES:
            errs.append(f"commands.tests.scope must be one of {TEST_SCOPES}")
        if tests.get("scope", "all") != "all" and "{files}" not in tests.get("run", ""):
            errs.append("commands.tests.run must contain {files} when scope is not 'all'")
    if lint:
        if "{files}" not in lint.get("run", ""):
            errs.append("commands.lint.run must contain {files}")
        if lint.get("output", "exit-code") not in LINT_OUTPUTS:
            errs.append(f"commands.lint.output must be one of {LINT_OUTPUTS}")
        if not _is_str_list(lint.get("file_globs", [])):
            errs.append("commands.lint.file_globs must be a list")
    if deps:
        if bool(deps.get("builtin")) == bool(deps.get("run")):
            errs.append("commands.deps needs exactly one of 'builtin' or 'run'")
        elif deps.get("builtin") and deps["builtin"] not in DEPS_BUILTINS:
            errs.append(f"commands.deps.builtin must be one of {DEPS_BUILTINS}")
    for key in ("deny", "ask"):
        if not _is_str_list((cfg.get("guards") or {}).get(key, [])):
            errs.append(f"guards.{key} must be a list of regex strings")
    return errs
