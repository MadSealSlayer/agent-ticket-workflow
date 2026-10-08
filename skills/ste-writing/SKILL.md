---
name: {{skill.ste-writing}}
description: Use when writing or editing project documentation, investigation findings or comms drafts produced by the ticket workflow. Applies Simplified Technical English (ASD-STE100) rules to that prose. Not for chat replies or code.
---

# STE writing (advisory)

These rules adapt ASD-STE100 Simplified Technical English for software text. They are a
paraphrase; the official STE dictionary is not included, so use the plainest common word and
use it consistently.

## Scope

Apply to Markdown deliverables of the ticket workflow (the `placement` folders in
`.atw/atw.config.json`) and to the project's documentation. Do not apply to chat replies,
code or string literals.

## Never change

Code, identifiers, file paths, commands, flags, quoted errors, numbers, units, product names
and facts. If a rule conflicts with an exact literal, keep the literal.

## Rules

1. Put the condition before the command: "If the tunnel fails, restart it."
2. An instruction has 20 words at most; a description has 25 at most. One instruction per sentence.
3. Use the active voice and name the actor: "The handler writes the row."
4. Use simple tenses. Not "has been", "is running", "would have".
5. Use only "can", "must" and "will" as modals. A required "should" becomes "must"; an optional
   one is deleted. No "may", "might", "could", "would".
6. No semicolons, contractions or Latin abbreviations ("e.g.", "i.e.", "via", "etc.").
7. One word for one meaning in a document.
8. Define a term at first use, in fewer than ten words. Standard names need no definition.
9. No noun chains longer than three words. Use a preposition instead.
10. One topic per paragraph, six sentences at most.

State current behavior, not history. Do not reference ticket ids in permanent docs.

This check is advisory: fix a violation when the fix keeps the meaning, and do not rewrite text
you did not change.
