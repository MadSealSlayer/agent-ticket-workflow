<!-- atw:begin -->
## Ticket workflow

Tickets in this repository go through the agent ticket workflow. Start every ticket with the
`{{skill.ticket}}` skill:
- Claude Code: `/{{skill.ticket}}`
- Codex: `${{skill.ticket}}`
- other agents: read `{{skill_dir}}/{{skill.ticket}}/SKILL.md`

The user starts a ticket. In Claude Code only the user can invoke the skill. If you are asked to
work on a ticket without it, ask the user to run `/{{skill.ticket}} <TICKET>`.

The skill classifies the ticket, plans it with the user, proves red, runs fresh gates, gets a
clean-room review and closes with evidence. The state engine is `{{atw}}`.

- Open a run: `{{atw}} start <TICKET> --kind <kind>` (enabled kinds: {{kinds}}).
- **Plan (code tickets).**
  - Claude Code: use plan mode. A hook records the approval.
  - Other agents: plan with your host's planning mode and save the plan to
    `{{plan_dir}}/<TICKET>.md`. Ask the user for an explicit yes, then run
    `{{atw}} plan --files "..." --plan-file <path> --approval "<the user's words>"`.
- **Before ending a turn while a run is open:**
  - Claude Code: the Stop hook checks the gates for you.
  - Other agents: run `{{atw}} status`. If anything is unmet, keep working. Stop only to ask the
    user a question that is genuinely theirs.
- Never skip, fake or reorder a gate. A refusal names the next step, so follow it.
- Ask the user whenever a decision is theirs. Follow the approved plan, and re-plan with the
  user if it stops fitting.
- Commit locally only when the user asks, and only if the project's own rules allow it. If they
  forbid commits, they win. Never push.

Configuration: `.atw/atw.config.json`. Installed by agent-ticket-workflow {{version}}.
<!-- atw:end -->
