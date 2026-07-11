# FAILURE_CATALOGUE.md -- the 16 failure classes of LLM-built Dash apps

Each entry: **Symptom → Mechanism → Detection → Fix pattern.**
Detection commands are ripgrep/PowerShell/bash-agnostic where possible; adjust paths per repo.
`dash-diagnose` runs all detections automatically; this file is the reference behind it.

Classes 1–8 came from a deep audit of a production Dash app; classes 9–11 were
discovered LIVE by running the `dash-ui-verify` harness against a lab copy of
the same app — each one is a real bug that import-level smoke tests provably
could not see (validation writeup: the lab repo's LESSONS.md).
Classes 13-16 came from a multi-agent workflow audit of the same app after
real use -- defects that shipped repeatedly despite green import-level smoke tests.

---

## 1. Verification gap (the meta-cause)

**Symptom.** Agent reports "done", app compiles, smoke test passes — but the button doesn't click, the margin is off, the dropdown is white-on-white. Owner discovers every UI bug manually. Fixing one thing silently breaks another because nothing catches the breakage.

**Mechanism.** The only checks are server-side: module imports, schema migrations, config dicts. Dash apps break in the **browser**: clientside callbacks, CSS specificity, portaled components, Plotly.js state. An LLM without browser feedback is optimizing "code that looks right", not "app that works". The owner becomes the test harness, at minutes-to-hours per feedback cycle.

**Detection.**
```
# any browser-level tests at all?
rg -l "playwright|selenium|dash.testing|dash_duo" --glob '!node_modules'
# what do hooks/CI actually run?
cat .claude/settings.json 2>/dev/null; ls .github/workflows 2>/dev/null
```
If the first command returns nothing, this class applies — and it dominates every other class, because none of the others can be fixed reliably while the agent is blind.

**Fix pattern.** Stand up the `dash-ui-verify` harness (Playwright, in-process app boot, sandboxed state, console-error net, computed-style asserts, screenshot CLI). Wire the fast tier into the agent's stop/post-edit hook; put the canonical command in AGENTS.md/.cursor rules so every agent runs it before claiming done. See `skills/dash-ui-verify/`.

---

## 2. uirevision viewport swallowing ("calendar doesn't update the graph")

**Symptom.** User changes the date range (calendar, preset button); the chart's data updates or seems to, but the visible x-range stays where it was — especially after the user has zoomed/panned once. Feels intermittent ("works sometimes").

**Mechanism.** `layout.uirevision` is set (correctly!) to preserve legend hides and zoom across figure rebuilds, typically keyed on trace names. But when the date window changes, trace names don't — so uirevision matches, and Plotly.js **restores the old zoom viewport over the new data slice**. Setting an explicit `xaxis.range` does NOT fix it: an explicit range is also ignored when uirevision matches and the user has touched the axis. The failure needs prior user interaction, which is why it reproduces "sometimes".

**Detection.**
```
rg -n "uirevision" --type py
```
Red flag: any `uirevision=` whose key does **not** include the data window (date_start/date_end/normalize/transform), on a figure whose date range is user-controllable.

**Fix pattern — axis-scoped uirevision.** Plotly resolves this precisely:
- Keep `layout.uirevision` keyed on trace identity (preserves legend hides — trace-level uirevision inherits it).
- Set `xaxis.uirevision` and **every** `yaxis*.uirevision` to a data-window key, e.g. `f"{date_start}|{date_end}|{normalize}|{transform}"`.
- Zoom/pan then resets exactly when the window/transform deliberately changes; legend state survives.
- Thread it as a kw-only param (`axes_revision: str | None = None`) through the shared figure factory; callers compute the key from the spec.

**Done-when test.** Hide one trace via legend → drag-zoom into a subrange → change date range via the control → rendered `gd._fullLayout.xaxis.range` shows the new window AND the hidden trace stays hidden. (Executable template: `dash-ui-verify/templates/` date-viewport test, shipped as `xfail` until the fix lands, then the marker is removed and it becomes the permanent guard.)

---

## 3. Version drift (agents code against the wrong framework)

**Symptom.** Patterns that "should work" silently don't (callbacks that never fire, CSS written for DOM structures that don't exist). GOTCHA-class bugs where the fix targets class names that aren't in the rendered DOM.

**Mechanism.** `pyproject.toml` and the repo's agent docs claim one version (e.g. "Dash 2.17+"); the environment actually runs another (e.g. Dash 4.x, where `dcc.Dropdown` renders a Radix-based DOM, not react-select, and mount-triggered `allow_duplicate` URL writes no longer chain to downstream callbacks). LLMs weight the documented version and their training prior — both wrong. Drift can go **both directions** (a dependency below its floor pin is just as silent).

**Detection.**
```
python -c "import importlib.metadata as m; [print(p, m.version(p)) for p in ('dash','plotly','dash-mantine-components','dash-ag-grid','pandas','numpy')]"
# compare against pyproject pins AND against what CLAUDE.md/AGENTS.md claims
rg -n "dash|plotly" pyproject.toml; rg -in "dash [0-9]" *.md
```

**Fix pattern.**
1. Pin `==` to **installed reality** (upgrades become deliberate acts).
2. Rewrite the agent docs' tech-stack section to the same versions, with version-specific warnings ("Dash 4: dcc.Dropdown renders `.dash-dropdown-content`/`.dash-options-list-option`, NOT `.Select-*`").
3. Add a runtime gate to the repo's verify script: parse pyproject, compare `importlib.metadata.version()` per `==` pin, FAIL on mismatch. The gate runs in the post-edit hook, so drift can never be silent again.

**Known Dash 4 landmines** (each independently rediscovered by multiple agents in a controlled fan-out — put this list verbatim in your agent docs):
- `dcc.Slider(style=...)` → TypeError; the prop was removed. Wrap in `html.Div(style=...)`. (7 of 10 build agents hit this.)
- `dcc.Dropdown` open menu = Radix popover (`.dash-dropdown-content`, options `.dash-options-list-option`, state via `aria-selected`/`data-highlighted`) — NOT react-select `.Select-*`.
- `.dash-options-list-option` classes are SHARED by `dcc.Checklist` — a selector "for the dropdown" also matches checklists; scope by container (`:not(.dash-checklist)`).
- Mount-triggered callbacks writing a URL via `allow_duplicate` don't chain to URL-reading callbacks (see class 4 / bootstrap anti-pattern).
- Synthetic JS `el.click()` does NOT open Radix popovers — real pointer events (Playwright locator.click) required.
- **Minor-version churn continues** (verify per installed x.y, not just major): 4.1 (2026-03) added `dcc.Dropdown` `debounce` prop, searchable-when-focused, large-option-list performance work — hand-rolled debounce/perf workarounds may now fight native ones. 4.2 "Freedom Update" (2026-06) decoupled Dash from Flask: `app.server` may be FastAPI/Quart (ASGI) — anything assuming Flask/werkzeug (test harness boot, WSGI middleware, `@server.route` health endpoints) breaks. The Dash 4 DCC redesign also restyled core components (new `dcc.Button`, WCAG 2.2 AA defaults) — re-inspect rendered DOM per minor upgrade before trusting selectors.

---

## 4. God module (one file owns the whole interactive surface)

**Symptom.** Any edit to the main view file risks breaking an unrelated feature. Agents "fix" one callback and violate an invariant defined 2000 lines away. Regressions cluster in one file.

**Mechanism.** A single module (often the main view) accumulates 15–25 callbacks, several shared mutable `dcc.Store`s, multiple `allow_duplicate=True` writers to the same Store, and cross-location invariants ("these 5 places must agree") documented only in prose. The file exceeds what an agent can hold with the invariants in attention; every edit is a dice roll.

**Detection.**
```
# size + callback census per module
rg -c "@callback|@app.callback" --type py | sort -t: -k2 -rn | head
rg -c "clientside_callback" --type py
rg -n "allow_duplicate=True" --type py | wc -l
# writers per Store output (repeat per hot store id)
rg -n 'Output\("<store-id>"' --type py
```
Red flags: any module > ~800 lines with > ~8 callbacks; ≥3 writers to one Store; invariants that exist only in markdown.

**Fix pattern (strict order).**
1. **First make invariants executable** (class 7 below): derive repeated key-lists from a single source; add verify-script checks that walk the rendered layout and count Store writers from `app.callback_map` against a declared manifest — fail loudly on ANY diff.
2. **Only then split**, mechanically: package conversion → pure functions out → layout out → callbacks regrouped by concern. Bodies move **verbatim**; zero changes to component/Store IDs, Input/Output/State lists, `prevent_initial_call`. Gate per step: verify script green + `@callback`/`clientside_callback` counts across the package equal pre-split counts. One step = one commit.

---

## 5. CSS override war (fighting the component library instead of theming it)

**Symptom.** Margins/paddings "evidently off"; dropdown menus, calendars, tooltips white-on-white in dark themes; a fix for one component breaks another; hundreds of `!important`; hand-rolled JS with MutationObservers forcing inline styles.

**Mechanism.** Runtime theme switching implemented by overriding third-party components' rendered DOM: Layer 1 CSS variables, Layer 2 injected `<style>` with `!important`, Layer 3 `el.style.setProperty(...,'important')` re-applied by MutationObservers watching portal mounts. Every new component (or sub-element, or open/focus state, or portal surface) needs manual enumeration in all layers; each miss is a user-visible bug. Meanwhile the native theming API (e.g. `dmc.MantineProvider` theme) is often instantiated but unused because the UI is built from raw `dcc.*`/`html.*` that ignores it. Structural: the surface area grows with the app; coverage is always one step behind.

**Detection.**
```
rg -c "!important" assets/*.css
rg -c "MutationObserver|setProperty" assets/*.js
# dead selectors: classes styled in CSS that never appear in any rendered DOM dump
# native theming unused?
rg -n "MantineProvider|mantine_theme" --type py; rg -c "dmc\." --type py
```

**Fix pattern.**
- **Incremental:** component inventory (which library, which portal target, which sub-elements, which layer covers each); palette-sweep browser test asserting computed background/foreground of trigger + open menu + calendar popup under every theme (makes coverage machine-checked); purge dead selectors.
- **Structural (the real fix, owner sign-off):** migrate raw `dcc` controls to the natively-themeable library already wrapping the app (`dcc.Dropdown`→`dmc.Select`, `dcc.DatePickerRange`→`dmc.DatePickerInput(type="range")`, Tabs/Checklist/Input likewise), then delete Layers 2–3 and most of the observer JS. Each migration is one session; re-verify ID/property contracts (`value` vs `data`, date string formats) and pattern-matching ID shapes.

---

## 6. Hot-path I/O and full-rebuild rendering (slow, unresponsive)

**Symptom.** Pages take forever; typing feels laggy; every control change re-paints the whole chart; the app stutters on cloud-synced machines.

**Mechanism (stacking):**
- Dash ships the **complete figure JSON** on every callback render — every keystroke = server round-trip + full rebuild + full payload + client repaint. Grid/matrix layouts multiply this (N figures × ~30KB+).
- **Auto-save writes on every state change**, often to a cloud-synced path (100–500ms each, several per interaction), sometimes with an O(N) directory scan per save.
- **Large data files read inside callbacks** on cache miss, from cloud-synced storage.
- Redundant `dcc.Interval` polling.

**Detection.**
```
rg -n "dcc.Interval" --type py
rg -n "write_text|json.dump|to_json|open\(" <services-dir> --type py
# writes fired per interaction: trace the save callback's Inputs
rg -n "def _save|auto_save" --type py
# is the data/state dir under OneDrive/Dropbox?  echo paths from config
```

**Fix pattern (ranked, cheapest first).**
1. **Local mirror for read-only data:** robocopy/rsync the DB file(s) to a local dir on launch (`/XO` only-if-newer), env-var override in config; zero split-brain risk.
2. **Write-behind auto-save:** clientside trailing debounce (~800ms) into a single `*-save-debounced` Store; the save callback triggers on that Store only, reads values from `State`. Keep manual-save immediate. Every user field must remain an Input **of the debounce stage** (fields declared only as State on the writer chain silently drop out of auto-save). Add a path cache to kill O(N) scans.
3. Interval polling → event-driven tick or 30s+.
4. Grid/matrix: lazy render (first N cells + "render all").
5. Downsample traces above ~20k points — measure first.
6. `Patch()` partial updates: usually **rejected** for date-window changes (the sliced data must ship anyway; Patch adds a second update path per figure for layout-bytes-only savings).

---

## 7. Prose invariants + no git discipline (nothing is enforced, nothing is revertible)

**Symptom.** The repo has excellent rules docs (invariants, gotcha logs, prompting guides) — and the same regressions keep happening anyway. When something breaks, there's no known-good state to return to; agents "fix forward" and compound the damage.

**Mechanism.** Every invariant lives in markdown, which only helps when (a) the agent reads it, (b) it fits in attention, (c) the agent complies. All three degrade with repo size and session length. Meanwhile git has 1–2 giant commits, dirty tree, tracked `.pyc`, no `.gitignore` → no bisect, no revert, no per-change blame. And multi-agent setups (Cursor + Codex + Claude Code) each read **different** rule files — often only one of them sees the rules at all.

**Detection.**
```
git log --oneline | wc -l; git status --porcelain | wc -l
git ls-files "*.pyc" | head; test -f .gitignore && echo ok || echo MISSING
ls AGENTS.md .cursor/rules 2>/dev/null    # do non-Claude agents see anything?
```

**Fix pattern.**
1. **Git baseline first, before any other fix**: `.gitignore` (pyc, logs, user-state dirs), untrack junk, one baseline commit. Rule: one prompt = one verified change = one commit; never commit with the verify script failing.
2. **Executable invariants:** move every "these N places must agree" rule into the verify script (walk the rendered layout; derive key-lists from a single source; writer-count manifest from `app.callback_map` with fail-loud diffs that instruct the agent to update docs + manifest together).
3. **One rules source, mirrored:** designate the main doc as source of truth; generate/maintain `AGENTS.md` (Codex + modern Cursor read it natively) and `.cursor/rules/*.mdc` (`alwaysApply: true`) containing the invariants + the canonical verify commands + "source of truth wins on conflict".

---

## 8. Plotting reinvention (no blessed factories; legends/axes hand-rolled per view)

**Symptom.** Every dashboard builds figures its own way; a legend/axis fix in one view doesn't help the others. Subplot grids show one giant 30-item legend at the bottom (or suppress legends entirely and fake them with HTML chips). Multi-axis layouts drift ("off sometimes") when specs change.

**Mechanism.** No shared figure factories: each view hand-rolls `go.Figure`/`make_subplots` + layout dicts. Multi-axis positioning computed once with hardcoded gaps, not recomputed when the spec changes. And the actual Plotly feature for per-subplot legends — **multiple legends via trace-level `legend="legend2"..."legendN"` + positioned `layout.legend2..N` (plotly ≥5.15)** — is absent from most training-data code, so agents never reach for it.

**Detection.**
```
rg -n "make_subplots|go.Figure\(" --type py | wc -l   # per module
rg -n "showlegend=False" --type py                     # suppressed-legend workarounds
rg -n "legend2|legendgroup" --type py                  # is multi-legend used at all?
```

**Fix pattern.**
- One `plotting/factories.py` with a small blessed API, e.g.:
  ```python
  def make_subplot_grid(cells, n_cols, palette, *,
                        per_subplot_legends=True, shared_x=False,
                        cell_height=220, axes_revision=None) -> go.Figure
  ```
  When `per_subplot_legends`: assign every trace of cell *k* `legend=f"legend{k+1}"` (cell 0 uses `legend`) and set `layout[f"legend{k+1}"] = {"x": xdom[1], "y": ydom[1], "xanchor": "right", "yanchor": "top", "bgcolor": "rgba(0,0,0,0)", "font": {"size": 9}}` from each subplot's domain.
- Migrate hand-rolled `_fig_*` functions one per prompt, deleting their legend-suppression workarounds.
- Don't over-abstract: if a good single-figure factory exists (`make_line`), re-export it — don't wrap it (no abstractions until 3+ concrete cases).
- Note: layouts that render one `dcc.Graph` **per cell** (not one subplot figure) can't use legend refs — a shared legend strip is correct there; state this in the factory docstring so agents stop "fixing" it.

---

## 9. Saved-state destruction — control sync + option normalization + auto-save

**Symptom.** A saved view/config opens EMPTY or partially wiped — and the wipe is then persisted, destroying the saved state by the mere act of opening it. Related milder form: a setting saved via UI silently persists the OLD value when clicked fast.

**Mechanism (three innocent parts, lethal chain).**
1. Dash ≥4 `dcc.Dropdown` NORMALIZES a value missing from `options` to `None` at mount (e.g. the saved ticker was removed from the reference list, or was loaded data not present in the options source).
2. A mount-firing "control → store" sync callback writes the normalized `None` back into the spec store (`r["ticker"] = value or ""`).
3. Auto-save persists the wiped spec. No error anywhere.
Sibling race: a Save callback reading `State` of a HIDDEN mirror control that is synced from visible controls by a SERVER callback — a fast click saves the stale mirror; the live-preview signal (body class flip) makes it look saved.

**Detection.**
```
# mount-firing syncs writing user-editable stores:
rg -n 'def _sync|Input\(\{"type"' --type py     # then check prevent_initial_call + "or ''" overwrites
# option sources vs legal saved values: are options a superset of anything a saved spec may contain?
# hidden mirrors: rg -n 'State\("<hidden-control>"' + a server callback syncing it from visible controls
```

**Fix pattern.** Break any link of the chain: (a) options must be a SUPERSET of every value that can legally appear in saved state (union reference list + loaded/lively values, cache-invalidated); (b) sync callbacks preserve, never overwrite, values a control reports as None at mount (`value or existing`); (c) auto-save skips pure-mount writes. For hidden mirrors: sync CLIENTSIDE (synchronous) and/or make the saver read the visible source controls as State. Tests must wait on the PERSISTENCE acknowledgment (saved-message), never on preview-driven signals.

---

## 10. Boot-frozen layout state (static `app.layout`)

**Symptom.** A setting saved through the UI (theme, defaults) reverts on F5 / new tab, until server restart. Session navigation looks fine (stores mask it); full page loads expose it.

**Mechanism.** `app.layout` assigned a static component tree built once in `build_app()`; any `dcc.Store(data=<loaded settings>)` inside captures BOOT-time state. Dash serves that frozen snapshot on every full page load.

**Detection.**
```
rg -n "app.layout" --type py    # assignment of an OBJECT (not a function) + data=<loaded state> inside
```

**Fix pattern.** `app.layout = layout_fn` (a callable) — Dash re-evaluates per page load; re-read persisted state inside (keep it cheap: one small JSON read). Test: save a setting → `page.goto()` full reload → assert the setting's effect (body class/computed style) survived.

---

## 11. Metadata/store drift — the UI advertises data that doesn't exist

**Symptom.** "Load data" fails with a raw store-internals error (`object 'X' doesn't exist`) for whole categories the pickers happily offer. Or: agents curate defaults from the metadata table and every one of them fails to load.

**Mechanism.** Ticker/category metadata (xlsx/DB table) and the actual data store (HDF5/parquet/DB) evolve independently; nothing cross-checks. Every dropdown built from metadata offers unloadable entries; failures surface only at load-click, deep in store jargon.

**Detection.**
```python
# cross-check metadata (level1, level2) pairs against actual store groups:
meta_leaves = set(map(tuple, main_table[["level1","level2"]].drop_duplicates().values))
store_leaves = {(g1, g2) for g1 in h5.keys() for g2 in h5[g1].keys()}
print(meta_leaves - store_leaves)   # advertised-but-absent  -> the bug list
```

**Fix pattern.** Run the cross-check in the verify script; hide or badge unavailable leaves in pickers; translate load-boundary errors into "leaf X advertised by metadata but absent from store". Rule for agent context packs: curated defaults must be validated against the STORE, not the metadata.

---

## 12. Dead-series windows — wall-clock-anchored ranges empty the panel

**Symptom.** A panel (or whole figure) renders empty/None for SHORT range selections but fine on "Max" — or the reverse: a spread/basis panel is blank while its leg panels draw. No error anywhere.

**Mechanism.** Range dropdowns implemented as `start = today - offset` assume every series extends to today. Discontinued series (Libor swaps end 2023-06-30 at cessation; delisted tickers; stale leaves last refreshed months ago) have zero overlap with a today-anchored 1Y window. Derived series inherit the earliest death among their legs. Found live: a SOFR-vs-Libor basis panel that was silently empty at every range except Max.

**Detection.** For each plotted series: `s.index.max()` vs wall clock; any gap larger than the shortest range option will blank that range. Grep for `Timestamp.today()`, `datetime.now()`, `pd.Timestamp("now")` inside window/range helpers.

**Fix pattern.** Anchor trailing windows on the DATA's own last observation, per panel: `end = s.index.max(); s.loc[s.index >= end - offset]`. Put the helper in the shared compute layer — in one 10-agent fan-out, 5 agents hand-rolled this mapping and only one anchored it correctly by luck.

---

## 13. Mount-echo persistence -- opening a saved view rewrites its file

**Symptom.** Saved views/configs change on disk with ZERO user edits: colors null out, numeric fields snap to dropdown steps, names get backfilled, file mtimes churn on every open. Sibling of class 9, but needs no missing option -- the mere act of opening is the write.

**Mechanism (three innocent parts, lethal chain).**
1. **The insert loophole.** `prevent_initial_call=True` does NOT suppress a pattern-matching callback whose Inputs are INSERTED by another callback's render -- unless its Output is inserted in the same render. A rebuild-all children callback (spec store -> row cards) re-inserts the inputs on every render, so the control->store sync re-fires on every spec write AND on the initial mount of a saved view.
2. **The sync is lossy.** It reconstructs the store from rendered control values, normalizing on the way: `value or ""`, a hex color missing from the named list -> None, line width snapped to the nearest dropdown step, display name backfilled from the ticker (e.g. a row editor whose color/width/name round-trip through dcc controls).
3. **Auto-save persists the echo.** The store is an Input of the save chain; the first post-mount sync always differs from the saved spec (step 2), so opening the view writes the mutated spec to disk. No error anywhere; smoke tests that call render() never see it -- the damage happens in the post-mount callback storm.

Variant: a control sync mutates the SPEC to enforce a display rule the render path already applies (e.g. normalize-on -> force every row to one axis). With auto-save, trying the feature once permanently destroys the saved layout. Display coercions belong in the render path ONLY.

**Detection.**
```
# pattern-input syncs whose Output lives OUTSIDE the rebuilt children:
rg -n 'Input\(\{"type"' --type py
# lossy normalization inside them:
rg -n 'or ""|or 0|else None' --type py
# runtime proof: open a saved view, touch nothing, navigate away -- byte-compare the file
```

**Fix pattern.** No-op guard in the sync: diff the reconstructed fields against `State` of the store and `PreventUpdate` when nothing changed (this also breaks the class-15 cascade). Write only the triggered row's keys (`ctx.triggered_id`). Never normalize-then-persist: accept raw values; treat None as "not rendered yet", not "user cleared". Ratchet test: the state-file byte-compare open/close test (see `dash-ui-verify`).

---

## 14. Payload bloat -- the slowness that gets blamed on plotting

**Symptom.** Typing lags; every control change takes ~1s; the app degrades linearly with row/option count; profiling the figure code finds nothing. DevTools shows multi-MB `_dash-update-component` responses.

**Mechanism (stacking).**
- **Embedded per-row option lists.** Every dynamically rendered card embeds the same full options list (e.g. ~3000 tickers x 11 row editors = ~33k option dicts, multi-MB JSON per response). Caching the Python list does nothing -- the WIRE payload is re-serialized on every response.
- **Rebuild-all children.** One callback `Output(container, "children") <- Input(store)` rebuilds ALL cards on ANY store write -- every keystroke-scale edit re-ships and remounts everything (destroying focus/open state as a bonus).
- **Closed-panel serialization.** Callbacks build payloads for panels that default closed -- e.g. a data grid's full `.to_dict("records")` of every displayed series' history, shipped on every edit and never looked at.

**Detection.**
```
rg -n "options=" --type py                          # full list embedded in a repeated card?
rg -n 'Output\("[^"]*", "children"\)' --type py     # container rebuilds keyed on a whole store
rg -n 'to_dict\("records"\)' --type py              # grids built regardless of panel state
# runtime: harness request log -- response sizes during ONE edit
```

**Fix pattern.** Options cross the wire once per page: a `search_value` callback returning a filtered top-N slice, or `options=[]` plus a clientside assign from one shared Store/asset. Patch only the changed card (MATCH-scoped outputs / `Patch()`); never rebuild the whole container from the store. Gate expensive panel payloads on the panel actually being open (`State` of the ui-state store, `no_update` otherwise). Add a payload-size budget assert to the harness so regressions fail loudly.

---

## 15. Callback echo cascade -- one edit, seven round-trips

**Symptom.** One control edit produces a visible cascade: spinners flicker, the UI "ticks" a second later, the server log shows the same callbacks firing 2-3x per interaction, figures rebuild twice, disk writes double.

**Mechanism.**
- **Multi-writer RMW stores.** N `allow_duplicate=True` writers each do `State(store)` -> mutate -> return the WHOLE dict. Overlapping fires lose updates: last writer wins with a stale base and silently reverts the other edit.
- **The echo.** A store write fans out to rebuild-all children + figure rebuild + auto-save; the rebuilt children RE-INSERT the pattern inputs, which re-fire the sync (class 13's insert loophole), which writes the store AGAIN -- and the first pass always differs (lossy normalization), so the ENTIRE fan-out runs a second time, including a second figure rebuild and a second disk write. The chain stops only when dcc.Store equality finally makes a write a no-op: 5-7 sequential round-trips per edit (debounced date presets prepend more hops).

**Detection.**
```
rg -n "allow_duplicate=True" --type py | wc -l      # 40+ repo-wide is a symptom in itself
rg -c 'Output\("<store-id>"' --type py              # writers per hot store; >=4 -> redesign
# runtime: count POST /_dash-update-component per single edit in the harness log; >2 = cascade
```

**Fix pattern.** One reducer per store: every mutation trigger an Input of ONE callback dispatching on `ctx.triggered_id` -- zero `allow_duplicate`, no lost updates. No-op guards wherever a sync reconstructs state (`PreventUpdate` on equality). Debounce the save behind a timer store. Drop `allow_duplicate=True` from any output the census shows has one writer -- the flag pre-emptively disables the duplicate-output validation that would catch the next accidental writer. Ratchet: the interaction-latency budget test locks the round-trip count (see `dash-ui-verify`).

---

## 16. Stale-server debugging -- turns burned on code that never ran

**Symptom.** Owner reports "nothing changed" after a shipped fix; the agent re-implements a feature it already shipped; screenshots later prove the browser was running 3-turn-old code. Whole sessions spent "fixing" correct files.

**Mechanism.** The dev server runs with `debug=False` (no hot reload), so edits never reach the running process until a manual kill+restart -- and nothing in the UI identifies WHICH code is serving, so neither the human nor the agent can tell a stale process from a failed fix. The agent piles changes onto an already-correct file; the owner re-issues already-implemented requests; both burn turns debugging code that never ran.

**Detection.**
```
rg -n "debug=" run.py app.py *.bat                  # hot reload off? launcher passes no --debug?
rg -in "build|stamp|version" <layout footer module> # any serving-code identifier at all?
```

**Fix pattern.** Two halves. (1) **Build stamp**: a footer element rendering a short hash (git SHA or source-tree hash) computed at process start -- staleness becomes self-evident to both parties. (2) **Restart-and-assert**: after any UI edit, kill the port, relaunch, GET the route, and assert the NEW stamp (and any new component IDs) appear in the served HTML before reporting done -- wire it into the verify flow (`dash-install-guardrails`). The `dash-ui-verify` harness boots the app in-process, so TESTS never see a stale server; the owner's browser does -- the stamp is for the human loop.

---


## Cross-cutting: which class is it?

| You observe | Start with class |
|---|---|
| "It worked when the agent tested it, broke in my browser" | 1 |
| Date/calendar/zoom weirdness, intermittent | 2 |
| CSS written for elements that don't exist; callbacks that never fire | 3 (then 5) |
| Edits to the big file keep breaking unrelated features | 4 (gate with 7 first) |
| Dark-mode/portal/margin bugs recurring | 5 |
| Slow, laggy typing, long loads | 6 |
| Same regression keeps returning despite documented rules | 7 |
| Legend piles, axis drift, per-view figure code | 8 |
| Saved views/settings wiped or reverting after open/save | 9 |
| Settings revert on F5 but survive SPA navigation | 10 |
| Pickers offer data that always fails to load | 11 |
| Panel empty at short ranges, fine at Max (or vice versa) | 12 |
| Saved file's content/mtime churns on mere open; colors/widths/names mutate without edits | 13 (sibling of 9) |
| Multi-MB callback responses; slowness that profiling the figure code can't find | 14 (then 6) |
| One edit fires the same callbacks 2-3x; double rebuilds and double writes | 15 |
| "Nothing changed" after a shipped fix; agent re-ships already-shipped features | 16 |
| "Missing data" for SOME tickers of a leaf after a restart | 6/11 lifecycle note: in-process caches die per restart; partial-column loaders make leaves half-present — check which loads ran THIS process before suspecting data |
