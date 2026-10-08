"""Shared test helpers: a throwaway git project and a CLI runner."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core"
ATW = CORE / "atw.py"
MINITEST = REPO / "tests" / "fixtures" / "minitest.py"

if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

PY = sys.executable.replace("\\", "/")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def python_config(**overrides) -> dict:
    """A config for a plain-Python project tested with the bundled minitest."""
    mt = str(MINITEST).replace("\\", "/")
    cfg = {
        "schema_version": 1,
        "python": f'"{PY}"',
        "protected_paths": ["src/"],
        "test_paths": ["tests/"],
        "commands": {
            "proof": {"run": f'"{PY}" "{mt}" --junit {{junit}} {{ids}}', "id_style": "pytest"},
            "tests": {"run": f'"{PY}" "{mt}" {{files}}', "scope": "changed-tests"},
        },
    }
    for k, v in overrides.items():
        cfg[k] = v
    return cfg


class Project(unittest.TestCase):
    """A fresh git repo per test with one commit, a config and a ticket."""

    config: dict | None = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="atw-test-"))
        self.root = self.tmp / "proj"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "atw test")
        git(self.root, "config", "core.autocrlf", "false")
        self.write(".gitignore", ".atw/runs/\n.atw/tmp/\n__pycache__/\n")
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n")
        self.write("tests/test_calc.py",
                   "import sys, pathlib\n"
                   "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))\n"
                   "from calc import add\n\n"
                   "def test_add():\n    assert add(1, 2) == 3\n")
        self.write("tickets/T-1.md", "# T-1\n\nAdd `sub(a, b)` to calc.\n\n## Acceptance\n- sub(5, 3) == 2\n")
        self.write_config(self.config if self.config is not None else python_config())
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        return p

    def write_config(self, cfg: dict) -> None:
        self.write(".atw/atw.config.json", json.dumps(cfg, indent=2))

    def atw(self, *args: str, stdin: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
        e = {k: v for k, v in os.environ.items() if k not in ("ATW_RUN", "CLAUDE_PROJECT_DIR", "CLAUDECODE")}
        e.update({"ATW_PROJECT_DIR": str(self.root), "ATW_HOST": "other", "PYTHONIOENCODING": "utf-8"})
        e.update(env or {})
        return subprocess.run([sys.executable, str(ATW), *args], cwd=self.root, env=e, input=stdin,
                              capture_output=True, text=True, encoding="utf-8")

    def ok(self, *args: str, **kw) -> str:
        r = self.atw(*args, **kw)
        self.assertEqual(r.returncode, 0, f"atw {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}")
        return r.stdout

    def refused(self, *args: str, contains: str = "", **kw) -> str:
        r = self.atw(*args, **kw)
        self.assertNotEqual(r.returncode, 0, f"atw {' '.join(args)} should have been refused:\n{r.stdout}")
        text = r.stdout + r.stderr
        if contains:
            self.assertIn(contains, text)
        return text

    def run_ref(self, start_output: str) -> str:
        for line in start_output.splitlines():
            if line.startswith("run: "):
                return line.split()[1]
        raise AssertionError(f"no run ref in: {start_output}")
