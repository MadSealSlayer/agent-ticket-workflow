# Ticket workflow setup: questions and decisions

This file records how the ticket workflow was set up in this project, and why. The next person
who upgrades it starts from here. In commit mode, commit it with the rest. In local mode, it
stays in `.atw/` on this machine.

- Git mode: <local (only on this machine) | commit (shared through the repository)> - the user's answer
- Package version: <version>
- Setup mode: <fresh | upgrade | reinstall>
- Date: <YYYY-MM-DD>
- Run by: <name>

## Discovery summary

<at most 15 lines: stack, how tests run (with evidence), existing agent setup, similar practices>

## Decided for you

Only items with one obvious answer, which are reversible and touch nothing existing. Change any
of them in `.atw/atw.config.json`, or tell the agent during setup.

| Item | Value | Evidence | Config key |
|---|---|---|---|
| <item> | <value> | <file / CI step> | <key> |

## Questions for you

### Q1. <question>

- Options: <a> / <b> / <c>
- Recommendation: <option>, because <reason>
- Evidence: <what was found>
- **Answer:** <the user's answer, in their words>

## Collisions

| Id | What | Decision | Why |
|---|---|---|---|
| <collision id> | <what exists> | <merge / namespace / skip / abort> | <reason> |

## Not touched

<existing files, hooks and skills this setup deliberately left alone>
