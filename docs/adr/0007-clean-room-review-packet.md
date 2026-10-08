# 0007. Clean-room review through a hashed packet

- Status: accepted
- Date: 2026-10-04

## Context

A reviewer that sees the author's reasoning reviews like the author. Some hosts cannot start a clean subagent.

## Decision

`atw review-packet` writes only the diff, the requirements and the settled decisions, and hashes them. The review runs in a fresh subagent, or in a new session on hosts without subagents. `accept-review` checks the packet hash and the report format. Any later edit makes the review stale.

## Consequences

Review works the same on every host. Starting a new session costs the user a step on hosts without subagents.
