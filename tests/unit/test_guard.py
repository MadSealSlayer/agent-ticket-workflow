"""The parsed command guard: shell parsing, git rules, git add of data files,
test deletion, custom regexes, the legacy-pattern warning and session binding."""
from __future__ import annotations

import json
import unittest

from _helpers import Project, git
from atwlib import config, doctor, guard, hooks, shell, state


class Parsing(unittest.TestCase):

    def test_heredoc_body_is_removed(self):
        cmd = "cat > NOTES.md <<'EOF'\ngit push --force is dangerous\nEOF\nls"
        self.assertEqual(shell.segments(cmd), ["cat > NOTES.md", "ls"])

    def test_here_string_is_not_a_heredoc(self):
        self.assertEqual(shell.segments('git commit -F - <<< "msg"\nls'), ['git commit -F - <<< "msg"', "ls"])

    def test_powershell_here_string_body_is_removed(self):
        cmd = "$m = @'\ngit push --force\n'@\ngit status"
        self.assertEqual(shell.segments(cmd, powershell=True), ["$m =", "git status"])

    def test_separators_outside_quotes_only(self):
        self.assertEqual(shell.segments("a; b && c || d | e & f\ng"), ["a", "b", "c", "d", "e", "f", "g"])
        self.assertEqual(shell.segments("python -c \"import a;import b\" | tee x"),
                         ['python -c "import a;import b"', "tee x"])
        self.assertEqual(shell.segments("cmd 2>&1 &> log"), ["cmd 2>&1 &> log"])
        self.assertEqual(shell.segments("ls # a; b\npwd"), ["ls", "pwd"])

    def test_command_substitution_is_its_own_segment(self):
        self.assertIn("git push --force", shell.segments('echo "$(git push --force)"'))
        self.assertIn("git push --force", shell.segments("echo `git push --force`"))
        self.assertIn("git push --force", shell.segments("(cd sub && git push --force)"))
        self.assertIn("git push --force", shell.segments("{ git push --force; }"))
        self.assertEqual(shell.segments("echo ${HOME}/x"), ["echo ${HOME}/x"])
        self.assertEqual(shell.segments("xargs -I {} git add {}"), ["xargs -I {} git add {}"])

    def test_powershell_backtick_is_an_escape(self):
        self.assertEqual(shell.segments("echo `$x; ls", powershell=True), ["echo `$x", "ls"])

    def test_shell_dash_c_script_is_parsed(self):
        self.assertIn("git push --force", shell.segments('bash -c "git push --force"'))
        self.assertIn("git push --force", shell.segments('pwsh -NoProfile -Command "git push --force"'))

    def test_normalized_tokens(self):
        self.assertEqual(shell.normalized("FOO=1 sudo -n env BAR=2 /usr/bin/git.exe push"), ["git", "push"])
        self.assertEqual(shell.normalized('"C:\\Program Files\\Git\\cmd\\git.exe" push'), ["git", "push"])
        self.assertEqual(shell.normalized('& "C:\\Git\\GIT.EXE" push', powershell=True), ["git", "push"])
        self.assertEqual(shell.normalized("echo 'a b' \"c d\""), ["echo", "a b", "c d"])
        self.assertEqual(shell.normalized('atw.py" kind code'), ["atw.py", "kind", "code"])

    def test_git_global_options_are_skipped(self):
        inv = shell.git_invocation(shell.normalized(
            "git -C ../other -c user.name=x --git-dir=.git --no-pager push --force"))
        self.assertEqual(inv, ("push", ["--force"], "../other"))
        self.assertIsNone(shell.git_invocation(shell.normalized("echo git push")))


class GuardCase(Project):

    def cfg(self, **guards):
        raw = json.loads((self.root / ".atw/atw.config.json").read_text(encoding="utf-8"))
        raw["guards"] = {**(raw.get("guards") or {}), **guards}
        return config._merge(config.DEFAULTS, raw)

    def decide(self, cmd, powershell=False, cfg=None):
        d = guard.evaluate(self.root, cfg or self.cfg(), cmd, powershell)
        return d[0] if d else None


class GitRules(GuardCase):

    def test_default_denies(self):
        for cmd in ("git reset --hard origin/main", "git push --force", "git push -f origin main",
                    "git push --force-with-lease", "git push --force-with-lease=main:abc origin",
                    "git push origin +main", "git rebase main", "git commit --amend -m x",
                    "git clean -fd", "git clean -xdf", "git clean -dfx", "git clean --force"):
            self.assertEqual(self.decide(cmd), "deny", cmd)

    def test_wrapper_and_prefix_forms_still_deny(self):
        for cmd in ("sudo git push --force", "FOO=bar git push --force", "/usr/bin/git push --force",
                    "git.exe push --force", "env git push --force", "sudo -n git push --force",
                    "env FOO=bar git push --force", "nohup git push --force",
                    '"C:\\Program Files\\Git\\cmd\\git.exe" push --force',
                    "git -C ../other push --force", "git -c user.name=x commit --amend",
                    "git --git-dir=.git --no-pager rebase main", "time -p git push --force",
                    "echo main | xargs -I {} git push --force origin {}", "sudo -u dev git rebase main"):
            self.assertEqual(self.decide(cmd), "deny", cmd)

    def test_powershell_forms_deny(self):
        for cmd in ('& "C:\\Program Files\\Git\\cmd\\git.exe" push --force', "GIT push --force",
                    "Set-Location sub; git rebase main"):
            self.assertEqual(self.decide(cmd, powershell=True), "deny", cmd)

    def test_every_segment_is_checked(self):
        for cmd in ("yes | git clean -fdx", "echo ok; git rebase main", "ls && git reset --hard",
                    "false || git rebase main", "echo $(git push --force)", "echo `git push --force`",
                    "(cd sub && git push --force)", "{ git push --force; }", 'bash -c "git push --force"',
                    "echo hi & git push --force", "ls\ngit push --force"):
            self.assertEqual(self.decide(cmd), "deny", cmd)

    def test_plain_push_asks_and_deny_wins_over_ask(self):
        self.assertEqual(self.decide("git push origin feature/x"), "ask")
        self.assertEqual(self.decide("git push origin x && git push --force"), "deny")

    def test_text_that_only_mentions_git_is_allowed(self):
        for cmd in ("git status", 'echo "git commit"', "sed -i 's/git push/x/' f", "grep -n 'git rebase' f",
                    "git log --grep commit", 'git log --grep "push --force"',
                    "cat > NOTES.md <<'EOF'\nDo not run git push --force on main.\nEOF",
                    "cat > NOTES.md <<EOF\ngit push --force is dangerous\nEOF",
                    "echo 'remember to git push later'", "git commit -m 'add dump.csv to repo'",
                    'git commit -F - <<< "git push --force"', 'git commit -m "x" 2>&1',
                    "rg 'git reset --hard' docs/", "ls  # then git push --force",
                    "git log --format='#%h git rebase'"):
            self.assertIsNone(self.decide(cmd), cmd)

    def test_powershell_here_string_body_is_allowed(self):
        cmd = "$msg = @'\ngit push --force\n'@\ngit status"
        self.assertIsNone(self.decide(cmd, powershell=True))

    def test_never_commit_or_push_policy(self):
        cfg = self.cfg(git={"deny": ["reset-hard", "push-force", "rebase", "clean-force", "commit-amend",
                                     "commit", "push"], "ask": []})
        for cmd in ("git commit -m x", "git -C sub commit -am x", "git push origin main", "sudo git push"):
            self.assertEqual(self.decide(cmd, cfg=cfg), "deny", cmd)
        for cmd in ('echo "git commit"', "git log --grep commit", "sed 's/git push/x/' f", "git add src/calc.py"):
            self.assertIsNone(self.decide(cmd, cfg=cfg), cmd)

    def test_commit_message_heredoc_idiom(self):
        cmd = ("git commit -m \"$(cat <<'EOF'\ngit rebase is now blocked by the guard\n"
               "rm tests/test_calc.py was removed\nEOF\n)\"")
        self.assertIsNone(self.decide(cmd))
        cfg = self.cfg(git={"deny": ["commit"], "ask": []})
        d = guard.evaluate(self.root, cfg, cmd)
        self.assertEqual(d[0], "deny")
        self.assertIn("'commit'", d[1])
        self.assertNotIn("rebase", d[1])

    def test_command_after_the_heredoc_operator_is_kept(self):
        cmd = "cat <<'EOF' | git commit -F -\nmessage\nEOF"
        self.assertIsNone(self.decide(cmd))
        self.assertEqual(self.decide(cmd, cfg=self.cfg(git={"deny": ["commit"], "ask": []})), "deny")

    def test_extra_history_rules(self):
        cfg = self.cfg(git={"deny": ["push-delete", "filter-branch", "update-ref-delete", "reflog-expire"],
                            "ask": []})
        for cmd in ("git push origin --delete old", "git push -d origin old", "git push origin :old",
                    "git filter-branch --tree-filter x", "git update-ref -d refs/heads/x",
                    "git reflog expire --expire=now --all"):
            self.assertEqual(self.decide(cmd, cfg=cfg), "deny", cmd)
        self.assertIsNone(self.decide("git push origin main", cfg=cfg))

    def test_rules_off(self):
        cfg = self.cfg(git={"deny": [], "ask": []})
        self.assertIsNone(self.decide("git push --force", cfg=cfg))


class CustomRegexes(GuardCase):

    def test_regex_applies_per_command_without_heredoc_bodies(self):
        cfg = self.cfg(deny=[r"^npm\s+publish\b"], ask=[r"^docker\s+push\b"])
        self.assertEqual(self.decide("npm publish", cfg=cfg), "deny")
        self.assertEqual(self.decide("npm test && npm publish", cfg=cfg), "deny")
        self.assertEqual(self.decide("docker push img", cfg=cfg), "ask")
        self.assertIsNone(self.decide("cat <<'EOF'\nnpm publish\nEOF", cfg=cfg))
        self.assertIsNone(self.decide('echo "npm publish"', cfg=cfg))

    def test_quoted_text_inside_a_command_still_matches_a_regex(self):
        cfg = self.cfg(deny=[r"\bnpm\s+publish\b"])
        self.assertEqual(self.decide('echo "npm publish"', cfg=cfg), "deny")


class GitAddData(GuardCase):

    def test_image_asks_and_source_is_silent(self):
        self.write("helpers/img.webp", "x")
        self.assertEqual(self.decide("git add helpers/img.webp"), "ask")
        self.assertEqual(self.decide("git add -- helpers/img.webp"), "ask")
        self.write("helpers/scratch.py", "x = 1\n")
        self.assertIsNone(self.decide("git add helpers/scratch.py"))

    def test_lockfiles_are_exempt_at_any_size(self):
        self.write("package-lock.json", "{" + "x" * 1_200_000 + "}")
        self.write("tsconfig.app.json", "{" + "x" * 60_000 + "}")
        self.assertIsNone(self.decide("git add package-lock.json tsconfig.app.json"))

    def test_large_files_ask(self):
        self.write("helpers/dump.dat", "x" * 1_200_000)
        self.write("helpers/big.json", "{" + "x" * 60_000 + "}")
        self.assertEqual(self.decide("git add helpers/dump.dat"), "ask")
        self.assertEqual(self.decide("git add helpers/big.json"), "ask")

    def test_whole_tree_and_folder_adds_scan_changed_files(self):
        self.write("helpers/RM/dump.csv", "a,b\n1,2\n")
        for cmd in ("git add -A", "git add .", "git add", "git add --all", "git add helpers",
                    "git -C helpers add RM", "git add 'helpers/*'"):
            self.assertEqual(self.decide(cmd), "ask", cmd)

    def test_clean_tree_is_silent(self):
        self.write("helpers/scratch.py", "x = 1\n")
        self.assertIsNone(self.decide("git add -A"))

    def test_can_be_turned_off(self):
        self.write("helpers/img.png", "x")
        self.assertIsNone(self.decide("git add helpers/img.png", cfg=self.cfg(git_add_data=False)))


class TestDelete(GuardCase):

    def test_deleting_a_test_file_asks(self):
        for cmd in ("rm tests/test_calc.py", "rm -f ./tests/test_calc.py", "del tests/test_calc.py",
                    "rm -rf tests", "rm -rf .", "git rm tests/test_calc.py", "rm src/app.spec.ts",
                    f"rm {self.root.as_posix()}/tests/test_calc.py"):
            self.assertEqual(self.decide(cmd), "ask", cmd)
        for cmd in ("Remove-Item tests\\test_calc.py", "Remove-Item -Path tests -Recurse -Force",
                    "ri tests/test_calc.py"):
            self.assertEqual(self.decide(cmd, powershell=True), "ask", cmd)

    def test_folder_with_tracked_tests_asks(self):
        self.write("web/app.spec.ts", "it('x', () => {});\n")
        git(self.root, "add", "web/app.spec.ts")
        self.assertEqual(self.decide("rm -rf web"), "ask")

    def test_other_deletes_are_silent(self):
        for cmd in ("rm src/calc.py", "rm -rf node_modules", "git rm --cached tests/test_calc.py",
                    'echo "rm tests/test_calc.py"'):
            self.assertIsNone(self.decide(cmd), cmd)

    def test_can_be_turned_off(self):
        self.assertIsNone(self.decide("rm tests/test_calc.py", cfg=self.cfg(test_delete=False)))


class ConfigAndMigration(unittest.TestCase):

    def test_defaults_keep_todays_behaviour(self):
        g = config.DEFAULTS["guards"]
        self.assertEqual(g["git"], {"deny": ["reset-hard", "push-force", "rebase", "clean-force", "commit-amend"],
                                    "ask": ["push"]})
        self.assertEqual((g["deny"], g["ask"], g["git_add_data"], g["test_delete"]), ([], [], True, True))

    def test_validation(self):
        def errs(**guards):
            return config.validate(config._merge(config.DEFAULTS, {"guards": guards}))
        self.assertFalse([e for e in errs() if "guards" in e])
        self.assertTrue(any("unknown rule" in e for e in errs(git={"deny": ["force-push"]})))
        self.assertTrue(any("guards.git.ask" in e for e in errs(git={"ask": "push"})))
        self.assertTrue(any("unknown key" in e for e in errs(git={"block": []})))
        self.assertTrue(any("guards.git_add_data" in e for e in errs(git_add_data="yes")))

    def test_legacy_patterns_warn_with_the_git_equivalent(self):
        old = {"guards": {"deny": [r"\bgit\s+reset\s+--hard\b", r"\bgit\s+rebase\b", r"\bgit\s+commit\b",
                                   r"\bgit\s+push\b", r"\bnpm\s+publish\b"],
                          "ask": []}}
        found = config.legacy_git_patterns(old)
        self.assertEqual([rule for _, rule in found["deny"]], ["reset-hard", "rebase", "commit", "push"])
        r = doctor.Report()
        doctor._legacy_guard_check(r, old)
        text = "\n".join(msg for _, msg in r.lines)
        self.assertTrue(all(level == "WARN" for level, _ in r.lines))
        self.assertIn('"deny": ["reset-hard", "push-force", "rebase", "clean-force", "commit-amend", '
                      '"commit", "push"], "ask": []', text)
        self.assertNotIn("npm", text)
        r = doctor.Report()
        doctor._legacy_guard_check(r, {"guards": {"deny": [r"\bnpm\s+publish\b"]}})
        self.assertEqual(r.lines, [])


class Binding(unittest.TestCase):

    def bound(self, *commands, powershell=False):
        seen = []
        orig = state.bind_session
        state.bind_session = lambda root, sid, ticket: seen.append(ticket)
        try:
            for c in commands:
                hooks.bind_from_command(None, "s", c, powershell)
        finally:
            state.bind_session = orig
        return seen

    def test_real_calls_bind(self):
        self.assertEqual(self.bound("python .atw/core/atw.py start T-3 --kind comms",
                                    "atw gate tests --run=T-4/r1",
                                    "py -3 .atw/core/atw.py close --ticket T-5",
                                    "atw gate tests --run T-6/r1 && atw start T-2",
                                    "uv run python .atw/core/atw.py start T-8"), ["T-3", "T-4", "T-5", "T-2", "T-8"])
        self.assertEqual(self.bound('& "C:\\Python\\python.exe" .atw\\core\\atw.py start T-7', powershell=True),
                         ["T-7"])

    def test_mentions_and_read_only_calls_do_not_bind(self):
        self.assertEqual(self.bound('echo "atw start T-9"', "git commit -m 'atw start T-8'",
                                    "atw status --ticket T-7", "cat <<'EOF'\natw start T-6\nEOF",
                                    "grep 'atw.py close --ticket T-5' notes.md"), [])


class HookCli(Project):

    def test_quoted_git_text_is_allowed_through_the_hook(self):
        payload = json.dumps({"session_id": "s", "cwd": str(self.root), "tool_name": "Bash",
                              "tool_input": {"command": 'echo "git push --force" && grep -n "git rebase" f'}})
        self.assertEqual(self.ok("hook", "guard", stdin=payload).strip(), "")
        payload = json.dumps({"session_id": "s", "cwd": str(self.root), "tool_name": "PowerShell",
                              "tool_input": {"command": "Remove-Item tests/test_calc.py"}})
        out = json.loads(self.ok("hook", "guard", stdin=payload))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")


if __name__ == "__main__":
    unittest.main()
