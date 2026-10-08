# Contributing

This workflow decides when an agent may call a ticket done. A change to a gate changes what every
team that uses it can ship, so keep changes small and well argued.

## Issues, not pull requests

This repository does not accept pull requests from outside contributors. Only the maintainer
can open them. Issues are welcome:

- **Bug:** a gate, setup step or skill did the wrong thing. Use the *Bug* template.
- **Proposal:** a new gate, kind, preset, host or behavior change. Use the *Proposal* template.
  Say what goes wrong today and how you would know the change works.

For a security problem, do not open a public issue. See [SECURITY.md](SECURITY.md).

## How changes land

The maintainer makes each change on a branch, with one concern per pull request. The pull
request template asks for evidence. CI must be green on Linux and Windows before a merge.
The rules below apply to every change.

## Rules for the code

- **The core uses the standard library only.** It is copied into other people's projects. A
  dependency there becomes their dependency.
- **Python 3.10+.** CI runs 3.10 to 3.13.
- **Determinism first.** If a script can check a fact, the script checks it, not the agent.
  Leave to the agent only what a script cannot check, and say so in the skill.
- **Never overwrite what is not ours.** Install and apply refuse when a target file is not in the
  manifest, or was edited since install. Keep it that way, and test it.
- **No org names or hardcoded remote URLs** in code, config or docs (`CODEOWNERS` is the
  exception). `tools/check_repo.py` checks this.
- **Skills:**
  - Rendered skills use only the tokens in `core/atwlib/install.py` (`tokens()`).
  - `skills/ticket-setup/` must have **no** tokens, because `install.py` copies it raw.
  - Write in plain, short sentences (ASD-STE100 style is the house standard).

## Tests

```bash
python -m unittest discover -s tests/unit -t tests/unit
```

- Every gate change needs a test that fails without the change.
- Install, apply and brownfield tests (`tests/unit/test_install.py`) must stay green. They check
  that a user's files are byte-identical after a setup that chose not to touch them.
- Test commands in tests use `tests/fixtures/minitest.py`, so the suite runs without pytest.

## Releases

1. Bump `VERSION` (semantic versioning). Change the minor version for new gates, kinds or config
   keys, and the major version for a config change that is not backward compatible.
2. Commit, tag `v<VERSION>` and push the tag.
3. Optional: build the offline zip (`python tools/make_dist.py`) and attach it to a GitHub
   release, with `gh release create v<VERSION> dist/*.zip dist/SHA256SUMS`.
4. Projects upgrade by running `install.py` from the new package and then the setup skill.
