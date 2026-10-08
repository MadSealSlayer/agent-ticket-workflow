# 0012. Published on GitHub under the MIT license

- Status: accepted
- Date: 2026-10-08
- Supersedes: [0008](0008-local-only-until-published.md)

## Context

The owner and the hosting place are now decided. ADR 0008 kept the repository local until then.

## Decision

The repository is published on GitHub under a personal account. It starts private and becomes
public later. The license is MIT. Commits use the GitHub noreply email of the author.
`CODEOWNERS` names the owner. Code, config and docs still have no hardcoded remote URLs.

## Consequences

Anyone can use, change and share the package. The zip (`tools/make_dist.py`) still works
without git. Changes land through pull requests, as `CONTRIBUTING.md` says.
