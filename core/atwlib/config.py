"""Project configuration: `.atw/atw.config.json`.

`/ticket-setup` writes this file from the interview. Everything that is
project-specific lives here and nowhere in the core: ticket locations,
protected paths, deliverable folders, and the commands the gates run.
"""
from __future__ import annotations

import copy
import re
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
AUDIT_ROUTES = ("agent", "t3-delegate")
VERIFY_WHEN = ("big", "always", "off")
DEFAULT_TEST_MARKERS = (
    # jasmine / jest / vitest / mocha: x- (disabled) and f- (focused) variants
    r"(?<![\w.$])(xit|xdescribe|xtest|xcontext|xspecify|fit|fdescribe|fcontext)\s*\(",
    # it.skip(, describe.only(, test.skip.each(, ...
    r"(?<![\w.$])(it|describe|test|context|suite|specify)\.(skip|only)\b",
    # pytest and unittest
    r"@pytest\.mark\.(skip|skipif|xfail)\b",
    r"\bpytest\.(skip|xfail)\s*\(",
    r"@unittest\.(skip|skipIf|skipUnless|expectedFailure)\b",
)

DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "python": "python",
    "tickets": {
        # `{id}` is replaced with the ticket id given to `atw start`.
        "globs": ["tickets/**/{id}.md", "tickets/**/ticket-{id}.md", "tickets/{id}.md"],
        # `atw new-ticket`: a ticket written from the conversation, after the
        # user approves the draft. `path` and `id_format` are str.format
        # templates: {n} is the next free number, {id} the formatted id, and
        # {lo}/{hi} the bounds of the range of `range_size` numbers that holds n
        # (range 100: 1-100, 101-200, ...).
        "new": {"path": "tickets/ticket-{id}.md", "id_format": "{n:03d}", "range_size": 100},
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
    # route "agent": a fresh sub-agent of the host reviews. "t3-delegate": in
    # T3 Code (T3CODE_THREAD_ID set), a Claude session hands the packet to a
    # T3 `delegate_task` child on `t3.provider`/`t3.model`, and falls back to
    # "agent" when that is not possible. Read by the ticket skill only.
    "audit": {
        "model": "opus",
        "route": "agent",
        "t3": {"provider": "codex", "model": "gpt-6.2-sol", "reasoning_effort": "medium"},
    },
    # Realistic verification (the `verify` gate): run the change for real
    # (integration, browser, end-to-end) before close, next to the static
    # review. "big": required for coordinated code runs and for runs whose
    # plan or proof set reaches a threshold. `how` names the project's own
    # check (a skill, a command or a checklist); "" means none is configured,
    # and then every criterion is reported "not run" for the user to accept.
    "verify": {
        "when": "big",                # "big" | "always" | "off"
        "how": "",
        "min_planned_files": 8,
        "min_proof_ids": 8,
        "recheck_after_rounds": 2,    # review rounds after the check that make it stale
        "ignore": [],                 # paths the check writes that must not count as the change
    },
    "context": {"enabled": False, "index": "docs/agent-context/INDEX.md"},
    "guards": {
        # Named git rules (guard.GIT_RULES), checked on each parsed command,
        # so `echo "git push"` or a grep pattern never matches. Deny wins
        # over ask. An "ask" list set here replaces this one: write
        # "ask": [] to drop the default ask.
        "git": {
            "deny": ["reset-hard", "push-force", "rebase", "clean-force", "commit-amend"],
            "ask": ["push"],
        },
        # Ask before `git add` stages data, binary or very large files.
        "git_add_data": True,
        # Ask before rm / del / Remove-Item / git rm deletes a test file.
        "test_delete": True,
        # Custom regexes, searched in each parsed command's text (heredoc
        # bodies removed; quoted text inside the command still matches).
        # Use "git" above for git commands.
        "deny": [],
        "ask": [],
        "protect_before_plan": True,
        # An Edit/Write that adds one of these to a test file asks the user
        # first: disabling or focusing a test is the user's call. [] = off.
        "test_markers": list(DEFAULT_TEST_MARKERS),
    },
    "ste": {"enabled": False},
    # Free-form pointers for investigation tickets: the project's own data
    # tools and where their credentials come from. Read by the skill only.
    "investigation": {"tools": [], "notes": ""},
    # Jira through the host's Atlassian MCP connector (the `jira` skill). The
    # core never calls Jira; `atw import-jira` only turns a fetched issue into
    # <import_dir>/<KEY>.md.
    "jira": {
        "enabled": False,
        "site": "",                   # host only, e.g. "example.atlassian.net"
        "projects": [],               # [{"key": "ABC", "use": "the team's board"}]
        "default_project": "",
        "start_transition": None,     # e.g. "In Progress": move To Do issues there at start of work; None = ask
        "in_progress_aliases": [],    # status names that already count as in progress
        "import_dir": "tickets",
    },
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
    for key in ("deny", "ask", "test_markers"):
        pats = (cfg.get("guards") or {}).get(key, [])
        if not _is_str_list(pats):
            errs.append(f"guards.{key} must be a list of regex strings")
            continue
        for pat in pats:
            try:
                re.compile(pat)
            except re.error as e:
                errs.append(f"guards.{key} has an invalid regex {pat!r}: {e}")
    errs += _validate_git_guards(cfg)
    errs += _validate_new_ticket(cfg)
    errs += _validate_audit(cfg)
    errs += _validate_verify(cfg)
    errs += _validate_jira(cfg)
    return errs


def _validate_verify(cfg: dict) -> list[str]:
    v = cfg.get("verify")
    if not isinstance(v, dict):
        return ["verify must be an object"]
    errs = []
    if v.get("when") not in VERIFY_WHEN:
        errs.append(f"verify.when must be one of {VERIFY_WHEN}")
    if not isinstance(v.get("how"), str):
        errs.append("verify.how must be a string (a skill, a command or a checklist; \"\" = none)")
    for key in ("min_planned_files", "min_proof_ids", "recheck_after_rounds"):
        n = v.get(key)
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            errs.append(f"verify.{key} must be a positive integer")
    if not _is_str_list(v.get("ignore")):
        errs.append("verify.ignore must be a list of paths")
    return errs


def _validate_git_guards(cfg: dict) -> list[str]:
    from .guard import GIT_RULES
    guards = cfg.get("guards") or {}
    errs = []
    git = guards.get("git")
    if not isinstance(git, dict):
        errs.append('guards.git must be an object {"deny": [rule, ...], "ask": [rule, ...]}')
    else:
        for kind in ("deny", "ask"):
            rules = git.get(kind, [])
            if not _is_str_list(rules):
                errs.append(f"guards.git.{kind} must be a list of rule names")
                continue
            bad = [r for r in rules if r not in GIT_RULES]
            if bad:
                errs.append(f"guards.git.{kind} has unknown rule(s) {bad}; known: {sorted(GIT_RULES)}")
        unknown = sorted(set(git) - {"deny", "ask"})
        if unknown:
            errs.append(f"guards.git has unknown key(s) {unknown}; use deny and ask")
    for key in ("git_add_data", "test_delete", "protect_before_plan"):
        if not isinstance(guards.get(key, True), bool):
            errs.append(f"guards.{key} must be true or false")
    return errs


# The regexes that guards.deny/guards.ask had by default before 0.3.0, plus
# the usual "agents never commit or push" additions, with the guards.git rule
# that replaces each. `atw doctor` warns about them; it never rewrites a config.
LEGACY_GIT_PATTERNS = {
    r"\bgit\s+reset\s+--hard\b": "reset-hard",
    r"\bgit\s+push\b[^\n]*\s(--force|-f)(\s|$)": "push-force",
    r"\bgit\s+push\b[^\n]*--force-with-lease": "push-force",
    r"\bgit\s+commit\b[^\n]*--amend": "commit-amend",
    r"\bgit\s+clean\b[^\n]*\s-[a-zA-Z]*f": "clean-force",
    r"\bgit\s+rebase\b": "rebase",
    r"\bgit\s+push\b": "push",
    r"\bgit\s+commit\b": "commit",
}


def legacy_git_patterns(raw: dict) -> dict:
    """{"deny": [(pattern, rule), ...], "ask": [...]} for the old raw git
    regexes in a project's own config file (not the merged defaults)."""
    guards = (raw or {}).get("guards") or {}
    out = {}
    for kind in ("deny", "ask"):
        pats = guards.get(kind) or []
        found = [(p, LEGACY_GIT_PATTERNS[p]) for p in pats if isinstance(p, str) and p in LEGACY_GIT_PATTERNS]
        if found:
            out[kind] = found
    return out


def _validate_new_ticket(cfg: dict) -> list[str]:
    """Structure only. Whether `tickets.globs` finds the path is checked by
    `atw new-ticket` itself, so older configs with their own globs stay valid."""
    new = (cfg.get("tickets") or {}).get("new")
    if not isinstance(new, dict):
        return ["tickets.new must be an object with path, id_format and range_size"]
    errs = []
    size = new.get("range_size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        errs.append("tickets.new.range_size must be a positive integer")
        size = 100
    path = new.get("path")
    if (not isinstance(path, str) or "{id}" not in path or path.startswith(("/", ".."))
            or "\\" in path or "/../" in path or not path.endswith(".md")):
        errs.append("tickets.new.path must be a .md path inside the project that contains {id}")
    else:
        try:
            path.format(id="001", n=1, lo=1, hi=size)
        except (KeyError, IndexError, ValueError) as e:
            errs.append(f"tickets.new.path: only the fields {{id}}, {{n}}, {{lo}} and {{hi}} are allowed ({e})")
    fmt = new.get("id_format")
    try:
        sample = fmt.format(n=1) if isinstance(fmt, str) else None
    except (KeyError, IndexError, ValueError):
        sample = None
    from .state import TICKET_ID
    if not sample or not TICKET_ID.fullmatch(sample) or "{n" not in fmt:
        errs.append('tickets.new.id_format must format {n} into a valid ticket id, e.g. "{n:03d}"')
    return errs


def _validate_audit(cfg: dict) -> list[str]:
    audit = cfg.get("audit") or {}
    errs = []
    if audit.get("route", "agent") not in AUDIT_ROUTES:
        errs.append(f"audit.route must be one of {AUDIT_ROUTES}")
    t3 = audit.get("t3")
    if not isinstance(t3, dict) or not all(isinstance(t3.get(k), str) and t3[k].strip()
                                           for k in ("provider", "model", "reasoning_effort")):
        errs.append("audit.t3 must have non-empty provider, model and reasoning_effort strings")
    return errs


def _validate_jira(cfg: dict) -> list[str]:
    from . import jira as jira_mod
    jira = cfg.get("jira") or {}
    if not jira.get("enabled"):
        return []
    errs = []
    if not isinstance(jira.get("site"), str) or not jira_mod.SITE_RE.fullmatch(jira["site"]):
        errs.append('jira.site must be a host name such as "example.atlassian.net" (no scheme, no path)')
    projects = jira.get("projects")
    if not isinstance(projects, list) or not projects or not all(
            isinstance(p, dict) and isinstance(p.get("key"), str) and jira_mod.PROJECT_RE.fullmatch(p["key"])
            for p in projects):
        errs.append('jira.projects must be a non-empty list of {"key": "ABC", "use": "..."}')
    keys = [p.get("key") for p in projects or [] if isinstance(p, dict)]
    if jira.get("default_project") and jira["default_project"] not in keys:
        errs.append("jira.default_project must be one of jira.projects")
    st = jira.get("start_transition")
    if st is not None and (not isinstance(st, str) or not st.strip()):
        errs.append("jira.start_transition must be a status name or null")
    if not _is_str_list(jira.get("in_progress_aliases", [])):
        errs.append("jira.in_progress_aliases must be a list of status names")
    imp = jira.get("import_dir")
    if not isinstance(imp, str) or not imp.strip() or imp.startswith(("/", "..")) or "\\" in imp:
        errs.append("jira.import_dir must be a folder inside the project")
    elif not jira_mod.matched_by_globs(jira_mod.target_path(cfg, "ABC-1"), (cfg.get("tickets") or {}).get("globs"), "ABC-1"):
        errs.append(f"jira.import_dir {imp}/ is not covered by tickets.globs: imported tickets could not be started")
    return errs
