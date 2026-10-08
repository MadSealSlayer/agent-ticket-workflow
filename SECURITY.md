# Security policy

## Reporting a vulnerability

Do not open a public issue for a security problem. Use GitHub's private reporting instead:
the **Security** tab of this repository, then **Report a vulnerability**.

Include the version (`python .atw/core/atw.py version`), the host (Claude Code, Codex or other),
and the steps to reproduce it.

## Scope

The workflow runs commands from your own `.atw/atw.config.json` and installs Claude Code hooks
into your project. Reports about these are in scope, for example:

- a hook or gate that runs something the config did not ask for;
- install or apply writing outside the files it owns;
- a guard rule that can be bypassed.

## Supported versions

Only the latest release gets fixes.
