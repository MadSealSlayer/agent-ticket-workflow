# 0015. A ticket can be written from the conversation, once

- Status: accepted
- Date: 2026-11-24
- Amends: [0003](0003-local-markdown-tickets.md)

## Context

0003 says that the workflow never changes the ticket file, and that the ticket comes from
somewhere else. In practice the user is often not the ticket owner, and there is often no ticket
at all. The user talks with the agent, they settle what to change, and then the user says "make
a ticket from this". The user then had to write the file by hand before `/ticket` could start.

## Decision

- `atw new-ticket --title "<title>" --body-file <path>` creates a ticket file from a draft that
  the agent wrote from the conversation. The agent writes the body to a file; ticket text never
  goes on a command line.
- The agent must show the full draft and get the user's explicit approval first. Nothing is
  written before that. The draft has fixed sections: problem / goal, settled decisions,
  acceptance criteria, out of scope, open questions. Only what the user stated or agreed to goes
  in; unknowns go to open questions. The CLI refuses a body without these sections.
- The CLI takes the next free number among the ticket files that `tickets.globs` finds. The
  path comes from `tickets.new` (`path`, `id_format`, `range_size`). Line 1 is
  `Source: conversation <date>`, like the `Jira:` line of an imported ticket.
- The file is created once (exclusive create) and is never overwritten. The CLI refuses a path
  that `tickets.globs` would not find. After creation the file is read-only to the workflow, as
  0003 says. A change of scope is a new conversation, not an edit.
- After `start`, the agent records each settled decision with `atw decide --verdict
  settled-question`, so the clean-room reviewer does not raise it again.

## Consequences

The agent writes a ticket file, which 0003 did not allow. The exception is narrow: one write, at
creation, after the user's yes, through the CLI. The quality of the ticket depends on the agent's
draft and the user's review of it. A script cannot check that the draft is faithful to the
conversation; it checks only the shape.
