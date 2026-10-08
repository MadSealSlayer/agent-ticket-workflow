# Harnesses

The workflow is a set of steps and contracts. Only the enforcement layer depends on the host.

| Part | Claude Code | Codex | Other agents |
|---|---|---|---|
| Entry | `/ticket` skill (`.claude/skills/`) | `$ticket` skill (`.agents/skills/`) | Read `.agents/skills/ticket/SKILL.md` |
| Instructions | `AGENTS.md` block, read natively (2.1.277+). If a `CLAUDE.md` exists, a one-line `@AGENTS.md` bridge | `AGENTS.md` block | `AGENTS.md` block |
| Hooks file | `.claude/settings.json` (commit) or `settings.local.json` (local) | - | - |
| Turn-end enforcement | **Stop hook**: the turn cannot end while a gate is unmet | The agent runs `atw status` before it ends a turn (instruction) | Same as Codex |
| Plan gate | Plan mode. A PostToolUse hook stamps the plan-mode exit | Plan saved to `plan_dir`, plus the user's approval words: `atw plan --plan-file --approval` | Same as Codex |
| Guard | PreToolUse hook denies the `guards` patterns | Instruction only | Instruction only |
| Clean-room review | Fresh subagent, given only the packet | A new session, or a subagent if the host has one, given only the packet | A new session, given only the packet |
| Gates, red, packets | `atw` | `atw` | `atw` |

The state, the gates and the evidence are the same on every host. You can start a ticket in one
host and finish it in another. That helps when a usage limit is reached or a service is down.

**An honest limit.** Claude Code has the most automatic enforcement. On other hosts, more of the
discipline depends on the agent following the `AGENTS.md` block. `atw close` still refuses to
close a run with an unmet gate on every host, but nothing stops a Codex turn from ending early.
How well each host follows the block is not measured yet.

## Adding a host

1. Find where it reads skills and instructions. If it reads `AGENTS.md` and `.agents/skills/`,
   it works now as `other`.
2. If it has hooks, map them to `atw hook stop|guard|planmode`. The hooks read a JSON payload on
   stdin, as Claude Code sends it. A thin translator is fine.
3. Add the host to `HOST_SKILL_DIRS` in `install.py` and to `config.HOSTS`. Add detection markers
   in `detect.py`.
4. Add a test, and a row to this table.
