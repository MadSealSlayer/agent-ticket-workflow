# Experimental: spike sessions

**Read this before you enable the spike kind.**

This workflow is a port of a spike harness that was used **once**, on one long measurement spike
that ran over several sessions. It worked, but only with **a lot of human steering**:

- The human had to read the state file closely and push back. Twice, the agent recorded a
  recommendation as a decision that nobody had made.
- The first version optimised for facts, not decisions. Four sessions produced many facts and
  no prototype. The tiers, the backlog split and the cost line came from that lesson.
- The original had a project-specific helper kit: a validator for the fact ledger, a credential
  preflight, and an artifact writer. **That kit is not included here.** The rules that the
  validator enforced are now process rules that the agent must follow. Nothing checks them
  mechanically.

So:

- It is **not battle tested**. Expect to steer it.
- No gate is armed for the `spike` kind. `atw close` records the run, and that is all.
- **A rebuild is recommended** before the team relies on it. See `ROADMAP.md` ("Spike rebuild").
  A rebuild should bring back a mechanical ledger check.

Install it only if you plan a multi-session, measurement-heavy investigation and accept the
steering cost. Setup asks before it installs this, and the default answer is no.
