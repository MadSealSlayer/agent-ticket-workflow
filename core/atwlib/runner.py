"""Run a configured command with placeholders filled in.

Commands come from `.atw/atw.config.json` and run through the shell, so a
project can use whatever it already uses (`npx vitest run`, `.venv/bin/pytest`,
`go test`). Placeholders:
  {files}     changed files, each quoted
  {ids}       proof-set test ids, each quoted
  {id_files}  the distinct files named by the ids (the part before `::`), quoted
  {junit}     path of the JUnit XML file the command must write
  {python}    the configured Python command
A command may also set environment variables (`"env": {"NAME": "{junit}"}`),
which keeps reporters that read their output path from the environment
portable across shells.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def quote(arg: str) -> str:
    # Double quotes work in both POSIX shells and cmd.exe for paths and test
    # ids. Embedded double quotes are escaped for POSIX shells.
    return '"' + arg.replace('"', '\\"') + '"'


def render(template: str, *, files=None, ids=None, junit=None, python=None) -> str:
    out = template
    if "{files}" in out:
        out = out.replace("{files}", " ".join(quote(f) for f in files or []))
    if "{id_files}" in out:
        files_of_ids = dict.fromkeys(i.split("::", 1)[0] for i in ids or [] if "::" in i)
        out = out.replace("{id_files}", " ".join(quote(f) for f in files_of_ids))
    if "{ids}" in out:
        out = out.replace("{ids}", " ".join(quote(i) for i in ids or []))
    if "{junit}" in out:
        out = out.replace("{junit}", quote(str(junit)) if junit else "")
    if "{python}" in out:
        out = out.replace("{python}", python or "python")
    return out


def run(root: Path, command: str, timeout: int = 600, env: dict | None = None) -> dict:
    try:
        proc = subprocess.run(
            command, cwd=str(root), shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            env={**os.environ, **env} if env else None,
        )
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return {"returncode": proc.returncode, "output": output, "stdout": proc.stdout or "",
                "command": command, "error": None}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "output": "", "stdout": "", "command": command,
                "error": f"timed out after {timeout}s"}
    except Exception as e:
        return {"returncode": -1, "output": "", "stdout": "", "command": command, "error": str(e)}


def tail(text: str, lines: int = 1) -> str:
    parts = [l for l in (text or "").strip().splitlines() if l.strip()]
    return "\n".join(parts[-lines:])
