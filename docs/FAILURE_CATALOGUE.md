# FAILURE_CATALOGUE.md — the 8 failure classes of LLM-built Dash apps

Each entry: **Symptom → Mechanism → Detection → Fix pattern.**
Detection commands are ripgrep/PowerShell/bash-agnostic where possible; adjust paths per repo.
`dash-diagnose` runs all detections automatically; this file is the reference behind it.

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
