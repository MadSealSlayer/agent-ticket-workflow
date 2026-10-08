"""`atw doctor` (is the installation healthy?) and `atw hygiene` (stray files).

Both are read-only. doctor exits 1 on any FAIL; WARN never fails it.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import config, runner, state, util

MANIFEST = ".atw/install-manifest.json"


class Report:
    def __init__(self):
        self.lines: list[tuple[str, str]] = []

    def ok(self, msg): self.lines.append(("OK", msg))
    def warn(self, msg): self.lines.append(("WARN", msg))
    def fail(self, msg): self.lines.append(("FAIL", msg))

    def print(self) -> int:
        for level, msg in self.lines:
            print(f"[{level:4}] {msg}")
        fails = sum(1 for lvl, _ in self.lines if lvl == "FAIL")
        warns = sum(1 for lvl, _ in self.lines if lvl == "WARN")
        print(f"\n{'HEALTHY' if not fails else 'NOT HEALTHY'}: {fails} fail, {warns} warn")
        return 1 if fails else 0


def _first_token(command: str) -> str:
    try:
        parts = shlex.split(command, posix=(sys.platform != "win32"))
    except ValueError:
        parts = command.split()
    return parts[0].strip('"') if parts else ""


def _executable(cfg: dict, command: str) -> str | None:
    rendered = runner.render(command, files=[], ids=[], junit="x.xml", python=cfg.get("python"))
    tok = _first_token(rendered)
    if not tok:
        return None
    return tok if (shutil.which(tok) or Path(tok).is_file()) else None


def run(root: Path, run_commands: bool = False) -> int:
    r = Report()
    manifest = util.read_json(root / MANIFEST, default=None)
    cfg = config.load(root)

    # Git.
    if util.is_git_repo(root):
        r.ok(f"git repository (branch {util.current_branch(root)})")
    else:
        r.fail("not a git repository - runs need git for baselines and diffs")

    # Config.
    if not config.exists(root):
        r.fail(f"{config.CONFIG_PATH} is missing - run the setup skill")
    else:
        raw = util.read_json(config.config_path(root), default=None)
        if not isinstance(raw, dict):
            r.fail(f"{config.CONFIG_PATH} is not valid JSON")
        else:
            problems = config.validate(cfg)
            for p in problems:
                r.fail(f"config: {p}")
            if not problems:
                r.ok(f"config valid (kinds: {', '.join(cfg['kinds']['enabled'])})")

    # Manifest and owned files.
    if not manifest:
        r.fail(f"{MANIFEST} is missing - the install was not applied")
    else:
        core_version = (root / ".atw/core/VERSION").read_text(encoding="utf-8").strip() \
            if (root / ".atw/core/VERSION").is_file() else None
        if core_version != manifest.get("version"):
            r.fail(f"core version {core_version} differs from manifest {manifest.get('version')}")
        else:
            r.ok(f"agent-ticket-workflow {core_version} installed for {', '.join(manifest.get('hosts') or [])}")
        missing, modified = [], []
        for rel, sha in (manifest.get("files") or {}).items():
            p = root / rel
            if not p.is_file():
                missing.append(rel)
            elif rel != config.CONFIG_PATH and util.sha256_file(p) != sha:
                modified.append(rel)
        if missing:
            r.fail(f"{len(missing)} installed file(s) missing: {', '.join(missing[:5])}")
        if modified:
            r.warn(f"{len(modified)} installed file(s) edited locally (an upgrade will ask before replacing): "
                   f"{', '.join(modified[:5])}")
        if not missing and not modified:
            r.ok(f"{len(manifest.get('files') or {})} installed files intact")

        hosts = manifest.get("hosts") or []
        merges = manifest.get("merges") or {}
        kinds = {rel: (v.get("kind") if isinstance(v, dict) else ("hooks" if isinstance(v, list) else "block"))
                 for rel, v in merges.items()}
        mode = manifest.get("git_mode") or "commit"
        r.ok(f"git_mode: {mode} ({'only on this machine' if mode == 'local' else 'committed for the team'})")
        if "claude" in hosts:
            hook_files = [rel for rel, k in kinds.items() if k == "hooks"]
            for rel in hook_files:
                try:
                    settings = json.loads((root / rel).read_text(encoding="utf-8")) if (root / rel).is_file() else {}
                except Exception:
                    r.fail(f"{rel} is not valid JSON")
                    continue
                ours = {ev: any(".atw/core/atw.py" in json.dumps(e) for e in (settings.get("hooks") or {}).get(ev, []))
                        for ev in ("Stop", "PreToolUse", "PostToolUse")}
                if all(ours.values()):
                    r.ok(f"Claude hooks registered in {rel} (Stop, PreToolUse, PostToolUse)")
                else:
                    r.fail(f"Claude hooks missing in {rel} for: {', '.join(k for k, v in ours.items() if not v)}")
            if not hook_files:
                r.warn("Claude hooks were skipped at setup - the Stop gate is not enforced in Claude Code")
        blocks = [rel for rel, k in kinds.items() if k == "block"]
        for rel in blocks:
            _block_check(r, root, rel, merges)
        if not blocks:
            r.warn("no instructions block (skipped at setup) - agents learn the workflow only from the skills")
        targets = manifest.get("targets") or {}
        if "claude" in hosts and targets.get("instructions", "skip") != "skip" \
                and targets.get("claude_bridge", "skip") == "skip":
            if (root / "CLAUDE.md").is_file() or (root / "CLAUDE.local.md").is_file():
                r.warn(f"a CLAUDE.md exists but no bridge imports {targets['instructions']} - "
                       "Claude Code ignores AGENTS.md when a CLAUDE.md exists")
            elif targets["instructions"] == "AGENTS.md":
                r.ok("Claude Code reads AGENTS.md natively (needs Claude Code 2.1.277 or newer)")
        if mode == "local" and util.is_git_repo(root):
            visible = _visible_in_git(root, manifest)
            if visible:
                r.warn(f"git_mode is local, but git shows {len(visible)} of our file(s) as changes: "
                       f"{', '.join(visible[:5])} - exclude them, or re-run setup")
            else:
                r.ok("nothing installed shows up in git status")
        for rel, k in kinds.items():
            if k == "ignore" and Path(rel).is_absolute():
                r.warn(f"linked worktree: our ignore block is in {rel}, which is shared with the main checkout "
                       "and every other worktree - the same paths are hidden from git there too")
        for event in ("stop", "guard", "planmode"):
            res = subprocess.run([sys.executable, str(root / ".atw/core/atw.py"), "hook", event],
                                 input="{}", capture_output=True, text=True, cwd=root,
                                 env={**os.environ, "ATW_PROJECT_DIR": str(root)})
            if res.returncode != 0:
                r.fail(f"hook '{event}' exited {res.returncode}: {res.stderr.strip()[:200]}")
        skills = {k: v for k, v in (manifest.get("skills") or {}).items() if v}
        for name in skills.values():
            dirs = {rel.split(f"/{name}/")[0] for rel in manifest.get("files") or {} if f"/{name}/SKILL.md" in rel}
            if not dirs:
                r.fail(f"skill '{name}' is not installed anywhere")
        if skills:
            r.ok(f"skills: {', '.join(skills.values())}")

    # Run state must stay out of git (checked by git itself, so .gitignore,
    # .git/info/exclude and a global excludes file all count).
    if util.is_git_repo(root):
        if all(util.git(root, "check-ignore", "-q", "--no-index", p)[0] == 0 for p in (".atw/runs/x", ".atw/tmp/x")):
            r.ok(".atw/runs/ and .atw/tmp/ are ignored by git")
        else:
            r.warn(".atw/runs/ and .atw/tmp/ are not ignored by git - run state could be committed")

    # Tickets.
    globs = (cfg.get("tickets") or {}).get("globs") or []
    bases = {g.split("{id}")[0].split("*")[0].rstrip("/") for g in globs}
    if any((root / b).is_dir() for b in bases if b):
        r.ok(f"ticket folder exists ({', '.join(sorted(b for b in bases if (root / b).is_dir()))})")
    else:
        r.warn(f"no ticket folder yet ({', '.join(sorted(bases))}) - tickets are read from {globs}")

    # Commands.
    for name in ("proof", "tests", "lint"):
        spec = (cfg.get("commands") or {}).get(name)
        if not spec or not spec.get("run"):
            continue
        exe = _executable(cfg, spec["run"])
        if exe:
            r.ok(f"commands.{name}: `{_first_token(runner.render(spec['run'], python=cfg.get('python')))}` found")
        else:
            r.warn(f"commands.{name}: the program in `{spec['run']}` was not found on PATH")
    if run_commands:
        tests = (cfg.get("commands") or {}).get("tests") or {}
        if tests.get("run") and tests.get("scope", "all") == "all":
            res = runner.run(root, runner.render(tests["run"], python=cfg.get("python")),
                             (cfg.get("timeouts") or {}).get("command_seconds", 600))
            (r.ok if res["returncode"] == 0 else r.warn)(
                f"tests command exit {res['returncode']}: {res['error'] or runner.tail(res['output'])}")
        else:
            r.warn("--run-commands: the tests command is file-scoped; it runs per ticket, not here")

    # Open runs.
    runs = state.open_runs(root)
    if runs:
        r.warn(f"{len(runs)} open run(s): {', '.join(x['ticket'] + '/' + x['run_id'] for x in runs[:5])}")
    return r.print()


def _visible_in_git(root: Path, manifest: dict) -> list[str]:
    """Our files (owned or merged into) that git status lists as changes."""
    rc, out = util.git(root, "status", "--porcelain", "-uall")
    if rc != 0:
        return []
    ours = set(manifest.get("files") or {}) | set(manifest.get("merges") or {})
    changed = [line[3:].strip().strip('"') for line in out.splitlines()]
    return [c for c in changed if c in ours or c.startswith(".atw/")]


def _block_check(r: Report, root: Path, name: str, merges: dict) -> None:
    p = root / name
    has = p.is_file() and "<!-- atw:begin -->" in p.read_text(encoding="utf-8", errors="ignore")
    if has:
        r.ok(f"{name} has the workflow block")
    else:
        r.warn(f"{name} lost its workflow block (removed by hand?) - re-run setup to restore it, or leave it out")


def hygiene(root: Path, cfg: dict) -> int:
    """Report likely-misplaced agent output. Never moves or deletes anything."""
    findings = []
    placement = cfg.get("placement") or {}
    for kind in ("investigation", "comms"):
        folder = placement.get(kind)
        base = root / folder if folder else None
        if base and base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file() and not any(ch.isdigit() for ch in p.stem) and p.name != "README.md":
                    findings.append(f"{util.rel(root, p)}: no ticket id in the name ({kind} files need one)")
    for rel in util.untracked_files(root):
        if "/" not in rel and rel.lower().endswith((".md", ".txt", ".log", ".json", ".csv")) \
                and rel not in ("README.md", "CHANGELOG.md"):
            findings.append(f"{rel}: untracked file at the repository root - move it to its kind's folder")
    tmp = root / ".atw" / "tmp"
    if tmp.is_dir():
        old = [p for p in tmp.iterdir() if util.now_epoch() - p.stat().st_mtime > 86400]
        if old:
            findings.append(f".atw/tmp/: {len(old)} leftover item(s) older than a day (safe to delete)")
    for r in state.open_runs(root):
        age_days = (util.now_epoch() - r.get("started_at_epoch", util.now_epoch())) / 86400
        if age_days > 14:
            findings.append(f"run {r['ticket']}/{r['run_id']} open for {int(age_days)} days - close or abort it")
    for f in findings:
        print(f"- {f}")
    print(f"{len(findings)} finding(s)" if findings else "clean")
    return 0
