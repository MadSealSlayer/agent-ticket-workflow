# 0003. Version 1 reads tickets from local markdown files

- Status: accepted
- Date: 2026-10-04

## Context

Teams keep tickets in different places: local files, Jira, GitHub Issues, chat.

## Decision

Version 1 finds the ticket file through `tickets.globs` in the config. The workflow never changes the ticket file. Other sources are on the roadmap.

## Consequences

Simple and offline. Teams that use a tracker copy the ticket text into a file for now.
