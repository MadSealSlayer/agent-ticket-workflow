# Harnesses

The workflow is a set of steps and contracts. Only the enforcement layer depends on the host.

| Part | Claude Code | Codex | Other agents |
|---|---|---|---|
| Entry | `/ticket` skill (`.claude/skills/`) | `$ticket` skill (`.agents/skills/`) | Read `.agents/skills/ticket/SKILL.md` |
| Instructions | `AGENTS.md` block, read natively (2.1.277+). If a `CLAUDE.md` exists, a one-line `@AGENTS.md` bridge | `AGENTS.md` block | `AGENTS.md` block |
| Hooks file | `.claude/settings.json` (commit) or `settings.local.json` (local) | - | - |
| Turn-end enforcement | **Stop hook**: the turn cannot end while a gate is unmet (reads cached tests/lint/deps results, never runs them) | The agent runs `atw status` before it ends a turn (instruction) | Same as Codex |
| Plan gate | Plan mode. A PostToolUse hook stamps the plan-mode exit | Plan saved to `plan_dir`, plus the user's approval words: `atw plan --plan-file --approval` | Same as Codex |
| Guard | PreToolUse hook parses each shell command and applies the `guards` rules (git rules, `git add` of data files, test deletion, custom regexes). It also asks before an edit that adds a test skip or focus marker | Instruction only | Instruction only |
| Clean-room review | Fresh subagent, given only the packet. In T3 Code, optionally a delegated child on another model | A new session, or a subagent if the host has one, given only the packet | A new session, given only the packet |
| Parallel sessions on one branch | Hooks bind each session to its ticket and never gate it with another session's run | `--run` on every command | Same as Codex |
| Gates, red, packets | `atw` | `atw` | `atw` |
| Jira (optional) | Atlassian MCP connector and the `jira` skill | Same, if the Atlassian MCP server is configured | Same, if the agent has an MCP client |

The state, the gates and the evidence are the same on every host. You can start a ticket in one
host and finish it in another. That helps when a usage limit is reached or a service is down.

**An honest limit.** Claude Code has the most automatic enforcement. On other hosts, more of the
discipline depends on the agent following the `AGENTS.md` block. `atw close` still refuses to
close a run with an unmet gate on every host, but nothing stops a Codex turn from ending early.
How well each host follows the block is not measured yet.

## T3 Code

T3 Code runs Claude Code and Codex threads side by side, often in one checkout and on one
branch. Three things help there:

- **Plan approval.** T3 Code captures the plan itself: `ExitPlanMode` always returns an error
  ("The client captured your proposed plan..."), and a failed tool call never fires
  `PostToolUse`, so the native approval stamp is never written. Instead:
  1. A `PreToolUse` hook on `ExitPlanMode` (`atw hook planproposed`) stamps "plan proposed" for
     the session's ticket (or the branch, for an unbound session). It never blocks.
  2. The ticket skill then asks `AskUserQuestion` with one question: header `Plan`, question
     "Approve this plan?", options `Approve` and `Decline`. T3 renders it; the user can also
     type their own text.
  3. The `PostToolUse` hook (`atw hook planmode`, matcher `ExitPlanMode|AskUserQuestion`) turns
     an exact `Approve` to a pending proposal into the same approval stamp that a successful
     `ExitPlanMode` writes. `Decline` or free text is recorded and consumes the proposal: the
     agent revises the plan and proposes again.

  `atw plan` records the route (`exit-plan-mode` or `ask-approve`) in the gate evidence. While a
  proposal waits for an answer, the Stop hook's plan hint says to ask the `Plan` question
  instead of "call EnterPlanMode". The `--no-plan-mode` escape hatch is not needed in T3. Known
  limit: the hook trusts the answer in `tool_input.answers`, as the host UI filled it. ADR 0018
  has the reasons.
- **Session isolation.** The Claude hooks act only on the run that the session drives. A thread
  that is not working on a ticket is not stopped by another thread's gates. See "Concurrent work"
  in [workflow.md](workflow.md).
- **Review on another model.** Set `audit.route` to `t3-delegate`. A Claude ticket session then
  checks for `T3CODE_THREAD_ID`, calls `orchestrator_capabilities` once, and makes one
  `delegate_task` per review or simplify round:

  | Field | Value |
  |---|---|
  | `role` | `review` |
  | `isolation` | `shared` (a worktree child does not see uncommitted edits) |
  | `mode` | `async` |
  | `target` | `providerInstanceId` = `audit.t3.provider`, `model` = `audit.t3.model`, reasoning effort = `audit.t3.reasoning_effort` |
  | `task` | the packet path and the `ticket-audit` skill path only |

  The child follows the "delegated reviewer" rules of the `ticket-audit` skill: no `atw`, no
  hooks, no tests, and no file changes except the report. The session waits without polling or
  editing, then runs `atw accept-review`, which refuses a report when the diff changed. Outside
  T3, or when the model or the child fails, the round falls back to a Claude sub-agent. ADR 0016
  has the reasons.

  The realistic check of a big change (`verify`, ADR 0019) takes the same route, with `role`
  `test` and only the verification packet path in `task`. It is dispatched together with review
  round 1 and runs in parallel. The verifier may start the app and run the project's checks; the
  packet's rules keep its output in its own folder. If the T3 child lacks a tool the check needs
  (a browser, an MCP server), the session runs a new packet once on a Claude sub-agent.

## Adding a host

1. Find where it reads skills and instructions. If it reads `AGENTS.md` and `.agents/skills/`,
   it works now as `other`.
2. If it has hooks, map them to `atw hook stop|guard|planmode|planproposed`. The hooks read a JSON payload on
   stdin, as Claude Code sends it. A thin translator is fine.
3. Add the host to `HOST_SKILL_DIRS` in `install.py` and to `config.HOSTS`. Add detection markers
   in `detect.py`.
4. Add a test, and a row to this table.
