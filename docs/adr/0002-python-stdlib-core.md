# 0002. Python standard library only for the core

- Status: accepted
- Date: 2026-10-04

## Context

The core is copied into other teams' projects, including frontend projects that may not use Python for anything else.

## Decision

The core uses Python 3.10+ and the standard library only. It is ported from the original scripts, not rewritten.

## Consequences

There is nothing to install beyond Python. Some parsing (JUnit, lint JSON) is done by hand. A frontend project needs Python 3.10+ on the developer's machine.
