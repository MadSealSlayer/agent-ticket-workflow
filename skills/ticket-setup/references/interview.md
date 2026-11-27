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

**A4. Where do tickets made from the conversation go?** → `tickets.new` (`path`, `id_format`,
`range_size`). `atw new-ticket` writes a ticket that the agent drafted from the conversation,
after the user approved it, with the next free number. `path` and `id_format` are templates:
`{n}` is the number, `{id}` the formatted id, `{lo}`/`{hi}` the range of `range_size` numbers
that holds it. Propose a path that matches the existing ticket files, for example
`tickets/ticket-{id}.md` (default), `tickets/{lo}-{hi}/ticket-{id}.md` for range folders, or
`local_tickets/{lo:03d}-{hi:03d}/ticket-{id}.md`. The path must be found by `tickets.globs`;
check it with `atw new-ticket --title x --body-file <a valid body> --dry-run` after apply.

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
For Angular with Karma, use the `karma` preset: it ships its own wrapper in
`.atw/core/presets/karma/` and adds no dependency. Tell the user its two limits (from the
preset's `notes`), and show the mapping: before apply, run
`node .atw/staging/core/presets/karma/karma-run.cjs --dry-run <one spec file>`. If another runner
needs a small wrapper script (for example, no JUnit reporter or no single-test filter), put it
in `.atw/local/` in local mode. In commit mode, put it in the
project's own scripts folder. Never add dependencies to tracked manifests without asking.

**C2. Which tests run for the `tests` gate?** → `commands.tests.scope`:
`stem-match` (changed tests plus tests that mention a changed source file; recommended for
large suites), `changed-tests` (only changed test files), `all` (the whole suite; fine when it
is fast). The proof set always runs in addition.

**C3. Lint.** → `commands.lint` (or none). Only findings on changed lines fail. Ask whether lint
should be a gate at all.
For TypeScript projects without a linter gate, the `tsc` preset runs `tsc --noEmit` as the lint
gate (exit code; every type error fails, also on unchanged lines). Confirm first that the project
typechecks cleanly today, and which tsconfig covers the specs.

**C4. Dependency declarations.** → `commands.deps` (`python-imports`, `node-imports`, a custom
command, or none). For shared code packaged into several deployables, ask which manifests must
also declare its imports → `deps.python_extra_requirements`.

**C5. Simplify pass.** → `simplify`: `off`, `advisory` (packet available, not required) or
`gate` (required before review). Recommend `off` or `advisory` to start.

**C6. Review route** (only if Claude Code is a host). → `audit.route`, `audit.t3`.
`agent` (default): a fresh Claude sub-agent reviews. `t3-delegate`: when the session runs inside
T3 Code, the review and simplify rounds go to a T3 child task on another model
(`audit.t3.provider`, `audit.t3.model`, `audit.t3.reasoning_effort`, default `codex`,
`gpt-6.2-sol`, `medium`). Outside T3, or when the child cannot run, it falls back to `agent`.
Recommend `agent`, unless the user works in T3 Code and has access to the other provider.

**C7. Realistic verification.** → `verify.how`, `verify.when`, `verify.ignore`. Unit tests and
the static review never run the app. For big code changes (coordinated, or at least
`verify.min_planned_files` planned files or `verify.min_proof_ids` proof tests; both 8 by
default) the `verify` gate has a fresh agent run the change for real, in parallel with the
review. Show what discovery found: the `workflow:realistic verification` hit (a skill or
instruction text that starts a dev server, drives a browser, runs e2e or integration tests),
`playwright.config.*`, `cypress.config.*`, an `e2e/` folder, `e2e` or `test:e2e` scripts.
- If the project has such a check, **it goes into `verify.how`**: one or two lines that say how
  to run it, for example "follow `.claude/skills/<name>/SKILL.md`" or "`npm run e2e`". Never let
  the review replace it.
- If it has none, ask for a short manual checklist, or leave `how` empty: big tickets then need
  the user to accept "not run" items at close.
- `verify.ignore`: paths the check writes into the project that git does not ignore (screenshots,
  `test-results/`, logs), so they do not count as the change.
- `when`: `big` (default, recommended), `always`, or `off`. `off` is the user's explicit choice,
  with their reason in the decisions.

## D. Extras

**D1. Project-context index.** → `context.enabled`, `context.index`, plan `context_index`.
If an index exists, propose using it. Otherwise ask whether to create one from the template.
When enabled, closing a code ticket needs `--context updated|no-op`.

**D2. Guard rules.** → `guards.git`, `guards.git_add_data`, `guards.test_delete`,
`guards.deny`, `guards.ask`, `guards.protect_before_plan`, `guards.test_markers`. The guard
parses each command first, so text that only mentions git (`echo "git push"`, a grep pattern, a
heredoc body) never matches. Show the `guards.git` defaults: deny `reset-hard`, `push-force`,
`rebase`, `clean-force`, `commit-amend`; ask `push`. Other rules: `commit`, `push-delete`,
`filter-branch`, `update-ref-delete`, `reflog-expire`. Ask about the team's commit policy. If
agents must never commit or push, propose `"deny": [the five defaults, "commit", "push"]` with
`"ask": []` (a project `ask` list replaces the default one). Compare with the existing permission
rules in `.claude/settings.json`, and with any git hook that already blocks commits. Ask whether
to keep, edit or turn off. `git_add_data` (default on) asks before `git add` stages data,
binary or very large files; `test_delete` (default on) asks before a shell command deletes a
test file. Use `guards.deny`/`guards.ask` (regexes, default `[]`) only for project-specific
commands such as `npm publish`; they match the text of each command, quoted text included. If
the project's config already has the old git regexes in `guards.deny`/`guards.ask`, propose the
`guards.git` block that `atw doctor` prints instead. `test_markers` (Claude Code only): an edit to a test file that adds a
skip or focus marker (`xit(`, `fit(`, `it.skip(`, `describe.only(`, `@pytest.mark.skip`,
`pytest.skip(`, ...) asks the user first. Recommend the defaults; add the project's own markers
if it uses another runner; `[]` turns it off.

**D3. STE writing check (advisory).** → install the `ste-writing` skill or not; `ste.enabled`.

**D4. Investigation tools** (only if investigation is enabled). → `investigation.tools`,
`investigation.notes`. Confirm the helpers you found and where credentials come from.

**D5. Jira** (only if the team tracks tickets in Jira). → `jira.*`, plan `skills.jira`.
Jira is reached through the host's Atlassian MCP connector; the core never calls Jira and needs
no token. Ask:
- Use Jira? If no, leave `jira.enabled` false and `skills.jira` null.
- The site host (`example.atlassian.net`) and the projects in scope, each with a one-line use
  (`jira.projects`, `jira.default_project`).
- Start of work: move a To Do issue to a status automatically when work starts? If yes, which
  status (`jira.start_transition`, e.g. `In Progress`) and which other status names already
  count as in progress (`jira.in_progress_aliases`). If no, leave it `null`: the agent asks.
- Where imported tickets go (`jira.import_dir`). It must be covered by `tickets.globs`.

When enabled, install the `jira` skill. Check that the connector is connected in the user's host;
if not, tell them how to add it, and continue (Jira failures never block the workflow).

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
