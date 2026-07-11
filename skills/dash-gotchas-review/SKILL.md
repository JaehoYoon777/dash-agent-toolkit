---
name: dash-gotchas-review
description: Pre-ship review checklist for Plotly Dash UI changes -- catches the recurring failure patterns (portal coverage gaps, asymmetric sub-element styling, stale DOM assumptions, uirevision scope bugs, store-writer sprawl, mount-bootstrap anti-patterns, mount-time store writes that rewrite saved files on open, per-instance payload bloat, unkeyed-Graph remounts that reset zoom, version drift) before they reach the user. Use when reviewing any Dash change touching layout, callbacks, CSS, clientside JS, theming, or Plotly figures (for mid-fix debugging of a fix that "didn't take", use dash-fix); when opening a view modifies its saved file or state changes with zero user edits; when every click feels slow or callback responses run to megabytes; when zoom or legend state resets at random; or before reporting done on any Dash UI work.
---

# dash-gotchas-review

Read-only review. Run every applicable check; report findings as `location — problem — fix`, one line each. If the target repo has its own `GOTCHAS.md`, read it first and apply its entries too; when this review catches a NEW pattern, append an entry there (symptom → root cause → rule).

## P1 — Live DOM before CSS (the #1 killer)

Any change writing CSS selectors or `querySelector` targets for third-party components: **verify the class names exist in the rendered DOM.** Source comments, prior sessions, and training data lie — Dash's internals changed across major versions (e.g. Dash ≥3 `dcc.Dropdown` renders a Radix popover: `.dash-dropdown-content`, `.dash-options-list-option`, state via `aria-selected`/`data-highlighted` — NOT react-select `.Select-*`).
Check: boot the app / use the ui-verify harness, `document.querySelectorAll('<selector>').length > 0` for every new selector. A selector matching zero elements = dead code that will "not take effect".

## P2 — When a fix doesn't take, the model is wrong, not the force

If a CSS/JS fix had no visible effect: do NOT add more `!important`, more observers, more guards. First question: "do my selectors match real elements?" Verify, then rewrite against reality.

## P3 — Portal symmetry

Components that mount parts to `<body>` (menus, calendars, tooltips, modals — Radix-based components ALWAYS portal) need, for each portaled part:
- unscoped CSS variant (shell-scoped rules never reach it),
- inline-style overrides that sweep `document.body`, not just the app shell,
- a `document.body` MutationObserver (or equivalent) so late mounts get styled.
Check: for every component touched, list its portal surfaces; confirm each has all three.

## P4 — Asymmetric sub-element coverage

A component is trigger + open menu + items + item sub-elements + focus/selected/disabled states. Fixing the visible part and missing a parallel part is the single most recurrent bug class.
Check: enumerate ALL sub-elements from BOTH the JS/py template and the CSS file (grep the class prefix); confirm each is covered or state-independent. Then ask: what OTHER component uses the same pattern (fixed the dropdown — what about the select? the calendar?).

## P5 — Dynamic state coverage

Libraries rewrite inline `style=` and toggle `data-*`/`aria-*` attributes on open/close/focus/select. Static-state CSS does not cover this.
Check: does the styling handle state via attribute selectors (`[aria-selected="true"]`, `[data-highlighted]`, `[data-state="open"]`)? Does any observer watching it include attribute changes AND reach the actual mount point?

## P6 — uirevision scope

Any change to figures with user-controllable ranges:
- `layout.uirevision` keyed on trace identity only? Then date/window changes will be swallowed by restored zoom (explicit `xaxis.range` loses to matching uirevision — it is not a fix).
- Correct pattern: `layout.uirevision` = trace identity (preserves legend hides); `xaxis.uirevision` + every `yaxis*.uirevision` = data-window key (`date_start|date_end|transform`).
Check: `rg -n "uirevision"` on touched files; confirm axis-level keys include the window.

## P7 — Store-writer audit

Before adding any `Output` to an existing `dcc.Store` (especially with `allow_duplicate=True`):
```
rg -n 'Output\("<store-id>"' --type py
```
List ALL existing writers. ≥2 existing → the new writer needs a comment naming the others and why coexistence is safe. ≥4 existing → refuse; redesign (single writer + upstream trigger store). Also confirm the write-order assumption: does anything downstream depend on which writer fires last?

## P8 — Mount-bootstrap anti-pattern (Dash ≥3/4)

Flows that create a resource then navigate to it must do the create on the **user event** (click/submit), not on a placeholder route's layout mount. Under Dash 4, `prevent_initial_call="initial_duplicate"` callbacks writing a URL via `allow_duplicate=True` update the location but do NOT re-fire callbacks reading the URL as Input — the user is stranded.
Check: any callback with `initial_duplicate` + URL output? Any `dcc.Link` to a route whose data doesn't exist yet? Any editable surface mounted before its persistence ID exists (keystrokes during the window get silently dropped by downstream guards)?

## P9 — Version drift spot check

Before trusting any framework idiom in the change: `python -c "import dash; print(dash.__version__)"` vs what pyproject/docs claim. If they disagree, flag it as its own finding — the idiom may be written for the wrong version.

## P10 — Persistence round-trip

Any change touching saved state (specs, ui-state stores, settings):
- Is every user-editable field an Input of the save chain (fields only declared as `State` silently drop out of auto-save)?
- Does the rendered layout restore ALL of it on remount (uncontrolled native elements like `<details>` need explicit sync)?
- Schema shape changed? Then version bump + migration + spec docstring, same commit.
Check by scenario: edit each touched field → navigate away → back → still there.

## P11 — Blast radius

For each edited file: which OTHER views/pages import it or share its Stores/pattern-matching ID types? A fix verified on one surface can cross-fire on another (`{"type": ...}` IDs shared across features fire each other's callbacks).
Check: grep the edited symbols and ID types across the repo; name every surface that needs a look.

## P12 — Option-list superset + mount-sync preservation (saved-state destruction)

Any dropdown whose value can come from SAVED state: Dash ≥4 normalizes a value missing from `options` to `None` at mount; a mount-firing sync callback writing `value or ""` back into the spec store then WIPES the saved row, and auto-save persists the wipe.
Check: (a) is the options source a superset of every value legally present in saved specs (reference list ∪ loaded/live values)? (b) do control→store syncs preserve existing values when the control reports None (`value or existing`, never `value or ""`)? (c) does auto-save fire on pure mounts?

## P13 — Persistence signal ≠ preview signal

A UI confirmation driven by a live-preview path (body class flip on radio check, optimistic store update) is NOT proof of persistence. Saves that read `State` of a hidden mirror control synced by a SERVER callback lose a fast-click race — persist the stale mirror while the preview looks right.
Check: mirror syncs are clientside (synchronous) or the saver reads the visible source controls; any test/verification waits on the explicit save acknowledgment ("Saved." message) before navigating.

## P14 — Boot-frozen layout state

`app.layout` assigned a static object freezes every `dcc.Store(data=<loaded state>)` at boot — saved settings revert on F5/new tab until server restart (SPA navigation masks it).
Check: `rg -n "app.layout"` — if it's not a callable and any Store inside carries loaded persisted state, flag it. Verify with save → full reload → effect survives.

## P15 — Popup lists: visible height must scale with content

Component libraries ship compact popup defaults (Dash's dropdown popover: inline `max-height` ≈ a handful of rows, plus an inline FIXED height on the inner virtualized scroller). Fine for short lists; a UX defect on long ones — the user scrolls a tiny window through hundreds of options.
The generic principle: **let content drive height under a generous, viewport-aware cap.** Don't hardcode a row count. Mechanics that make it adaptive by construction:
- Raise the popup's `max-height` cap (`min(calc(100vh - <margin>), <comfortable-cap>)`); content-driven height keeps short lists compact automatically.
- Virtualized scrollers often carry an inline FIXED height — and are typically mounted ONLY for long lists, so overriding that class targets exactly the menus that need it. CSS `!important` beats non-important inline styles.
- Library-native prop beats CSS when it exists: dmc Select/MultiSelect take `maxDropdownHeight` directly (viewport-relative values like `"55vh"` work) — zero override CSS, content-driven below the cap.
Check: open the app's longest option list AND a short one — long shows substantially more rows under the cap, short stays content-sized; after a deep scroll the virtualized list still renders items (no blank gap — proves the windowing survived the height override).

## P16 -- Insert-loophole mount writes

Pattern-matching callbacks re-fire whenever their Inputs are RE-INSERTED by a container rebuild (a callback returning fresh cards into `children`). `prevent_initial_call=True` does NOT suppress this unless the callback's outputs are inserted alongside its inputs -- an output living outside the container (a page-level store) re-fires on every render, including plain view open. If that callback writes normalized values back into the store (`value or ""`, snapped line widths, colors wiped to None) and an auto-save chain reads the store, merely OPENING a saved surface rewrites its file (e.g. a row-cells sync persisting lossy normalization on view mount).
Check: every store-writing sync callback whose inputs live inside rebuilt children diffs its reconstructed payload against `State` of the store and raises `PreventUpdate` when nothing changed -- a no-op guard, not a prevent_initial_call flag. Verify with the dash-ui-verify harness: open the surface with ZERO edits; assert zero disk writes / byte-identical state file.

## P17 -- Payload budget

Serialization is the usual "slow app", not plotting. Three payload sins:
- Big option lists embedded per component instance: grep `options=<fn>()` inside per-row/card builders. N instances x thousands of options re-serialize on every container rebuild (e.g. a ~3000-ticker dropdown per row = multi-MB per control tweak; a Python-side cache does not help -- the WIRE payload is rebuilt). Serve via a `search_value` callback or one shared clientside source.
- Serializing content for closed-by-default panels (grid rowData, hidden figures) on every change: gate on the panel's open state, return `no_update` while closed.
- Container-children rebuild-all driven by a store Input (`Output(..., "children") <- Input(store, "data")`): needs a written justification for why MATCH-scoped per-item outputs or `Patch()` don't apply; rebuild-all also remounts every child (feeds P16 and P18).
Check: Network tab (or a temporary after_request size logger), one interaction of each hot type; content-length per response under a STATED budget -- name the number in the finding (e.g. <100 KB per control tweak).

## P18 -- Unkeyed Graph remount

A `dcc.Graph` delivered inside rebuilt `children` without a stable `id`, sitting after conditional siblings (failure banner, warning div), changes React position whenever a sibling appears or disappears -- React remounts the Graph and silently discards uirevision state (zoom/legend "randomly" reset). Unkeyed delivery also blocks `Patch()` adoption, so every tweak re-ships the whole figure.
Check: hot figures render as a persistent `dcc.Graph(id=...)` declared once in the static layout, updated via `Output(id, "figure")` -- never a fresh Graph inside `children`; conditional content lives in a separate sibling Div. Verify: zoom in, then toggle EVERY conditional sibling (force the banner, empty state, etc.) -- zoom survives each toggle.

## Output format

```
FINDINGS (N)
1. <file:line> — <problem> — <fix>
...
CLEAN: <checks that passed and matter for this change>
VERIFY: <the exact harness/screenshot commands to run before shipping>
```
