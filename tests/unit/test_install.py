"""install.py -> apply -> doctor, on a fresh and on a brownfield project,
plus the zip distribution path."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from _helpers import MINITEST, PY, REPO, git

TEMPLATE_PLAN = json.loads((REPO / "templates" / "install-plan.example.json").read_text(encoding="utf-8"))


def sha_tree(root: Path, rels) -> dict:
    return {r: hashlib.sha256((root / r).read_bytes()).hexdigest() for r in rels}


class InstallBase(unittest.TestCase):
    package = REPO

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="atw-install-"))
        self.root = self.tmp / "proj"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "atw test")
        git(self.root, "config", "core.autocrlf", "false")
        self.write("src/calc.py", "def add(a, b):\n    return a + b\n")
        self.write("tests/test_calc.py", "def test_ok():\n    assert True\n")
        self.write("tickets/T-1.md", "# T-1\nWrite a reply.\n")
        self.brownfield()
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")

    def brownfield(self):
        pass

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")

    def env(self):
        e = {k: v for k, v in os.environ.items() if k not in ("ATW_RUN", "CLAUDE_PROJECT_DIR", "CLAUDECODE")}
        e.update({"ATW_PROJECT_DIR": str(self.root), "ATW_HOST": "other", "PYTHONIOENCODING": "utf-8"})
        return e

    def run_py(self, *args, cwd=None):
        return subprocess.run([sys.executable, *map(str, args)], cwd=cwd or self.root, env=self.env(),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8")

    def install(self, *extra, package=None):
        return self.run_py((package or self.package) / "install.py", self.root, *extra)

    def plan(self, **overrides) -> Path:
        plan = copy.deepcopy(TEMPLATE_PLAN)
        mt = str(MINITEST).replace("\\", "/")
        plan["config"]["python"] = f'"{PY}"'
        plan["config"]["commands"] = {
            "proof": {"run": f'"{PY}" "{mt}" --junit {{junit}} {{ids}}', "id_style": "pytest"},
            "tests": {"run": f'"{PY}" "{mt}" {{files}}', "scope": "changed-tests"},
        }
        plan["launcher"] = f'"{PY}"'
        plan["git_mode"] = "commit"
        plan.update(overrides)
        p = self.root / ".atw" / "staging" / "install-plan.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return p

    def apply(self, plan_path, *extra):
        return self.run_py(self.root / ".atw/staging/core/atw.py", "apply", "--plan", plan_path, *extra)

    def atw(self, *args):
        return self.run_py(self.root / ".atw/core/atw.py", *args)

    def status_files(self) -> set[str]:
        out = git(self.root, "status", "--porcelain", "-uall")
        return {line[3:] for line in out.splitlines()}


class FreshInstall(InstallBase):

    def test_install_touches_only_setup_skill(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.root / ".atw/staging/PAYLOAD.json").is_file())
        changed = self.status_files()
        self.assertTrue(changed)
        self.assertTrue(all(f.startswith((".claude/skills/ticket-setup/", ".agents/skills/ticket-setup/"))
                            for f in changed), changed)  # staging is self-gitignored

    def test_full_setup_then_ticket(self):
        self.assertEqual(self.install().returncode, 0)
        plan = self.plan()
        dry = self.apply(plan, "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stdout)
        self.assertFalse((self.root / ".atw/install-manifest.json").exists())
        r = self.apply(plan)
        self.assertEqual(r.returncode, 0, r.stdout)

        settings = json.loads((self.root / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(set(settings["hooks"]), {"Stop", "PreToolUse", "PostToolUse"})
        stop = settings["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(stop["command"], PY)  # exec form: bare executable, unquoted
        self.assertEqual(stop["args"][0], "-c")
        self.assertIn("<!-- atw:begin -->", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertFalse((self.root / "CLAUDE.md").exists())  # Claude Code reads AGENTS.md itself
        self.assertIn(".atw/runs/", (self.root / ".gitignore").read_text(encoding="utf-8"))
        skill = (self.root / ".claude/skills/ticket/SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("{{", skill)
        self.assertIn(".atw/core/atw.py", skill)
        self.assertIn(".claude/skills/ticket-audit/SKILL.md", skill)  # per-host skill dir
        codex_skill = (self.root / ".agents/skills/ticket/SKILL.md").read_text(encoding="utf-8")
        self.assertIn(".agents/skills/ticket-audit/SKILL.md", codex_skill)

        doc = self.atw("doctor")
        self.assertEqual(doc.returncode, 0, doc.stdout)
        self.assertIn("HEALTHY", doc.stdout)

        # The installed core runs a real (non-code) ticket.
        self.assertEqual(self.atw("start", "T-1", "--kind", "comms").returncode, 0)
        self.write("docs/agent-notes/comms/T-1-reply.md", "Hello.\n")
        close = self.atw("close")
        self.assertEqual(close.returncode, 0, close.stdout + close.stderr)

        # Run state never shows up as a change to commit.
        self.assertFalse(any(f.startswith(".atw/runs/") for f in self.status_files()))

    def test_reapply_is_idempotent_and_respects_local_edits(self):
        self.install()
        plan = self.plan()
        self.assertEqual(self.apply(plan).returncode, 0)
        self.assertEqual(self.apply(plan).returncode, 0)
        settings = json.loads((self.root / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)  # not duplicated
        agents_md = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(agents_md.count("<!-- atw:begin -->"), 1)

        edited = self.root / ".claude/skills/ticket/SKILL.md"
        edited.write_text(edited.read_text(encoding="utf-8") + "\nlocal note\n", encoding="utf-8")
        r = self.apply(plan)
        self.assertEqual(r.returncode, 1)
        self.assertIn("edited locally", r.stdout)
        self.assertIn("local note", edited.read_text(encoding="utf-8"))
        r = self.apply(self.plan(overwrite_modified=[".claude/skills/ticket/SKILL.md"]))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("local note", edited.read_text(encoding="utf-8"))

    def test_renamed_skill_removes_old_unedited_copy(self):
        self.install()
        self.assertEqual(self.apply(self.plan()).returncode, 0)
        skills = dict(TEMPLATE_PLAN["skills"], ticket="atw-ticket")
        r = self.apply(self.plan(skills=skills))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse((self.root / ".claude/skills/ticket/SKILL.md").exists())
        self.assertIn("name: atw-ticket", (self.root / ".claude/skills/atw-ticket/SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("/atw-ticket", (self.root / "AGENTS.md").read_text(encoding="utf-8"))

    def test_experimental_spike_and_no_unrendered_tokens(self):
        self.install()
        plan = self.plan(spike="spike", spike_dir="research/spikes")
        data = json.loads(plan.read_text(encoding="utf-8"))
        data["config"]["kinds"]["enabled"].append("spike")
        plan.write_text(json.dumps(data), encoding="utf-8")
        r = self.apply(plan)
        self.assertEqual(r.returncode, 0, r.stdout)
        spike = (self.root / ".agents/skills/spike/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("research/spikes/<slug>/", spike)
        self.assertIn(".agents/skills/spike/verifier-prompt.md", spike)
        for d in (".claude/skills", ".agents/skills"):
            for p in (self.root / d).rglob("*.md"):
                if "ticket-setup" not in p.parts:
                    self.assertNotIn("{{", p.read_text(encoding="utf-8"), p)
        self.assertNotIn("{{", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(self.atw("start", "T-1", "--kind", "spike").returncode, 0)
        self.assertEqual(self.atw("close", "--note", "spike demo: scaffolded").returncode, 0)

    def test_invalid_plan_writes_nothing(self):
        self.install()
        plan = self.plan()
        data = json.loads(plan.read_text(encoding="utf-8"))
        data["config"]["protected_paths"] = []
        plan.write_text(json.dumps(data), encoding="utf-8")
        before = self.status_files()
        r = self.apply(plan)
        self.assertEqual(r.returncode, 1)
        self.assertIn("protected_paths", r.stdout)
        self.assertEqual(self.status_files(), before)


class Launcher(unittest.TestCase):

    def test_split_launcher(self):
        sys.path.insert(0, str(REPO / "core"))
        try:
            from atwlib.install import hook_fragment, split_launcher
        finally:
            sys.path.pop(0)
        self.assertEqual(split_launcher('"C:\\Program Files\\Py\\python.exe"'), ["C:\\Program Files\\Py\\python.exe"])
        self.assertEqual(split_launcher("py -3"), ["py", "-3"])
        self.assertEqual(split_launcher("python3"), ["python3"])
        raw = (REPO / "adapters/claude-code/settings.fragment.json").read_text(encoding="utf-8")
        h = hook_fragment(raw, "py -3")["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual((h["command"], h["args"][:2]), ("py", ["-3", "-c"]))


THEIR_SKILL ="---\nname: ticket\ndescription: our own ticket flow\n---\nTheirs.\n"
THEIR_SETTINGS = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python their_gate.py"}]}]},
                  "permissions": {"deny": ["Bash(rm -rf*)"]}}
THEIR_CLAUDE = "# Project rules\n\nUse tabs.\n"


class Brownfield(InstallBase):

    def brownfield(self):
        self.write(".claude/skills/ticket/SKILL.md", THEIR_SKILL)
        self.write(".claude/settings.json", json.dumps(THEIR_SETTINGS, indent=2))
        self.write("CLAUDE.md", THEIR_CLAUDE)

    THEIRS = (".claude/skills/ticket/SKILL.md", ".claude/settings.json", "CLAUDE.md")

    def test_detect_reports_collisions(self):
        self.install()
        r = self.run_py(self.root / ".atw/staging/core/atw.py", "detect", "--json")
        report = json.loads(r.stdout)
        ids = {c["id"] for c in report["collisions"]}
        self.assertIn("skill:.claude/skills/ticket", ids)
        self.assertIn("hooks:.claude/settings.json:Stop", ids)
        self.assertIn("instructions:CLAUDE.md", ids)
        self.assertEqual(report["atw"]["mode"], "fresh")
        # The setup skill install.py copied is ours: no collision, no "similar practice".
        self.assertFalse([i for i in ids if "ticket-setup" in i], ids)
        self.assertFalse([w for w in report["similar_workflows"]
                          if any("ticket-setup" in f for f in w["found_in"])], report["similar_workflows"])

    def test_clashing_skill_name_is_refused_and_nothing_written(self):
        self.install()
        before = sha_tree(self.root, self.THEIRS)
        r = self.apply(self.plan())
        self.assertEqual(r.returncode, 1)
        self.assertIn(".claude/skills/ticket/SKILL.md: exists and is not ours", r.stdout)
        self.assertEqual(sha_tree(self.root, self.THEIRS), before)
        self.assertFalse((self.root / ".atw/install-manifest.json").exists())

    def test_namespaced_install_keeps_theirs(self):
        self.install()
        skills = dict(TEMPLATE_PLAN["skills"], ticket="atw-ticket")
        r = self.apply(self.plan(skills=skills))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual((self.root / ".claude/skills/ticket/SKILL.md").read_text(encoding="utf-8"), THEIR_SKILL)
        self.assertTrue(self_text := (self.root / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertTrue(self_text.startswith(THEIR_CLAUDE))
        self.assertIn("<!-- atw:begin -->\n@AGENTS.md\n<!-- atw:end -->", self_text)  # the bridge, nothing more
        settings = json.loads((self.root / ".claude/settings.json").read_text(encoding="utf-8"))
        stops = json.dumps(settings["hooks"]["Stop"])
        self.assertIn("their_gate.py", stops)
        self.assertIn(".atw/core/atw.py", stops)
        self.assertEqual(settings["permissions"], THEIR_SETTINGS["permissions"])
        backups = list((self.root / ".atw/backup").rglob("settings.json"))
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), THEIR_SETTINGS)
        manifest = json.loads((self.root / ".atw/install-manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn(".claude/skills/ticket/SKILL.md", manifest["files"])

    def test_skipping_shared_files_leaves_them_byte_identical(self):
        self.install()
        before = sha_tree(self.root, self.THEIRS)
        skills = dict(TEMPLATE_PLAN["skills"], ticket="atw-ticket")
        r = self.apply(self.plan(skills=skills, claude_settings="skip", claude_bridge="skip"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(sha_tree(self.root, self.THEIRS), before)
        doc = self.atw("doctor")
        self.assertIn("hooks were skipped", doc.stdout)

    def test_setup_skill_name_clash(self):
        self.write(".claude/skills/ticket-setup/SKILL.md", "---\nname: ticket-setup\n---\nmine\n")
        r = self.install()
        self.assertEqual(r.returncode, 1)
        self.assertIn("--setup-name", r.stdout)
        self.assertFalse((self.root / ".atw/staging").exists())
        r = self.install("--setup-name", "atw-setup")
        self.assertEqual(r.returncode, 0, r.stdout)
        text = (self.root / ".claude/skills/atw-setup/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: atw-setup", text)
        self.assertEqual((self.root / ".claude/skills/ticket-setup/SKILL.md").read_text(encoding="utf-8"),
                         "---\nname: ticket-setup\n---\nmine\n")


class GitMode(InstallBase):
    """Local only vs committed for the team: the user's answer, never a default."""

    def git_status(self) -> str:
        return git(self.root, "status", "--porcelain", "-uall").strip()

    def test_git_mode_is_required(self):
        self.install()
        before = self.status_files()
        r = self.apply(self.plan(git_mode=None))
        self.assertEqual(r.returncode, 1)
        self.assertIn("git_mode is required", r.stdout)
        self.assertEqual(self.status_files(), before)

    def test_local_install_leaves_git_status_clean(self):
        self.assertEqual(self.install().returncode, 0)
        r = self.apply(self.plan(git_mode="local"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.git_status(), "")  # not even the setup skill install.py copied
        self.assertFalse((self.root / ".gitignore").exists())
        self.assertFalse((self.root / ".claude/settings.json").exists())
        local = json.loads((self.root / ".claude/settings.local.json").read_text(encoding="utf-8"))
        self.assertIn(".atw/core/atw.py", json.dumps(local["hooks"]["Stop"]))
        self.assertIn("<!-- atw:begin -->", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        exclude = (self.root / ".git/info/exclude").read_text(encoding="utf-8")
        self.assertIn("/.atw/", exclude)
        self.assertIn("/AGENTS.md", exclude)
        # A later setup run does not mistake our own files or hooks for the user's practices.
        report = json.loads(self.run_py(self.root / ".atw/staging/core/atw.py", "detect", "--json").stdout)
        self.assertEqual(report["similar_workflows"], [])
        self.assertEqual(report["collisions"], [])
        doc = self.atw("doctor")
        self.assertEqual(doc.returncode, 0, doc.stdout)
        self.assertIn("nothing installed shows up in git status", doc.stdout)
        self.assertIn(".atw/runs/ and .atw/tmp/ are ignored by git", doc.stdout)
        # The workflow itself works in local mode.
        self.assertEqual(self.atw("start", "T-1", "--kind", "comms").returncode, 0)
        self.write("docs/agent-notes/comms/T-1-reply.md", "Hello.\n")
        self.assertEqual(self.atw("close").returncode, 0)
        self.assertEqual(self.git_status(), "?? docs/agent-notes/comms/T-1-reply.md")

    def test_switching_modes_removes_only_our_parts(self):
        self.install()
        self.assertEqual(self.apply(self.plan()).returncode, 0)            # commit
        self.assertTrue((self.root / ".gitignore").is_file())
        r = self.apply(self.plan(git_mode="local"))
        self.assertEqual(r.returncode, 0, r.stdout)
        for gone in (".gitignore", ".claude/settings.json"):            # we created them, only ours inside
            self.assertFalse((self.root / gone).exists(), gone)
        self.assertEqual(self.git_status(), "")
        r = self.apply(self.plan(git_mode="commit"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("atw:begin", (self.root / ".git/info/exclude").read_text(encoding="utf-8"))
        self.assertFalse((self.root / ".claude/settings.local.json").exists())
        self.assertTrue((self.root / ".claude/settings.json").is_file())

    def test_local_install_in_a_linked_worktree(self):
        main = self.root
        git(main, "worktree", "add", "-q", "-b", "trial", str(self.tmp / "wt"))
        self.root = self.tmp / "wt"
        self.assertEqual(self.install().returncode, 0)
        r = self.apply(self.plan(git_mode="local"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("linked worktree", r.stdout)
        shared = main / ".git/info/exclude"
        self.assertIn("/AGENTS.md", shared.read_text(encoding="utf-8"))
        self.assertEqual(self.git_status(), "")
        self.assertEqual(git(main, "status", "--porcelain", "-uall").strip(), "")
        doc = self.atw("doctor")
        self.assertEqual(doc.returncode, 0, doc.stdout)
        self.assertIn("linked worktree", doc.stdout)
        manifest = json.loads((self.root / ".atw/install-manifest.json").read_text(encoding="utf-8"))
        self.assertFalse([k for k in manifest["merges"] if "\\" in k], manifest["merges"])
        # Moving to commit mode takes our block out of the shared file again.
        self.assertEqual(self.apply(self.plan(git_mode="commit")).returncode, 0)
        self.assertNotIn("atw:begin", shared.read_text(encoding="utf-8"))


TRACKED_AGENTS = "# Agents\n\nTeam rules.\n"


class GitModeBrownfield(InstallBase):
    """Local mode in a project whose instruction and settings files are tracked."""

    def brownfield(self):
        self.write("CLAUDE.md", THEIR_CLAUDE)
        self.write("AGENTS.md", TRACKED_AGENTS)
        self.write(".claude/settings.json", json.dumps(THEIR_SETTINGS, indent=2))
        self.write(".gitignore", "node_modules/\n")

    TRACKED = ("CLAUDE.md", "AGENTS.md", ".claude/settings.json", ".gitignore")

    def test_local_defaults_touch_no_tracked_file(self):
        self.install()
        before = sha_tree(self.root, self.TRACKED)
        r = self.apply(self.plan(git_mode="local"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(sha_tree(self.root, self.TRACKED), before)
        self.assertEqual(git(self.root, "status", "--porcelain", "-uall"), "")
        self.assertIn("instructions -> skip", r.stdout)
        doc = self.atw("doctor")
        self.assertIn("no instructions block", doc.stdout)

    def test_local_with_a_surgical_override(self):
        """The user keeps tracked files untouched but still wants Claude to see the rules."""
        self.install()
        before = sha_tree(self.root, self.TRACKED)
        r = self.apply(self.plan(git_mode="local", instructions=".atw/AGENTS.md"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(sha_tree(self.root, self.TRACKED), before)
        self.assertIn("@.atw/AGENTS.md", (self.root / "CLAUDE.local.md").read_text(encoding="utf-8"))
        self.assertEqual(git(self.root, "status", "--porcelain", "-uall"), "")

    def test_commit_mode_bridges_and_keeps_their_text(self):
        self.install()
        r = self.apply(self.plan())
        self.assertEqual(r.returncode, 0, r.stdout)
        claude = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(claude.startswith(THEIR_CLAUDE))
        self.assertTrue((self.root / "AGENTS.md").read_text(encoding="utf-8").startswith(TRACKED_AGENTS))
        self.assertTrue((self.root / ".gitignore").read_text(encoding="utf-8").startswith("node_modules/\n"))
        # Switching the bridge off later removes exactly our line and nothing else.
        r = self.apply(self.plan(claude_bridge="skip"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual((self.root / "CLAUDE.md").read_text(encoding="utf-8"), THEIR_CLAUDE)
        self.assertIn("no bridge imports AGENTS.md", self.atw("doctor").stdout)


class Distribution(InstallBase):

    def test_zip_installs_without_git_and_detects_upgrade(self):
        out = self.tmp / "dist"
        r = self.run_py(REPO / "tools" / "make_dist.py", "--out", out, cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        zpath = out / f"agent-ticket-workflow-{version}.zip"
        digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
        self.assertIn(digest, (out / "SHA256SUMS").read_text(encoding="utf-8"))
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            self.assertFalse(any("/.git/" in n or "__pycache__" in n for n in names))
            self.assertIn(f"agent-ticket-workflow-{version}/INSTALL.txt", names)
            zf.extractall(self.tmp / "unzipped")
        pkg = self.tmp / "unzipped" / f"agent-ticket-workflow-{version}"
        self.assertFalse((pkg / ".git").exists())

        self.assertEqual(self.install(package=pkg).returncode, 0)
        self.assertEqual(self.apply(self.plan()).returncode, 0)
        self.assertEqual(self.atw("doctor").returncode, 0)

        # A newer package is detected as an upgrade.
        (pkg / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        r = self.install(package=pkg)
        self.assertIn("upgrade", r.stdout)
        report = json.loads(self.run_py(self.root / ".atw/staging/core/atw.py", "detect", "--json").stdout)
        self.assertEqual(report["atw"]["mode"], "upgrade")
        r = self.apply(self.plan())
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("(upgrade)", r.stdout)


if __name__ == "__main__":
    unittest.main()
