---
name: ticket-setup
description: Set up (or upgrade) the agent ticket workflow in this project. Discovers what the project already has, reports collisions, interviews the user with a question sheet, shows the exact install plan, and applies it only after approval. Invoke as /ticket-setup.
disable-model-invocation: true
---

# Ticket workflow setup

You are installing a workflow into someone's project. Their existing hooks, skills, instruction
files and habits come first. **You decide only what is straightforward; the user decides
everything that matters to them.** Nothing is written before the user approves the plan, and the
apply step refuses to overwrite anything that is not ours.

Paths below assume the staged package at `.atw/staging/` (made by `install.py`). Use the Python
command that works on this machine (`python`, `python3` or `py`) wherever you see `python`.

Read these references when the step says so:
- `references/discovery.md` - reading the detection report, and what to check by hand
- `references/collisions.md` - the options for each kind of collision
- `references/decision-policy.md` - what you may decide alone
- `references/interview.md` - the question catalogue

## Step 0 - Preflight

1. `.atw/staging/PAYLOAD.json` must exist. If not, tell the user to run
   `python <package>/install.py <this project>` first, and stop.
2. Check `python --version` (3.10 or newer) and that this is a git repository.
3. If the working tree has uncommitted changes, tell the user. Recommend committing or stashing
   first so the setup diff is easy to review. Ask whether to continue.
4. `install.py` copied this setup skill and `.atw/staging/` into the project. Until `apply`
   runs, they show as untracked in `git status`. That is expected. In local mode, `apply` adds
   them to `.git/info/exclude`.

## Step 1 - Discover (read-only)

```
python .atw/staging/core/atw.py detect
python .atw/staging/core/atw.py detect --json > .atw/staging/detect.json
```

The report's `mode` says `fresh`, `upgrade` or `reinstall`. For `upgrade`/`reinstall`, read
`.atw/install-manifest.json` and `.atw/atw.config.json` first: reuse every earlier answer, and
ask only about what is new or changed (see `references/interview.md`, "Upgrades").

Then follow `references/discovery.md`. Script detection is a starting point, not the truth: read
the CI workflows, the instruction files, and every existing skill or hook the report lists
as similar or colliding. Understand what they do before you propose anything.

## Step 2 - Show what you found

Give the user a short discovery summary: stack, how tests run today (with evidence), existing
agent setup, similar workflows, and the **collision list**, one line each with its options (see
`references/collisions.md`). Do not resolve collisions yet; they go into the question sheet.

## Step 3 - Build the question sheet

Write `.atw/setup-questions.md` from `.atw/staging/templates/setup-questions.md`:

- **Decided for you:** only items that pass `references/decision-policy.md`, each with its
  evidence and how to change it. The user can override any of them.
- **Questions for you:** everything else, from `references/interview.md`, plus one question per
  collision. Give each question its options, your recommendation with the reason, and the
  evidence. Skip questions that do not apply (for example, no lint question for a project with
  no linter).

**Ask the git question first, on its own:** local only, or committed to git for the team
(`git_mode`, `references/interview.md` section 0). It is always the user's answer, and `apply`
refuses a plan without it. It sets the defaults for every shared file. After that, the user can
still point any single item somewhere else or skip it.

Then ask the rest. On Claude Code use `AskUserQuestion`, at most 4 per call, most important
first: hosts and kinds, protected paths, test commands, collisions. Elsewhere, ask in chat in
small groups. Record every answer in the sheet as you go. If an answer creates a new question,
ask it. Never fill an unanswered question with your recommendation; ask again or leave the
setup unfinished.

## Step 4 - Draft the plan and show it

1. Write the config from the answers, starting from
   `.atw/staging/templates/atw.config.example.json`, with the matched presets in
   `.atw/staging/core/presets/` as the source for commands.
   The config must match every answer. If a follow-up detail is still open (for example, where an
   enabled kind puts its output), ask it. Do not drop or change an answered item to work around
   it.
2. Write `.atw/staging/install-plan.json` (shape: `.atw/staging/templates/install-plan.example.json`).
   Put every decision in `decisions` with `by: "user"` or `by: "agent"`.
3. Dry-run it:
   ```
   python .atw/staging/core/atw.py apply --plan .atw/staging/install-plan.json --dry-run
   ```
   If it refuses (invalid config, or a file that is not ours), fix the plan with the user. Never
   work around a refusal.
4. Prove the commands work before relying on them. Run the configured proof command on one
   existing test id and check that it writes JUnit XML. Run the lint command on one file. A
   command that cannot run here becomes a question for the user, not a guess.
5. Show the user the summary: what will be written, created or merged (from the dry run), the
   config in short form, and what will **not** be touched. Ask for an explicit yes.

## Step 5 - Apply

```
python .atw/staging/core/atw.py apply --plan .atw/staging/install-plan.json
```

It writes nothing if anything collides, backs up every changed file to `.atw/backup/`, and
records everything in `.atw/install-manifest.json`.

## Step 6 - Verify

```
python .atw/core/atw.py doctor
```

Fix every FAIL with the user. Explain every WARN in one line. Then:

- Claude Code: tell the user to **restart the session** so the new hooks and skills load.
- Commit mode: tell the user which files to review and commit. **Do not commit** unless they
  ask.
- Local mode: run `git status` and confirm that nothing we installed shows up. `doctor` checks
  this too.
- Suggest a first ticket: a small, real one, run with `/ticket <id>` (Codex: `$ticket`), using
  the skill name chosen in the plan if it was namespaced.

## Rules

- Never edit a file the user owns outside our marked blocks (`<!-- atw:begin -->` ...
  `<!-- atw:end -->`) and our own hook entries. `apply` enforces this. Do not do it by hand
  either.
- Never delete or move the user's skills, hooks or instructions, even when ours replaces their
  purpose. If they want theirs retired, that is a separate step they do themselves.
- Keep the question sheet (`.atw/setup-questions.md`). It records why the project is configured
  this way, for the next person who upgrades it. In commit mode it is committed with the rest.
- Keep it surgical (`references/decision-policy.md`). A brownfield project may want fewer
  touchpoints than the defaults. That is a valid setup.
