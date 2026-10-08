---
name: {{skill.spike}}
description: "EXPERIMENTAL. Use when you start, continue or end a session on a multi-session spike workspace under {{spike_dir}}/<slug>/. Reads STATE.md and the current phase brief, proposes the next parallel batch of ready tasks (respecting resource exclusivity and read-only resources), and checkpoints facts, task status and STATE.md only after the user approves. Modes: start, next, verify, checkpoint."
---

# Spike session (experimental)

> **Experimental.** This was used once and needed a lot of human steering. It is not battle
> tested, and a rebuild is recommended. Nothing checks these rules mechanically: you are the
> enforcement. Tell the user this once, at the start of the first session on a spike.

A measurement spike is a phased investigation over many sessions, often with several agents per
session. It uses real scripts and real artifacts. Without a structured workspace, two things go
wrong:
- Every session re-reads a long design doc to find out what to do next.
- Numbers drift between what an artifact measured and what a later session remembers.

The workspace carries the state. This skill is the discipline for reading it, advancing it and
writing it back.

## Workspace

`{{spike_dir}}/<slug>/`:

| File | What it holds |
|---|---|
| `STATE.md` | Max ~150 lines. The decision the spike must produce, current phase, next batch, resources and access, guardrails, decisions taken (with fact ids and what would reverse them), open questions for the human |
| `TASKS.md` | One row per task: `id, title, phase, status (ready/blocked/running/done/verified/failed), depends_on, resource, mutates, gate, tier, brief, expected_facts, facts, artifact` |
| `BACKLOG.md` | Optional. Off-critical-path tasks. They are not run unless the human pulls them into `TASKS.md` |
| `facts/phase-N.md` | The fact ledger: `| id | claim | value | confidence | source | inputs | verified | supersedes |`, plus a Sources table that maps short names to artifact paths. Fact ids are global across the spike |
| `facts/archive.md` | Superseded facts |
| `briefs/phase-N.md` | Self-contained phase brief: objective, tasks, input fact ids, method, expected artifacts, gate criteria, known traps. Write at most one brief ahead |
| `SESSIONS.md` | Append-only session log, with a `**Cost:**` line per entry |
| `HOW-TO-RUN-SESSIONS.md` | The human-facing guide: what to check before closing a session, how to start the next, which decisions belong to the human |

`confidence` is one of `measured`, `projected`, `vendor-doc`, `third-party-claim`, `inconclusive`.
`resource` names come from the `STATE.md` resources table. That table also says which resources
are **read-only** and which are **exclusive** (one task at a time, including with themselves).

## Modes

The user (or `/ticket` handing off a `spike` ticket) says which mode to run. If no mode is given,
pick `next` for an existing workspace and `start` for a new one, and say which you picked.

### start: scaffold a new spike

Ask the user for the slug, the decision the spike must produce, the resources (and which of them
are read-only or exclusive), and the phase plan. Then create `STATE.md`, an empty `TASKS.md`,
`facts/phase-0.md`, one brief and `HOW-TO-RUN-SESSIONS.md`. Do not write one long design doc that
holds the status in prose. Show the scaffold before you write it.

### next: run the next batch

**Start**

1. Read `STATE.md` in full. Read the current phase's brief.
2. Do not read a frozen design doc unless the brief or `STATE.md` points you to a section of it.
3. If the project has a preflight script for the resources you are about to touch, run it first.

**Execute**

1. **Compute the batch from `TASKS.md` only, never from `BACKLOG.md`.** A task is dispatchable when:
   - its `status` is `ready`;
   - every `depends_on` task is `verified`;
   - its `gate` is satisfied, or you are about to ask the human for it.

   Two tasks share a batch only if their resources do not collide. Do not run off-path work just
   because it is unblocked.
2. **Read-only resources are never mutated.** Never dispatch a task with `mutates: true` against a
   read-only resource. That is a task-authoring bug: report it, and do not route around it.
3. **Propose the batch and wait for one approval for the whole batch.** Stop completely, without
   proposing a batch, at:
   - a phase gate;
   - a `gate: spend` task;
   - a `gate: prod-load` task;
   - a `gate: conclusion` task.
4. **Measurement is a script; agents are for judgment.** If a task is "run a script and read its
   summary", run it yourself. A parameter sweep is one loop in one script, not one agent per value.
5. **Dispatch each task as a fresh agent with no memory of the other tasks.**
   - Give it the brief reference and its inputs, and nothing else.
   - Use the model tier that the task's `tier` says (`cheap`, `default` or `strong`). A task with
     no tier is not dispatched.
   - Dispatched agents never write `STATE.md`, `TASKS.md` or `facts/`. They return their artifact
     path, their findings and `proposed_facts` **without ids**. Only you write the workspace,
     serially, at checkpoint.
6. **A failed task still gets a status (`failed`) and a pointer to its output.** For an ambiguous
   result, write two facts:
   - a `measured` fact for what was observed;
   - an `inconclusive` fact for the interpretation.

   Never write one fact that splits the difference.
7. **Verify before `done` becomes `verified`** (tiers below). Then run **checkpoint**.

### verify: one-off clean-room check

Arguments: `<slug> <fact-id>`. Find the fact row and resolve its source:
- Map the short name to the artifact path through the Sources table.
- For a URL source, fetch the URL.

Then dispatch a fresh agent with `{{skill_dir}}/{{skill.spike}}/verifier-prompt.md`, filled in
with a one-claim list. The agent must not see `STATE.md`, `TASKS.md`, other facts or this
conversation. Report its verdict. Do not edit the ledger without the user's yes.

### checkpoint: write back (orchestrator only, never delegated)

**Step 0: ask the human every open question now.** This covers:
- questions that are new this session;
- questions still open from earlier sessions.

Do not leave them in `STATE.md` as homework. Then fold in the answers:
- A resolved question moves to "Decisions taken", or is dropped.
- An answer that creates work becomes a new `TASKS.md` row.
- A partly answered question is rewritten narrower.
- If an answer changes an existing task, update that row now.

**Nothing is written until the human has seen the whole draft and said yes.** This is not
size-gated, and you do not curate what is "worth showing".

1. Draft the full checkpoint in memory:
   - every proposed fact with its verifier verdict;
   - every task status change;
   - every decision, tagged `human-approved` or `technical (from data)`;
   - every open question, new or resolved;
   - every change to provisioned resources.
2. Show it and stop. Wait for an explicit yes. If anything is corrected and the change is
   material, show the corrected draft again.
3. Merge the proposed facts, assigning ids one at a time in task completion order.
4. Update `TASKS.md`: status, fact ids and artifact path.
5. Compare `expected_facts` with the actual facts. A task that ran and added no facts is a
   signal, not a silent `done`.
6. Supersession:
   - The new fact names the old id in `supersedes`.
   - The old fact moves to `facts/archive.md`.
   - No live text may still cite the old id.
   - A `projected` fact whose inputs include the old id becomes `stale` until it is re-derived.
7. Update `STATE.md` with exactly what was approved. Stay under the line cap. Move detail to a
   brief or the ledger.
8. Append one entry to `SESSIONS.md`: date, intent, what changed, what is deliberately not done,
   and `**Cost:**` (agents by tier, scripts run, wall clock). Never edit past entries.
9. Re-read the ledger. Check that every fact has a source, every `verified` fact has a verdict,
   and no superseded id is cited outside the archive. Fix problems now.
10. Tell the human what was written. Note anything that differs from the approved draft.

## Verification tiers

| Tier | For | Method | Model tier |
|---|---|---|---|
| 1 | Facts with decision leverage (the recommendation would change if they were wrong). Record other facts, but do not verify them | One clean-room verifier **per artifact**, checking all leveraged claims from it in one pass with `verifier-prompt.md` | cheap |
| 2 | Phase-gate conclusions and the final recommendation | Three independent refuters: arithmetic, apples-to-apples method, alternative explanation. **Any single refutation raises a human flag.** Never majority-vote | strong |
| 3 | `vendor-doc` / `third-party-claim` facts | Re-fetch the cited source and confirm the value is there | cheap |

Standing checks for every verifier:
- Does the artifact's own caveat contradict the claim?
- Is a `projected` number being cited as `measured`?
- Is a population claim drawn from an unstated sample?
- Is a gated number quoted without its attrition?
- Is there a different live measurement of the same value elsewhere in the ledger?

## Hand-off from /{{skill.ticket}}

A `spike` ticket starts an `atw` run, and no gates are armed. Run this skill in the mode the
user wants. When the session ends, close the run with a note that names the workspace:

```
{{atw}} close --note "spike <slug>: <what this session changed>"
```
