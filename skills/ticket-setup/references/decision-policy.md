# Decision policy: what the agent may decide alone

You may decide an item **only if all three are true**:

1. **One obvious answer.** The evidence points to exactly one sensible value, and you can cite it
   (a file, a config line, a CI step). "Most projects do X" is not evidence.
2. **Reversible.** The user can change it later by editing `.atw/atw.config.json`, with no
   migration and no lost data.
3. **Touches nothing existing.** It does not change, shadow or overlap anything already in the
   project: no existing file edited, no skill or command name reused, no existing practice
   replaced.

Everything you decide goes into the sheet's **Decided for you** section, with its evidence and the
config key to change it. Read that list to the user before the plan is approved, so they can
override any item.

## Never decide alone

These always go to the user, even when the answer looks obvious:

- **Whether the install is local only or committed to git (`git_mode`).** Ask it first, every
  time there is no recorded answer.
- Which hosts (agents) the team uses.
- Which ticket kinds are enabled, and whether the experimental spike is installed.
- `protected_paths` and `test_paths`: they define what "code" means for every future ticket.
- Any command that runs code: proof, tests, lint, deps.
- How strict the workflow is: simplify mode, test scope, guard rules.
- Every collision, whatever its type.
- Any change to an existing file, including adding our marked block or hook entries.
- Whether investigation and comms notes are committed or kept local.
- Where tickets live, if more than one candidate exists or none does.

## Typical straightforward items

- `python` for gates: the project's virtualenv interpreter when one exists and works (evidence:
  `.venv/pyvenv.cfg`, a CI step that uses it).
- The hook launcher (`python`, `python3` or `py`): whichever command you just ran successfully.
- `audit.model`: `opus` (Claude Code only, no effect elsewhere).
- `timeouts.command_seconds`: 600, unless the test suite you measured takes longer.
- `tickets.globs`: when exactly one ticket folder exists and its file names show one clear
  pattern (for example `tickets/**/ticket-{id}.md`).
- `id_style` and placeholders: fixed by the chosen preset.

When in doubt, it is a question.

## Keep it surgical

The workflow goes into projects that already work. Prefer the smallest change that does the
job:
- Every shared-file item (`instructions`, `claude_bridge`, `claude_settings`, `ignore`) can
  point to another file or be `skip`. Offer that whenever the default would touch something the
  user cares about.
- Do not push for the defaults. A setup with fewer touchpoints, chosen by the user, is a good
  result.
- Never edit a user's file to make a check green. `doctor` warnings about choices the user made
  are expected. Explain each one in one line, and leave it.
