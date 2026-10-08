# Question catalogue

Ask only what applies. For each question give: the options, your recommendation and why, and the
evidence. Ask most important first. Config keys are in `.atw/atw.config.json`.

## 0. Local only, or committed? (always first, always the user's answer)

**Q0. Should this install stay on your machine only, or be committed to git for the team?**
→ plan `git_mode`. Ask it in a git repository before any other question, even when the answer
looks obvious. `atw apply` refuses a plan without it. Explain both options in plain words:

- `local`: only on this machine. Nothing we add shows up in `git status`. Teammates do not get
  the workflow. Everything we install is listed in `.git/info/exclude` (it is like `.gitignore`,
  but it is never committed). The Claude hooks go to `.claude/settings.local.json`. Tracked
  files (for example a committed `AGENTS.md` or `CLAUDE.md`) are not edited.
- `commit`: shared through the repository. The user reviews and commits the files. You do not
  commit, unless they ask.

Evidence to show: `git.remotes`, `git.dirty_files`, and which instruction and settings files
are already tracked. In a linked worktree (`git rev-parse --git-dir` differs from
`--git-common-dir`), say that `.git/info/exclude` is shared with the main checkout and every
other worktree, so local mode hides the same paths there too. Do not recommend one. If the user is not sure, suggest `local` to try it
first. Switching later is a re-run of the setup with the other answer, and it removes what is
no longer used.

`git_mode` only sets **defaults**. Each item in section E can be changed one by one. Tell the
user this after they answer, and ask about an item only when the default does not fit (see E).

## A. Scope

**A1. Which agents does the team use here?** (multi-select: Claude Code, Codex, other) → plan
`hosts`, `skill_dirs` (`.claude/skills` for Claude Code; `.agents/skills` for Codex and others).
Evidence: `harness.present`. Do not assume everyone uses what one developer uses.

**A2. Which ticket kinds should be enabled?** (multi-select: code, investigation, comms, docs,
tooling, and spike marked *experimental*) → `kinds.enabled`, plan `spike`.
Recommend the five stable kinds. Spike: say plainly that it is experimental, was used once, and
needed heavy human steering. Recommend it only for a user who wants to try it.

**A3. Where do tickets live?** → `tickets.globs` (patterns with `{id}`). Evidence: `ticket_dirs`
and their example file names. If none exist, propose `tickets/{id}.md`.

## B. What counts as code

**B1. Protected source paths.** → `protected_paths`. Non-code tickets fail the `nocode` gate if
they touch these. Code tickets are asked to plan before editing them. Propose the source folders
you confirmed in discovery. Ask about generated code, migrations and infrastructure folders
one by one.

**B2. Test paths.** → `test_paths`. Same edit protection, and where related tests are searched.

**B3. Deliverable folders.** → `placement.investigation`, `placement.comms`, `placement.docs`,
`placement.tooling`. Also ask: **are investigation and comms notes committed, or kept local?**
If local, list those folders in plan `ignore_extra`. They go into our ignore block (state this in
the plan).

## C. Gates

**C1. Proof and test commands.** → `commands.proof`, `commands.tests`. Show the matched preset
and the evidence (CI step, interpreter). Explain that the proof command runs exact test ids and
must write JUnit XML. If no preset fits, ask the user for a command that does, and test it.
If it needs a small wrapper script (for example, a test runner with no JUnit reporter or no
single-test filter), put it in `.atw/local/` in local mode. In commit mode, put it in the
project's own scripts folder. Never add dependencies to tracked manifests without asking.

**C2. Which tests run for the `tests` gate?** → `commands.tests.scope`:
`stem-match` (changed tests plus tests that mention a changed source file; recommended for
large suites), `changed-tests` (only changed test files), `all` (the whole suite; fine when it
is fast). The proof set always runs in addition.

**C3. Lint.** → `commands.lint` (or none). Only findings on changed lines fail. Ask whether lint
should be a gate at all.

**C4. Dependency declarations.** → `commands.deps` (`python-imports`, `node-imports`, a custom
command, or none). For shared code packaged into several deployables, ask which manifests must
also declare its imports → `deps.python_extra_requirements`.

**C5. Simplify pass.** → `simplify`: `off`, `advisory` (packet available, not required) or
`gate` (required before review). Recommend `off` or `advisory` to start.

## D. Extras

**D1. Project-context index.** → `context.enabled`, `context.index`, plan `context_index`.
If an index exists, propose using it. Otherwise ask whether to create one from the template.
When enabled, closing a code ticket needs `--context updated|no-op`.

**D2. Guard rules.** → `guards.deny`, `guards.ask`, `guards.protect_before_plan`. Show the
defaults (deny history rewrites and force pushes; ask before any push). Compare them with
existing permission rules in `.claude/settings.json`. Ask whether to keep, edit or turn off.

**D3. STE writing check (advisory).** → install the `ste-writing` skill or not; `ste.enabled`.

**D4. Investigation tools** (only if investigation is enabled). → `investigation.tools`,
`investigation.notes`. Confirm the helpers you found and where credentials come from.

## E. Instruction files and collisions

Each item below has a default from `git_mode`. Show the user the resolved defaults (the dry
run prints them on its first lines), and ask only about the ones that need a choice. These are
the usual cases: a tracked file in local mode, an existing file the user does not want touched,
or a team that keeps agent rules in another file. Any item can be `skip`.

**E1. Where do our instructions go?** → plan `instructions`: a file, or `skip`. The default is
`AGENTS.md` (Claude Code and Codex both read it). In local mode the default is `skip` when
`AGENTS.md` is tracked. In that case, offer a file that git does not see, for example
`.atw/AGENTS.md`. Claude Code then reads it through the bridge (E2). Codex does not read it, but
the skills still carry the workflow. Show the block text
(`.atw/staging/adapters/agents-md/agents-md-block.md`).

**E2. Claude bridge.** → plan `claude_bridge`: `auto`, a file, or `skip`. Claude Code reads
`AGENTS.md` by itself (version 2.1.277 or newer) **only when no `CLAUDE.md` exists**. When one
exists, the bridge adds a marked block with one line, `@AGENTS.md` (an import), and nothing
else. `auto` puts it in `CLAUDE.md` in commit mode, and in `CLAUDE.local.md` in local mode, so
a tracked `CLAUDE.md` is never edited. With no `CLAUDE.md`, `auto` adds nothing.

**E3. Claude Code hooks.** → plan `claude_settings`: `merge` (`.claude/settings.json`, shared),
`local` (`.claude/settings.local.json`, this machine), or `skip`. The default comes from
`git_mode`. Explain what each hook does:
- Stop: blocks the end of a turn while a gate is unmet. It releases after 3 identical blocks.
- PreToolUse: guard rules and plan-before-edit.
- PostToolUse on ExitPlanMode: records that plan mode ran.

Skipping the hooks means the Stop gate is not enforced.

**E4. Where do the ignore rules go?** → plan `ignore`: `gitignore`, `exclude`
(`.git/info/exclude`, never committed) or `skip`. Run state (`.atw/runs/`, `.atw/tmp/`) must
stay out of git in every mode. Recommend `skip` only if the user already ignores `.atw/`
another way. In local mode, the block also lists every file we install.

**E5. One question per collision** (see `collisions.md`).

## Upgrades

On `upgrade` or `reinstall`: load the existing config and manifest. Ask only:
- questions whose config key is new in this version, or whose default changed;
- new collisions (compare with the manifest's recorded decisions);
- what to do with installed files the user edited (the dry run lists them as conflicts): keep
  their edit (skip that skill) or overwrite it (`overwrite_modified`).

Re-use every other recorded answer, and list them under "Decided for you, from the last setup".
`git_mode` is recorded too. Re-use it, but name it in the summary ("still local only"), so a
user who now wants to share it with the team can say so. An install from before `git_mode`
existed has no recorded answer, so ask Q0.
