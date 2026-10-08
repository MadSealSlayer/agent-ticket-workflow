"""Shared helpers: paths, atomic writes, time, and git access.

Rules for everything in this module:
  - Never talk to the network.
  - Never raise from a read helper. A Stop hook calls into this code and a
    bug here must not trap a session. Callers that need hard failures check
    return values themselves.
"""
from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

ATW_DIR = ".atw"
# Paths that belong to the workflow itself. They never count as a ticket's
# change: run state, scratch output, and the staged install payload.
INTERNAL_PREFIXES = (".atw/runs/", ".atw/tmp/", ".atw/staging/")


# ---------------------------------------------------------------------------
# Time and files
# ---------------------------------------------------------------------------

def now_iso() -> str:
    # Microseconds matter: gate freshness compares these against file mtimes.
    return datetime.now().isoformat(timespec="microseconds")


def now_epoch() -> float:
    return datetime.now().timestamp()


def epoch_of_iso(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value.strip()).timestamp()
    except Exception:
        return None


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a sibling temp file and os.replace, so a reader never sees a
    half-written file when two hooks write the same state at once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_json(path: Path, payload) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes())
    except Exception:
        return None


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()) or "unknown"


def posix(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def rel(root: Path, path: Path) -> str:
    try:
        return posix(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return posix(path)


def _strip_dot_slash(p: str) -> str:
    """Drop leading `./` and `/` only; a leading dot of a name (`.github`) stays."""
    while p.startswith(("./", "/")):
        p = p[2:] if p.startswith("./") else p[1:]
    return p


def under_any(path: str, prefixes) -> bool:
    """True if repo-relative `path` is under one of `prefixes`.
    A prefix without a trailing slash still matches whole path segments only."""
    p = _strip_dot_slash(posix(path))
    for raw in prefixes or ():
        pre = _strip_dot_slash(posix(raw)) if raw not in (".", "./") else ""
        if not pre:
            return True
        pre = pre if pre.endswith("/") else pre + "/"
        if p.startswith(pre) or p + "/" == pre:
            return True
    return False


def glob_match(path: str, patterns) -> bool:
    """fnmatch against the full posix path and the basename. `*` also crosses
    `/`, so `src/**/*.py` and `src/*.py` both match nested files."""
    p = posix(path)
    name = p.rsplit("/", 1)[-1]
    for pat in patterns or ():
        pat = posix(pat)
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(name, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(p, pat[3:]):
            return True
    return False


# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------

def project_root(start: Path | None = None) -> Path:
    """$ATW_PROJECT_DIR, then $CLAUDE_PROJECT_DIR, then git toplevel, then cwd."""
    for var in ("ATW_PROJECT_DIR", "CLAUDE_PROJECT_DIR"):
        env = os.environ.get(var)
        if env and Path(env).is_dir():
            return Path(env).resolve()
    cwd = start or Path.cwd()
    rc, out = git(cwd, "rev-parse", "--show-toplevel")
    if rc == 0 and out.strip():
        return Path(out.strip()).resolve()
    return cwd.resolve()


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def git(root: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=off", *args],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        return out.returncode, out.stdout
    except Exception as e:  # git missing, timeout
        return -1, str(e)


def is_git_repo(root: Path) -> bool:
    rc, out = git(root, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out.strip() == "true"


def current_branch(root: Path) -> str:
    rc, out = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    b = out.strip() if rc == 0 else ""
    if b and b != "HEAD":
        return b
    rc, out = git(root, "symbolic-ref", "--short", "HEAD")  # unborn branch
    return out.strip() if rc == 0 and out.strip() else "detached"


def head_sha(root: Path) -> str | None:
    rc, out = git(root, "rev-parse", "--verify", "-q", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def untracked_files(root: Path) -> list[str]:
    """Every untracked, non-ignored file. `ls-files --others` never collapses a
    new directory into one entry the way `git status` does."""
    rc, out = git(root, "ls-files", "--others", "--exclude-standard")
    return sorted(l.strip() for l in out.splitlines() if l.strip()) if rc == 0 else []


def _names(root: Path, *args: str) -> set[str]:
    rc, out = git(root, *args)
    return {l.strip() for l in out.splitlines() if l.strip()} if rc == 0 else set()


def changed_files(root: Path, baseline_ref: str | None, baseline_untracked=None) -> list[str]:
    """Repo-relative paths changed since `baseline_ref`, plus new untracked
    files. Files that were already untracked at run start do not count, and
    neither do the workflow's own internal paths."""
    files: set[str] = set()
    files |= _names(root, "diff", "--name-only", *([baseline_ref] if baseline_ref else []))
    files |= _names(root, "diff", "--cached", "--name-only")
    untracked = set(untracked_files(root))
    if baseline_untracked:
        untracked -= set(baseline_untracked)
    files |= untracked
    return sorted(f for f in files if not under_any(f, INTERNAL_PREFIXES))


def new_files(root: Path, baseline_ref: str | None, baseline_untracked=None) -> set[str]:
    result = set(untracked_files(root)) - set(baseline_untracked or ())
    for args in (("diff", "--cached", "--name-status"),
                 ("diff", "--name-status", *([baseline_ref] if baseline_ref else []))):
        rc, out = git(root, *args)
        for line in out.splitlines() if rc == 0 else []:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].startswith("A"):
                result.add(parts[1])
    return {f for f in result if not under_any(f, INTERNAL_PREFIXES)}


def changed_line_ranges(root: Path, baseline_ref: str | None, files: list[str]) -> dict[str, set[int]]:
    """Added or modified line numbers per tracked file. Untracked files are
    absent from the result, which callers read as "every line is new"."""
    ranges: dict[str, set[int]] = {}
    for f in files:
        rc, out = git(root, "diff", "-U0", *([baseline_ref] if baseline_ref else []), "--", f)
        if rc != 0:
            continue
        lines: set[int] = set()
        for hunk in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", out, re.MULTILINE):
            start = int(hunk.group(1))
            count = int(hunk.group(2)) if hunk.group(2) is not None else 1
            lines.update(range(start, start + count))
        if lines:
            ranges[f] = lines
    return ranges


def unified_diff(root: Path, baseline_ref: str | None, baseline_untracked=None, exclude=()) -> str:
    """The full change since the baseline as one text patch: tracked changes
    from git, new untracked files rendered with difflib. Deterministic for the
    same tree, so its hash is a staleness key for reviews."""
    files = [f for f in changed_files(root, baseline_ref, baseline_untracked) if not under_any(f, exclude)]
    untracked = set(untracked_files(root))
    tracked = [f for f in files if f not in untracked]
    chunks: list[str] = []
    if tracked:
        ref = [baseline_ref] if baseline_ref else (["--cached"] if not head_sha(root) else ["HEAD"])
        rc, out = git(root, "diff", "--no-color", "--no-ext-diff", *ref, "--", *tracked)
        if rc == 0:
            chunks.append(out)
    for f in sorted(set(files) & untracked):
        path = root / f
        try:
            after = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except Exception:
            after = ["<unreadable>\n"]
        lines = list(difflib.unified_diff([], after, fromfile="/dev/null", tofile=f"b/{f}"))
        chunks.append("".join(l if l.endswith("\n") else l + "\n" for l in lines) or f"+++ b/{f} (empty)\n")
    return "".join(chunks)


def files_written_since(root: Path, rel_dir: str, since_epoch: float) -> list[str]:
    """Files under `rel_dir` modified after `since_epoch`, by mtime. Needed for
    deliverables written to gitignored folders, which git cannot see."""
    d = root / rel_dir
    if not d.is_dir():
        return []
    threshold = since_epoch - 0.5  # tolerate coarse filesystem clocks
    out = []
    for p in d.rglob("*"):
        try:
            if p.is_file() and p.stat().st_mtime > threshold:
                out.append(rel(root, p))
        except Exception:
            continue
    return sorted(out)
