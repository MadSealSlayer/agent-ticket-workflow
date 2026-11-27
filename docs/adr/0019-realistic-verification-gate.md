# 0019. Big code changes are run for real, next to the review

- Status: accepted
- Date: 2026-11-27

## Context

A pilot project (an Angular frontend) closed a coordinated code ticket with about 30 fixes and 31
acceptance criteria. Every gate passed: plan, red (74 proof specs), tests, lint, deps, simplify
and four clean-room review rounds. Nobody ran the changed behavior. The proof specs mocked their
services and the reviews were static.

Before the install, the project had a way to check this: a skill that starts the dev server and
drives a browser with a mocked backend. The install did not remove it, but nothing in the ticket
flow called it. `atw detect` did not know this kind of practice, so setup never asked about it.
The setup notes said the workflow's review replaces the project's audit steps, and the fixed
ticket sequence left no step where it fit.

## Decision

- A recorded gate `verify` for code runs. Config `verify.when`: `big` (default), `always` or
  `off`. `big` means coordinated, or at least `min_planned_files` planned files, or at least
  `min_proof_ids` proof tests (8 each). The size is read from the run, so `plan` and `red`
  announce when the gate starts to apply.
- `verify.how` holds the project's own check as text (a skill path, a command or a checklist).
  The core never runs it: `atw verify-packet` writes a packet with the ticket and `how`, and a
  fresh agent runs it. The route is the review's: a sub-agent, or a T3 `delegate_task` on
  `audit.t3` (role `test`). The verifier writes only into its packet's folder.
- `atw accept-verify` checks the packet id, a verifier other than the implementer, the three
  headings (Checked, Failed, Not run) and the diff hash at packet time. An open Failed item
  always blocks. Open Not-run items, or nothing checked, block unless the user's own words are
  given (`--user-approved`); that is recorded as an accepted trade-off. With `how` empty, this
  is the fallback: the user decides about each check that was not run.
- `review-packet` does not wait for `verify`, and the verifier's output (its folder under
  `.atw/`, plus `verify.ignore`) is outside the reviewed diff. The two run in parallel.
- Staleness: unlike `audit`, an edit does not make `verify` stale. It goes stale when
  `verify.recheck_after_rounds` (2) review rounds were made on a changed diff after the check.
  A round on the same diff, such as the parallel round 1, does not count.
- Setup must not drop a check like this again: `detect` reports a `realistic verification`
  practice, the setup decision policy forbids replacing an existing check without a gate that
  covers it, and `doctor` warns while `verify.how` is empty or `when` is `off`.

## Consequences

- Upgraded projects get `when: big` with an empty `how`. Big tickets then stop at close until
  the user accepts the unrun checks, or until setup fills `how`. This is deliberate: the silent
  pass is the failure this ADR fixes.
- `close` does not re-run the check (unlike tests, lint and deps in ADR 0013). A browser run
  per close would be slow and flaky; the report and its round count are the evidence.
- The gate checks the report, not the browser. A verifier could still write a false report; the
  fresh agent, the artifacts folder and the per-criterion lines make that visible, not
  impossible.
