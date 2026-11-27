"""Command rules of the PreToolUse guard (Bash and PowerShell tools).

A command line is parsed into the commands it runs (`shell.segments`). The
rules apply to each command, not to the raw text, so a command that only
mentions `git push` in a string, a sed or grep pattern, or a heredoc body is
never matched. Every rule is checked on every command; a deny always wins
over an ask, so approving one prompt never runs a denied part of a chain.

Rules, all from `guards` in the config:
  git           named git rules, {"deny": [...], "ask": [...]} (GIT_RULES)
  git_add_data  ask before `git add` of data, binary or very large files
  test_delete   ask before a shell command deletes a test file
  deny / ask    custom regexes, searched in each command's text (quoted
                text inside that command still matches)
"""
from __future__ import annotations

import re
from pathlib import Path

from . import gates, shell, util


def _push_force(a: list[str]) -> bool:
    return (any(x in ("--force", "--force-if-includes") or x.startswith("--force-with-lease") for x in a)
            or shell.short_flag_has(a, "f")
            or any(x.startswith("+") for x in a))


def _push_delete(a: list[str]) -> bool:
    return ("--delete" in a or shell.short_flag_has(a, "d")
            or any(x.startswith(":") and len(x) > 1 for x in a))


# name -> (description, predicate(subcommand, args))
GIT_RULES: dict = {
    "reset-hard": ("git reset --hard", lambda s, a: s == "reset" and "--hard" in a),
    "push-force": ("force push (--force, -f, --force-with-lease, +refspec)", lambda s, a: s == "push" and _push_force(a)),
    "push-delete": ("push that deletes a remote branch (--delete, -d, :branch)",
                    lambda s, a: s == "push" and _push_delete(a)),
    "push": ("any git push", lambda s, a: s == "push"),
    "rebase": ("git rebase", lambda s, a: s == "rebase"),
    "clean-force": ("git clean -f / --force", lambda s, a: s == "clean" and ("--force" in a or shell.short_flag_has(a, "f"))),
    "commit-amend": ("git commit --amend", lambda s, a: s == "commit" and "--amend" in a),
    "commit": ("any git commit", lambda s, a: s == "commit"),
    "filter-branch": ("git filter-branch / filter-repo", lambda s, a: s in ("filter-branch", "filter-repo")),
    "update-ref-delete": ("git update-ref -d", lambda s, a: s == "update-ref" and "-d" in a),
    "reflog-expire": ("git reflog expire", lambda s, a: s == "reflog" and a[:1] == ["expire"]),
}

# git add: files that are data, not source. Images are included on purpose:
# it is an ask, and a screenshot or a chart is the usual accident.
DATA_EXTS = {
    ".csv", ".tsv", ".parquet", ".feather", ".avro", ".xlsx", ".xls", ".jsonl", ".ndjson",
    ".pkl", ".pickle", ".joblib", ".npy", ".npz", ".h5", ".hdf5", ".pt", ".pth", ".onnx", ".ckpt", ".safetensors",
    ".sqlite", ".sqlite3", ".db", ".dump", ".bak", ".log", ".har",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".pdf",
    ".mp4", ".mov", ".webm", ".mp3", ".wav",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".whl",
}
# Manifests and lock files: never data, at any size (a package-lock.json is
# often over 1 MB).
SIZE_EXEMPT = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock",
    "angular.json", "tsconfig.json", "jsconfig.json", "composer.json", "composer.lock",
    "pyproject.toml", "poetry.lock", "Pipfile.lock", "uv.lock", "pdm.lock", "Cargo.lock",
}
JSON_SIZE_LIMIT = 50_000
SIZE_LIMIT = 1_000_000
_WHOLE_TREE = {"-A", "--all", "-u", "--update", "--no-ignore-removal"}

DELETE_COMMANDS = {"rm", "del", "erase", "remove-item", "ri", "rmdir", "rd", "unlink"}

DENY_TAIL = "This command is the developer's call: ask them to run it."


def is_test_file(cfg: dict, rel: str) -> bool:
    if util.under_any(rel, cfg.get("test_paths") or []):
        return True
    tests = (cfg.get("commands") or {}).get("tests") or {}
    return util.glob_match(rel, tests.get("test_globs") or gates.DEFAULT_TEST_GLOBS)


def evaluate(root: Path, cfg: dict, command: str, powershell: bool = False) -> tuple[str, str] | None:
    """("deny" | "ask", reason) for a Bash/PowerShell command, or None."""
    guards = cfg.get("guards") or {}
    git_cfg = guards.get("git") or {}
    matches: list[tuple[str, str]] = []
    for seg in shell.segments(command, powershell):
        toks = shell.normalized(seg, powershell)
        git = shell.git_invocation(toks)
        if git:
            sub, args, cdir = git
            for kind in ("deny", "ask"):
                for name in git_cfg.get(kind) or []:
                    rule = GIT_RULES.get(name)
                    if rule and rule[1](sub, args):
                        matches.append((kind, _git_reason(kind, name, seg)))
            if sub == "add" and guards.get("git_add_data", True):
                flagged = _data_files_added(root, args, cdir)
                if flagged:
                    matches.append(("ask", f"`git add` stages data, binary or very large file(s): "
                                           f"{', '.join(flagged[:5])}. Data does not belong in the repository "
                                           "unless the user says so."))
            if sub == "rm" and "--cached" not in args and guards.get("test_delete", True):
                matches += _test_delete(root, cfg, args, cdir)
        elif toks and toks[0] in DELETE_COMMANDS and guards.get("test_delete", True):
            matches += _test_delete(root, cfg, toks[1:], None)
        for kind in ("deny", "ask"):
            for pat in guards.get(kind) or []:
                if re.search(pat, seg):
                    matches.append((kind, f"blocked by the ticket workflow guard ({pat}). {DENY_TAIL}"
                                    if kind == "deny" else f"the ticket workflow asks before this command ({pat})"))
    if not matches:
        return None
    denies = [m for m in matches if m[0] == "deny"]
    return denies[0] if denies else matches[0]


def _git_reason(kind: str, name: str, seg: str) -> str:
    what = GIT_RULES[name][0]
    if kind == "deny":
        return f"blocked by the ticket workflow guard (guards.git rule '{name}': {what}) in `{seg}`. {DENY_TAIL}"
    return f"the ticket workflow asks before this command (guards.git rule '{name}': {what})"


def _paths(args: list[str]) -> tuple[list[str], list[str]]:
    """(options, paths) of a command's arguments; `--` ends the options."""
    opts, paths, ended = [], [], False
    for a in args:
        if not ended and a == "--":
            ended = True
        elif not ended and a.startswith("-") and len(a) > 1:
            opts.append(a)
        else:
            paths.append(a)
    return opts, paths


def _rel(root: Path, base: Path, arg: str) -> str:
    p = Path(arg)
    return util.rel(root, p if p.is_absolute() else base / p)


def _data_files_added(root: Path, args: list[str], cdir: str | None) -> list[str]:
    opts, paths = _paths(args)
    base = root / cdir if cdir else root
    changed = None
    if not paths or "." in paths or any(o in _WHOLE_TREE for o in opts):
        candidates = util.changed_files(root, None)
    else:
        candidates = []
        for arg in paths:
            rel = _rel(root, base, arg)
            if (root / rel).is_dir() or any(c in arg for c in "*?["):
                changed = util.changed_files(root, None) if changed is None else changed
                candidates += [f for f in changed if util.under_any(f, [rel]) or util.glob_match(f, [rel])]
            else:
                candidates.append(rel)
    return [f for f in dict.fromkeys(candidates) if _is_data_file(root, f)]


def _is_data_file(root: Path, rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if name in SIZE_EXEMPT or re.fullmatch(r"tsconfig\..+\.json", name):
        return False
    ext = Path(name).suffix.lower()
    if ext in DATA_EXTS:
        return True
    try:
        size = (root / rel).stat().st_size if (root / rel).is_file() else 0
    except OSError:
        size = 0
    return size > SIZE_LIMIT or (ext == ".json" and size > JSON_SIZE_LIMIT)


def _test_delete(root: Path, cfg: dict, args: list[str], cdir: str | None) -> list[tuple[str, str]]:
    base = root / cdir if cdir else root
    hit = []
    for arg in _paths(args)[1]:
        rel = _rel(root, base, arg)
        if _holds_tests(root, cfg, rel):
            hit.append(rel)
    if not hit:
        return []
    return [("ask", f"this deletes test file(s): {', '.join(hit[:5])}. Removing a test to make a gate pass "
                    "is what the workflow prevents; deleting one needs the user's OK.")]


def _holds_tests(root: Path, cfg: dict, rel: str) -> bool:
    if is_test_file(cfg, rel):
        return True
    if any(util.under_any(tp, [rel]) for tp in cfg.get("test_paths") or []):
        return True  # a folder that contains a test folder (rm -rf ., rm -r src)
    if (root / rel).is_dir():
        rc, out = util.git(root, "ls-files", "--", rel)
        return rc == 0 and any(is_test_file(cfg, f) for f in out.splitlines())
    return False
