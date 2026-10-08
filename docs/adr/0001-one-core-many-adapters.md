# 0001. One host-neutral core, thin host adapters

- Status: accepted
- Date: 2026-10-04

## Context

The original project had two state systems: one for Claude Code hooks and one launcher for other hosts. They had different gate lists, and the docs and code disagreed about them.

## Decision

One state engine (`core/atw.py`) owns runs, gates and packets for every host. Adapters only connect a host to it: Claude Code hooks, and an `AGENTS.md` block.

## Consequences

One gate list and one place to fix bugs. A run can move between hosts. Hosts without hooks depend more on instructions (see `docs/harnesses.md`).
