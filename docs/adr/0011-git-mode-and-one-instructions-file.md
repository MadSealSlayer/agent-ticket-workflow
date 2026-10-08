# 0011. Git mode, one instructions file, surgical touchpoints

- Status: accepted
- Date: 2026-10-04

## Context

The workflow goes into brownfield projects. Some developers want to try it alone, without
changing anything their team sees. Others set it up for the whole team. Earlier versions wrote
the same instructions to both `CLAUDE.md` and `AGENTS.md`, and always edited `.gitignore` and
`.claude/settings.json`.

Claude Code now reads `AGENTS.md` (version 2.1.277 and newer), but only when there is no
`CLAUDE.md` or `CLAUDE.local.md`.

## Decision

- In a git repository, the install plan must have `git_mode`: `local` or `commit`. The setup
  asks it first, and it is always the user's answer. `apply` refuses a plan without it.
- `git_mode` only sets defaults for four touchpoints:
  - `instructions`
  - `claude_bridge`
  - `claude_settings`
  - `ignore`

  Each one can point to another file, or be `skip`.
- Local mode does not edit tracked files by default. It uses `.git/info/exclude` for everything
  it installs, `.claude/settings.local.json` for the hooks, and `CLAUDE.local.md` for the bridge.
- Our instructions live in one host-neutral `AGENTS.md` block. When a `CLAUDE.md` exists, a
  marked block with only `@AGENTS.md` bridges it for Claude Code.
- Re-running with other choices removes only our parts from the files no longer used.
- `doctor` warns, and does not fail, on deviations the user chose.

## Consequences

- A developer can try the workflow without a trace in git, and commit it later by re-running
  the setup.
- There is one text to maintain, not two.
- There are more combinations to test. `tests/unit/test_install.py` covers both modes, the
  brownfield defaults, a surgical override and switching between modes.
