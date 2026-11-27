# Architecture

## Parts

```
package (this repo)                        target project after setup
-------------------                        ---------------------------
install.py  ── stages ──────────────────>  .atw/staging/   (self-gitignored: PAYLOAD.json, bootstrap.json)
skills/ticket-setup ── copies raw ──────>  .claude/skills/ticket-setup, .agents/skills/ticket-setup
                                            │
          /ticket-setup: detect -> question sheet -> install plan -> apply -> doctor
                                            ▼
core/ ──────────────── apply copies ────>  .atw/core/            state engine (+ VERSION)
templates/atw.config ─ from answers ────>  .atw/atw.config.json
skills/* ───────────── apply renders ───>  .claude/skills/*, .agents/skills/*
adapters/claude-code ─ merged entries ──>  .claude/settings.json or settings.local.json (our hook entries only)
adapters/agents-md ─── marked block ────>  AGENTS.md, or another file the user picks (<!-- atw:begin/end -->)
(bridge) ───────────── marked block ────>  CLAUDE.md or CLAUDE.local.md: one line, @AGENTS.md
adapters/gitignore ─── marked block ────>  .gitignore or .git/info/exclude (# atw:begin/end)
                                           .atw/install-manifest.json   what is ours, with hashes
                                           .atw/setup-questions.md      why it is set up this way
                                           .atw/runs/  .atw/tmp/        run state (ignored by git)
```

Every shared-file arrow is optional. The plan's `git_mode` (`local` or `commit`, always the
user's answer in a git repository) chooses the default target for each one. The plan can point
any single item to another file, or `skip` it:

| Plan key | `commit` default | `local` default |
|---|---|---|
| `instructions` | `AGENTS.md` | `AGENTS.md`, or `skip` when it is tracked |
| `claude_bridge` (`auto`) | `CLAUDE.md`, only when one exists | `CLAUDE.local.md`, only when a `CLAUDE.md` exists |
| `claude_settings` | `merge` (`.claude/settings.json`) | `local` (`.claude/settings.local.json`) |
| `ignore` | `gitignore` | `exclude` (`.git/info/exclude`), listing everything we install |

Our instructions live in one file. Claude Code reads `AGENTS.md` by itself only when there is no
`CLAUDE.md`. The bridge covers the other case with an import, so the text is never duplicated.

## The state engine (`core/`)

`atw.py` is the only entry point. Every host uses it: the skills call it, and the Claude Code
hooks call it through `atw.py hook <name>`.

| Module | Job |
|---|---|
| `config.py` | Defaults, loading, validation of `.atw/atw.config.json` |
| `state.py` | Runs: one folder per (ticket, run id) with `run.json` and a log. It also handles selection by `--run`, `--ticket` or `$ATW_RUN`, the baseline (HEAD sha plus files untracked at start), and the session-to-ticket bindings that keep parallel Claude sessions apart |
| `runner.py` | Renders command templates (`{files}`, `{ids}`, `{id_files}`, `{junit}`, `{python}`) and runs them |
| `junit.py` | Parses JUnit XML. Behavioral red: refuses errors, skips, passes and missing-symbol failures |
| `gates.py` | Every gate. Live gates are computed by a script; tests, lint and deps are cached by a fingerprint of the change. Recorded gates check their stored hash |
| `deps.py` | New third-party imports against pip / npm declarations |
| `packets.py` | Review and simplify packets: the diff, requirements and settled decisions, hashed |
| `hooks.py` | Claude Code hooks: Stop (gate check from cached results, never runs tests; release after 3 identical blocks), guard (command rules, session binding, test markers, plan-before-edit), plan approval stamps (PostToolUse on ExitPlanMode, or an `Approve` answer to the `Plan` AskUserQuestion in T3 Code; PreToolUse ExitPlanMode stamps the proposal) |
| `guard.py` | The guard's command rules: named git rules (`guards.git`), `git add` of data files, test deletion, custom regexes. Deny wins over ask |
| `shell.py` | Best-effort parsing of a Bash or PowerShell command line into the commands it runs (heredocs, separators, quotes, wrappers, git global options) |
| `jira.py` | `atw import-jira`: a fetched Jira issue (JSON file) to a local ticket file. Never calls Jira |
| `tickets.py` | `atw new-ticket`: an approved draft from the conversation to a new, numbered ticket file (`tickets.new`) |
| `detect.py` | Read-only discovery for setup: stack, CI, hooks, skills, instruction files, collisions |
| `install.py` | Applies an approved install plan: ownership checks, render, merge, backup, manifest |
| `doctor.py` | Installation health and `hygiene` |
| `presets/` | Stack presets: detection rules and command templates. A preset that needs a wrapper keeps it in a folder of its name (`presets/karma/`, `presets/tsc/`); commands call it as `.atw/core/presets/<name>/...` |

## Determinism boundaries

| Decided by a script | Decided by the agent | Decided by the user |
|---|---|---|
| Gate results, staleness, red validity, placement, ownership of files, collisions | The kind (proposed), the plan content, the proof test ids, the review findings | The kind (when unclear), plan approval, every collision, the config questions, accepting Warnings |

The setup skill's decision policy (`skills/ticket-setup/references/decision-policy.md`) lists
what the agent may decide alone. An item qualifies only when all three are true:
- there is one obvious answer;
- the choice is reversible;
- it touches nothing that already exists.

## Ownership model

A file is **ours** if it is in the manifest's `files` map, or in `.atw/staging/bootstrap.json`
(the setup skill that `install.py` copied), **and** its current hash matches. Apply:

- **Refuses** to write a file that exists and is not ours. Nothing is written when anything
  collides.
- **Refuses** to write a file of ours that was edited, unless the plan lists it in
  `overwrite_modified`.
- Changes **shared files** only inside marked blocks (the instructions file, the bridge file, the
  ignore file). In the Claude settings file it changes only hook entries that run
  `.atw/core/atw.py`.
- **Cleans up surgically** when a re-run moves or skips a shared-file item: it removes only our
  block or hook entries from the old file. It deletes the file only if we created it and it is
  now empty.
- **Backs up** every file it changes to `.atw/backup/<stamp>/`, then writes atomically.
- **Removes** owned files that are no longer installed, for example after a skill rename, but
  only if they are unedited.

## Rendering

Skills and adapter blocks use `{{tokens}}`: `atw`, `python`, `version`, `kinds`, `plan_dir`,
`skill_dir`, `skill.<name>`, `spike_dir`. Apply renders each skill once per host skill folder, so
`{{skill_dir}}` points at the right place. The setup skill has no tokens, because `install.py`
copies it before any config exists. `tools/check_repo.py` enforces this.

## Claude Code hook launcher

The hooks use exec form:
- `command` is the Python executable.
- `args` is a short `-c` launcher, followed by `.atw/core/atw.py hook <name>`.

The launcher resolves the script through `CLAUDE_PROJECT_DIR`, and it does nothing if the file
is missing. So a clone without `.atw/core/` never blocks a session. Extra launcher words (such as
`py -3`) go in front of `args`.

## Guard (PreToolUse)

For the Bash and PowerShell tools, the guard parses the command line first (`shell.py`, ADR 0017).
It is not a full shell parser. It does these steps:

1. It removes heredoc bodies (`<<'EOF' ... EOF`) and PowerShell here-string bodies (`@' ... '@`).
2. It splits the line into commands at `;`, `&`, `&&`, `||`, `|`, newlines, `( )` and `{ }`
   groups, when they are outside quotes. A command substitution (`$( )`, backticks) is a command
   of its own, also inside double quotes. The script of `bash -c "..."` or `pwsh -Command "..."`
   is parsed again. A `#` comment is removed.
3. In each command, it skips `VAR=x` assignments and wrappers (`sudo`, `env`, `time`, `nohup`,
   `npx`, `xargs`, `command`, `exec`, the PowerShell `&`). The command word becomes a lowercase
   basename without `.exe`, so `/usr/bin/git`, `git.exe` and `"C:\Program Files\Git\cmd\git.exe"`
   are all `git`.
4. For git, it skips the global options (`-C <dir>`, `-c k=v`, `--git-dir=...`, `--no-pager`)
   to find the subcommand.

Then every rule is checked on every command. A deny wins over an ask, so approving one prompt
never runs a denied part of a chain (`git push origin x && git push --force` is denied).

| Config | Rule |
|---|---|
| `guards.git` | Named git rules, `{"deny": [...], "ask": [...]}`: `reset-hard`, `push-force` (`--force`, `-f` in any short-option cluster, `--force-with-lease`, `--force-if-includes`, a `+refspec`), `push-delete` (`--delete`, `-d`, `:branch`), `push`, `rebase`, `clean-force`, `commit-amend`, `commit`, `filter-branch`, `update-ref-delete`, `reflog-expire`. Default: deny `reset-hard`, `push-force`, `rebase`, `clean-force`, `commit-amend`; ask `push` |
| `guards.git_add_data` | `git add` of data, binary or very large files asks (images, CSV/Parquet/pickles, databases, archives, logs; JSON over 50 KB; any file over 1 MB). Manifests and lock files are exempt at any size. `git add -A`, `.`, `-u` or a folder checks the changed files. Default `true` |
| `guards.test_delete` | `rm`, `del`, `erase`, `rmdir`, `unlink`, `Remove-Item`, `ri` or `git rm` (not `--cached`) on a test file asks: a file under `test_paths` or matched by the test globs, or a folder that holds one. Default `true` |
| `guards.deny`, `guards.ask` | Custom regexes, searched in the text of each parsed command. Heredoc bodies are removed, but quoted text inside a command still matches: `\bnpm\s+publish\b` also matches `echo "npm publish"`. Anchor a pattern with `^` to match the command start only. Use `guards.git` for git. Default `[]` |

`guards.git.ask` from the project config replaces the default list. To deny `push`, write
`"ask": []` as well; a rule in both lists is denied anyway. Known gaps: git aliases
(`git ci`), `eval`, and scripts that the command runs are not looked into.

`atw doctor` warns when `guards.deny` or `guards.ask` still holds the git regexes from before
0.3.0 (or the usual `\bgit\s+commit\b` and `\bgit\s+push\b` deny patterns), and it prints the
`guards.git` block that replaces them. It never changes the config.

The guard also binds a session to its ticket. Only a parsed `atw` call counts (`atw ...` or
`python .../atw.py ...`): `start X`, or a subcommand that changes a run with `--ticket X` or
`--run X/RUN_ID`. `echo "atw start X"` does not bind.
