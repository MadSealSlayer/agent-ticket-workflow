# 0010. Simplify is optional

- Status: accepted
- Date: 2026-10-04

## Context

A simplify pass helps large diffs, but as a fixed gate it adds cost to every small ticket.

## Decision

`simplify` in the config is `off`, `advisory` or `gate`. Setup asks. As a gate, it uses a hashed packet like the review does.

## Consequences

Each team picks its own trade-off.
