# agent-ticket-workflow

A portable, gated ticket workflow for AI coding agents. Install it into any project (backend or
frontend, any stack) and use it from Claude Code, Codex or another agent.

Every ticket follows the same shape:

```
classify kind -> load context -> plan + approval -> prove RED on behavior
              -> fresh gates (tests, lint, deps) -> clean-room review -> close with evidence
```

A ticket is not done because the agent says it is done. It is done when a script has checked the
facts: the proof tests failed before the change and pass after, lint is clean on the changed
lines, new imports are declared, and a reviewer that never saw the author's reasoning found no
open Critical or Warning items. Most tickets are not code. Investigations, drafts, docs and
helper scripts take a lighter path, with their own checks.

Read [docs/workflow.md](docs/workflow.md) for the reasoning behind it.

## What you get

- **One state engine** (`.atw/core/atw.py`). Python 3.10+ standard library only, no dependencies.
  It holds every run, gate and review packet, for every host.
- **Skills** for the workflow: `ticket`, `ticket-investigation`, `ticket-audit`, project-context
  load and update, and an advisory writing check.
- **Host adapters.**
  - Claude Code: a Stop hook that blocks the turn while a gate is unmet, a plan-mode marker
    and a guard.
  - Codex and other agents: an `AGENTS.md` block. The agent runs `atw status` before it ends a
    turn.
- **A setup skill** (`/ticket-setup`). It looks at what your project already has, asks you about
  everything that matters, shows the exact changes, and writes nothing before you approve.
- **Stack presets**: pytest, vitest, jest, go test, ruff, eslint, and pip / npm dependency checks.
  You can configure any other command, as long as the test runner writes JUnit XML.

## Install

You need Python 3.10+ and git. The installed workflow needs no network access and no account.

1. Get the package: clone this repository, or download it from GitHub (**Code → Download ZIP**)
   and unzip it. It does not need to be inside your project.
2. Stage it into your project:

   ```bash
   python path/to/agent-ticket-workflow/install.py path/to/your-project
   ```

   This changes very little. It stages the package in `.atw/staging/` (which ignores itself in
   git) and copies the setup skill into `.claude/skills/` and `.agents/skills/`. If you already
   have a skill called `ticket-setup`, it stops and tells you to use `--setup-name`.
3. Open your agent in the project and run the setup:
   - Claude Code: `/ticket-setup`
   - Codex: `$ticket-setup`
   - Other agents: "follow `.agents/skills/ticket-setup/SKILL.md`"

In a git repository, the setup's first question is: **local only, or committed to git?**
- **Local only** keeps everything on your machine. Nothing it adds shows up in `git status`.
  It uses `.git/info/exclude`, `.claude/settings.local.json` and `CLAUDE.local.md`, and it does
  not edit tracked files.
- **Commit** sets it up for the team to review and commit.

Either way, you can move or skip any single touchpoint (the instructions file, the Claude
bridge, the hooks file, the ignore rules). This lets you add it to an existing project with as
few changes as you want.

The workflow's agent instructions live in one file, `AGENTS.md`, which Claude Code and Codex both read. If
your project has a `CLAUDE.md`, the setup adds only a one-line `@AGENTS.md` import to it.

The setup detects your stack, test and lint commands, CI, existing hooks, skills and instruction
files. Anything that collides with what you already have becomes a question: merge, use a
namespaced name (for example `atw-ticket`), skip, or abort. It never overwrites your files.
After you approve, it writes everything, backs up each changed file to `.atw/backup/`, and runs
`atw doctor`.

To upgrade, run `install.py` from the newer package and run the setup again. It reuses your
earlier answers and asks only about what changed.

## Daily use

```text
/ticket T-123            Claude Code
$ticket T-123            Codex
```

The agent classifies the ticket and confirms the kind with you when it is unclear. Then it
follows the gates. When it gets stuck, `atw status` names the next step:

```bash
python .atw/core/atw.py status
```

## Building an offline zip

To give the package to someone who has no access to git or GitHub, build a zip from your copy:

```bash
python tools/make_dist.py
```

This writes `dist/agent-ticket-workflow-<VERSION>.zip` and `dist/SHA256SUMS`. The zip is not in
the repository, because `dist/` is ignored by git. It has an `INSTALL.txt` at the top and leaves
out `.git/`, caches and local tool folders. The same tree always gives the same zip bytes, so the
checksum can be compared.

## Experimental: spikes

`experimental/spike/` holds a workflow for multi-session measurement spikes. It was used once and
needed a lot of human steering. Read [experimental/spike/WARNING.md](experimental/spike/WARNING.md)
before you enable it. The setup asks, and recommends no.

## Repository map

| Path | What |
|---|---|
| `install.py` | Bootstrap: stages the package and copies the setup skill |
| `core/` | The state engine (`atw.py`, `atwlib/`) and stack presets |
| `skills/` | The workflow skills, rendered into your project by the setup |
| `adapters/` | Claude Code hooks fragment, the `AGENTS.md` block, the ignore block |
| `templates/` | Config, install-plan and question-sheet templates, context index |
| `experimental/` | Opt-in features that are not stable yet |
| `docs/` | [workflow](docs/workflow.md), [architecture](docs/architecture.md), [harnesses](docs/harnesses.md), [ADRs](docs/adr/) |
| `tests/` | Unit and end-to-end tests (`python -m unittest discover -s tests/unit -t tests/unit`) |
| `tools/` | `make_dist.py` (offline zip), `check_repo.py` (static checks that CI runs) |

## Contributing

Issues are welcome: bugs and proposals. Pull requests from outside contributors are not
accepted. See [CONTRIBUTING.md](CONTRIBUTING.md) and [ROADMAP.md](ROADMAP.md).

## License

MIT. See [LICENSE](LICENSE).

---

*Vibecoded by Ádám.*
