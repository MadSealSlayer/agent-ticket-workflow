# 0016. In T3 Code, the review can run on another model through a delegated task

- Status: accepted
- Date: 2026-11-24
- Amends: [0007](0007-clean-room-review-packet.md)

## Context

The clean-room review (0007) runs in a fresh sub-agent. On Claude Code that is a Claude model,
the same family that wrote the change. A reviewer from another model family finds problems that
the author's model does not see. A pilot project ran its audit on Codex through T3 Code's
`delegate_task` and found such problems.

T3 Code also runs several threads in one checkout and on one branch. That is why session
isolation in the hooks matters for this route (see the hooks in `docs/architecture.md`).

## Decision

- A config key `audit.route` chooses the route: `agent` (default) or `t3-delegate`, with
  `audit.t3` = `{provider, model, reasoning_effort}`.
- With `t3-delegate`, a Claude session inside T3 Code (`T3CODE_THREAD_ID` is set) checks once
  with `orchestrator_capabilities` that the provider has the model and can run a child task.
  Then it makes one new `delegate_task` per review or simplify round: role `review`, isolation
  `shared` (a worktree child does not see the uncommitted change), mode `async`. The task holds
  only the packet path and the path of the `ticket-audit` skill.
- The child follows the "delegated reviewer" rules in the `ticket-audit` skill: no `atw`, no
  hooks, no tests, no file changes except the report the packet names.
- The session waits for the child without polling and without editing files. Then it runs
  `atw accept-review` as usual. The review packet is bound to the diff hash, so `accept-review`
  refuses a report for a working tree that changed. A patch rebuild and comparison, which the
  pilot needed, is not necessary.
- When the session is not in T3, the model is missing, or the delegation or the child fails,
  the round falls back to the `agent` route, and the session says so.
- The core does not change. The route is skill text and config only.

## Consequences

The review needs T3 Code and access to the other provider. Without them, nothing changes. The
child shares the checkout, so its rules are instructions, not enforcement; the diff-hash check
in `accept-review` catches a child that changed a file anyway. The simplify packet is not bound
to the diff hash, so its freshness still comes from re-running the gates.
