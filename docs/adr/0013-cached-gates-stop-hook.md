# 0013. The Stop hook reads cached tests/lint/deps results

- Status: accepted
- Date: 2026-11-12

## Context

The Stop hook re-ran every live gate at each turn end while a run was open. On a large diff the
scoped test run, the linter and the dependency check took about two minutes per turn, even when
nothing had changed, and could exceed the hook's timeout. A pilot project measured this.

## Decision

`tests`, `lint` and `deps` are **cached** live gates. `atw gate` runs them and saves each result
with a fingerprint of the change: the path and content of every changed file, the run's kind,
baseline, proof set and red record, and the configured commands.

- `atw status` reuses a saved result while the fingerprint matches, and re-runs it otherwise.
- The Stop hook never runs them. A missing or outdated result blocks the turn as `stale`, with
  the `atw gate` command that refreshes it.
- `atw close` always re-runs them. The fingerprint does not cover ignored files or the
  environment, so the final check never trusts it.

`nocode`, `placement` and `provenance` are cheap and still run on every check. The fingerprint
is taken before a gate runs, so a file edited during the run makes the result stale, never
wrongly fresh.

## Consequences

A turn end costs a few hashes instead of a test suite. The agent must run `atw gate tests lint
deps` after its last edit. The skills and the `AGENTS.md` block say so, and the hook names the
command when the agent forgets.
