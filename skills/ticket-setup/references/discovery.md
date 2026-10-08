# Discovery: reading the report, and what to check by hand

`atw detect` is read-only and shallow by design. It finds files; it does not understand them.
Before you propose anything, confirm each of these by reading the actual files.

## How tests really run

- Read the CI workflows the report lists. The test step in CI is the best evidence of the real
  command, its working directory, its environment and its interpreter.
- Read `package.json` scripts, `pytest.ini`/`pyproject.toml` test sections, `Makefile`, `tox.ini`,
  `noxfile.py`, `justfile`. Note any wrapper the team uses (for example `make test`).
- Monorepo? Find each package's own test command. Note whether tests run from the repo root or
  per package. The workflow runs commands from the repository root. A per-package command
  needs a `cd` or a `--prefix`/`--dir` flag, and that is a question for the user.
- Find a virtualenv or tool manager (`.venv`, `uv`, `poetry`, `pdm`, `nvm`, `volta`, `asdf`).
  Gates must use the same interpreter as the team.
- The proof command must write **JUnit XML**. Check that the runner can (pytest: `--junitxml`;
  vitest: the junit reporter; jest: the `jest-junit` package; go: `gotestsum`). If it cannot,
  that is a question, not a silent change to the project's dependencies.

## What code means here

- Source folders (`layout.source_dirs`) and test folders (`layout.test_dirs`,
  `nested_test_dirs`) are only candidates. Look at the tree. Generated code, vendored code,
  migrations and infrastructure folders need a decision: protected or not.
- Find shared code that several deployables use (a shared layer, a `packages/shared`, a
  `libs/common`). It matters for `deps.python_extra_requirements` and for the review's blast
  radius check.

## Existing agent setup

- Read every instruction file in the report (CLAUDE.md, AGENTS.md, Cursor/Copilot rules).
- Read every skill, command and hook in the collision and similar-practice lists. For each,
  write one line: what it does, and whether it overlaps a part of this workflow.
- Note project-context files that already exist (an architecture index, a `docs/context`
  folder). If one exists, propose pointing `context.index` at it instead of creating a new one.
- Note how the team handles tickets today: a ticket folder, a tracker, plain chat.

## Investigation tools (only if the investigation kind will be enabled)

Look for the project's own helpers for logs, databases, queues and cloud resources (scripts
folder, a `helpers/` or `tools/` package, a README section). Record them for the
`investigation.tools` and `investigation.notes` config keys, which the investigation skill
reads. Note where credentials come from, but never the values.

## Output

Give the user a summary of at most 15 lines, then the collision list. Keep detail in the
question sheet.
