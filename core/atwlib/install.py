"""Apply an approved install plan to a project (`atw apply --plan <file>`).

The setup skill writes the plan only after the user has answered the
question sheet and approved the summary. This module then:

  1. Validates the plan and the config it carries.
  2. Computes every write, and refuses the whole apply (writing nothing) if
     any write would replace a file we do not own, or a file we own that
     was edited locally since the last install (unless the plan lists it in
     `overwrite_modified`).
  3. Backs up every existing file it changes to `.atw/backup/<stamp>/`.
  4. Writes, then records everything in `.atw/install-manifest.json`.

Ownership: a file is ours when the manifest lists it. Shared files are
never owned: the instructions file (AGENTS.md), the Claude bridge
(CLAUDE.md or CLAUDE.local.md), the ignore file (.gitignore or
.git/info/exclude) and the Claude settings file. In those we only add,
replace or remove our marked block or our own hook entries. A shared file
we used before but not now is cleaned up the same way, so every item can be
changed or switched off later.

Plan shape (JSON), see templates/install-plan.example.json:
  hosts            ["claude", "codex", "other"]
  launcher         python command for hooks and docs ("python", "python3", "py")
  git_mode         "commit" | "local". Required in a git repository; the user
                   answers it. It only sets the defaults of the four items below,
                   each of which the plan may override.
  instructions     file for our instructions block, or "skip" (default AGENTS.md;
                   in local mode "skip" when AGENTS.md is tracked by git)
  claude_bridge    "auto" | "skip" | a file. A one-line "@<instructions>" block so
                   Claude Code reads the instructions when a CLAUDE.md exists
                   (it ignores AGENTS.md then). auto: CLAUDE.md in commit mode,
                   CLAUDE.local.md in local mode, nothing when no CLAUDE file exists
  claude_settings  "merge" (.claude/settings.json) | "local" (.claude/settings.local.json)
                   | "skip"   (default: merge in commit mode, local in local mode)
  ignore           "gitignore" | "exclude" (.git/info/exclude) | "skip"
                   (default: gitignore in commit mode, exclude in local mode; in local
                   mode the exclude block also lists every file we install)
  ignore_extra     [folders to keep out of git, e.g. the investigation and comms folders]
  context_index    "create" | "skip"
  spike            installed name for the experimental spike skill, or null
  spike_dir        where spike workspaces live (default docs/spikes)
  overwrite_modified  [paths we own that the user agreed to overwrite]
  decisions        [{item, choice, by: "user"|"agent", why}]   (recorded as-is)
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from . import config, util

MANIFEST = ".atw/install-manifest.json"
BOOTSTRAP = ".atw/staging/bootstrap.json"
CORE_DEST = ".atw/core"
SKILL_NAMES = ("ticket-setup", "ticket", "ticket-investigation", "ticket-audit",
               "project-context-loading", "project-context-updating", "ste-writing")
TEXT_EXT = (".md", ".txt", ".json", ".py")
BEGIN, END = "<!-- atw:begin -->", "<!-- atw:end -->"
GI_BEGIN, GI_END = "# atw:begin", "# atw:end"
_TOKEN = re.compile(r"\{\{([a-z_]+(?:\.[a-z0-9_-]+)?)\}\}")


class ApplyError(Exception):
    pass


def default_payload() -> Path | None:
    """The package that the running atw.py belongs to, if it is a full one."""
    pkg = Path(__file__).resolve().parents[2]
    return pkg if (pkg / "VERSION").is_file() and (pkg / "skills").is_dir() else None


def payload_version(payload: Path) -> str:
    return (payload / "VERSION").read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------- helpers

def tokens(plan: dict, cfg: dict, version: str) -> dict:
    names = {k: v for k, v in (plan.get("skills") or {}).items() if v}
    launcher = plan.get("launcher") or "python"
    t = {
        "python": launcher,
        "atw": f"{launcher} .atw/core/atw.py",
        "version": version,
        "kinds": ", ".join(cfg["kinds"]["enabled"]),
        "plan_dir": cfg.get("plan_dir") or ".atw/plans",
        "skill_dir": (plan.get("skill_dirs") or [".agents/skills"])[0],
    }
    for k in SKILL_NAMES:
        t[f"skill.{k}"] = names.get(k, k)
    t["skill.spike"] = plan.get("spike") or "spike"
    t["spike_dir"] = (plan.get("spike_dir") or "docs/spikes").rstrip("/")
    return t


def render(text: str, toks: dict) -> str:
    return _TOKEN.sub(lambda m: toks.get(m.group(1), m.group(0)), text)


def split_launcher(launcher: str) -> list[str]:
    """'"C:\\Program Files\\Python\\python.exe"' or 'py -3' -> argv. Backslashes stay literal."""
    return [a if a is not None and a != "" else b
            for a, b in re.findall(r'"([^"]*)"|(\S+)', launcher)] or ["python"]


def hook_fragment(raw: str, launcher: str) -> dict:
    """The settings fragment with exec-form hooks: command is the bare executable,
    extra launcher words go before the fragment's args."""
    fragment = json.loads(raw)
    argv = split_launcher(launcher)
    for groups in fragment.get("hooks", {}).values():
        for group in groups:
            for h in group.get("hooks", []):
                if h.get("command") == "{{python}}":
                    h["command"] = argv[0]
                    h["args"] = argv[1:] + list(h.get("args") or [])
    return fragment


def upsert_block(text: str, block: str, begin: str, end: str) -> str:
    block = block.strip("\n")
    if begin in text and end in text:
        start = text.index(begin)
        stop = text.index(end, start) + len(end)
        return text[:start] + block + text[stop:]
    if not text:
        return block + "\n"
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + block + "\n"


def remove_block(text: str, begin: str, end: str) -> str:
    """Take our block out, with the blank line we put before it."""
    if begin not in text or end not in text:
        return text
    start = text.index(begin)
    stop = text.index(end, start) + len(end)
    if text[stop:stop + 1] == "\n":
        stop += 1
    head = text[:start]
    if head.endswith("\n\n"):
        head = head[:-1]
    return head + text[stop:]


def _is_ours(entry: dict) -> bool:
    return ".atw/core/atw.py" in json.dumps(entry)


def merge_settings(current: dict, fragment: dict) -> tuple[dict, list]:
    """Add our hook entries; replace older entries of ours. Theirs are kept as-is."""
    out = json.loads(json.dumps(current))
    hooks = out.setdefault("hooks", {})
    added = []
    for event, entries in fragment.get("hooks", {}).items():
        existing = [e for e in hooks.get(event, []) if not _is_ours(e)]
        hooks[event] = existing + entries
        added += [{"event": event, "entry": e} for e in entries]
    return out, added


def unmerge_settings(current: dict) -> dict:
    """Remove our hook entries; drop events and the hooks key that we leave empty."""
    out = json.loads(json.dumps(current))
    hooks = out.get("hooks") or {}
    for event in list(hooks):
        hooks[event] = [e for e in hooks[event] if not _is_ours(e)]
        if not hooks[event]:
            del hooks[event]
    if "hooks" in out and not hooks:
        del out["hooks"]
    return out


def is_tracked(root: Path, rel: str) -> bool:
    return util.git(root, "ls-files", "--error-unmatch", "--", rel)[0] == 0


def exclude_path(root: Path) -> str | None:
    """The repository's info/exclude file, relative to root when it is inside it."""
    rc, out = util.git(root, "rev-parse", "--git-path", "info/exclude")
    if rc != 0 or not out.strip():
        return None
    p = Path(out.strip())
    p = p if p.is_absolute() else (root / p)
    try:
        return util.posix(p.resolve().relative_to(root.resolve()))
    except ValueError:
        return util.posix(p.resolve())  # a linked worktree: the exclude file is in the main repository


def resolve_targets(root: Path, plan: dict) -> dict:
    """Turn git_mode and the per-item choices into concrete files. Explicit
    choices in the plan always win over the git_mode defaults."""
    mode = plan.get("git_mode") or "commit"
    local = mode == "local"
    instructions = plan.get("instructions")
    if instructions is None and "agents_md" in plan:          # older plans
        instructions = "AGENTS.md" if plan["agents_md"] == "block" else "skip"
    if instructions is None:
        instructions = "skip" if local and is_tracked(root, "AGENTS.md") else "AGENTS.md"
    bridge = plan.get("claude_bridge", "auto")
    if instructions == "skip" or "claude" not in (plan.get("hosts") or []):
        bridge = "skip"
    elif bridge == "auto":
        has_claude_md = (root / "CLAUDE.md").is_file() or (root / ".claude" / "CLAUDE.md").is_file()
        if local:
            bridge = "CLAUDE.local.md" if has_claude_md or (root / "CLAUDE.local.md").is_file() else "skip"
        else:
            bridge = "CLAUDE.md" if has_claude_md else "skip"
    if bridge == instructions:
        bridge = "skip"
    settings = plan.get("claude_settings") or ("local" if local else "merge")
    if "claude" not in (plan.get("hosts") or []):
        settings = "skip"
    ignore = plan.get("ignore")
    if ignore is None and "gitignore" in plan:                 # older plans
        ignore = "gitignore" if plan["gitignore"] == "block" else "skip"
    ignore = ignore or ("exclude" if local else "gitignore")
    return {"git_mode": mode, "instructions": instructions, "claude_bridge": bridge,
            "claude_settings": settings, "ignore": ignore}


def _block_files(merges: dict) -> dict[str, str]:
    """{file: kind} for every shared file of a manifest's merges, old formats included."""
    out = {}
    for rel, val in (merges or {}).items():
        if isinstance(val, dict):
            out[rel] = val.get("kind", "block")
        elif isinstance(val, list):
            out[rel] = "hooks"
        else:
            out[rel] = "ignore" if rel.endswith((".gitignore", "info/exclude")) else "block"
    return out


def _walk(src: Path):
    for p in sorted(src.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(".pyc"):
            yield p


# --------------------------------------------------------------------------- planning

class Writer:
    """Collects writes, checks ownership, then performs them."""

    def __init__(self, root: Path, manifest: dict, overwrite_modified):
        self.root = root
        # install.py records the setup skill it bootstrapped; those copies are ours too.
        bootstrap = util.read_json(root / BOOTSTRAP, default={}) or {}
        self.owned = {**(bootstrap.get("files") or {}), **((manifest or {}).get("files") or {})}
        self.overwrite_modified = set(overwrite_modified or [])
        self.writes: list[tuple[str, bytes, str]] = []   # (rel, data, why)
        self.conflicts: list[str] = []
        self.new_owned: dict[str, str] = {}

    def owned_file(self, rel: str, data: bytes, why: str) -> None:
        p = self.root / rel
        if p.exists():
            cur = util.sha256_file(p)
            if rel in self.owned:
                if cur != self.owned[rel] and cur != util.sha256_bytes(data) and rel not in self.overwrite_modified:
                    self.conflicts.append(f"{rel}: ours, but edited locally since the last install "
                                          "(keep the edit by skipping, or list it in overwrite_modified)")
            elif cur != util.sha256_bytes(data):
                self.conflicts.append(f"{rel}: exists and is not ours")
        self.writes.append((rel, data, why))
        self.new_owned[rel] = util.sha256_bytes(data)

    def shared_file(self, rel: str, data: bytes, why: str) -> None:
        p = self.root / rel
        if p.exists() and p.read_bytes() == data:
            return
        self.writes.append((rel, data, why))


def build(root: Path, plan: dict, payload: Path) -> tuple[Writer, dict, list[str]]:
    version = payload_version(payload)
    manifest = util.read_json(root / MANIFEST, default=None) or {}
    cfg = config._merge(config.DEFAULTS, plan.get("config") or {})
    cfg["names"] = {k: v for k, v in (plan.get("skills") or {}).items() if v and v != k}
    problems = config.validate(cfg)
    hosts = plan.get("hosts") or []
    if not hosts or any(h not in config.HOSTS for h in hosts):
        problems.append(f"hosts must be a non-empty subset of {config.HOSTS}")
    for key, allowed in (("git_mode", ("commit", "local")), ("claude_settings", ("merge", "local", "skip")),
                         ("ignore", ("gitignore", "exclude", "skip")), ("agents_md", ("block", "skip")),
                         ("gitignore", ("block", "skip")), ("context_index", ("create", "skip"))):
        if plan.get(key) is not None and plan[key] not in allowed:
            problems.append(f"{key} must be one of {allowed}")
    if util.is_git_repo(root) and plan.get("git_mode") not in ("commit", "local"):
        problems.append('git_mode is required in a git repository: ask the user whether to install '
                        'locally only ("local") or to commit it for the team ("commit")')
    for key in ("instructions", "claude_bridge"):
        val = plan.get(key)
        if val is not None and (not isinstance(val, str) or not val or val.startswith(("/", "..")) or "\\" in val):
            problems.append(f"{key} must be \"skip\", \"auto\" (bridge only) or a relative path inside the project")
    if plan.get("ignore") == "exclude" and not util.is_git_repo(root):
        problems.append('ignore "exclude" needs a git repository; use "gitignore" or "skip"')
    names = [v for v in (plan.get("skills") or {}).values() if v]
    if len(names) != len(set(names)):
        problems.append("two skills cannot share an installed name")
    for k in plan.get("skills") or {}:
        if k not in SKILL_NAMES:
            problems.append(f"unknown skill '{k}'")
    if problems:
        raise ApplyError("the plan is not valid:\n  - " + "\n  - ".join(problems))

    toks = tokens(plan, cfg, version)
    w = Writer(root, manifest, plan.get("overwrite_modified"))

    # Core engine.
    for p in _walk(payload / "core"):
        w.owned_file(f"{CORE_DEST}/{util.posix(p.relative_to(payload / 'core'))}", p.read_bytes(), "core")
    w.owned_file(f"{CORE_DEST}/VERSION", (version + "\n").encode(), "core")

    # Config: the plan carries the full content; local edits are expected, so
    # it is always replaced (after a backup) rather than treated as a conflict.
    cfg_out = dict(plan.get("config") or {})
    if cfg["names"]:
        cfg_out["names"] = cfg["names"]
    w.writes.append((config.CONFIG_PATH, (json.dumps(cfg_out, indent=2) + "\n").encode(), "config"))
    w.new_owned[config.CONFIG_PATH] = util.sha256_bytes(w.writes[-1][1])

    # Skills.
    installed_dirs: set[str] = set()
    for skill, name in (plan.get("skills") or {}).items():
        if not name:
            continue
        src = payload / "skills" / skill
        if not src.is_dir():
            raise ApplyError(f"payload has no skill '{skill}'")
        for d in plan.get("skill_dirs") or []:
            installed_dirs.add(f"{d}/{name}/")
            dir_toks = {**toks, "skill_dir": d}
            for p in _walk(src):
                rel = f"{d}/{name}/{util.posix(p.relative_to(src))}"
                data = p.read_bytes()
                if p.suffix in TEXT_EXT:
                    text = render(data.decode("utf-8"), dir_toks)
                    if skill == "ticket-setup" and name != skill and p.name == "SKILL.md":
                        # The setup skill has no tokens (install.py copies it raw).
                        text = text.replace("name: ticket-setup", f"name: {name}", 1) \
                                   .replace("/ticket-setup", f"/{name}")
                    data = text.encode("utf-8")
                w.owned_file(rel, data, f"skill {skill} as {name}")
    if plan.get("spike"):
        src = payload / "experimental" / "spike" / "skill"
        for d in plan.get("skill_dirs") or []:
            installed_dirs.add(f"{d}/{plan['spike']}/")
            for p in _walk(src):
                data = render(p.read_text(encoding="utf-8"), {**toks, "skill_dir": d}).encode("utf-8")
                w.owned_file(f"{d}/{plan['spike']}/{util.posix(p.relative_to(src))}", data, "experimental spike")

    # Project-context index (created once; the project owns it afterwards).
    ctx = cfg.get("context") or {}
    created: list[str] = []      # files that did not exist before; local mode keeps them out of git
    if plan.get("context_index") == "create" and ctx.get("enabled"):
        idx = root / ctx["index"]
        if not idx.exists():
            text = render((payload / "templates/context/INDEX.md").read_text(encoding="utf-8"), toks)
            w.writes.append((ctx["index"], text.encode(), "context index"))
            created.append(ctx["index"])

    # Shared files. Every item is optional and can point somewhere else; a
    # shared file we used before but not now gets our part removed again.
    t = resolve_targets(root, plan)
    local = t["git_mode"] == "local"
    old_merges = manifest.get("merges") or {}
    previous = _block_files(old_merges)
    bootstrap = util.read_json(root / BOOTSTRAP, default={}) or {}
    if bootstrap.get("agents_md_pointer") and not manifest:
        previous.setdefault("AGENTS.md", "block")
    was_created = {rel: bool(v.get("created")) for rel, v in old_merges.items() if isinstance(v, dict)}
    merges: dict = {}

    def text_of(rel: str) -> str:
        p = root / rel
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def record(rel: str, kind: str, **more) -> None:
        new = was_created.get(rel, not (root / rel).exists())
        if new:
            created.append(rel)
        merges[rel] = {"kind": kind, "created": new, **more}

    if t["instructions"] != "skip":
        rel = t["instructions"]
        block = render((payload / "adapters/agents-md/agents-md-block.md").read_text(encoding="utf-8"), toks)
        w.shared_file(rel, upsert_block(text_of(rel), block, BEGIN, END).encode(), "instructions block")
        record(rel, "block")
    if t["claude_bridge"] != "skip":
        rel = t["claude_bridge"]
        target = os.path.relpath(t["instructions"], os.path.dirname(rel) or ".").replace(os.sep, "/")
        block = f"{BEGIN}\n@{target}\n{END}"
        w.shared_file(rel, upsert_block(text_of(rel), block, BEGIN, END).encode(), "Claude bridge (@import)")
        record(rel, "block")
    if t["claude_settings"] != "skip":
        rel = ".claude/settings.json" if t["claude_settings"] == "merge" else ".claude/settings.local.json"
        try:
            current = json.loads(text_of(rel) or "{}")
        except Exception as e:
            raise ApplyError(f"{rel} is not valid JSON ({e}); fix it or choose another claude_settings")
        fragment = hook_fragment((payload / "adapters/claude-code/settings.fragment.json")
                                 .read_text(encoding="utf-8"), toks["python"])
        merged, added = merge_settings(current, fragment)
        w.shared_file(rel, (json.dumps(merged, indent=2) + "\n").encode(), "hook entries")
        record(rel, "hooks", entries=added)
    ignore_rel = {"gitignore": ".gitignore", "exclude": exclude_path(root)}.get(t["ignore"])
    if ignore_rel:
        lines = (payload / "adapters/gitignore-block.txt").read_text(encoding="utf-8").strip("\n").splitlines()[:-1]
        extra = plan.get("ignore_extra") or plan.get("gitignore_extra") or []
        if extra:
            lines += ["# local-only ticket notes", *(x.rstrip("/") + "/" for x in extra)]
        if local:
            # Ours, plus the two files Claude Code itself treats as personal. A file
            # the user already had is not hidden from git on their behalf.
            personal = [r for r in merges if r in (".claude/settings.local.json", "CLAUDE.local.md")]
            ours = {".atw/", *installed_dirs, *created, *personal}
            ours |= {util.posix(Path(r).parent) + "/" for r in (bootstrap.get("files") or {}) if r.endswith("/SKILL.md")}
            lines += ["# installed locally only (git_mode: local)", *sorted("/" + x.lstrip("/") for x in ours)]
        lines.append(GI_END)
        w.shared_file(ignore_rel, upsert_block(text_of(ignore_rel), "\n".join(lines), GI_BEGIN, GI_END).encode(),
                      f"ignore block ({t['ignore']})")
        merges[ignore_rel] = {"kind": "ignore", "created": was_created.get(ignore_rel, not (root / ignore_rel).exists())}

    shared_removals = []
    for rel, kind in previous.items():
        if rel in merges or not (root / rel).is_file():
            continue
        if kind == "hooks":
            try:
                left = unmerge_settings(json.loads(text_of(rel)))
            except Exception:
                continue  # not JSON any more: leave it to the user
            data = (json.dumps(left, indent=2) + "\n") if left else ""
        else:
            begin, end = (GI_BEGIN, GI_END) if kind == "ignore" else (BEGIN, END)
            data = remove_block(text_of(rel), begin, end)
        if not data.strip() and was_created.get(rel):
            shared_removals.append(rel)
        elif data != text_of(rel):
            w.shared_file(rel, data.encode(), f"remove our {kind} (no longer used)")

    # Files we owned before but no longer install (renamed or dropped skills,
    # removed core modules): removed when unmodified, otherwise kept and reported.
    removals, kept = [], []
    for rel, sha in (manifest.get("files") or {}).items():
        if rel in w.new_owned or rel == config.CONFIG_PATH:
            continue
        p = root / rel
        if not p.exists():
            continue
        (removals if util.sha256_file(p) == sha else kept).append(rel)
    removals += shared_removals

    new_manifest = {
        "schema_version": 1,
        "version": version,
        "installed_at": util.now_iso(),
        "hosts": hosts,
        "launcher": plan.get("launcher") or "python",
        "git_mode": t["git_mode"],
        "targets": t,
        "files": w.new_owned,
        "merges": merges,
        "skills": plan.get("skills") or {},
        "spike": plan.get("spike"),
        "spike_dir": plan.get("spike_dir") if plan.get("spike") else None,
        "decisions": plan.get("decisions") or [],
        "history": [*(manifest.get("history") or []),
                    {"version": version, "at": util.now_iso(),
                     "mode": "fresh" if not manifest else ("upgrade" if manifest.get("version") != version else "reinstall")}],
    }
    notes = [f"kept (edited locally, no longer installed): {r}" for r in kept]
    return w, {"manifest": new_manifest, "removals": removals}, notes


def apply(root: Path, plan_path: Path, dry_run: bool = False, payload: Path | None = None) -> int:
    payload = payload or default_payload() or (root / ".atw" / "staging")
    if not (payload / "VERSION").is_file():
        print(f"refused: no package payload at {payload} - run install.py first, or pass --payload")
        return 1
    plan_file = plan_path if plan_path.is_absolute() else root / plan_path
    plan = util.read_json(plan_file, default=None)
    if not isinstance(plan, dict):
        print(f"refused: cannot read the install plan {plan_path}")
        return 1
    try:
        w, extra, notes = build(root, plan, payload)
    except ApplyError as e:
        print(f"refused: {e}")
        return 1
    if w.conflicts:
        print("refused: nothing was written. These files would be overwritten:")
        for c in w.conflicts:
            print(f"  - {c}")
        print("Resolve each in the plan (rename the skill, skip it, or list the path in overwrite_modified).")
        return 1

    by_why: dict[str, list[str]] = {}
    for rel, _, why in w.writes:
        by_why.setdefault(why, []).append(rel)
    print(f"{'DRY RUN - ' if dry_run else ''}install agent-ticket-workflow {extra['manifest']['version']} "
          f"({extra['manifest']['history'][-1]['mode']}) into {root}")
    t = extra["manifest"]["targets"]
    print(f"  git_mode {t['git_mode']}: instructions -> {t['instructions']}, Claude bridge -> {t['claude_bridge']}, "
          f"Claude hooks -> {t['claude_settings']}, ignore -> {t['ignore']}")
    shared = [rel for rel in extra["manifest"]["merges"] if Path(rel).is_absolute()]
    for rel in shared:
        print(f"  note: this is a linked worktree. {rel} is shared with the main checkout and every other "
              "worktree, so the paths in our block are hidden from git there too")
    for why, rels in by_why.items():
        shown = rels if len(rels) <= 4 else rels[:3] + [f"... {len(rels) - 3} more"]
        print(f"  write  [{why}] {', '.join(shown)}")
    for rel in extra["removals"]:
        print(f"  remove [no longer installed] {rel}")
    for n in notes:
        print(f"  note   {n}")
    if dry_run:
        return 0

    stamp = util.now_iso().replace(":", "").replace("-", "")[:15]
    backup = root / ".atw" / "backup" / stamp
    for rel, data, _ in w.writes:
        p = root / rel
        if p.exists() and p.read_bytes() != data:
            dest = backup.joinpath(*[x for x in Path(rel).parts if x not in ("..", Path(rel).anchor)])
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    for rel, data, _ in w.writes:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".atw-tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    for rel in extra["removals"]:
        try:
            (root / rel).unlink()
        except FileNotFoundError:
            pass
    util.write_json(root / MANIFEST, extra["manifest"])
    if backup.exists():
        print(f"  backups of changed files: {util.rel(root, backup)}/")
    print(f"done. Next: {tokens(plan, config._merge(config.DEFAULTS, plan.get('config') or {}), '')['atw']} doctor")
    return 0
