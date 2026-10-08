---
name: {{skill.project-context-updating}}
description: Use after a code ticket's implementation. Decide whether the change is architecturally significant, and only then update the project-context index or a topic file. Not a changelog. Most runs end with "no update needed".
---

# Project context updating

The context index (`context.index` in `.atw/atw.config.json`) and its topic files are the
project's architecture reference. Keep them accurate and terse. **If in doubt, do not edit.**

## 1. What changed

```
git diff --stat <run baseline>        (or: {{atw}} status shows the run)
```

## 2. Significance filter

For each change ask: *would a developer starting a new session need this to understand the
architecture?*

- **Update for:** a new service, module, handler, endpoint, table or column, shared utility,
  message or event, data flow, config key, or a new "to do X, go to Y" pattern.
- **Skip for:** bug fixes, refactors that keep interfaces, performance work, new parameters,
  tests, helper scripts.

## 3. Update (only if warranted)

1. Read the index in full and the topic file the change belongs to.
2. Edit the file that owns the content: detail in the topic file, never in the index. A new
   topic file needs a row in the index's file list, or nothing will route to it.
3. Match the existing style: same tables, present tense, terse.

## Rules

- State what the code does now. Never "changed X to Y", "previously", "no longer", "added on".
- No dates, commit hashes or ticket ids anywhere in these files.
- Rewrite the existing sentence when a fact changes; do not add a newer one beside it.
- Keep the index short (about 150 lines). Topic files may grow; narrative may not.

## 4. Report

Tell the user which files you updated, or "No context update needed - <reason>". Then close the
ticket with `--context updated` or `--context no-op --why "<reason>"`.
