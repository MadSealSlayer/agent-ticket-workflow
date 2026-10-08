---
name: {{skill.ticket-investigation}}
description: Sub-skill of the ticket workflow for investigation tickets. Plan the questions first, gather evidence with the project's own data tools, fan out only independent questions to cheap sub-agents, and write findings with sources.
argument-hint: <ticket-id>
---

# Investigation

This adds investigation-specific guidance to the `{{skill.ticket}}` workflow's non-code path.
Gates, placement and the close procedure stay as that skill describes.

## 1. Plan the questions before touching any data

Write a short investigation plan, with minimal context:

- What exactly must this ticket answer? What would count as an answer?
- Which environment, which time window, which records? **If the ticket does not say, ask the
  user.** Never assume production versus staging, or a time window.
- Which data sources answer each question? Most tickets need one or two, not all.

## 2. Use the project's own tools and credentials

Investigation data sources are project-specific. Look for them in this order, and use what
exists instead of writing raw clients or SQL from scratch:

1. The investigation notes in `.atw/atw.config.json` (`investigation.tools`,
   `investigation.notes`) if the setup recorded any.
2. Helper modules or scripts the project already has for logs, databases and queues (search
   the tooling and scripts folders, and the project's instruction files).
3. Only then, standard CLIs or SDKs, read-only.

Credentials, profiles and account ids come from the project's configuration, never from the user
restating them in chat. If configuration is missing, say exactly what is missing and wait.

**Read-only by default.** Never write to, restart or redeploy anything during an investigation.
If a fix seems needed, that is the user's decision: offer to re-kind to code, or a new ticket.

## 3. Fan out only what is independent

If the plan has questions that are truly independent (one log group over one window, one record
lookup, one table count), you may dispatch one cheap sub-agent per question, in parallel. The
right number is sometimes zero. A question answered by reading code needs no fan-out.

A dispatched agent starts with none of this context. Its brief must state, by name: the exact
question, the tool or module to use, the environment and window, "read-only", and the
return format. Each agent returns **distilled findings**: the answer, the evidence (ids, counts,
timestamps, the query used) and what came back empty or ambiguous. No raw dumps.

## 4. Write findings with provenance

Write to the investigation folder (`placement.investigation`), with the ticket id in the file
name. Required shape:

```
# <TICKET> - <short title>

## Question
## Findings
- Error rate rose to 6 of 343 requests on 2026-10-01 (measured, [S1]).
- The spike most likely came from cold starts (inferred, [S1], [S2]).
## Unknowns and not checked
## Sources
- [S1] <tool/query/command, environment, time window>
- [S2] <file:line or document>
```

`measured` means you observed it in data. `inferred` means you reasoned to it. Every tagged
claim cites a source id. The `provenance` gate checks this shape.

Then present the substance in chat and hand the decision back, as the ticket skill says.
