## What and why

<!-- What goes wrong today, and what this change does about it. Link the issue. -->

## Kind of change

- [ ] Fix
- [ ] Gate or state engine behavior (core)
- [ ] Setup, detection or install
- [ ] Skill or adapter text
- [ ] Preset
- [ ] Docs only

## Evidence

<!-- A test that fails without this change, or a before/after run. Paste the command and output. -->

- [ ] `python -m unittest discover -s tests/unit -t tests/unit` passes
- [ ] A new or changed gate has a test that fails without the change
- [ ] Install and apply still refuse to overwrite files that are not ours
- [ ] Core still uses the standard library only
- [ ] `skills/ticket-setup/` has no `{{tokens}}`
- [ ] No org names, owners or URLs added
- [ ] `VERSION` bumped, if this is a release

## Effect on installed projects

<!-- Does an upgrade change config keys, hook entries or skill names? What must users do? -->
