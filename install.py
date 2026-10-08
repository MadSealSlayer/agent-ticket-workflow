#!/usr/bin/env python3
"""Bootstrap agent-ticket-workflow into a project.

    python install.py <path-to-your-project> [--hosts claude,codex] [--setup-name NAME]

Works from any copy of this folder (git clone or unzipped archive), with no
network or git access needed. It changes very little on purpose:

  - stages this package in <project>/.atw/staging/ (self-gitignored), and
  - copies the setup skill into the skill folder of each chosen host.

Everything else (config, hooks, other skills, the AGENTS.md block) is decided
with you inside an agent session by the setup skill. It first asks whether the
install stays local only or is committed to git, detects what your project
already has, and never overwrites it without asking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGED = ("core", "skills", "adapters", "templates", "experimental", "VERSION")
HOST_SKILL_DIRS = {"claude": ".claude/skills", "codex": ".agents/skills", "other": ".agents/skills"}
POINTER_BEGIN, POINTER_END = "<!-- atw:begin -->", "<!-- atw:end -->"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def posix(p: Path) -> str:
    return str(p).replace("\\", "/")


def ignore(_dir, names):
    return [n for n in names if n == "__pycache__" or n.endswith(".pyc")]


def ask(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="the project to install into")
    ap.add_argument("--hosts", default="claude,codex",
                    help="comma-separated: claude, codex, other (default: claude,codex)")
    ap.add_argument("--setup-name", default="ticket-setup",
                    help="install the setup skill under this name (use it if 'ticket-setup' is taken)")
    ap.add_argument("--agents-md-pointer", action="store_true",
                    help="also add a short pointer block to AGENTS.md (asked interactively otherwise)")
    ap.add_argument("--yes", action="store_true", help="answer yes to questions")
    ap.add_argument("--dry-run", action="store_true", help="show what would be done")
    args = ap.parse_args(argv)

    version = (HERE / "VERSION").read_text(encoding="utf-8").strip()
    target = Path(args.target).expanduser().resolve()
    if not target.is_dir():
        print(f"error: {target} is not a folder")
        return 1
    if target == HERE or HERE in target.parents:
        print("error: install into your project, not into this package")
        return 1
    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    bad = [h for h in hosts if h not in HOST_SKILL_DIRS]
    if not hosts or bad:
        print(f"error: unknown host(s) {bad}; use claude, codex, other")
        return 1
    if not (target / ".git").exists():
        print(f"warning: {target} is not a git repository root. The workflow needs git; "
              "you can still stage now and init git before setup.")

    staging = target / ".atw" / "staging"
    if staging.exists() and not (staging / "PAYLOAD.json").is_file():
        print(f"error: {staging} exists and was not made by this installer - move it away first")
        return 1

    bootstrap_path = staging / "bootstrap.json"
    previous = {}
    if bootstrap_path.is_file():
        previous = json.loads(bootstrap_path.read_text(encoding="utf-8")).get("files") or {}
    manifest_path = target / ".atw" / "install-manifest.json"
    if manifest_path.is_file():
        previous.update(json.loads(manifest_path.read_text(encoding="utf-8")).get("files") or {})
        installed = json.loads(manifest_path.read_text(encoding="utf-8")).get("version")
        print(f"found an existing install ({installed}); staging {version} - the setup skill will run as "
              f"{'an upgrade' if installed != version else 'a reinstall'}")

    # Plan the setup-skill copies and check for collisions first.
    src = HERE / "skills" / "ticket-setup"
    dests = sorted({HOST_SKILL_DIRS[h] for h in hosts})
    copies, conflicts = [], []
    for d in dests:
        prefix = f"{d}/{args.setup_name}/"
        if (target / prefix).is_dir() and not any(r.startswith(prefix) for r in previous):
            conflicts.append(f"{prefix} (an existing skill or folder with this name)")
            continue
        for f in sorted(p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            rel = prefix + posix(f.relative_to(src))
            dest = target / rel
            # Ours from an earlier install, unedited, may be replaced; anything else is not ours.
            if dest.exists() and sha(dest) != sha(f) and previous.get(rel) != sha(dest):
                conflicts.append(f"{rel} (edited since it was installed)")
            copies.append((f, rel))
    if conflicts:
        print("error: nothing was changed. These files belong to something else:")
        for c in conflicts:
            print(f"  - {c}")
        print("Re-run with --setup-name <another-name> (for example atw-setup).")
        return 1

    pointer = False
    agents_md = target / "AGENTS.md"
    if any(h in hosts for h in ("codex", "other")):
        has_block = agents_md.is_file() and POINTER_BEGIN in agents_md.read_text(encoding="utf-8", errors="ignore")
        if not has_block:
            pointer = args.agents_md_pointer or ask(
                f"Add a 6-line pointer block to {'the existing ' if agents_md.is_file() else 'a new '}AGENTS.md "
                "so agents without skill support can find the setup? (git will show this change; "
                "skip it to keep the install local only)", args.yes)

    print(f"agent-ticket-workflow {version} -> {target}")
    print(f"  stage package     .atw/staging/ ({', '.join(STAGED)})")
    for d in dests:
        print(f"  setup skill       {d}/{args.setup_name}/")
    if pointer:
        print("  AGENTS.md         add a marked pointer block (replaced by the full block during setup)")
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for name in STAGED:
        s = HERE / name
        if s.is_dir():
            shutil.copytree(s, staging / name, ignore=ignore)
        elif s.is_file():
            shutil.copy2(s, staging / name)
    (staging / ".gitignore").write_text("*\n", encoding="utf-8")
    (staging / "PAYLOAD.json").write_text(json.dumps({
        "version": version, "staged_at": datetime.now().isoformat(timespec="seconds"),
        "hosts": hosts, "setup_name": args.setup_name}, indent=2) + "\n", encoding="utf-8")

    owned = {}
    for f, rel in copies:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        if f.name == "SKILL.md" and args.setup_name != "ticket-setup":
            text = dest.read_text(encoding="utf-8")
            dest.write_text(text.replace("name: ticket-setup", f"name: {args.setup_name}", 1)
                            .replace("/ticket-setup", f"/{args.setup_name}"), encoding="utf-8")
        owned[rel] = sha(dest)
    if pointer:
        block = (f"{POINTER_BEGIN}\n## Ticket workflow (setup pending)\n\n"
                 f"agent-ticket-workflow {version} is staged but not set up yet. To set it up, follow\n"
                 f"`{HOST_SKILL_DIRS['codex']}/{args.setup_name}/SKILL.md` (Codex: `${args.setup_name}`).\n"
                 f"{POINTER_END}\n")
        text = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else ""
        sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        agents_md.write_text(text + sep + block, encoding="utf-8")
    bootstrap_path.write_text(json.dumps({"version": version, "files": owned, "agents_md_pointer": pointer},
                                         indent=2) + "\n", encoding="utf-8")

    print("\nStaged. Next, inside your project:")
    if "claude" in hosts:
        print(f"  Claude Code:  open a session and run  /{args.setup_name}")
    if "codex" in hosts:
        print(f"  Codex:        open a session and run  ${args.setup_name}")
    if "other" in hosts:
        print(f"  Other agents: ask it to follow {HOST_SKILL_DIRS['other']}/{args.setup_name}/SKILL.md")
    if manifest_path.is_file():
        print("The setup reuses your earlier answers, asks only about what is new, and shows the changes "
              "before it writes anything.")
    else:
        print("The setup first asks whether to keep the install on this machine only or to commit it to git. "
              "Then it interviews you, shows what it found and what it wants to change, and asks before "
              "touching anything you already have.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
