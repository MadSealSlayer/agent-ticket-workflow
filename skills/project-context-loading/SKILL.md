---
name: {{skill.project-context-loading}}
description: Use when you receive a task to plan, implement, explore or debug. Read the project-context index with the task in mind, load only the topic files the task touches, and assert the engineering rules before work begins.
---

# Project context loading

The project keeps a short **index** of its architecture (path: `context.index` in
`.atw/atw.config.json`) and longer **topic files** next to it. The index is always read; topic
files are read only when the task touches their topic.

## When

When you have a task: planning, implementing, exploring or debugging. The trigger is the task,
not the session start. You need the task to know which topics to load.

## Process

1. **Understand the task.** Which components, data flows, tables, shared modules does it touch?
2. **Read the index in full.** It is short by design. Always internalize its cross-cutting rules
   section; those apply whatever the topic.
3. **Load the relevant topic files in full.** Use the index's "load when" column. When unsure
   whether a topic applies, read it. A wrong skip costs more than a read.
4. **Acknowledge** in one line: "Project context loaded: <topic files> because <reason>." Do not
   recite their contents.

If the index does not exist yet, say so, read the project's instruction files and the code the
task touches, and suggest creating the index after the ticket (`{{skill.project-context-updating}}`).

## Engineering rules (non-negotiable on code tickets)

- **No assumptions.** Verify behavior against code and tests, never against what "should" happen.
  New behavior is covered by tests, including edge cases: empty and null input, boundaries,
  error and timeout paths, fallbacks.
- **Red first, on behavior.** A new test must fail against the old code because the behavior is
  wrong, then pass after the change. A failure from a missing import or name proves nothing.
  `{{atw}} red` enforces this.
- **Blast radius.** Before finishing, find every consumer of what you changed (callers,
  importers, producers and consumers of changed data) and check them. Shared modules first.
- **Import-check every new file** once (import it, or run it with a dummy entry point) before it
  is wired in.
