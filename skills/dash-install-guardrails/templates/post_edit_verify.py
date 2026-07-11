"""Template: Claude Code PostToolUse hook - run the repo's verify command when
a protected file is touched by an editor tool OR by a Bash command.

Install: copy to <repo>/.claude/hooks/post_edit_verify.py, adapt the CONFIG
block, wire via templates/settings_hooks.json. The matcher MUST include Bash
("Edit|Write|MultiEdit|NotebookEdit|Bash") - editor-only matchers let
`sed -i`, `python -c`, or `>>` redirects modify protected files with zero
verification (observed bypass in a real Dash repo).

Behavior:
  - Edit/Write/MultiEdit/NotebookEdit: exact paths from tool_input.
  - Bash: best-effort path extraction from the command string, matched
    against PROTECTED_GLOBS. When ambiguous the check RUNS - a spurious
    verify costs seconds; a skipped one ships a broken app.
  - Drops DIRTY_FLAG so the Stop hook (stop_smoke_gate.py) knows watched
    files changed this turn and arms the turn-end smoke gate.

Exit codes (Claude Code hooks spec):
  0 - nothing protected touched, or verify passed
  2 - verify FAILED, or the verify toolchain is missing/misconfigured.
      stderr is returned to the agent as blocking feedback.

Deliberate fail-closed choices (do not "fix" these back):
  - missing interpreter / missing verify script -> exit 2, never 0. A gate
    that silently cannot run is indistinguishable from a passing one, and it
    disappears exactly when the environment breaks.
  - unparseable stdin payload -> run verify anyway.
  - .js and .css stay in PROTECTED_GLOBS: in Dash repos, clientside JS and
    asset CSS are the highest-risk surface, not an exception.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# --- CONFIG (adapt per repo) -------------------------------------------------
REPO = Path(__file__).resolve().parents[2]  # .claude/hooks/<file> -> repo root

# Interpreter for the verify subprocess. Hooks may run under a different
# python than the app - point this at the APP env when verify imports the app.
#   PYTHON = r"C:\Users\me\anaconda3\envs\app311\python.exe"
#   PYTHON = "py"   # Windows launcher; then VERIFY_CMD = [PYTHON, "-3.11", ...]
PYTHON = sys.executable

VERIFY_CMD = [PYTHON, str(REPO / "verify.py"), "--quiet"]
TIMEOUT_S = 60  # keep the per-edit tier fast; browser smoke belongs in the Stop gate
TAIL_LINES = 40

# Matched against repo-relative, forward-slash, lowercase paths.
PROTECTED_GLOBS = [
    "app/**/*.py",   # app package (e.g. "core/**/*.py")
    "assets/*.css",
    "assets/*.js",
    "app.py",        # entry point (e.g. "run.py")
]

# Marker consumed by stop_smoke_gate.py.
DIRTY_FLAG = REPO / ".claude" / ".guardrails_dirty"

# Bash commands that start with one of these AND contain no redirect/tee are
# treated as read-only and skipped. Anything ambiguous runs the check.
READONLY_PREFIXES = (
    "rg ", "grep ", "cat ", "ls ", "dir ", "head ", "tail ", "find ", "wc ",
    "git diff", "git status", "git log", "git show", "git grep",
    "select-string ", "get-content ", "get-childitem ",
)

# Commands that rewrite tracked files without naming them (no path tokens to
# match). Extend with repo generator scripts, e.g. r"|\bgen_assets\.py\b".
ALWAYS_VERIFY_RE = re.compile(r"\bgit\s+(checkout|restore|apply|stash\s+pop)\b")
# ------------------------------------------------------------------------------


def _glob_to_re(g: str) -> re.Pattern[str]:
    """Minimal **-aware glob compiler.

    fnmatch's `*` crosses `/` (so "app/**/*.py" never matches "app/x.py") and
    PurePath.match lacks `**` before 3.13 - neither is safe here.
    """
    g = g.lower().replace("\\", "/")
    out: list[str] = []
    i = 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append(r"(?:[^/]+/)*")
            i += 3
        elif g.startswith("**", i):
            out.append(r".*")
            i += 2
        elif g[i] == "*":
            out.append(r"[^/]*")
            i += 1
        elif g[i] == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


_PROTECTED_RES = [_glob_to_re(g) for g in PROTECTED_GLOBS]
# Literal prefix before the first wildcard ("assets/", "app.py") - the coarse
# substring test for Bash commands whose paths hide behind wildcards or vars.
_GLOB_PREFIXES = [
    re.split(r"[*?\[{]", g.lower().replace("\\", "/"), maxsplit=1)[0]
    for g in PROTECTED_GLOBS
]
# Extension-bearing path-like tokens inside a shell command.
_PATH_TOKEN = re.compile(r"[\w.:~$\-/\\]+\.[A-Za-z0-9_]{1,8}")


def _norm(path: str) -> str:
    """Repo-relative, forward-slash, lowercase. Handles Windows backslashes,
    drive letters, and git-bash /c/Users/... absolute paths."""
    q = path.strip("\"'").replace("\\", "/")
    m = re.match(r"^/([a-zA-Z])/", q)  # git-bash /c/Users/... -> c:/Users/...
    if m:
        q = m.group(1) + ":" + q[2:]
    if q.startswith("./"):
        q = q[2:]
    try:
        p = Path(q)
        if p.is_absolute():
            sq = str(p.resolve()).replace("\\", "/")
            sr = str(REPO.resolve()).replace("\\", "/").rstrip("/")
            q = sq[len(sr) + 1 :] if sq.lower().startswith(sr.lower() + "/") else sq
    except OSError:
        pass
    return q.lower()


def _is_protected(path: str) -> bool:
    q = _norm(path)
    return any(rx.match(q) for rx in _PROTECTED_RES)


def _bash_touches_protected(command: str) -> bool:
    """Best-effort: does this shell command plausibly touch a protected file?

    False negatives are the expensive error, so the ladder errs toward True:
      1. ALWAYS_VERIFY_RE: commands that rewrite files without naming them;
      2. read-only opt-out: known read-only leading binary, no redirect/tee;
      3. any extension-bearing token that normalizes onto a protected glob;
      4. coarse: the command mentions a protected glob's literal prefix
         (catches wildcards `del assets\\*.css` and vars `$A/assets/x.css`).
    """
    if not command.strip():
        return False
    if ALWAYS_VERIFY_RE.search(command):
        return True
    text = command.replace("\\", "/").lower()
    head = command.strip().lower()
    if (
        any(head.startswith(p) for p in READONLY_PREFIXES)
        and ">" not in command
        and " tee " not in text
    ):
        return False
    for tok in _PATH_TOKEN.findall(command):
        if _is_protected(tok):
            return True
    return any(pref and pref in text for pref in _GLOB_PREFIXES)


def _paths_from_editor(tool_input: dict) -> list[str]:
    paths: list[str] = []
    for key in ("file_path", "notebook_path", "path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            paths.append(v)
    edits = tool_input.get("edits")
    if isinstance(edits, list):  # older MultiEdit payloads carried per-edit paths
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("file_path"), str):
                paths.append(e["file_path"])
    return paths


def _drop_dirty_flag() -> None:
    try:
        DIRTY_FLAG.parent.mkdir(parents=True, exist_ok=True)
        DIRTY_FLAG.write_text("dirty\n", encoding="utf-8")
    except OSError:
        pass  # marker is an optimization; the Stop hook also scans the transcript


def _run_verify() -> int:
    # Pre-flight: fail LOUD on a broken toolchain. The baseline this template
    # replaces exited 0 on FileNotFoundError and silently stopped verifying.
    for part in VERIFY_CMD:
        if part.lower().endswith(".py") and not Path(part).exists():
            print(
                f"post_edit_verify: verify script MISSING: {part} - fix hook CONFIG; NOT skipping",
                file=sys.stderr,
            )
            return 2
    exe = VERIFY_CMD[0]
    if not Path(exe).exists() and shutil.which(exe) is None:
        print(
            f"post_edit_verify: interpreter NOT FOUND: {exe} - fix hook CONFIG; NOT skipping",
            file=sys.stderr,
        )
        return 2
    try:
        r = subprocess.run(
            VERIFY_CMD,
            cwd=str(REPO),
            capture_output=True,
            encoding="utf-8",   # never text=True: locale codecs (cp949...) choke on app output
            errors="replace",
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        print(
            f"post_edit_verify: verify timed out (>{TIMEOUT_S}s) - treating as FAILED",
            file=sys.stderr,
        )
        return 2
    except OSError as e:
        print(
            f"post_edit_verify: cannot launch verify ({e}) - fix hook CONFIG; NOT skipping",
            file=sys.stderr,
        )
        return 2
    if r.returncode != 0:
        tail = "\n".join(((r.stdout or "") + "\n" + (r.stderr or "")).splitlines()[-TAIL_LINES:])
        print("verify FAILED - fix before continuing:\n" + tail, file=sys.stderr)
        return 2
    return 0


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        # Cannot tell what was touched -> err on the side of checking.
        print("post_edit_verify: unparseable hook payload - running verify anyway", file=sys.stderr)
        _drop_dirty_flag()
        return _run_verify()

    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool_name == "Bash" or (not tool_name and "command" in tool_input):
        touched = _bash_touches_protected(str(tool_input.get("command") or ""))
    else:
        touched = any(_is_protected(p) for p in _paths_from_editor(tool_input))

    if not touched:
        return 0
    _drop_dirty_flag()
    return _run_verify()


if __name__ == "__main__":
    sys.exit(main())
