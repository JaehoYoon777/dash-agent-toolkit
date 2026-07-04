# Harness spec — Playwright verification for a Dash app

Design rationale + the solved tricky parts. Generic: `<AppRepo>` placeholders throughout. Derived from a real implementation against a production Dash 4 app; verify every selector/ID against the target repo's live DOM before trusting it.

## Key decisions

**Boot in-process, not via subprocess.** Three reasons:
1. In-process lets you **seed the app's data cache with synthetic series before the server starts** — no production DB read, ever. Tests become deterministic and fast. Generate with `np.random.default_rng(0)` cumulative-return walks over a business-day index matching the app's expected key shape.
2. The app's user-state directory is usually a hardcoded module constant. Tests exercising create/save flows would write into the owner's real saved views. Fix: ONE small production edit — an env-var override in the config module:
   ```python
   USER_STATE_DIR: Path = Path(os.environ.get("<APP>_STATE_DIR", str(DEFAULT_STATE_DIR)))
   ```
   CRITICAL: services typically do `from config import VIEWS_DIR` (value copied at import time), so conftest must set the env var **before any app import**.
3. Clean teardown via `werkzeug.serving.make_server(...).shutdown()` — no orphaned python.exe holding ports.

**Playwright over dash[testing]/Selenium**: first-class `page.on("console")`, `getComputedStyle`, `_fullLayout` evaluation, screenshots.

**Free port always** (`socket.bind(("127.0.0.1", 0))`) — the owner's live app may be on the default port.

## File layout

```
<AppRepo>/
  tests/ui/
    conftest.py          # sandbox, data seed, in-process server, console net  (~170 LOC)
    helpers.py           # viewport reader, palette rgb sets, contrast JS      (~130 LOC)
    fixtures/            # settings.json + one minimal saved-view JSON (synthetic tickers)
    test_00_boot.py      # boot + all routes render                    [smoke]
    test_10_graph.py     # traces paint, control mutation, date-viewport, round-trip
    test_20_palettes.py  # N-palette computed-style sweep + contrast heuristic
    test_30_flows.py     # create-view flow, grid/matrix layout
    snap.py              # CLI screenshot tool for agent self-verification
    artifacts/           # screenshots (gitignored)
  .claude/hooks/stop_ui_smoke.py   # Stop hook: smoke tier once per turn
```

## The universal regression net (conftest `page` fixture teardown)

Collect `console` errors, `pageerror`, and HTTP ≥500 responses during every test; fail the test in teardown if any non-benign entry exists (benign-list: favicon, React DevTools ad, third-party cookies). This single mechanism surfaces broken clientside callbacks, Dash callback exceptions, and JS crashes in EVERY test — including tests asserting something else. On failure, drop a full-page screenshot and print its absolute path.

See `templates/conftest.py` for the full implementation.

## The 12 test cases (map to owner pain)

| # | Test | Tier | Pain covered |
|---|---|---|---|
| 1 | boot, zero console errors | smoke | app actually renders |
| 2 | all routes render non-empty | smoke | route/page regressions, mount-bootstrap breakage |
| 3 | saved view paints expected trace count | smoke | store→render→figure pipeline |
| 4 | control mutation (add row / toggle) | smoke | pattern-matching callbacks, store writers |
| 5 | date preset changes rendered viewport | smoke | **uirevision bug — executable repro** (below) |
| 6 | default palette: trigger + open menu computed styles | smoke | minimal CSS-war guard |
| 7 | calendar input (typed date) changes viewport | full | the literal calendar→debounce→spec path |
| 8 | palette sweep, all N palettes | full | portal/inline-style coverage per palette |
| 9 | contrast heuristic (no invisible text) | full | white-on-white class |
| 10 | create-new-view flow lands on canonical URL, file exists in sandbox | full | bootstrap-flow anti-pattern |
| 11 | state round-trip: edit → navigate away → back → intact | full | "saved views don't stick" |
| 12 | matrix/grid layout renders ≥2 figures | full | the N-figure worst case |

## Tricky part 1 — rendered-viewport assertion (uirevision repro)

Read Plotly's **rendered** viewport, not the data — that is exactly what uirevision corrupts. The bug needs prior user interaction, so drag-zoom first (that is the honest repro):

```python
GD = "<figure-container-selector> .js-plotly-plot"

def x_range(page):
    return page.evaluate(f"""() => {{
        const gd = document.querySelector('{GD}');
        return gd && gd._fullLayout && gd._fullLayout.xaxis.range
               ? gd._fullLayout.xaxis.range.map(String) : null; }}""")

# 1. drag-zoom into a sub-window via mouse on '.nsewdrag'
# 2. click the date preset / type into the calendar input
# 3. poll x_range(page) up to ~10s: assert the rendered range matches the
#    requested window (e.g. 300 <= (hi-lo).days <= 430 for a "1y" preset)
```

Ship as `@pytest.mark.xfail(strict=False, reason="uirevision swallows date change — roadmap fix")` while the bug exists; on XPASS remove the marker in the same commit as the fix. Full code: `templates/test_date_viewport.py`.

## Tricky part 2 — palette computed-style sweep

Expected colors come from the app's theme module **in-process** (single source of truth; no hardcoded hex). Invariant asserted: "rendered background is a color the active palette declares".

```python
def palette_rgb_set(name) -> set[str]:
    # import the theme module, regex all #RRGGBB out of its css_variables()/palette dict,
    # convert to "rgb(r, g, b)" strings as getComputedStyle returns them
```

Per palette: switch via the app's real settings flow → wait for the palette class on `<body>` (portaled components depend on it) → assert computed `backgroundColor` of the **trigger AND the open menu AND the calendar popup** (the classic asymmetric-coverage trio) ∈ palette set → for dark palettes additionally assert menu ≠ `rgb(255, 255, 255)` → full-page screenshot to artifacts every run (visual record across palettes).

Portaled components (Radix popovers under Dash ≥3: `.dash-dropdown-content`, options `.dash-options-list-option`) mount on `<body>`, not inside the app shell — selectors must account for that. **Verify every selector against the live DOM first.**

Contrast heuristic: one `page.evaluate` of ~35 lines — for each visible text element, WCAG luminance ratio of `color` vs first non-transparent ancestor `backgroundColor`; fail if any ratio < 1.6. Catches white-on-white without enumerating components.

## Tiering + hook wiring

- **Do NOT run browser tests per-edit** (a multi-edit turn would launch Chromium N times). PostToolUse hook (if one runs an import-smoke script) additionally touches a `.ui_dirty` flag when the edited path is UI-critical.
- **Stop hook** (`stop_ui_smoke.py`, timeout ~150s): on stop, if `stop_hook_active` → exit 0 (loop guard); if no `.ui_dirty` → exit 0; else delete flag, run the smoke tier, exit 2 with the last ~40 lines on stderr if red — the agent must fix before finishing the turn.
- Budget: smoke tier shares one session-scoped app boot (~4s) + one Chromium (~2s) → target 25–40s total.

## Canonical commands (mirror into AGENTS.md + .cursor/rules + CLAUDE.md)

```
<repo-python> -m pytest tests/ui -m smoke -q     # fast
<repo-python> -m pytest tests/ui -q              # full
<repo-python> tests/ui/snap.py --route <r> --palette <p> --out tests/ui/artifacts/claim.png
```
Plus the rule: "any visual claim requires producing and LOOKING at a screenshot before reporting done."

## Pitfalls

- **Backend detection (Dash ≥4.2):** the "Freedom Update" (2026-06) decoupled Dash from Flask — apps may run FastAPI or Quart. The `werkzeug.serving.make_server(app.server, ...)` boot fixture assumes Flask/WSGI. Detect before assuming: `type(app.server).__module__` — `flask.*` → werkzeug boot as spec'd; `fastapi.*`/ASGI → boot with a `uvicorn.Server` in a thread (`server.should_exit = True` for clean teardown); `quart.*` → `hypercorn` equivalent. A harness written for Flask silently failing on an ASGI Dash app is version-drift class 3 wearing a new coat.
- Env var before app imports (config constants are copied at import).
- Playwright browsers live in `%LOCALAPPDATA%/ms-playwright` — fine; never set `PLAYWRIGHT_BROWSERS_PATH` into a synced repo.
- Sandbox via pytest `tmp_path_factory` (system temp — outside cloud sync).
- `pyproject`: `[tool.pytest.ini_options] markers=["smoke"]`, `addopts="--screenshot only-on-failure --output tests/ui/artifacts"`.
- Gitignore `tests/ui/artifacts/` and the dirty-flag file.
- If the app factory regenerates asset files at boot (palette CSS etc.), that's normal app behavior — harmless in tests.
