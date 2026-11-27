# 0017. The guard parses commands and has named git rules

- Status: accepted
- Date: 2026-11-24

## Context

Until 0.3.0, the PreToolUse guard searched the `guards.deny` and `guards.ask` regexes in the raw
command text. A command that only mentioned a guarded command was blocked too:
`echo "git commit"`, `sed -i 's/git push/x/' f`, `grep -n 'git rebase' f`, a commit message, or a
heredoc body that documents `git push --force`. A project whose policy is "agents never commit or
push" adds `\bgit\s+commit\b` and `\bgit\s+push\b` to `guards.deny`, and then every such mention
is denied. The agent must work around its own guard to write docs or tests.

A pilot project's own guard had already solved this. It parses the command into the commands
that it runs and applies its rules to each one.

## Decision

- A new module `shell.py` parses a Bash or PowerShell command line, best effort: it removes
  heredoc and here-string bodies and `#` comments, splits on separators outside quotes, makes
  command substitutions and `bash -c` / `pwsh -Command` scripts commands of their own, removes
  `VAR=x` and wrapper commands, normalizes the command word, and skips git global options.
- A new module `guard.py` holds the rules. Every rule is checked on every command. A deny wins
  over an ask.
- `guards.git` holds named git rules (`reset-hard`, `push-force`, `push-delete`, `push`,
  `rebase`, `clean-force`, `commit-amend`, `commit`, `filter-branch`, `update-ref-delete`,
  `reflog-expire`), in a `deny` and an `ask` list. `config.validate` refuses unknown names.
- The defaults give the same result as the old default regexes: deny `reset-hard`,
  `push-force`, `rebase`, `clean-force`, `commit-amend`; ask `push`. The default `guards.deny`
  and `guards.ask` are now `[]`.
- Two new asks, on by default: `guards.git_add_data` (`git add` of data, binary or very large
  files) and `guards.test_delete` (a shell command that deletes a test file).
- `guards.deny` and `guards.ask` stay for custom rules. They are searched in the text of each
  parsed command, with heredoc bodies removed. Quoted text inside a command still matches.
- Session binding uses the parsed commands too.
- `atw doctor` warns about the old default git regexes (and `\bgit\s+commit\b` /
  `\bgit\s+push\b`) in a project's config and prints the `guards.git` block that replaces them.
  It never rewrites the config.

## Consequences

Text that mentions a git command is no longer blocked. A git command is still found behind
`sudo`, `env`, `VAR=x`, a full path, `.exe`, `git -C <dir>`, a pipe, a subshell, a command
substitution or `bash -c`.

The parser is not a shell. Git aliases (`git ci`), `eval`, and scripts that a command runs are
not looked into. The guard is a safety net for an agent that follows its instructions, not a
sandbox.

A project config that keeps the old regexes works as before, with the old false positives,
until it is changed. Such a config also gets the default `guards.git` rules through the merge
with the defaults. A project that had turned the git rules off with `"deny": []` must now also
write `"git": {"deny": [], "ask": []}`.
