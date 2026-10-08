#!/usr/bin/env python3
"""Build a shareable zip of this package (for Slack, a shared drive, email).

    python tools/make_dist.py [--out dist]

Writes dist/agent-ticket-workflow-<VERSION>.zip and dist/SHA256SUMS. The zip
has one top-level folder with an INSTALL.txt, and leaves out .git/, caches,
local tooling folders and dist/ itself. File order and timestamps are fixed,
so the same tree gives the same zip bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {".git", "dist", "__pycache__", ".tmp", ".venv", "venv", ".idea", ".vscode", ".pytest_cache",
                ".ruff_cache", ".mypy_cache", "node_modules"}
EXCLUDE_SUFFIX = (".pyc", ".pyo")
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

INSTALL_TXT = """agent-ticket-workflow {version}
==============================

1. Unzip this anywhere (it does not need to live inside your project).
2. From a terminal:

       python agent-ticket-workflow-{version}/install.py <path-to-your-project>

   Use python3 or py if that is your Python 3.10+ command.
3. Open your agent in the project and run the setup:

       Claude Code:  /ticket-setup
       Codex:        $ticket-setup

The setup looks at what your project already has, asks you about everything
that matters, shows the exact changes, and writes nothing before you approve.
Read README.md for the full picture.
"""


def files(root: Path):
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix()):
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts) or not p.is_file():
            continue
        if p.name.endswith(EXCLUDE_SUFFIX):
            continue
        yield p, rel


def build(out_dir: Path) -> Path:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    top = f"agent-ticket-workflow-{version}"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{top}.zip"

    def add(zf: zipfile.ZipFile, arcname: str, data: bytes, mode: int = 0o644):
        info = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (mode & 0xFFFF) << 16
        zf.writestr(info, data)

    with zipfile.ZipFile(zip_path, "w") as zf:
        add(zf, f"{top}/INSTALL.txt", INSTALL_TXT.format(version=version).encode("utf-8"))
        for p, rel in files(ROOT):
            mode = 0o755 if p.suffix == ".py" and p.read_bytes().startswith(b"#!") else 0o644
            add(zf, f"{top}/{rel.as_posix()}", p.read_bytes(), mode)

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (out_dir / "SHA256SUMS").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()
    path = build(Path(args.out))
    print(f"wrote {path}")
    print(f"wrote {path.parent / 'SHA256SUMS'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
