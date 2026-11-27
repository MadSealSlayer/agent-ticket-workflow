"""Best-effort shell command parsing for the guard hook.

Not a real shell parser. It finds the commands that a Bash or PowerShell
command line runs, so that guard rules apply to a command, and not to text
that only mentions one: `echo "git commit"`, `grep 'git rebase' f`, or a
heredoc body that says "never git push --force".

    segments(cmd)          heredoc bodies removed, split on ; & && || | newlines,
                           ( ) and command substitution $( ) / backticks
    tokens(seg)            quote-aware split, quotes removed
    normalized(seg)        tokens without leading VAR=x and wrapper commands,
                           command word as a lowercase basename without .exe
    git_invocation(toks)   (subcommand, args, -C dir) of a git command

Separators inside quotes do not split. Command substitution splits also
inside double quotes, because the shell runs it there. `bash -c "..."` and
`pwsh -Command "..."` are parsed again, one level deep.
"""
from __future__ import annotations

import re

WRAPPERS = {"sudo", "doas", "env", "time", "nohup", "npx", "command", "exec", "builtin", "xargs", "nice",
            "&", "."}
# Wrapper options that take the next token as their value (sudo -u USER ...).
_WRAPPER_ARG_OPTS = {
    "sudo": {"-u", "-g", "-C", "-D", "-U", "-p", "-r", "-t"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-s", "-E", "-a"},
    "nice": {"-n"},
}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "pwsh", "powershell", "cmd"}
_SHELL_SCRIPT_OPTS = {"-c", "-command", "/c", "/k"}
_VAR_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC_START = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][\w.-]*)\1")
# PowerShell here-strings: @' ... '@ and @" ... "@ (the closer starts a line).
_HERESTRING_START = re.compile(r"@(['\"])\s*$")

# git global options that take the next token as their value.
_GIT_ARG_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                 "--super-prefix", "--config-env", "--list-cmds", "--attr-source"}


def strip_heredocs(cmd: str) -> str:
    """Remove heredoc bodies (`<<'EOF' ... EOF`, `<<-EOF`) and PowerShell
    here-string bodies (`@' ... '@`). A body is data for a command, never a
    command itself."""
    lines = (cmd or "").split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HEREDOC_START.search(line)
        if m and not _inside_quotes(line, m.start()):
            delim = m.group(2)
            out.append(line[:m.start()] + line[m.end():])  # keep `| git commit -F -` after <<'EOF'
            i += 1
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
            i += 1
            continue
        h = _HERESTRING_START.search(line)
        if h:
            closer = h.group(1) + "@"
            out.append(line[:h.start()])
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith(closer):
                i += 1
            if i < len(lines):  # keep what follows the closer, e.g. `'@ | git commit -F -`
                out.append(lines[i].lstrip()[len(closer):])
            i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _inside_quotes(line: str, pos: int) -> bool:
    """True if `pos` is inside a quoted string. A command substitution starts
    unquoted, also inside double quotes: `git commit -m "$(cat <<'EOF'`."""
    quote = None
    text = line[:pos]
    for i, ch in enumerate(text):
        if quote == "'":
            if ch == "'":
                quote = None
        elif quote == '"' and (ch == "`" or (ch == "$" and text[i + 1:i + 2] == "(")):
            quote = None
        elif quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
    return quote is not None


def split_segments(text: str, powershell: bool = False) -> list[str]:
    """Split on command separators that are outside quotes. A command
    substitution ($( ) or backticks in Bash, $( ) in PowerShell) becomes a
    segment of its own; the outer segment keeps going without it."""
    segments: list[str] = []
    stack: list[tuple[list[str], str | None, str]] = []  # saved (chars, quote, closer)
    current: list[str] = []
    quote: str | None = None
    closer = ""  # ")" or "`" while inside a substitution
    i, n = 0, len(text)

    def flush():
        nonlocal current
        segments.append("".join(current))
        current = []

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if quote == "'":
            current.append(ch)
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\" and not powershell and nxt:
            current.append(ch + nxt)
            i += 2
            continue
        if ch == "`" and powershell and nxt:  # PowerShell escape character
            current.append(ch + nxt)
            i += 2
            continue
        # Command substitution: also runs inside double quotes.
        if (ch == "$" and nxt == "(") or (ch == "`" and not powershell and closer != "`"):
            stack.append((current, quote, closer))
            current, quote, closer = [], None, (")" if ch == "$" else "`")
            i += 2 if ch == "$" else 1
            continue
        if stack and quote is None and ch == closer:
            flush()
            current, quote, closer = stack.pop()
            current.append("$()")
            i += 1
            continue
        if quote == '"':
            current.append(ch)
            if ch == '"':
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            continue
        if ch == "#" and (i == 0 or text[i - 1] in " \t\n;&|(") and closer != "`":
            while i < n and text[i] != "\n":  # a comment, up to the end of the line
                i += 1
            continue
        if ch in ("&", "|") and nxt == ch:
            flush()
            i += 2
            continue
        if ch == "&" and ((i > 0 and text[i - 1] in "<>") or nxt == ">"):
            current.append(ch)  # a redirection (2>&1, &>), not a separator
            i += 1
            continue
        if ch in "|;&\n()" or (ch in "{}" and (powershell or not _brace_word(text, i))):
            flush()
            i += 1
            continue
        current.append(ch)
        i += 1
    flush()
    while stack:  # unterminated substitution: keep the outer text too
        current, _, _ = stack.pop()
        flush()
    return segments


def _brace_word(text: str, i: int) -> bool:
    """True for a `{` or `}` that is part of a word (`${VAR}`, `a{b,c}`, `@{u}`),
    not a Bash group `{ cmd; }`."""
    before = text[i - 1] if i > 0 else " "
    after = text[i + 1] if i + 1 < len(text) else " "
    if text[i] == "{":
        return not ((before.isspace() or before in ";&|(") and after.isspace())
    return not ((before.isspace() or before == ";") and (after.isspace() or after in ";&|)"))


def segments(cmd: str, powershell: bool = False, _depth: int = 0) -> list[str]:
    """Every command in `cmd`, heredoc bodies removed. The script of
    `bash -c "..."` / `pwsh -Command "..."` is added as more segments."""
    out = []
    for seg in split_segments(strip_heredocs(cmd or ""), powershell):
        seg = seg.strip()
        if not seg:
            continue
        out.append(seg)
        if _depth < 2:
            script = _shell_script(seg, powershell)
            if script is not None:
                out += segments(script[0], script[1], _depth + 1)
    return out


def _shell_script(seg: str, powershell: bool) -> tuple[str, bool] | None:
    toks = normalized(seg, powershell)
    if not toks or toks[0] not in SHELLS:
        return None
    for j, t in enumerate(toks[1:], 1):
        if t.lower() in _SHELL_SCRIPT_OPTS and j + 1 < len(toks):
            ps = toks[0] in ("pwsh", "powershell")
            return (" ".join(toks[j + 1:]) if ps or toks[0] == "cmd" else toks[j + 1]), ps
    return None


def tokens(seg: str, powershell: bool = False) -> list[str]:
    """Whitespace split outside quotes, with the quotes removed. An
    unterminated quote is taken as a literal character, so a broken command
    still yields its words."""
    out = _tokens(seg, powershell)
    return out if out is not None else [t.strip("'\"") for t in seg.split() if t.strip("'\"")]


def _tokens(seg: str, powershell: bool) -> list[str] | None:
    out: list[str] = []
    cur: list[str] = []
    has = False
    quote = None
    i, n = 0, len(seg)
    while i < n:
        ch = seg[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and not powershell and i + 1 < n and seg[i + 1] in '"\\$`':
                cur.append(seg[i + 1])
                i += 1
            else:
                cur.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote, has = ch, True
        elif ch.isspace():
            if cur or has:
                out.append("".join(cur))
            cur, has = [], False
        elif ch == "\\" and not powershell and i + 1 < n:
            cur.append(seg[i + 1])
            i += 1
        elif ch == "`" and powershell and i + 1 < n:
            cur.append(seg[i + 1])
            i += 1
        else:
            cur.append(ch)
        i += 1
    if quote:
        return None
    if cur or has:
        out.append("".join(cur))
    return out


def command_word(token: str) -> str:
    """`/usr/bin/git`, `C:\\Git\\cmd\\GIT.EXE` and `git` all give `git`."""
    base = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def normalized(seg: str, powershell: bool = False) -> list[str]:
    """The segment's tokens from the real command on: leading VAR=x
    assignments and wrapper commands (sudo, env, npx, PowerShell `&`, ...)
    with their options are skipped. tokens[0] is the command word in lower
    case without path or .exe; the arguments are unchanged."""
    toks = tokens(seg, powershell)
    i = 0
    while i < len(toks):
        if _VAR_ASSIGN.match(toks[i]):
            i += 1
        elif command_word(toks[i]) in WRAPPERS:
            arg_opts = _WRAPPER_ARG_OPTS.get(command_word(toks[i]), ())
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 2 if toks[i] in arg_opts else 1
        else:
            break
    if i >= len(toks):
        return []
    return [command_word(toks[i])] + toks[i + 1:]


def git_invocation(toks: list[str]) -> tuple[str, list[str], str | None] | None:
    """(subcommand, its arguments, the -C directory or None) when the
    normalized tokens are a git command. Global options before the
    subcommand (-C, -c, --git-dir=..., --no-pager, ...) are skipped."""
    if not toks or toks[0] != "git":
        return None
    cdir = None
    i = 1
    while i < len(toks) and toks[i].startswith("-"):
        opt = toks[i]
        if opt in _GIT_ARG_OPTS:
            if opt == "-C" and i + 1 < len(toks):
                cdir = toks[i + 1] if cdir is None else f"{cdir}/{toks[i + 1]}"
            i += 2
        else:
            i += 1
    if i >= len(toks):
        return None
    return toks[i], toks[i + 1:], cdir


def short_flag_has(args: list[str], ch: str) -> bool:
    """True if a short-option cluster (`-fd`, `-xdf`) contains `ch` anywhere."""
    return any(a.startswith("-") and not a.startswith("--") and ch in a[1:] for a in args)
