# 0004. Setup runs inside an agent session, with a question sheet

- Status: accepted
- Date: 2026-10-04

## Context

Brownfield projects already have hooks, skills, instruction files and habits. A script cannot judge them well; an agent left alone will make decisions that belong to the user.

## Decision

`install.py` only stages the package and copies the setup skill. `/ticket-setup` does read-only discovery, and writes a question sheet. The agent decides only items that have one obvious answer, are reversible and touch nothing existing. The user answers everything else. `atw apply` writes only an approved plan.

## Consequences

Setup takes a conversation, not one command. The sheet stays in the repo as the record of why the project is set up this way.
