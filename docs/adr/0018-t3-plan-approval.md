# 0018. In T3 Code, the plan is approved through an AskUserQuestion

- Status: accepted
- Date: 2026-11-24

## Context

On Claude Code, the plan gate checks a stamp that a `PostToolUse` hook writes when
`ExitPlanMode` succeeds ("User has approved your plan..."). Inside T3 Code, `ExitPlanMode`
always returns a tool error: "The client captured your proposed plan. Stop here and wait for the
user's feedback or implementation request in a later turn." A failed tool call never fires
`PostToolUse`, so the stamp is never written and `atw plan` refuses. Agents then used the
`--no-plan-mode` escape hatch or worked around the gate, and the Stop hook blocked the turn
that T3 had told to stop, pushing the agent on without an approval.

## Decision

- A `PreToolUse` hook on `ExitPlanMode` (`atw hook planproposed`) stamps "plan proposed". It
  fires in T3 too, before T3 rejects the call. It never blocks and fails open.
- The ticket skill then asks `AskUserQuestion`, which T3 renders, the way Claude Code's own plan
  dialog asks: one question, header `Plan`, question "Approve this plan?", options `Approve`
  ("Start implementing this plan") and `Decline` ("Don't implement; tell me what to change").
  The user may type their own text instead.
- The `PostToolUse` hook (`atw hook planmode`) now also matches `AskUserQuestion`. It finds the
  question whose header is `Plan` and reads its answer from `tool_input.answers` (keyed by the
  question text), or from `tool_response`. An answer of exactly `Approve`, to a proposal made
  after the run started and after the last approval and the last decline, writes the same
  approval stamp that `ExitPlanMode` writes. `Decline` or free text is recorded as a decline and
  consumes the proposal, so a later stray `Approve` cannot approve a plan the user rejected.
- The proposal, the approval and the decline use the same keys as the approval stamp had: the
  bound session's ticket, else the branch when it has an open run that no session drives.
- The approval stamp keeps its format (an ISO time). A JSON record next to it names its route
  (`exit-plan-mode` or `ask-approve`), the answer and any notes; `atw plan` copies the route into
  the plan gate's evidence. A stamp without a matching record counts as `exit-plan-mode`.
- When the plan gate is unmet and a proposal waits for an answer, the Stop hook's plan hint says
  to ask the `Plan` question instead of "call EnterPlanMode, then ExitPlanMode". The Stop hook
  is otherwise unchanged.
- Setup registers the new `PreToolUse` entry and the wider `PostToolUse` matcher. `apply`
  replaces our old hook entries on an upgrade; `atw doctor` fails when the installed entries do
  not cover `PreToolUse:ExitPlanMode` and `PostToolUse:AskUserQuestion`.

## Consequences

Plan approval works in T3 without the escape hatch, and the native path is unchanged. The hook
trusts `tool_input.answers` as the host UI filled it: an agent that fabricated the answer in its
own tool call could pass the gate. That is the same level of trust the native route gives the
host's plan dialog. An install that is not upgraded keeps working natively but cannot approve a
plan in T3, and doctor says so.
