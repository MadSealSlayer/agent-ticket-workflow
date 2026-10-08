# Roadmap

Not ordered by priority. Open an issue before you start on one, so the design can be agreed first.

## Lightweight / external-plan mode

The idea: one large plan, written up front (for example a spec-driven-development plan). Several
agents then work through its tickets in parallel.

- **Skip** the per-ticket plan-mode step. Each ticket points at its section of the external plan
  instead.
- **Keep** behavioral RED, the fresh gates and the clean-room review.

Open design questions:
- How a run proves which plan section it implements.
- How the plan hash goes stale.
- How parallel runs on one branch stay separate. Run ids already exist.

## More ticket sources

Version 1 reads local markdown files (`tickets.globs`). Next:
- **Pasted text:** `atw start --from-stdin`, saved under `.atw/`.
- **Jira:** read-only fetch to a local file, with credentials from the user's own environment.
- **GitHub Issues:** the same, through `gh`.

The ticket file stays read-only to the workflow, whatever its source.

## Spike rebuild

`experimental/spike/` is a port of a harness that was used once. A rebuild should:
- bring back a mechanical ledger check (fact ids, sources, supersession, read-only resources);
- add a preflight hook for resources;
- define a smaller and clearer file set.

Then it can leave `experimental/`.

## Changed-lines lint for more formats

Changed-lines lint now reads `ruff-json` and `eslint-json`. Add more formats:
- golangci-lint JSON;
- SARIF, which many linters can write;
- a plain `file:line:` text parser as a fallback.

## Uninstall

`atw uninstall` would use the manifest to remove:
- unedited owned files;
- our marked blocks;
- our hook entries.

It would keep edited files and list them. Version 1 has no uninstall. The manifest already holds
what an uninstall needs. A pilot showed why it matters: a local trial in a linked
worktree leaves its block in the shared `.git/info/exclude` after the worktree is deleted.

## Karma (Angular) preset

Karma has no single-test filter and no JUnit reporter by default. An Angular pilot needed a
wrapper that runs one spec file per call (`ng test --include`) and installs
`karma-junit-reporter` without saving it. A preset should ship that wrapper.

## Smaller items

- `atw doctor --fix` for safe repairs, such as re-adding a missing gitignore block.
- A parallel multi-lens review option for high-risk changes. It must keep a timeout, so that one
  slow reviewer cannot stall the gate.
- Measure the harness overhead per ticket. The target is 5 to 10 minutes.
