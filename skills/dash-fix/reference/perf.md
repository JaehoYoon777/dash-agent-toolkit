---
name: dash-fix-perf
description: Diagnosis-first playbook for slow, laggy, or unresponsive Plotly Dash apps -- attribute the time to payload / serialization / disk I/O / browser render BEFORE fixing, then apply the ranked fix menu for the winning bucket. Use when the user says "the app is slow", "laggy", "page becomes unresponsive", "I click and it reacts a second later", "chart takes forever", "blank page while loading", "make this Dash app fast", "there should not be any lag", or blames plotting/figures for slowness.
---

# perf -- slow/laggy Dash apps

Doctrine: **the reporter's attribution is usually wrong.** In the reference audit the owner blamed "plotting"; measurement ranked the real costs (1) serialization payload, (2) hot-path disk I/O, (3) callback cascades, (4) plotting -- plotting fourth. Never start with the named suspect. Attribute first, fix the top bucket only, re-measure, repeat. Fixing plotting first is whack-a-mole.

## 1. MEASURE FIRST -- four-bucket attribution

Reproduce the exact interaction the user calls slow. Assign its time to the four buckets below before touching code. Symptom priors (verify, don't assume):

| Symptom | Check first |
|---|---|
| blank/white page on route change | (a) route payload size, then (c) I/O inside the router callback |
| click reacts ~1 s later, then UI ticks | (c) synchronous disk write per interaction, then cascade |
| every control tweak is slow, even cosmetic ones | (a) payload -- something big is re-shipped per tweak |
| slowness grows with number of saved items | (c) O(N) dir scan on the hot path |
| pan/zoom/hover stutters after page settles | (d) render -- observer loop or shape/trace count |
| "plotting is slow" (user attribution) | all four IN ORDER -- plotting ranked last in the reference audit |
| slow to start / long gap before the server binds | boot-path I/O: time the app factory; grep `read_excel|read_csv|glob|purge` inside `build_app()`; move warmups/sweeps to a daemon thread started after bind |

### (a) Payload -- bytes over the wire per callback

Temporary server-side logger (remove after):

```python
from flask import request

@app.server.after_request
def _log_size(resp):
    if resp.content_length and resp.content_length > 50_000:
        print(f"{resp.content_length/1e6:6.2f} MB  {request.path}", flush=True)
    return resp
```

Or browser Network tab: filter `_dash-update-component`, enable the Size/Content-Length column, run the interaction once.

Red flags: MB-scale response to a cosmetic tweak (e.g. a ~3000-option ticker dropdown embedded in every row card and re-shipped for ALL rows on any spec edit, ~2 MB per color change); a multi-MB route response -- the browser parses it all before first paint, which IS the "blank page on navigation" symptom.

### (b) Server compute + serialization

Run with `debug=True`; the dev-tools callback graph shows per-callback wall time -- read it, do not guess.

Then check orjson:

```
python -c "import orjson"
```

Dash serializes every callback response through plotly's JSON path, which auto-uses orjson when importable and silently falls back to the pure-Python encoder otherwise -- 3-10x slower on MB payloads. If the import fails, `pip install orjson` into the app's env is a zero-code-change win. Verify with the same one-liner in the SAME env the app runs in.

### (c) Disk I/O per interaction

Count file touches in hot callbacks. Debug-run monkeypatch (top of the entrypoint):

```python
from collections import Counter
from pathlib import Path
IO = Counter()
_rt, _wt = Path.read_text, Path.write_text
Path.read_text  = lambda s, *a, **k: (IO.update([f"R {s.name}"]), _rt(s, *a, **k))[1]
Path.write_text = lambda s, *a, **k: (IO.update([f"W {s.name}"]), _wt(s, *a, **k))[1]
# after one interaction: print(IO.most_common(15))
```

On Windows, procmon filtered to the python.exe PID + the state dir gives the same answer without code.

Red flags: ANY write on a read-only interaction (mount-echo auto-save -- opening a view rewrites its file); read counts scaling with the number of saved files (O(N) open-and-parse dir scan per keystroke, e.g. 2N JSON reads per dropdown change); state dir under OneDrive/Dropbox -- each touch pays 100-500 ms sync latency, and renames become delete+create.

### (d) Browser render

DevTools Performance profiler, record the interaction, read the flame chart: long style/layout recalc (purple) vs script (yellow) tells you DOM-size vs JS.

**The disable-test for hand-rolled JS:** if any `assets/*.js` registers a MutationObserver, rename it out of `assets/` and re-measure. A whole-subtree observer (`{subtree: true, attributes: true, attributeFilter: ["class","style"]}`) whose handler itself writes styles re-triggers on every Plotly redraw -- a restyling feedback loop that grows with DOM size and masquerades as plot slowness (e.g. 4 observers + 81 `setProperty` calls sweeping the shell on each render). If the app is fast with the file removed, the fix is scoping the observer to portal containers, debouncing it, and stamping already-styled nodes (`data-styled` marker) so writes stop re-triggering observes -- not touching the figures.

## 2. RANKED FIX MENU -- keyed to the winning bucket

Free wins first, regardless of bucket (each is zero-risk and minutes of work): install orjson (b); `lru_cache` the plotly template (below); gate closed-panel data builds on ui-state (below). Then work the winning bucket only.

### Payload bucket

- **Never embed big option lists per component.** N rows x 3000 options = N x payload, re-serialized on every rebuild, and remounting the dropdowns destroys focus. Serve options dynamically via a `search_value` callback, or ship the full list ONCE as a static asset / shared `dcc.Store` and filter clientside.
- **Never serialize data for closed panels.** If a table/grid defaults closed, gate its build on the ui-state store: add it as `State`, `return no_update` while closed, populate on open. Same trap one level up: `dcc.Tabs` mounts ALL children eagerly -- render tab content via a callback on the active tab so only one heavy child is in the DOM at a time.
- **`Patch()` partial updates instead of figure rebuilds** for restyle-class changes (color, width, visibility, axis range). Requires a persistent `dcc.Graph(id=...)` in the layout with `Output(id, "figure")` -- figures delivered as unkeyed children inside a `Div` block Patch AND remount (silently discarding uirevision) whenever a sibling banner shifts their child index. Reserve full rebuilds for trace-set changes.
- **Don't park DataFrames in `dcc.Store`.** Store data re-uploads with every request that declares it as `State`. Keep frames server-side (in-process cache keyed by a small token; the Store holds only the token).
- **Perceived payload latency: wrap slow surfaces in `dcc.Loading` / a skeleton.** Not a speedup, but the difference between "loading" and the blank-page bug report. The page container and the main figure container both need it -- a Loading on side panels only does not cover the route swap. Pair with an error boundary: a router callback with `suppress_callback_exceptions=True` and no try/except blanks the page silently on any layout exception.

### I/O bucket

- **In-process index instead of O(N) dir scans.** Resolve id -> path via a dict `{id: (path, mtime)}` built once and invalidated by mtime -- or name files by id so no content scan is ever needed. Never open-and-parse every file to find one.
- **Dirty-check + write-behind debounce on auto-save.** Compare the incoming state against the last-persisted snapshot and skip no-op writes -- mount echoes WILL fire savers with unchanged (or lossily normalized) data. Collapse edit bursts into one write with a 1-2 s debounce (clientside timer or interval-flushed pending-write store).
- **Atomic writes.** tmp file + `os.replace`, never bare `write_text` on state files -- a crash mid-write corrupts JSON, and silent fallback-to-defaults on the next read persists the wipe.
- **State dirs OFF cloud-synced folders.** Make the state dir env-overridable and default it to local disk (`%LOCALAPPDATA%`), keeping the synced folder for explicit export only.
- **No disk reads in layout()/render paths.** Cache settings in-process with an mtime check; never let a read path write (migrations that save on load turn every render into a write).

### Compute bucket

Dev-tools graph shows one callback dominating wall time and its response is small: profile it (`cProfile` on the extracted pure function, or repeated-call timing). Standard moves: cache results in-process keyed on inputs/revision-tick; replace linear scans with dict indexes (a cache whose lookups scan all entries under a lock turns O(1) into O(rows x cached items)); `lru_cache` per-render recomputes with explicit invalidation; for irreducibly slow work, a background callback plus skeleton so the UI never blocks.

### Cascade bucket

Serial callback round-trips per interaction, duplicate store writers, mount echoes, double rebuilds -- see `reference/callbacks.md`. Fingerprint: the dev-tools graph shows 4+ callbacks firing sequentially per click, or the same figure builds twice per interaction.

### Plotting bucket (fix LAST unless measurement says otherwise)

- **`go.Scattergl` above ~5k pts/trace** -- for the single main chart only. WebGL contexts are limited to ~8-16 per page: a small-multiples matrix CANNOT go gl. There, decimate instead: LTTB or per-pixel min-max to 1-2k pts/trace preserves visual shape.
- **Shapes: assign once, never loop `add_vrect`.** Each `add_*` revalidates the whole shapes tuple (O(k^2) build) and each shape is an SVG node re-rendered per pan/zoom frame. Build the dict list, then `fig.layout.shapes = tuple(shapes)`.
- **Dozens of bands -> one trace, not N shapes.** Regime/drawdown shading as a single filled step trace (`fill="tozeroy"` against a hidden secondary y-axis), adjacent intervals merged. One trace replaces 30+ shapes across every figure that shades.
- **Grids: one `make_subplots` figure, not N `dcc.Graph` cells.** Each Graph is a full Plotly instance (own axes, legend machinery, embedded template, event handlers); 64 cells = tens of thousands of DOM nodes and 64x the payload. One subplotted figure is one instance and one payload; lazy-render below the fold if it must stay multi-Graph.
- **`lru_cache` the template object.** `go.layout.Template(...)` runs a full validator pass; building it per figure (x64 in a matrix) wastes 100-200 ms per render. Cache keyed on the (hashable) palette; treat as read-only.
- **Date axes, not category axes.** Pass the DatetimeIndex/datetime64 array as `x` directly; formatting to strings first works only while the format is ISO -- any other strftime silently flips the axis to category, rendering EVERY label. Display format belongs in `xaxis.tickformat`.
- **Spikelines/hover cost scales with traces.** `showspikes` + `spikemode="across"` forces per-mousemove hit-testing across all traces; with 20+ traces disable spikes or limit `hovermode`. Also dropna per series before plotting -- traces carried on a union index ship NaN-padded heads/gaps as dead payload.

## 3. Perf budget ratchet

A fix without a guard regresses silently -- the reference transcript has the owner reporting slowness twice because "no lag" was never encoded as a testable budget. After fixing, time the top 2-3 interactions the user actually complained about and assert a budget in the ui-verify harness (see `dash-ui-verify` for fixtures/boot):

```python
# tests/ui/test_perf_budget.py -- reuses the dash-ui-verify conftest (in-process app, sandboxed state)
import time

BUDGET_MS = 800  # measured post-fix p95 + ~50% headroom; ratchet DOWN over time, never up

def test_control_tweak_budget(page, app_server):
    page.goto(f"{app_server}/<hot-route>")
    page.wait_for_selector(".dash-graph .main-svg")            # initial render done
    t0 = time.perf_counter()
    page.click("<the-slow-control>")
    page.wait_for_selector('[data-dash-is-loading="true"]', timeout=2_000)
    page.wait_for_selector('[data-dash-is-loading="true"]', state="detached")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < BUDGET_MS, f"{elapsed_ms:.0f} ms > {BUDGET_MS} ms budget"
```

Notes:

- Run the timed interaction 3-5x and budget the worst run (or p95 if you loop more) -- single-shot timings on Windows are noisy.
- If the interaction has no loading state, wait on a condition that proves re-render completed: figure revision via `page.evaluate`, expected trace count, or a text change -- never a bare `wait_for_timeout`.
- Record the post-fix numbers as the budget in the same commit as the fix. "No lag" becomes a failing test instead of a repeated complaint; `dash-install-guardrails` can wire this test into the pre-done verify tier.

## Done-when

- The measured winning bucket shrank (re-run the SAME instrumentation from section 1 -- before/after numbers, not vibes).
- The user-reported interaction is under budget in the timing test, and the test is committed.
- No new bucket regressed: payload log shows no new MB responses, I/O counter shows no new writes on read-only interactions.
- Instrumentation (after_request logger, Path monkeypatch) removed from the app code.
