# The ticket workflow: how it works and why

This workflow was first built and used inside one backend project, where most tickets were code
or investigations. This package makes it portable. The shape is the same as in that project; only
the project-specific parts became configuration.

## Why it exists

An AI agent is fast, but it will skip the boring parts and then report success: tests, lint,
review, checking what else a change touches. So the discipline lives in scripts and hooks that
check the repository, not in the agent's memory.

Four principles:

1. **Most tickets are not code.** Many ask what happened, or want a drafted message. Forcing
   tests and a review onto those makes work for nothing. An empty diff can be a good result.
2. **Classify first.** The agent classifies the ticket from its text and confirms with a human
   when the kind is unclear. The kind decides the whole route.
3. **Gates check facts, not promises.** Every gate runs fresh: tests, lint, dependency check,
   review report. A gate that verifies nothing is worse than none, because it looks like coverage.
4. **Hard-to-reverse choices go to a human.** If an ambiguity would change the shape of the
   work, it becomes a question, never a silent default.

You can copy the shape without the tooling: classify, plan, prove red, gate, review clean-room,
close with evidence.

## Lifecycle

```
/ticket <id>
  -> classify the kind (confirm when unclear)  -> load project context
  -> code:     plan + approval -> RED on behavior -> implement -> tests/lint/deps
               -> (simplify) -> clean-room review -> close
  -> non-code: deliverable at its required place -> nocode/placement/provenance -> present -> close
```

`atw close` re-checks every gate and appends one line to the run log. The ticket file itself is
never changed.

## Kinds

| Kind | Signals | Deliverable |
|---|---|---|
| `investigation` | "check the logs", "what happened", "no fix yet" | Findings file with sources (`placement.investigation`) |
| `comms` | "draft an email", "talk track" | Draft (`placement.comms`) |
| `docs` | "write documentation", "handover doc" | Committed doc (`placement.docs`) |
| `tooling` | a helper script, nothing in protected source | Script (`placement.tooling`) |
| `code` | a functional change to `protected_paths` | Tested, gated, reviewed change |
| `spike` (experimental) | a multi-session measurement workspace | Handed to the spike skill |

When it is unclear, the default is `investigation` or a question, never `code`.

Code has a second split, the **scope**:
- **Coordinated** changes get the full plan. A change is coordinated if it changes any of these,
  or spans sessions:
  - a public API or event contract;
  - a schema or migration;
  - cross-service behavior;
  - infrastructure.
- **Isolated** is everything else.

A ticket can start as an investigation and be **re-kinded** to code once the findings show what to
fix (`atw kind code --why ...`). The `nocode` gate enforces this. If a non-code run touches
protected paths, the run must be re-kinded honestly. Hiding the change is not allowed.

## Gates

| Gate | Checks | Kinds |
|---|---|---|
| `plan` | The plan was approved. On Claude Code, a hook stamps the plan-mode exit. On other hosts, a saved plan file plus the user's approval words are recorded and hashed | code |
| `red` | Every proof-set test **fails on behavior** before the change | code |
| `tests` | Re-runs the tests the diff touches, plus the whole proof set, which must now pass | code |
| `lint` | The configured linter, on changed lines only | code |
| `deps` | Every new third-party import is declared (pip / npm presets) | code |
| `simplify` | Optional. A simplify report on the current diff | code |
| `audit` | A clean-room review report for the current diff, with no open Critical or Warning | code |
| `nocode` | The diff does not touch `protected_paths` | non-code |
| `placement` | The deliverable is where its kind requires | non-code |
| `provenance` | Findings have `## Sources`, and claims are tagged `measured` or `inferred` with a source id | investigation |

Gates are **live** or **recorded**:
- Live gates re-run on every check: nocode, placement, provenance, tests, lint, deps.
- Recorded gates are stored with a hash and go **stale** when what they cover changes: plan,
  red, simplify, audit. An edit after the review makes the audit stale.

Asking open questions, and presenting investigation findings before closing, are deliberately
**not** gates, because a script cannot check them. The skills require them.

On Claude Code, the Stop hook blocks the end of a turn while a required gate is unmet, and it
names the next step. Three identical blocks in a row release it, so that a broken gate cannot
trap a session. The release is recorded. On other hosts, the agent runs `atw status` before it
ends a turn.

## Code tickets

A code ticket has one spec: its **proof set**. That is one test id per acceptance criterion in
the approved plan. The run cannot close until every id passes.

1. **Plan first.** Settle the open questions in the plan: data model, ownership, error semantics,
   compatibility. Do not edit protected paths or tests before the plan gate passes.
2. **Record settled decisions** with `atw decide`, so the review does not raise them again.
3. **Prove RED on behavior.** Write the proof tests first. If the code does not exist yet, add a
   wrong-answer stub (for example `return None`), so the assertion fails and not the import.
   `atw red --test <id>` refuses any test that:
   - errors, skips or already passes;
   - fails only with ImportError, NameError, NotImplementedError or a similar error.

   A pure refactor records `atw red --none --why "..."` instead.
4. **Implement**, then `atw gate tests lint deps`. Every run is fresh, with no cache to go stale.
5. **Review clean-room** (next section). Fix every Critical and Warning, then gate again.
6. **Update project context** if the architecture changed, then `atw close`.

Why behavioral red matters: a test that fails only because a function is missing turns green
with any empty stub, so it proves nothing. Only a failing assertion shows that the test can catch
the bug it is meant to prevent.

Why plan every code ticket: a decision made in planning costs a sentence; the same decision found
after the code is written costs a rewrite. The approved plan also defines the proof set, so
"done" is agreed before the code starts. This costs time up front, and it is a trade-off. See
`ROADMAP.md` for a lighter mode that uses one external plan for many tickets.

## The clean-room review

The review runs in a **fresh agent** that never saw how the code was written. `atw review-packet`
writes what the reviewer may see, and nothing else:
- the diff;
- the ticket's requirements;
- the settled decisions.

The packet does not include the plan, the reasoning or the author's claim that the tests pass.
The reviewer works through five checks:

1. **Intent:** every requirement has code, and a test that asserts the behavior.
2. **Correctness and edge cases:** off-by-one errors, inverted conditions, empty input.
3. **Error handling:** swallowed exceptions, unguarded access.
4. **Side effects and integration:** consumers outside the diff.
5. **Population and denominator:** a count or rate is computed over the set it claims to cover.

New problems that the diff introduces block the gate. Bugs that already existed go to a backlog
and do not block. Later rounds review only the open items and the lines changed since then.
`atw accept-review` checks the packet hash and the report headings. A report must contain both
severity headings, so an empty report cannot pass as a clean one.

Why the review must be clean-room: whatever the author knows about how it built the change is
exactly what makes its review unreliable. A reviewer that sees the reasoning inherits the
reasoning. These studies point the same way:
- LLMs struggle to self-correct without external feedback (Huang et al., ICLR 2024).
- LLM evaluators rate their own output higher (Panickssery, Bowman and Feng, NeurIPS 2024).
- A "bug-free" framing can collapse vulnerability detection (Mitropoulos et al., 2026,
  arXiv:2603.18740, preprint).
- A fresh session with only the artifact found more errors than same-session review, but not
  when it was also given the generation prompt (Song, 2026, arXiv:2603.12123, preprint).

Treat the effect sizes as indicative; several of these are preprints. The rule is still cheap and
sound: **never validate code in the context window that produced it.**

One reviewer with five checks and a short time budget is a deliberate choice for speed and cost.
A parallel review with several agents covers more angles. It costs more tokens, and it needs a
timeout: without one, a single slow parallel reviewer can stall the gate.

## Investigations

No plan mode, no tests, no review. The goal is to answer a question with evidence.

1. **Plan the questions** first. Decide which data sources they need. Most tickets need one or
   two.
2. **Use the project's tools** (`investigation.tools` in the config), not raw ad-hoc access.
   Credentials come from the developer's own config, never from chat.
3. **Fan out only independent questions**, each to a cheap agent, and only when it helps.
   Subagents return distilled findings, never raw dumps.
4. **Write findings with provenance**: a `## Sources` section, and claims tagged
   `measured` or `inferred` with a `[S1]` id.
5. **Present, then stop.** End by handing the decision back: done, dig deeper, or re-kind to code.
   The ticket text is the user's informal notes. Re-derive the root cause; do not trust the
   ticket's diagnosis.

## Comms, docs, tooling

- **Comms:** a draft in a local folder. Present it, and the human decides when it is done.
- **Docs:** only permanent documentation goes in the committed docs folder. The test: is it meant
  to be committed?
- **Tooling:** helper scripts outside protected source. A tooling ticket never becomes code by
  growing.

## Guardrails

| Guardrail | What it does |
|---|---|
| Stop hook (Claude Code) | Blocks the end of a turn while a gate is unmet |
| Guard hook (Claude Code) | Denies history rewrites (`reset --hard`, `--amend`, `rebase`, force push) and other patterns in `guards` |
| Run baseline | Files that were untracked before a run starts are never counted as the run's changes |
| No push | The agent commits locally only when asked. The developer pushes and opens PRs |
| Hygiene | `atw hygiene` reports misplaced files. It is read-only |

## Working rules

The skills and the instruction blocks carry these rules on every host:
- **Think before coding.** State your assumptions. Name each possible reading of the request.
  Ask when something is unclear.
- **Simplicity first.** Write the least code that solves the problem. Add no features that
  were not asked for.
- **Surgical changes.** Every changed line must trace back to the request. Do not reformat
  nearby code.
- **Goal-driven.** Turn the task into checkable criteria, which here is the proof set, and loop
  until every one passes.
- **No idle stops.** Stop only for a decision that is the human's, and name that decision.

These come from a community distillation of public observations about coding agents. They are
cheap and they target failure modes that users recognize. Their effect on errors is not measured
here. The real protection comes from pairing them with checks that the agent cannot argue with.

## Project context

Use the lightest structure that lets the agent find the right file and know the rules. That is
one small index that is always loaded, plus topic files loaded by a "load when" condition.
- The loading skill reads the index, then only the topic files that match.
- The updating skill changes the index only for structural changes, and reports a no-op
  explicitly.

Consider a code graph only when search stops being enough.

## Concurrent work

Every run has an explicit id (`atw start` prints it). Pass it with `--run` or `$ATW_RUN` when
several tickets are open in parallel sessions. Run state lives under `.atw/runs/`, which is
gitignored.

## Lessons from the original project

- Mechanical gates caught real skips. Every gate now runs fresh.
- Classifying first, and asking only when the kind is unclear, stopped code-shaped work from
  being forced onto questions.
- Behavioral red made the tests trustworthy.
- The harness cost time to fix its own bugs, and it did not yet meet its target of 5 to 10
  minutes of overhead per ticket.
- A successful pilot is a green light to do the work. It is not the deliverable.
- Check the numerator and the denominator of every figure derived from logs.

---

*Vibecoded by Ádám.*
