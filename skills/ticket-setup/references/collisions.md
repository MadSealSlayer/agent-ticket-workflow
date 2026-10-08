# Collisions and their options

`atw detect` lists collisions with ids like `skill:.claude/skills/ticket`. Every collision becomes
one question in the sheet. Offer only the options listed for its type. Explain what each option
means for this project in one line, and give your recommendation and why.

| Option | Meaning |
|---|---|
| `merge` | Ours is added next to theirs: our marked block in the file, or our hook entries appended after theirs. Theirs is kept byte-for-byte. |
| `namespace` | Ours is installed under another name, for example `atw-ticket`, so both exist. |
| `skip` | Ours is not installed for this item. Say what the workflow loses (for example "no Stop gate in Claude Code"). |
| `abort` | Stop the setup. Nothing is written. |

## By type

**`skill:<dir>/<name>`: a skill with our name exists.** Options: namespace, skip, abort.
Read their skill first. If it is an earlier version of the same workflow (for example a project
that grew its own `/ticket`), say so. Recommend `namespace` so both can run side by side, and
let the team retire theirs later. Never overwrite it. Record the chosen name in the plan's
`skills` map. Every installed skill and instruction block refers to the new name.

**`command:<dir>/<name>`: a slash command with our skill's name.** Options: namespace, skip,
abort. A command and a skill with one name shadow each other. Recommend `namespace`.

**`hooks:<settings file>:<event>`: existing hooks on an event we use.** Options: merge, skip,
abort. Read each listed hook script. Explain what it does and whether it overlaps ours. A Stop
hook that also blocks the turn is the important case: two gates can both block, which is safe
but noisy. A PreToolUse guard that denies the same commands is harmless. `merge` appends our
entries; theirs keep running first. Hooks in `settings.local.json` are personal. Mention them.
Only add our entries there when the user chose `claude_settings: local`, and keep theirs as
they are.

**`instructions:CLAUDE.md` / `instructions:AGENTS.md`: the file exists.** Options: merge, another
file, skip, abort.
- For `AGENTS.md`, `merge` adds our instructions block at the end.
- For `CLAUDE.md`, `merge` adds only the bridge: a marked block with one line, `@AGENTS.md`.
  Our instructions live in one file.
- Both are shown in the dry run.
- "Another file" sets `instructions` or `claude_bridge` to a file the user picks, for example
  `CLAUDE.local.md` or `.atw/AGENTS.md`.

In local mode, a tracked file is skipped by default. Read the file. If it already describes a
ticket workflow, point out the overlap, and suggest that the user reconcile the text afterwards.
Do not edit their part.

**`workflow:<pattern>`: a similar practice exists** (plan mode, TDD, review agents, gates,
spec-driven development). Options: merge, skip, abort. This is about habits, not files. Read the
places listed. Ask whether our workflow should replace that practice for tickets (merge: both
exist, ours is used for tickets), stay out of it (skip: for example, do not install the kind
that overlaps), or whether setup should stop. For spec-driven setups (OpenSpec, spec-kit), note
the planned lightweight mode on the roadmap and ask whether per-ticket plans fit how this team
works.

**`settings:<file>`: settings file is invalid JSON.** Options: skip, abort. Never repair it
yourself; the user fixes it, then re-runs setup.

**`dir:.atw`: an `.atw/` folder exists without our manifest.** Option: abort. Something else
uses that name; the user must decide what to do with it.

## Record

For every collision, write the decision into `decisions` in the install plan:
`{"item": "<collision id>", "choice": "<option>", "by": "user", "why": "<their reason>"}`.
