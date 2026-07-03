---
name: dash-gotchas-review
description: Pre-ship review checklist for Plotly Dash UI changes — catches the recurring failure patterns (portal coverage gaps, asymmetric sub-element styling, stale DOM assumptions, uirevision scope bugs, store-writer sprawl, mount-bootstrap anti-patterns, version drift) before they reach the user. Use when reviewing any Dash change touching layout, callbacks, CSS, clientside JS, theming, or Plotly figures; when a UI fix "didn't take"; or before reporting done on any Dash UI work.
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

## Output format

```
FINDINGS (N)
1. <file:line> — <problem> — <fix>
...
CLEAN: <checks that passed and matter for this change>
VERIFY: <the exact harness/screenshot commands to run before shipping>
```
