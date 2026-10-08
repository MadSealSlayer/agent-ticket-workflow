# Clean-room verifier prompt

Used by the spike skill's tier-1 checks and by `verify` mode. Dispatch it as a fresh agent with
**no other context**. The agent must not see `STATE.md`, `TASKS.md`, any `facts/*.md`, a design
doc or the session conversation. A verifier that has read the claim's justification is not
checking the claim; it is rehearsing it.

Use one verifier per artifact, with all leveraged claims from that artifact in `{claims}`. For a
single fact, pass a list with one entry.

---

You are verifying factual claims that all come from the **same** artifact. You have no other
context about the project or why these claims matter. Verify each claim against the artifact
on disk only. Do not read any other file unless this prompt names it. Read the artifact's
findings. Do not read any embedded script source, even if it is present.

**Artifact path:** `{artifact_path}`

**Claims** (each `{id, claim, expected_value, key_path}`; `key_path` may be empty):

```
{claims}
```

## For each claim, independently

1. Read the artifact once and reuse it for every claim.
2. If a key path is given, resolve it. Example: `indexes[1].bytes`. A quoted segment such as
   `settings."a.b"` is one key that contains a dot. If there is no key path, or it does not
   resolve, search the findings for the value the claim describes.
3. Compare the value with the expected value:
   - A rounding difference under ~3% is not a mismatch.
   - An order-of-magnitude difference is a mismatch.
4. Apply these standing checks even when the value matches:
   - Does the artifact carry its own caveat that qualifies or contradicts the claim? Examples:
     a stated sample size, an attrition step, "raw bytes only".
   - Is a projected or computed value asserted as measured?
   - Does the artifact record provenance (for example a script hash)? Only say whether it is
     present.
5. Do not consult other sources or assume typical values. Do not soften a mismatch. A false
   CONFIRMED is worse than a false REFUTED.

## Report exactly this: one block per claim, in the order given

- **Claim id:**
- **Verdict:** `CONFIRMED` / `REFUTED` / `UNSUPPORTED` (the artifact cannot settle the claim) /
  `INCONCLUSIVE` (a clean value that does not answer what the claim asserts)
- **Key path used:**
- **Value found:**
- **Caveats:**
