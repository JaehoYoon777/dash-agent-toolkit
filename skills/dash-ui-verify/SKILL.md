---
name: dash-ui-verify
description: Browser-level verification for Plotly Dash apps — stand up and run a Playwright smoke suite (in-process app boot, sandboxed state, console-error net, computed-style palette sweeps, rendered-viewport asserts, screenshots) so UI changes are verified in the browser before being reported done. Use when asked to verify a Dash UI change, set up UI/browser tests for a Dash app, check that a visual fix actually works, or whenever editing Dash layout/callback/CSS/JS code and needing proof it renders and behaves correctly.
---

# dash-ui-verify

Two modes. Check which applies before doing anything:

- **Mode A — harness exists** (`tests/ui/` with a conftest booting the app): run it, read the results, screenshot for visual claims. Daily driver.
- **Mode B — no harness yet**: build it from `templates/` + `reference/harness_spec.md`, adapted to this repo. One-time setup (~1–2 sessions).

## Mode A — verify a change

1. **Fast tier after any UI-surface edit** (layout, callbacks, plotting, assets):
   ```
   <repo-python> -m pytest tests/ui -m smoke -q
   ```
2. **Full tier** before closing a session that touched CSS/palettes/portals, or on request:
   ```
   <repo-python> -m pytest tests/ui -q
   ```
3. **Any visual claim requires eyes.** If you are about to say "the legend no longer overlaps", "margins fixed", "dropdown readable in dark mode":
   ```
   <repo-python> tests/ui/snap.py --route <route> --palette <palette> --out tests/ui/artifacts/claim.png
   ```
   Then **Read the PNG and look at it**. If it doesn't show what you claimed, the fix isn't done. Never report a visual outcome you have not seen.
4. **On failure**: read the failure text (it prints artifact paths), Read the screenshot, fix the source, re-run. If a selector doesn't match, inspect the live DOM before writing new CSS/selectors (never trust class names from comments or memory — Dash internals change across major versions).
5. `xfail` tests are executable bug reports: an XPASS means your change fixed the tracked bug — remove the marker in the same commit so the test becomes a permanent guard.

## Mode B — build the harness

Read `reference/harness_spec.md` (design rationale + the tricky parts solved). Copy from `templates/` and adapt the `# --- CONFIG` block at the top of each file. Per-repo facts you must fill in:

| Config | How to find it |
|---|---|
| App factory import (`from core.app import build_app`) | the module `run.py`/`app.py` calls |
| State-dir env override | grep the config module for the user-state path constant; add a 2-line `os.environ.get()` override (the ONE production edit this harness needs) |
| Data seed | find the in-process data cache and its key shape; seed synthetic series so tests NEVER read the real DB |
| Routes to walk | the router callback / page registry |
| Palettes/themes | the theme module's palette dict |
| Key selectors (figure container, dropdown trigger, portaled menu, date input) | **verify against the live DOM** — boot the app once, inspect; do not trust source comments |

Build order (one commit each): (1) config override + pytest/playwright install + pyproject markers; (2) fixtures + conftest + boot/routes test — done-when smoke passes; (3) figure/control tests incl. the date-viewport test (mark `xfail` if the uirevision bug is unfixed); (4) palette sweep; (5) round-trip/flow tests + snap.py; (6) hook wiring + canonical commands into AGENTS.md/.cursor rules/CLAUDE.md.

Install (once per machine; binaries do not sync between machines — that's a feature):
```
<repo-python> -m pip install pytest playwright pytest-playwright
<repo-python> -m playwright install chromium
```

## Non-negotiables

- Tests boot the app **in-process** with a sandboxed state dir (tmp) and seeded synthetic data. They must never write to the user's real saved state or read the production DB.
- Serve on a **free port**, never the app's default (the owner's live instance may be running).
- The `page` fixture's teardown fails ANY test on console errors / pageerrors / HTTP 5xx — this net stays on in every test.
- Keep the smoke tier under ~40s so it can live in a hook; the full tier is on-demand only.
- Artifacts (`tests/ui/artifacts/`), browser binaries, and the state sandbox live outside cloud-synced dirs; gitignore artifacts.
