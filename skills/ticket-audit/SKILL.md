---
name: {{skill.ticket-audit}}
description: Clean-room review of a ticket's change from a review packet made by `atw review-packet`. Use only as the fresh reviewer the ticket workflow dispatches; never to review your own work.
argument-hint: <path to review packet>
---

# Clean-room review

You review a change **you did not write**. Your inputs are the review packet, the patch file it
names, and the repository. Do not read or ask for the author's plan, notes or conversation. If
you remember writing this change, stop: you are not a valid reviewer for it. Say so.

Your job: find regressions, unhandled edge cases, and gaps against the ticket's requirements.
It is not to grade style. Lint already covers style.

## 0. Read the packet

The packet's header gives `packet`, `patch`, `report` and the implementer id. It contains the
ticket text verbatim and the **settled decisions**. Every settled decision is closed: never
raise it as a finding, even if you would have decided differently.

**Delta mode (round 2+):** if the packet has a "Delta mode" section, review only (a) whether
each listed open item is resolved, cleanly, and (b) the lines that changed since the previous
round's patch. Do not re-review the whole diff.

If the patch is empty, say so in the Summary and write a report with empty sections. Do not
invent findings.

## 1. Review: five checks, one pass, by you alone

Stop early on a check when there is nothing to find, and say so. Do not manufacture findings.

1. **Intent.** Does the change do what the ticket asks? A requirement with no code change is a
   gap. For each requirement with a test, does the test assert the new behavior, not just that
   the code runs? A requirement covered only by a smoke test is Partial.
2. **Correctness and edge cases.** Off-by-one, inverted conditions, empty input, null/None,
   zero, negative values, boundaries, time zones, encoding.
3. **Error handling.** Swallowed exceptions, errors logged but not raised when the caller needs
   them, unguarded indexing, a nullable result used unchecked.
4. **Side effects and integration.** This is the one check that may look outside the diff. Do
   it only when the diff changes something with a plausible external consumer: a signature, an
   exported symbol, a data model, a message or event payload, a config key, a shared module. If
   it does, search (grep) for importers, call sites, producers and consumers. Delegate that
   search to one cheap helper agent if your host has them. The helper returns facts only; you
   judge. If nothing is exported or shared, write "no shared symbols changed" and move on.
5. **Population and denominator.** Whenever the diff counts, aggregates or divides: is the set
   it works on the set it claims? Is the work gated (caches, unchanged-hash skips, early
   returns), so touched does not mean processed? Is a pooled denominator mixing populations?
   Do the parts sum to the whole? A plausible number is not a verified number.

Report only gaps that affect correctness or a stated requirement. No speculative abstractions,
no defensive code for impossible cases.

## 2. Triage: introduced or pre-existing

For each file with a finding, check once whether the same problem exists before the change (the
packet's patch shows the old lines; `git show <baseline>:<file>` or `git log -L` also works).

- **Introduced by this change:** Critical or Warning. It blocks.
- **Pre-existing:** list it under "Pre-existing". It does not block. Do not argue it as new.

## 3. Write the report

Write the report to the exact path in the packet's `report:` line. The first two lines must be:

```
packet: <the packet id>
reviewer: <your id - anything except the implementer id>
```

Then:

```
## Intent check
| Requirement | Implementing code | Complete / Partial / GAP |

## Critical - blocks merge
- [ ] `file:line` - what is wrong and what to fix

## Warning - blocks merge
- [ ] `file:line` - ...

## Nit
- [ ] `file:line` - ...

## Pre-existing (not blocking)
- `file:line` - ...

## Summary
One paragraph: overall assessment, biggest risk, next step. Say if a check was cut short.
```

Keep the Critical, Warning and Nit headings **even when they are empty**. A report without them
is treated as unreadable, not as clean. Never use the words "critical", "warning" or "nit" in
the Pre-existing heading.

Do not edit any other file. When done, reply with the report path and a one-line verdict.
