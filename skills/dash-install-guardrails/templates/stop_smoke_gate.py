"""Template: Claude Code Stop hook - block turn completion while the smoke
tier is red; run only when watched files changed this turn.

Why a Stop gate at all: PostToolUse exit 2 is post-hoc feedback - the edit
already landed and nothing forces a re-check before the agent reports "done"
(observed failure mode). This hook runs when the agent tries to finish and
blocks (exit 2) until the smoke tier is green. Keep anything browser-level or
multi-second HERE, not in the per-edit hook - a multi-edit turn would launch
it N times (see the dash-ui-verify skill for the browser smoke tier itself).

Change detection, in order:
  1. DIRTY_FLAG dropped by the PostToolUse hook (post_edit_verify.py) -
     primary signal, works even when transcript parsing breaks.
  2. Best-effort transcript scan (payload["transcript_path"], JSONL): tool_use
     blocks since the last real user message whose inputs touch WATCHED_GLOBS.
     Fallback so the gate still works if the PostToolUse hook is not installed.

Exit codes (Claude Code hooks spec):
  0 - nothing watched changed, or smoke green (marker cleared)
  2 - smoke RED (stderr tail goes back to the agent; completion blocked),
      or the smoke toolchain is missing/broken (fail loud, never skip)

Loop guard: when payload["stop_hook_active"] is true we already blocked once
this turn - exit 0 so the agent is not trapped. The marker is deliberately
NOT cleared on that path: the next turn's Stop re-runs the smoke.
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
PYTHON = sys.executable  # or the app env, e.g. r"C:\Users\me\anaconda3\envs\app311\python.exe"

SMOKE_CMD = [PYTHON, "-m", "pytest", "tests/ui", "-m", "smoke", "-q"]
# SMOKE_CMD = [PYTHON, str(REPO / "verify.py")]   # script-based alternative
OK_EXIT_CODES = (0,)  # pytest: add 5 if "no tests collected" should pass

TIMEOUT_S = 90
TAIL_LINES = 40
DIRTY_FLAG = REPO / ".claude" / ".guardrails_dirty"  # must match post_edit_verify.py

# Matched against repo-relative, forward-slash, lowercase paths (transcript
# fallback only - the marker path already scoped this in the PostToolUse hook).
WATCHED_GLOBS = [
    "app/**/*.py",
    "assets/*.css",
    "assets/*.js",
    "app.py",
]
TRANSCRIPT_TAIL_BYTES = 2_000_000  # scan cap; older turns are irrelevant
# ------------------------------------------------------------------------------


def _glob_to_re(g: str) -> re.Pattern[str]:
    """Minimal **-aware glob compiler (fnmatch's * crosses '/')."""
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


_WATCHED_RES = [_glob_to_re(g) for g in WATCHED_GLOBS]
_GLOB_PREFIXES = [
    re.split(r"[*?\[{]", g.lower().replace("\\", "/"), maxsplit=1)[0]
    for g in WATCHED_GLOBS
]
_PATH_TOKEN = re.compile(r"[\w.:~$\-/\\]+\.[A-Za-z0-9_]{1,8}")


def _norm(path: str) -> str:
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


def _is_watched(path: str) -> bool:
    q = _norm(path)
    return any(rx.match(q) for rx in _WATCHED_RES)


def _bash_touches_watched(command: str) -> bool:
    if not command.strip():
        return False
    for tok in _PATH_TOKEN.findall(command):
        if _is_watched(tok):
            return True
    text = command.replace("\\", "/").lower()
    return any(pref and pref in text for pref in _GLOB_PREFIXES)


def _tool_uses_this_turn(transcript_path: str):
    """Yield (tool_name, tool_input) for tool_use blocks after the last real
    user message (tool_result-bearing user entries are results, not turns).
    Best-effort: any parse problem yields nothing."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return
    entries: list[dict] = []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            entries.append(e)
    start = 0
    for i, e in enumerate(entries):
        if e.get("type") != "user":
            continue
        content = (e.get("message") or {}).get("content")
        is_tool_result = isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
        if not is_tool_result:
            start = i  # real user message = turn boundary
    for e in entries[start:]:
        if e.get("type") != "assistant":
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield str(b.get("name") or ""), (b.get("input") or {})


def _turn_changed_watched(transcript_path: str) -> bool:
    for name, tool_input in _tool_uses_this_turn(transcript_path):
        if not isinstance(tool_input, dict):
            continue
        if name == "Bash":
            if _bash_touches_watched(str(tool_input.get("command") or "")):
                return True
            continue
        if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            for key in ("file_path", "notebook_path", "path"):
                v = tool_input.get(key)
                if isinstance(v, str) and _is_watched(v):
                    return True
    return False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if payload.get("stop_hook_active"):
        return 0

    changed = DIRTY_FLAG.exists()
    if not changed:
        tp = payload.get("transcript_path")
        if isinstance(tp, str) and tp:
            changed = _turn_changed_watched(tp)
    if not changed:
        return 0

    # Fail LOUD on a broken toolchain - never silently skip the gate.
    for part in SMOKE_CMD:
        if part.lower().endswith(".py") and not Path(part).exists():
            print(
                f"stop_smoke_gate: smoke script MISSING: {part} - fix hook CONFIG; NOT skipping",
                file=sys.stderr,
            )
            return 2
    exe = SMOKE_CMD[0]
    if not Path(exe).exists() and shutil.which(exe) is None:
        print(
            f"stop_smoke_gate: interpreter NOT FOUND: {exe} - fix hook CONFIG; NOT skipping",
            file=sys.stderr,
        )
        return 2
    try:
        r = subprocess.run(
            SMOKE_CMD,
            cwd=str(REPO),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        print(
            f"stop_smoke_gate: smoke timed out (>{TIMEOUT_S}s) - treating as FAILED; "
            "run it manually before shipping",
            file=sys.stderr,
        )
        return 2
    except OSError as e:
        print(
            f"stop_smoke_gate: cannot launch smoke ({e}) - fix hook CONFIG; NOT skipping",
            file=sys.stderr,
        )
        return 2
    if r.returncode not in OK_EXIT_CODES:
        tail = "\n".join(((r.stdout or "") + "\n" + (r.stderr or "")).splitlines()[-TAIL_LINES:])
        print("SMOKE RED - fix before finishing the turn:\n" + tail, file=sys.stderr)
        return 2
    DIRTY_FLAG.unlink(missing_ok=True)  # green: disarm until the next protected write
    return 0


if __name__ == "__main__":
    sys.exit(main())
