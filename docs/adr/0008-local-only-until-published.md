# 0008. Local repository, no remote, no commits until the owner is decided

- Status: superseded by [0012](0012-published-mit.md)
- Date: 2026-10-04

## Context

The hosting place and the author account were not decided.

## Decision

The repository is created locally with `git init` and no remote, and nothing is committed. There are no org names, owners or URLs; placeholders are used instead. The package also works as a zip (`tools/make_dist.py`), with no git needed.

## Consequences

It can be tried from a zip before it is published.
