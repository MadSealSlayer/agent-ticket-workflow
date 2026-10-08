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
| `state.py` | Runs: one folder per (ticket, run id) with `run.json` and a log. It also handles selection by `--run`, `--ticket` or `$ATW_RUN`, and the baseline (HEAD sha plus files untracked at start) |
| `runner.py` | Renders command templates (`{files}`, `{ids}`, `{id_files}`, `{junit}`, `{python}`) and runs them |
| `junit.py` | Parses JUnit XML. Behavioral red: refuses errors, skips, passes and missing-symbol failures |
| `gates.py` | Every gate. Live gates re-run every time. Recorded gates check their stored hash |
| `deps.py` | New third-party imports against pip / npm declarations |
| `packets.py` | Review and simplify packets: the diff, requirements and settled decisions, hashed |
| `hooks.py` | Claude Code hooks: Stop (gate check, with a release after 3 identical blocks), guard, plan-mode stamp |
| `detect.py` | Read-only discovery for setup: stack, CI, hooks, skills, instruction files, collisions |
| `install.py` | Applies an approved install plan: ownership checks, render, merge, backup, manifest |
| `doctor.py` | Installation health and `hygiene` |
| `presets/` | Stack presets: detection rules and command templates |

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
