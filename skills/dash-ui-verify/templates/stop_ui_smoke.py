"""Template: Claude Code Stop hook — run the UI smoke tier once per turn,
only when UI-surface files were edited.

Register in .claude/settings.json:
    "hooks": { "Stop": [ { "hooks": [ { "type": "command",
        "command": "<repo-python> .claude/hooks/stop_ui_smoke.py",
        "timeout": 150 } ] } ] }

Companion: the PostToolUse hook (or this repo's edit-verify hook) should
`touch` DIRTY_FLAG whenever an edited path matches UI_SURFACES. Do NOT run
browser tests per-edit — a multi-edit turn would launch Chromium N times.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# --- CONFIG (adapt per repo) -------------------------------------------------
REPO = Path(__file__).resolve().parents[2]
PYTHON = sys.executable  # or the absolute path to the app's env python
DIRTY_FLAG = REPO / ".claude" / ".ui_dirty"
SMOKE_CMD = [PYTHON, "-m", "pytest", "tests/ui", "-m", "smoke", "-q"]
# ------------------------------------------------------------------------------


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    # Loop guard: if we already blocked once this turn, let the agent finish.
    if payload.get("stop_hook_active"):
        return 0
    if not DIRTY_FLAG.exists():
        return 0
    DIRTY_FLAG.unlink(missing_ok=True)
    try:
        r = subprocess.run(SMOKE_CMD, cwd=REPO, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print("ui smoke tier timed out (120s) — run it manually before shipping", file=sys.stderr)
        return 2
    if r.returncode != 0:
        tail = "\n".join((r.stdout + "\n" + r.stderr).splitlines()[-40:])
        print(f"UI smoke tier FAILED — fix before finishing:\n{tail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
