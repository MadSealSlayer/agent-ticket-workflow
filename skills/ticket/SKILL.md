---
name: {{skill.ticket}}
description: Run a ticket through the gated agent workflow. Classify its kind with the user, plan and get approval, prove red on behavior, pass fresh gates, get a clean-room review, and close with evidence. Invoke as /{{skill.ticket}} <ticket-id | status | abort>.
argument-hint: <ticket-id | status | abort>
disable-model-invocation: true
---

# Ticket workflow

You run one ticket through a fixed sequence. A script (`{{atw}}`) checks every fact it can check
(plan approved, tests red then green, lint, dependencies, review freshness). You decide only what
is straightforward. **Everything that matters to the user, you ask.**

If the argument is `status` or `abort`, run `{{atw}} status` (or `{{atw}} abort --why "<reason>"`)
for the open run and stop.

## Rules that apply on every step

- **The approved plan is the boundary.** Implement the smallest complete change that satisfies
  it. No adjacent refactors, cleanups or "while I'm here" improvements. If work outside the plan
  turns up, leave it alone and report it as a follow-up. If the plan stops fitting, stop and
  re-plan with the user. Do not quietly deviate.
- **Ask; do not guess.** Never pick a plausible default for a decision that is hard to reverse
  or that the user would want to own: data model, ownership of a value, error semantics,
  backward compatibility, environment, time window, what counts as done. On Claude Code, use
  `AskUserQuestion`. Elsewhere, ask in chat and wait.
- **Ordinary ambiguity** (naming inside the change, the order of independent edits) you resolve
  with the smallest reversible choice. Report it at the end.
- **A refusal from `{{atw}}` is the next instruction.** It names what is missing. Never work
  around a gate: do not fake evidence, weaken a test, or re-kind a ticket just to escape a gate.
- **Destructive or hard-to-undo actions** (delete, reset, overwrite, broad moves, anything on
  shared infrastructure) need the user's explicit yes first, with the exact targets named.
- **Commits:** only when the user asks, local only, and only if the project's own rules allow
  it. Never push. Never rewrite history.

## Step 1 - Read the ticket

Tickets are markdown files found by the patterns in `.atw/atw.config.json` (`tickets.globs`;
`{id}` is the ticket id). Read the ticket in full. If no file exists, ask the user to save the
ticket text there, or to give you the path (`--ticket-file`).

## Step 2 - Classify the kind, and confirm it with the user

Propose one kind and quote the phrases that led you there. Only the kinds enabled for this
project can be used: {{kinds}}.

| Kind | Signals | Deliverable (folder from `placement` in the config) |
|---|---|---|
| `investigation` | "check the logs", "what happened", "what is the state of", "no fix yet" | Findings file in `placement.investigation`, ticket id in the file name, with sources |
| `comms` | "draft an email/message", "explain this to ...", "talk track" | Draft in `placement.comms`, ticket id in the file name |
| `docs` | "write documentation", "handover doc" | Committed doc under `placement.docs` |
| `tooling` | a helper script, nothing in protected source | Script under `placement.tooling` |
| `code` | a functional change to protected source (`protected_paths`) | A working change, proven red then green, reviewed |
| `spike` | an open-ended exploration session (only if enabled; experimental) | Hand off to the `{{skill.spike}}` skill (no gates are armed) |

**Do not decide this alone.** Unless the ticket is unambiguous, confirm the kind with the user.
Never default to `code` when it is unclear. Prefer `investigation`, or ask. A ticket can start
as `investigation` and be re-kinded to `code` once the findings show what to fix.

For `code`, also classify the **scope**, and confirm it:

- `coordinated` if it changes a public API or event contract, a schema or data model, a
  migration, cross-service behavior, infrastructure, or an architectural decision, or if it will
  span sessions. A coordinated change always gets a full plan.
- `isolated` for everything else.

## Step 3 - Load project context

If `.atw/atw.config.json` has `context.enabled: true`, invoke the
`{{skill.project-context-loading}}` skill now. Otherwise read the project's instruction files
(CLAUDE.md / AGENTS.md) and the code that the ticket touches. Load what the ticket needs, not
everything.

## Step 4 - Start the run

```
{{atw}} start <TICKET> --kind <kind> [--scope isolated|coordinated]
```

Keep the printed run reference (`TICKET/RUN_ID`). Pass `--run <ref>` to later commands when
more than one run is open (parallel sessions). On Claude Code the Stop hook is now armed: the
turn cannot end while a required gate is unmet. On other hosts, **run `{{atw}} status` before
you end any turn** and keep working while something is unmet. Stop early only to ask the user
a question that is genuinely theirs.

---

## Non-code path (investigation, comms, docs, tooling)

1. Do the work. For `investigation`, invoke the `{{skill.ticket-investigation}}` skill first.
2. Write the deliverable to its kind's folder (Step 2 table). `investigation` and `comms` files
   must have the ticket id in the file name. Findings need a `## Sources` section of `- [id] ...`
   entries, and every claim is tagged `measured` or `inferred` with an `[id]`, for example:
   `Errors rose to 6 of 343 requests (measured, [S1]).`
3. Run the gates: `{{atw}} gate nocode placement` (add `provenance` for investigation and docs,
   and `lint deps` for tooling when configured).
   `nocode` fails if the run touched protected source. If you really need that change, the
   ticket is not what you classified it as. Re-kind it honestly:
   `{{atw}} kind code --scope <scope> --why "<what changed your mind>"`, then follow the code path.
   Never revert or hide a change you mean to keep just to pass `nocode`.
4. **Investigation and comms: present, then stop.** Put the substance in your chat message: what
   you checked, what you found, what is still unknown, and what you have not looked at. Hand the
   decision back: done, dig deeper, or look elsewhere. Do not close in the same turn.
5. Iterate on the user's reply, updating the same file. Close only when the user says it is
   complete. An empty diff is the normal, successful outcome here.

Docs and tooling go straight to **Close** once their gates pass.

---

## Code path

### 1. Plan and get approval

**Claude Code:** your very next tool call after `start` is `EnterPlanMode` (the only exception
is `AskUserQuestion` for a question that blocks planning itself). Explore, ask the open
questions, design the change, then `ExitPlanMode` so the user approves it. Then:

```
{{atw}} plan --files "path/a,tests/test_a,path/b"
```

`plan` refuses unless a real `ExitPlanMode` happened after `start`. A genuine one-liner where a
plan round-trip is theater (isolated scope only): say so, then
`{{atw}} plan --files "..." --no-plan-mode --why "<reason>"`. The skip is recorded.

**Codex and other hosts:** use your host's planning mode. Save the plan to
`{{plan_dir}}/<TICKET>.md`, show it, and ask for an explicit yes. Then:

```
{{atw}} plan --files "..." --plan-file {{plan_dir}}/<TICKET>.md --approval "<the user's exact words>"
```

The plan is copied and hashed. Editing it afterwards makes the plan gate stale.

Before you edit protected source or tests, the plan gate must pass (Claude Code asks you to
confirm such edits until then).

**Record settled questions** as the user answers them. This is what stops the reviewer from
re-raising them:

```
{{atw}} decide --item "<decision, one line>" --verdict settled-question --why "<the user's reasoning>"
```

Use `accepted-tradeoff` for a deliberate trade-off. Record *that* something was decided and why,
never the plan or how the code was written. The review stays clean-room.

If the plan splits into independent pieces (disjoint files, no ordering), you may dispatch one
sub-agent per piece in parallel. Give each a narrow brief: its files, its proof ids, and the
rules above. Check what each returns against the plan.

### 2. Prove red on behavior

The ticket's spec is its **proof set**: one test per acceptance criterion in the approved plan.
Write those tests first. For code that does not exist yet, add a stub that returns a wrong
value, so each test fails on its assertion and not on a missing name. Then:

```
{{atw}} red --test "<test id>" --test "<test id>"
```

`red` runs exactly those ids. It refuses an id that passes, errors, is skipped, is not found,
or fails on an import error, a missing name or a "not implemented" stub. Calls add to the proof
set. For a change no test can fail on (pure refactor, text-only edit):
`{{atw}} red --none --why "<reason>"`.

### 3. Implement, then run the gates

Implement inside the plan boundary. Then run the gates together, as often as you need. They
always run fresh:

```
{{atw}} gate tests lint deps
```

`tests` runs the tests related to the diff and re-proves every proof id green. `lint` checks
only lines you changed. `deps` checks that every new import is declared in its manifest. A gate
that is not configured for this project passes with a note.

Before you review, check blast radius: every caller and consumer of what you changed, outside
the diff.

### 4. Simplify (only if the config has `simplify` set to `gate` or `advisory`)

```
{{atw}} simplify-packet
```

Dispatch a **fresh** agent (the same way as the review below) to write the report the packet
names. Then mark every recommendation `- [x] ... applied` or `- [x] ... declined: <reason>`,
re-run the gates, and run `{{atw}} accept-simplify --report <path>`.

### 5. Clean-room review

```
{{atw}} review-packet
```

The packet holds only the diff, the ticket text and the settled decisions. Hand **only the
packet path** to a reviewer with no memory of this session:

- **Claude Code:** dispatch an `Agent` (general-purpose, model `opus` unless the config says
  otherwise) with this prompt:
  "You are a clean-room reviewer. Read and follow `{{skill_dir}}/{{skill.ticket-audit}}/SKILL.md`
  for the review packet at `<packet path>`. Use only the packet, the patch and the repository."
- **Codex:** spawn a sub-agent with no forked conversation (`fork_turns="none"`) and the same
  prompt.
- **Any host without sub-agents:** ask the user to open a new session and paste that prompt.

Then: `{{atw}} accept-review --report <report path>`.

Open Critical or Warning items fail the gate. Fix them, re-run the gates, and make a new packet.
Round 2+ packets are delta reviews. Any edit after an accepted review makes it stale, by diff
hash. A Warning the user explicitly accepts can pass:
`--override "<item>" --user-approved "<their words>"`. A Critical can never be overridden.
Pre-existing findings are not this ticket's to fix. Record them with `--verdict pre-existing`.

### 6. Update project context

If context is enabled, invoke `{{skill.project-context-updating}}`. Most tickets need no update.
Note the result for close.

---

## Close

```
{{atw}} close --note "<one line>" [--context updated|no-op --why "<reason>"]
```

`close` re-checks every required gate, refuses if anything is unmet, then appends to the run
log. The ticket file is never modified. Finish with a short report: what changed, the
evidence (gates), assumptions you made, follow-ups, and anything you did not do.

To abandon a run: `{{atw}} abort --why "<reason>"`. At any time: `{{atw}} status`.
