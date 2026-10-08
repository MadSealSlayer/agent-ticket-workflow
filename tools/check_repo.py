#!/usr/bin/env python3
"""Static checks for this repository (run in CI and before a pull request).

    python tools/check_repo.py

- every skill has frontmatter with name and description
- rendered skills and adapters use only known tokens; the setup skill uses none
- every JSON file parses; presets have the required keys
- the example config validates
- no hardcoded remote URLs (use <ORG>/<REPO> placeholders)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from atwlib import config, install  # noqa: E402

SKIP = {".git", "dist", "__pycache__", ".venv", "venv", ".idea", ".vscode", "node_modules"}
REMOTE = re.compile(r"(https?://(www\.)?(github|gitlab|bitbucket)\.(com|org)/(?!<ORG>)[\w.-]+"
                    r"|git@(github|gitlab|bitbucket)\.(com|org):(?!<ORG>))", re.I)
PRESET_KEYS = {"name", "area", "detect", "commands"}


def files(pattern: str):
    for p in sorted(ROOT.rglob(pattern)):
        if not any(part in SKIP for part in p.relative_to(ROOT).parts):
            yield p


def known_tokens() -> set[str]:
    plan = json.loads((ROOT / "templates/install-plan.example.json").read_text(encoding="utf-8"))
    toks = set(install.tokens(plan, config.DEFAULTS, "0").keys())
    return toks | {"skill_dir"}


def main() -> int:
    errors: list[str] = []
    rel = lambda p: p.relative_to(ROOT).as_posix()  # noqa: E731
    toks = known_tokens()

    for p in files("SKILL.md"):
        text = p.read_text(encoding="utf-8")
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if not m:
            errors.append(f"{rel(p)}: no frontmatter")
            continue
        head = m.group(1)
        for key in ("name", "description"):
            if not re.search(rf"^{key}:\s*\S", head, re.M):
                errors.append(f"{rel(p)}: frontmatter has no {key}")

    for p in [*files("skills/**/*.md"), *files("adapters/**/*"), *files("experimental/**/*.md")]:
        if not p.is_file():
            continue
        found = set(install._TOKEN.findall(p.read_text(encoding="utf-8")))
        if "skills/ticket-setup/" in rel(p):
            if found:
                errors.append(f"{rel(p)}: the setup skill is copied raw and must have no tokens: {sorted(found)}")
        elif found - toks:
            errors.append(f"{rel(p)}: unknown tokens {sorted(found - toks)}")

    for p in files("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{rel(p)}: invalid JSON ({e})")
            continue
        if p.parent.name == "presets" and PRESET_KEYS - set(data):
            errors.append(f"{rel(p)}: preset is missing {sorted(PRESET_KEYS - set(data))}")

    example = json.loads((ROOT / "templates/atw.config.example.json").read_text(encoding="utf-8"))
    errors += [f"templates/atw.config.example.json: {e}" for e in config.validate(example)]

    for p in files("*"):
        if p.is_file() and p.suffix in {".py", ".md", ".json", ".txt", ".yml", ".yaml", ""}:
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if REMOTE.search(line):
                    errors.append(f"{rel(p)}:{n}: hardcoded remote URL - use <ORG>/<REPO>")

    for e in errors:
        print(f"FAIL {e}")
    print(f"{'FAILED' if errors else 'OK'}: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
