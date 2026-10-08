# 0006. Gates run configured commands; presets supply defaults

- Status: accepted
- Date: 2026-10-04

## Context

The original gates were written for pytest, ruff and requirements.txt. Other projects use vitest, jest, go test, eslint and npm.

## Decision

Gates run commands from the config. The proof command must write JUnit XML; the core decides red and green for the proof set from that XML, not from exit codes. The wider tests command and lint pass on exit code. Stack presets supply detected defaults. Setup proves each command on this machine before it relies on it.

## Consequences

Any stack works if its test runner can write JUnit XML. Changed-lines lint needs a parser per output format (ruff, eslint now; more on the roadmap).
