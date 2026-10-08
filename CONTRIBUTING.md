# Contributing

This workflow decides when an agent may call a ticket done. A change to a gate changes what every
team that uses it can ship, so keep changes small and well argued.

## How changes land

1. Open an issue for anything bigger than a fix: a new gate, a new kind, a new preset, a
   behavior change in setup. Say what goes wrong today and how you will know the change works.
2. Make a branch and keep the pull request to one concern.
3. The pull request template asks for evidence. Fill it in.
4. One approving review from a code owner (`CODEOWNERS`). CI must be green on Linux and Windows.

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
