"""Read-only brownfield discovery for /ticket-setup.

`detect(root)` looks at a project and reports what is already there: stack,
CI, agent harness files, hooks, skills, similar workflows, ticket folders.
It never writes. The setup skill turns this report into a collision list
and a question sheet; nothing here decides anything for the user.

Every collision carries the options the setup skill may offer:
    merge      add our part next to theirs (marked block, appended hook entry)
    namespace  install ours under another name
    skip       leave theirs, do not install ours
    abort      stop the setup
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config, util

OUR_SKILLS = ("ticket-setup", "ticket", "ticket-investigation", "ticket-audit",
              "project-context-loading", "project-context-updating", "ste-writing")
SKILL_DIRS = (".claude/skills", ".agents/skills", ".codex/skills", ".opencode/skills", ".cursor/skills")
COMMAND_DIRS = (".claude/commands", ".codex/prompts", ".opencode/command", ".cursor/commands")
INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", "AGENTS.md", "AGENTS.override.md",
                     "GEMINI.md", ".github/copilot-instructions.md", ".cursorrules", ".windsurfrules")
HARNESS_MARKERS = {
    "claude": [".claude", "CLAUDE.md", ".mcp.json"],
    "codex": [".codex", "AGENTS.md", ".agents"],
    "cursor": [".cursor", ".cursorrules"],
    "opencode": [".opencode", "opencode.json", "opencode.jsonc"],
    "gemini": [".gemini", "GEMINI.md"],
    "copilot": [".github/copilot-instructions.md"],
    "windsurf": [".windsurf", ".windsurfrules"],
}
SPEC_TOOLS = {
    "openspec": ["openspec"],
    "spec-kit": [".specify", "specs/.specify"],
    "superpowers-specs": ["docs/superpowers"],
    "kiro": [".kiro"],
    "adr": ["docs/adr", "docs/decisions", "adr"],
}
TICKET_DIR_CANDIDATES = ("tickets", "local_tickets", ".tickets", "issues", "docs/tickets", "work/tickets")
SOURCE_DIR_CANDIDATES = ("src", "app", "lib", "services", "packages", "apps", "server", "client", "api",
                         "internal", "cmd", "pkg", "components", "pages", "shared")
TEST_DIR_CANDIDATES = ("tests", "test", "__tests__", "spec", "e2e", "src/__tests__")
WORKFLOW_HINTS = {
    "plan-before-code": r"\b(EnterPlanMode|ExitPlanMode|plan mode|approved plan)\b",
    "red-first / TDD": r"\b(TDD|red[- ]green|failing test first|write the test first|proof test)\b",
    "independent review": r"\b(clean[- ]room|fresh (agent|reviewer|session)|code review agent|/audit|/review)\b",
    "ticket routing": r"\b(ticket kind|classify the ticket|investigation ticket|ticket workflow)\b",
    "stop/gate hooks": r"\b(Stop hook|ticket_gate|gate(s)? (must|before)|decision\"?: ?\"block)\b",
    "spec-driven": r"\b(SDD|spec[- ]driven|openspec|spec-kit|/specify)\b",
}
HOOK_EVENTS_WE_USE = ("Stop", "PreToolUse", "PostToolUse")
SCAN_LIMIT = 200_000


def _read(p: Path, limit: int = SCAN_LIMIT) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _file_contains(root: Path, spec: str) -> bool:
    """`file` or `file:needle`."""
    name, _, needle = spec.partition(":")
    p = root / name
    if not p.is_file():
        return False
    return not needle or needle in _read(p)


# --------------------------------------------------------------------------- sections

def _atw(root: Path, payload_version: str | None) -> dict:
    manifest = util.read_json(root / ".atw" / "install-manifest.json", default=None)
    installed = (manifest or {}).get("version")
    staged = (util.read_json(root / ".atw" / "staging" / "PAYLOAD.json", default={}) or {}).get("version")
    offered = payload_version or staged
    if not manifest:
        mode = "fresh"
    elif offered and installed and offered != installed:
        mode = "upgrade"
    else:
        mode = "reinstall"
    return {"installed_version": installed, "offered_version": offered, "mode": mode,
            "config_exists": config.exists(root), "manifest": manifest is not None}


def _package_json(root: Path) -> list[dict]:
    out = []
    for p in [root / "package.json", *sorted(root.glob("*/package.json")), *sorted(root.glob("*/*/package.json"))]:
        if "node_modules" in p.parts or not p.is_file():
            continue
        data = util.read_json(p, default={}) or {}
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            deps.update(data.get(key) or {})
        out.append({"path": util.rel(root, p), "name": data.get("name"), "scripts": data.get("scripts") or {},
                    "deps": sorted(deps), "workspaces": data.get("workspaces")})
    return out


def _stack(root: Path, presets: dict) -> dict:
    pkgs = _package_json(root)
    all_deps = {d for p in pkgs for d in p["deps"]}
    langs = []
    if any(_exists(root, f) for f in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile")) \
            or list(root.glob("requirements*.txt")) or list(root.glob("*/requirements*.txt")):
        langs.append("python")
    if pkgs:
        langs.append("node")
    for lang, files in {"go": ["go.mod"], "rust": ["Cargo.toml"], "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
                        "dotnet": list(map(str, root.glob("*.sln"))) or [], "ruby": ["Gemfile"], "php": ["composer.json"]}.items():
        if any(_exists(root, f) for f in files):
            langs.append(lang)
    lock = next((m for f, m in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"),
                                ("bun.lock", "bun"), ("package-lock.json", "npm")) if _exists(root, f)), None)
    matched = []
    for name, preset in presets.items():
        det = preset.get("detect") or {}
        hit_files = [f for f in det.get("files", []) if _file_contains(root, f)]
        hit_deps = [d for d in det.get("package_deps", []) if d in all_deps]
        if hit_files or hit_deps:
            matched.append({"preset": name, "area": preset.get("area"), "evidence": hit_files + hit_deps})
    venv = next((v for v in (".venv", "venv", "env") if (root / v / "pyvenv.cfg").is_file()), None)
    return {"languages": langs, "package_manager": lock, "packages": pkgs, "presets_matched": matched,
            "python_venv": venv, "unsupported": [l for l in langs if l not in ("python", "node", "go")]}


def _git(root: Path) -> dict:
    if not util.is_git_repo(root):
        return {"repo": False}
    rc, hooks_path = util.git(root, "config", "--get", "core.hooksPath")
    rc2, status = util.git(root, "status", "--porcelain")
    rc3, remotes = util.git(root, "remote")
    hook_tools = [n for n, f in (("husky", ".husky"), ("pre-commit", ".pre-commit-config.yaml"),
                                 ("lefthook", "lefthook.yml"), ("lefthook", ".lefthook.yml"),
                                 ("simple-git-hooks", ".simple-git-hooks.json")) if _exists(root, f)]
    active = []
    hooks_dir = root / ".git" / "hooks"
    if hooks_dir.is_dir():
        active = sorted(p.name for p in hooks_dir.iterdir() if p.is_file() and not p.name.endswith(".sample"))
    custom = root / hooks_path.strip() if rc == 0 and hooks_path.strip() else None
    if custom and custom.is_dir():
        active = sorted(p.name for p in custom.iterdir() if p.is_file() and not p.name.endswith(".sample"))
    return {"repo": True, "branch": util.current_branch(root), "dirty_files": len(status.splitlines()) if rc2 == 0 else None,
            "hooks_path": hooks_path.strip() if rc == 0 else None, "hook_tools": hook_tools,
            "active_git_hooks": active, "remotes": remotes.split() if rc3 == 0 else []}


def _ci(root: Path) -> list[str]:
    found = [util.rel(root, p) for p in sorted((root / ".github" / "workflows").glob("*.y*ml"))]
    found += [f for f in (".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml", "bitbucket-pipelines.yml",
                          ".circleci/config.yml", ".buildkite/pipeline.yml") if _exists(root, f)]
    return found


def _claude_settings(root: Path) -> dict:
    out = {}
    for name in (".claude/settings.json", ".claude/settings.local.json"):
        p = root / name
        if not p.is_file():
            continue
        try:
            data = json.loads(_read(p))
        except Exception as e:
            out[name] = {"invalid_json": str(e)}
            continue
        hooks = {}
        for event, entries in (data.get("hooks") or {}).items():
            cmds = []
            for entry in entries or []:
                for h in entry.get("hooks") or []:
                    cmds.append({"matcher": entry.get("matcher"), "command": hook_command_text(h)})
            hooks[event] = cmds
        out[name] = {"hooks": hooks, "enabled_plugins": sorted((data.get("enabledPlugins") or {}).keys()),
                     "permissions": bool(data.get("permissions"))}
    return out


def hook_command_text(h: dict) -> str:
    """`command` plus `args`, with an inline `-c <code>` launcher shortened."""
    args = [str(a) for a in h.get("args") or []]
    if len(args) >= 2 and args[0] == "-c":
        args = ["-c <launcher>", *args[2:]]
    return " ".join([str(h.get("command") or ""), *args]).strip()


def _skills(root: Path) -> dict:
    found = {}
    for d in SKILL_DIRS:
        base = root / d
        if base.is_dir():
            found[d] = sorted(p.parent.name for p in base.glob("*/SKILL.md"))
    commands = {}
    for d in COMMAND_DIRS:
        base = root / d
        if base.is_dir():
            commands[d] = sorted(util.posix(p.relative_to(base).with_suffix("")) for p in base.rglob("*.md"))
    agents = sorted(p.stem for p in (root / ".claude" / "agents").glob("*.md")) if (root / ".claude" / "agents").is_dir() else []
    return {"skills": found, "commands": commands, "claude_agents": agents}


def _instructions(root: Path) -> dict:
    out = {}
    for name in INSTRUCTION_FILES:
        p = root / name
        if p.is_file():
            text = _read(p)
            out[name] = {"lines": text.count("\n") + 1, "has_atw_block": "<!-- atw:begin -->" in text,
                         "imports": re.findall(r"^@(\S+)", text, re.MULTILINE)[:20]}
    return out


def _similar(root: Path, skills: dict, settings: dict) -> list[dict]:
    texts: list[tuple[str, str]] = []
    for name in INSTRUCTION_FILES:
        if (root / name).is_file():
            # Our own marked block is not someone else's practice.
            texts.append((name, re.sub(r"<!-- atw:begin -->.*?<!-- atw:end -->", "", _read(root / name), flags=re.S)))
    ours = _owned_files(root)
    for d, names in skills["skills"].items():
        for n in names:
            if f"{d}/{n}/SKILL.md" not in ours:
                texts.append((f"{d}/{n}/SKILL.md", _read(root / d / n / "SKILL.md")))
    for d, names in skills["commands"].items():
        for n in names:
            texts.append((f"{d}/{n}.md", _read(root / d / f"{n}.md")))
    for folder in (".claude/hooks",):
        base = root / folder
        if base.is_dir():
            for p in sorted(base.rglob("*"))[:200]:
                if p.is_file() and p.suffix in (".md", ".py", ".sh", ".js", ".ts"):
                    texts.append((util.rel(root, p), _read(p, 50_000)))
    for name, s in settings.items():
        for event, cmds in (s.get("hooks") or {}).items():
            for c in cmds:
                if ".atw/core/atw.py" not in (c.get("command") or ""):  # our own hooks are not a practice
                    texts.append((f"{name} hooks.{event}", f"{c.get('matcher')} {c.get('command')}"))
    hits = []
    for label, pattern in WORKFLOW_HINTS.items():
        rx = re.compile(pattern, re.IGNORECASE)
        where = [src for src, text in texts if rx.search(text)]
        if where:
            hits.append({"pattern": label, "found_in": where[:8], "count": len(where)})
    return hits


def _ticket_dirs(root: Path) -> list[dict]:
    out = []
    for d in TICKET_DIR_CANDIDATES:
        base = root / d
        if base.is_dir():
            mds = [p for p in base.rglob("*.md") if ".runs" not in p.parts]
            out.append({"dir": d, "markdown_files": len(mds),
                        "examples": [util.rel(root, p) for p in sorted(mds)[:5]]})
    return out


def _layout(root: Path) -> dict:
    src = [d for d in SOURCE_DIR_CANDIDATES if (root / d).is_dir()]
    tests = [d for d in TEST_DIR_CANDIDATES if (root / d).is_dir()]
    nested_tests = sorted({util.posix(p.relative_to(root).parent) for p in root.glob("*/*/tests") if p.is_dir()
                           and "node_modules" not in p.parts})[:20]
    docs = [d for d in ("docs", "doc", "documentation") if (root / d).is_dir()]
    scripts = [d for d in ("scripts", "tools", "bin") if (root / d).is_dir()]
    return {"source_dirs": src, "test_dirs": tests, "nested_test_dirs": nested_tests, "docs_dirs": docs,
            "script_dirs": scripts}


def _collisions(root: Path, report: dict, our_names) -> list[dict]:
    out = []
    names = list(our_names or OUR_SKILLS)
    for d, existing in report["harness"]["skills"]["skills"].items():
        for n in names:
            if n in existing:
                owned = _owned(root, f"{d}/{n}/SKILL.md")
                if not owned:
                    out.append({"id": f"skill:{d}/{n}", "path": f"{d}/{n}/", "what": f"a skill named '{n}' already exists",
                                "options": ["namespace", "skip", "abort"]})
    for d, existing in report["harness"]["skills"]["commands"].items():
        for n in names:
            if n in existing:
                out.append({"id": f"command:{d}/{n}", "path": f"{d}/{n}.md",
                            "what": f"a slash command '/{n}' exists and may shadow or be shadowed by the skill",
                            "options": ["namespace", "skip", "abort"]})
    for name, s in report["harness"]["claude_settings"].items():
        if s.get("invalid_json"):
            out.append({"id": f"settings:{name}", "path": name, "what": f"invalid JSON ({s['invalid_json']})",
                        "options": ["skip", "abort"]})
            continue
        for event in HOOK_EVENTS_WE_USE:
            theirs = [c for c in (s.get("hooks") or {}).get(event, []) if ".atw/core/atw.py" not in (c.get("command") or "")]
            if theirs:
                out.append({"id": f"hooks:{name}:{event}", "path": name,
                            "what": f"{len(theirs)} existing {event} hook(s): "
                                    + "; ".join(f"[{c.get('matcher') or '*'}] {c.get('command')}" for c in theirs[:3]),
                            "options": ["merge", "skip", "abort"]})
    for name, info in report["harness"]["instructions"].items():
        if name in ("CLAUDE.md", "AGENTS.md") and not info["has_atw_block"]:
            out.append({"id": f"instructions:{name}", "path": name,
                        "what": f"{name} exists ({info['lines']} lines); "
                                + ("ours would add only a one-line @AGENTS.md bridge block" if name == "CLAUDE.md"
                                   else "ours would add a marked block"),
                        "options": ["merge", "skip", "abort"]})
    for hit in report["similar_workflows"]:
        out.append({"id": f"workflow:{hit['pattern']}", "path": ", ".join(hit["found_in"][:3]),
                    "what": f"an existing '{hit['pattern']}' practice ({hit['count']} place(s)) may overlap",
                    "options": ["merge", "skip", "abort"]})
    if (root / ".atw").exists() and not report["atw"]["manifest"]:
        others = [p.name for p in (root / ".atw").iterdir() if p.name not in ("staging",)]
        if others:
            out.append({"id": "dir:.atw", "path": ".atw/", "what": f".atw/ exists without our manifest: {others[:5]}",
                        "options": ["abort"]})
    return out


def _owned_files(root: Path) -> dict:
    """Files we installed: the manifest, plus the setup skill install.py copied."""
    files = dict((util.read_json(root / ".atw" / "staging" / "bootstrap.json", default={}) or {}).get("files") or {})
    files.update((util.read_json(root / ".atw" / "install-manifest.json", default={}) or {}).get("files") or {})
    return files


def _owned(root: Path, rel_path: str) -> bool:
    return rel_path in _owned_files(root)


def load_presets(core_dir: Path) -> dict:
    out = {}
    for p in sorted((core_dir / "presets").glob("*.json")):
        data = util.read_json(p, default=None)
        if isinstance(data, dict):
            out[p.stem] = data
    return out


def detect(root: Path, our_names=None, payload_version: str | None = None) -> dict:
    core_dir = Path(__file__).resolve().parents[1]
    presets = load_presets(core_dir)
    skills = _skills(root)
    settings = _claude_settings(root)
    report = {
        "root": str(root),
        "atw": _atw(root, payload_version),
        "git": _git(root),
        "stack": _stack(root, presets),
        "layout": _layout(root),
        "ci": _ci(root),
        "harness": {
            "present": sorted(h for h, marks in HARNESS_MARKERS.items() if any(_exists(root, m) for m in marks)),
            "instructions": _instructions(root),
            "claude_settings": settings,
            "skills": skills,
        },
        "spec_tools": sorted(t for t, marks in SPEC_TOOLS.items() if any(_exists(root, m) for m in marks)),
        "ticket_dirs": _ticket_dirs(root),
        "similar_workflows": _similar(root, skills, settings),
    }
    report["collisions"] = _collisions(root, report, our_names)
    return report


def render(r: dict) -> str:
    L = []
    a = r["atw"]
    L.append(f"# Discovery report: {r['root']}")
    L.append(f"atw: mode={a['mode']} installed={a['installed_version']} offered={a['offered_version']} "
             f"config={'yes' if a['config_exists'] else 'no'}")
    g = r["git"]
    if g.get("repo"):
        L.append(f"git: branch={g['branch']} dirty={g['dirty_files']} remotes={g['remotes'] or 'none'} "
                 f"hooks_path={g['hooks_path']} hook_tools={g['hook_tools'] or 'none'} active={g['active_git_hooks'] or 'none'}")
    else:
        L.append("git: NOT a git repository (the workflow needs git for baselines and diffs)")
    s = r["stack"]
    L.append(f"stack: {', '.join(s['languages']) or 'unknown'} | package manager: {s['package_manager']} | venv: {s['python_venv']}")
    for m in s["presets_matched"]:
        L.append(f"  preset candidate: {m['preset']} ({m['area']}) <- {', '.join(m['evidence'])}")
    for p in s["packages"][:10]:
        scripts = ", ".join(f"{k}={v}" for k, v in list(p["scripts"].items())[:6])
        L.append(f"  package {p['path']}: scripts: {scripts or '-'}")
    if s["unsupported"]:
        L.append(f"  no preset for: {', '.join(s['unsupported'])} (configure commands by hand)")
    lay = r["layout"]
    L.append(f"layout: source={lay['source_dirs']} tests={lay['test_dirs']} nested tests={lay['nested_test_dirs'][:5]} "
             f"docs={lay['docs_dirs']} scripts={lay['script_dirs']}")
    L.append(f"ci: {', '.join(r['ci']) or 'none found'}")
    h = r["harness"]
    L.append(f"harnesses present: {', '.join(h['present']) or 'none'}")
    for name, info in h["instructions"].items():
        L.append(f"  {name}: {info['lines']} lines{' (has atw block)' if info['has_atw_block'] else ''}")
    for name, st in h["claude_settings"].items():
        if st.get("invalid_json"):
            L.append(f"  {name}: INVALID JSON")
            continue
        for event, cmds in st["hooks"].items():
            for c in cmds:
                L.append(f"  {name} hook {event} [{c['matcher'] or '*'}]: {c['command']}")
        if st["enabled_plugins"]:
            L.append(f"  {name} plugins: {', '.join(st['enabled_plugins'])}")
    for d, names in h["skills"]["skills"].items():
        L.append(f"  skills in {d}: {', '.join(names)}")
    for d, names in h["skills"]["commands"].items():
        L.append(f"  commands in {d}: {', '.join(names)}")
    if h["skills"]["claude_agents"]:
        L.append(f"  claude agents: {', '.join(h['skills']['claude_agents'])}")
    L.append(f"spec tools: {', '.join(r['spec_tools']) or 'none'}")
    for t in r["ticket_dirs"]:
        L.append(f"ticket dir candidate: {t['dir']} ({t['markdown_files']} .md) e.g. {', '.join(t['examples'][:3])}")
    for w in r["similar_workflows"]:
        L.append(f"similar practice: {w['pattern']} in {', '.join(w['found_in'][:4])}")
    L.append("")
    L.append(f"## Collisions ({len(r['collisions'])})")
    for c in r["collisions"]:
        L.append(f"- [{c['id']}] {c['what']}  (options: {'/'.join(c['options'])})")
    if not r["collisions"]:
        L.append("- none")
    return "\n".join(L)
