# 0009. Spike ships as experimental

- Status: accepted
- Date: 2026-10-04

## Context

The spike harness was used once and needed heavy human steering. Its mechanical validator was specific to one project.

## Decision

The spike skill is in `experimental/spike/` with a `WARNING.md`. It is installed only if the user opts in, and no gates are armed for the `spike` kind. A rebuild is on the roadmap.

## Consequences

It is available for teams that want it, with honest expectations. Nothing checks its rules mechanically.
