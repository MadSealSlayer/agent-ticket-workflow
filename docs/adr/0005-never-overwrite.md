# 0005. Never overwrite what is not ours

- Status: accepted
- Date: 2026-10-04

## Context

A setup that silently replaces a team's `CLAUDE.md`, hooks or skills destroys trust, and the damage may not be noticed.

## Decision

The manifest records every file we own, with its hash. Apply refuses to write any file that is not ours or that was edited since it was installed, and then writes nothing. Shared files change only inside marked blocks, or in hook entries that run our script. Every changed file is backed up first. A collision is a question: merge, namespace ours, skip, or abort.

## Consequences

Re-applying and upgrading are safe. A namespaced install (for example `atw-ticket`) can live next to the team's own `/ticket`.
