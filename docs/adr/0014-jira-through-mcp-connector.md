# 0014. Jira through the host's MCP connector

- Status: accepted
- Date: 2026-11-12
- Amends: [0003](0003-local-markdown-tickets.md)

## Context

Teams that track tickets in Jira copied the ticket text into a file by hand (0003). The roadmap
planned a read-only fetch with credentials from the user's environment. A pilot project used the
Atlassian MCP connector instead: the host already holds the user's sign-in, so no token reaches
the repository or the core, and the agent can also comment and move issues with the user's
approval.

## Decision

- The core never calls Jira and stays standard-library only (0002). The agent fetches an issue
  through the host's Atlassian MCP connector.
- `atw import-jira --issue-file <json>` turns a fetched issue into `<jira.import_dir>/<KEY>.md`.
  The ticket id is the Jira key. The file is created once and never overwritten. Jira text is
  passed in a file, never on a command line, where it could reach a shell.
- The ticket file keeps the owner's `## My notes` apart from `## From Jira`, which is quoted. Only
  the notes and the user's chat are instructions. Jira text is context written by other people.
- A `jira` skill holds the rules: nothing automatic, every write (comment, status change) needs
  the user's yes to the exact content, and Jira failures never block the local work.
- Moving a To Do issue to a working status at start of work is a project setting,
  `jira.start_transition`, off by default. When it is off, the agent asks.

## Consequences

Jira needs a host with an MCP connector. Without one, the workflow runs as before from local
files. GitHub Issues and pasted text stay on the roadmap.
