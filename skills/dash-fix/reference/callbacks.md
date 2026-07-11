---
name: dash-fix-callbacks
description: Fix playbook for Dash callback and store-state bugs -- mount-time callback storms, saves firing on view open, saved specs silently rewritten or wiped, echo cascades (4+ round-trips per click), zoom/legend resets on unrelated updates, lost edits between duplicate store writers. Use when "prevent_initial_call is set but it still fires", "opening a view rewrote the file", "it saves before I touch anything", "my edit got reverted", "zoom resets when something else updates", "every keystroke feels slow", or the Network tab shows a request storm.
---

# dash-fix: callbacks and state

Diagnose before patching. Every bug class below has a recon step, a fix pattern, and a browser-level assert (section 8) that proves the fix. Run the recon even when the symptom "obviously" points at one callback -- these classes co-occur and mask each other.

## 1 -- Callback-graph recon (always first)

Dump the real graph from the running registration, not from reading source top-to-bottom:

```python
import collections
from <app_module> import <factory>            # e.g. from core.app import build_app
app = <factory>()
w = collections.Counter()
for key in app.callback_map:                  # multi-output keys: "..a.prop...b.prop.."
    for out in key.strip(".").split("..."):
        w[out.split("@")[0].rsplit(".", 1)[0]] += 1   # @suffix = allow_duplicate entry
for comp, n in w.most_common():
    if n >= 2: print(n, comp)
```

Census the escape hatch, each hot store's writers, and pattern-ID types:

```
rg -c "allow_duplicate=True" --type py
rg -n 'Output\("<store-id>"' --type py
rg -o '"type":\s*"[^"]+"' --type py | sort | uniq -c | sort -rn
```

Rules of engagement:
- **>=2 writers on one store**: flag; every writer needs a comment naming the others and its disjoint key slice.
- **>=4 writers, all read-modify-write on the whole dict**: refuse to patch in place. Redesign into a single reducer -- one callback taking every mutation trigger as Input, dispatching on `ctx.triggered_id`, sole writer, no `allow_duplicate` (e.g. a spec store with 5 add/del/sync writers is the structural whack-a-mole engine; fixing any one symptom leaves four).
- A total `allow_duplicate` count in the dozens is a finding in itself: Dash's duplicate-output validation is off exactly where you need it.
- **Pattern types must be feature-prefixed.** Any `{"type": ...}` string appearing in 2+ modules is a cross-firing hazard: pattern IDs are global, so a future component reusing the type silently fires this callback (and vice versa). Per-item actions (toggle/star/delete) should be MATCH on both Input and Output -- an ALL->ALL handler rewrites every instance on the page per click and does O(n) service reads to answer the n-1 untouched ones.

Before ADDING any writer to an existing store, run the dash-gotchas-review P7 audit instead; this section is for fixing sprawl already present. For a whole-repo structural audit (this plus version drift, CSS wars, perf), hand off to dash-diagnose.

## 2 -- The insert loophole (top killer)

`prevent_initial_call=True` does NOT suppress a pattern-matching callback whose Inputs are inserted into the page by another callback's render -- unless its Outputs are inserted in the same render. The canonical shape: container `children` rendered from a store, pattern inputs live inside the container, the callback's Output is the store itself (outside the container). Every container render -- including the very first mount -- re-fires the sync, which writes the store back from whatever the freshly rendered controls report.

Symptoms: request storm on page load; files saved the moment a view opens; "prevent_initial_call is set but it fires anyway"; the echo cascade in section 3. This is the class that passes every server-side smoke test (`render()` never runs the post-mount storm) and fails on the first real open.

Detection:
- Temp-log `ctx.triggered_id` + `time.monotonic()` at the top of each store writer. Cold-open the page, touch nothing. Any writer line = loophole fire.
- Browser Network tab: count `_dash-update-component` POSTs after load and per single interaction. Write the numbers down -- they are the before/after metric.

Fixes, in preference order:
1. **Diff-against-State no-op guard**: reconstruct the would-be write, compare to `State("<store>", "data")`, `raise PreventUpdate` when equal. Kills the echo regardless of what triggered it; robust to future insertions.
2. **Move Outputs into the inserted subtree**: the loophole closes when outputs are inserted alongside inputs. Right fix for per-item status spans -- a MATCH output in the same rendered card plus `prevent_initial_call=True` suppresses the insert-time fire while keeping genuine events (e.g. a per-row parse-status span re-firing once per row per rebuild).
3. **Explicit revision key**: render stamps a nonce into the subtree; the sync skips when the nonce says "this fire is the render itself". Last resort -- more moving parts.

## 3 -- Echo cascade tracing

Measure round-trips per user action: open the Network tab (or the harness request log), perform ONE edit, count sequential POSTs until quiet. Budget: one edit = one store write + one render fan-out. Anything above ~2 sequential hops needs a trace.

Canonical worst case (each hop is a full server round-trip): RT1 control edit -> sync writes store; RT2 fan-out -- container rebuilds ALL children, figure rebuilds, auto-save hits disk; RT3 the freshly inserted inputs re-fire the sync (section 2) plus every MATCH callback lacking `prevent_initial_call`; RT4 the re-write differs from the store (section 4 lossiness -- first pass always differs), so the ENTIRE RT2 fan-out runs again, second disk write, second figure rebuild; RT5 finally idempotent, store equality stops the chain. Add upstream debounce hops (button -> control props -> clientside debounce -> trigger store -> sync) and one click costs ~7 round-trips. Users blame the plotting; the profile says serialization and re-entry.

Root antipattern: `Output(container, "children") <- Input(store)` rebuilding every child on any store change -- and re-shipping every child's payload (a 3000-option dropdown times N rows is multi-MB JSON per keystroke). Fixes:
- MATCH-scoped per-item outputs so an edit to one item updates one item.
- `Patch()` on the container for structural add/remove instead of full rebuild.
- Plus the section-2 no-op guard so RT3-RT5 never happen.

## 4 -- Lossy normalization writes (silent data destruction)

The chain: a sync callback reads rendered control values, normalizes them -- `value or ""`, snap-to-nearest-option, name backfilled from another field, values wiped to None when absent from the options list -- and writes the whole store; a downstream auto-save persists it. Combined with section 2, merely opening a saved view rewrites its file: colors nulled, widths snapped, blanks backfilled, zero user action.

Detection: byte-compare the saved file before/after an open-then-navigate-away with no edits. Any diff = a lossy writer on the mount path. Then grep the writers:

```
rg -n 'or ""|or 0|else None' <store-writer files>
```

Fixes:
- Write only the keys belonging to `ctx.triggered_id`; leave everything else untouched (or use the section-2 diff guard).
- Treat None from a control as "not rendered / unchanged", never "user cleared": `value if value is not None else existing["key"]` -- never `value or ""`.
- Persist raw values; snap to UI option grids at render time only. A saved 1.2 must not become 1.0 because the dropdown lacks a 1.2 entry.
- Render-time coercion beats spec mutation: if a display mode forces a derived value (e.g. a normalize toggle forcing all series onto one axis), apply it in the figure builder. Mutating the spec is redundant with the render override and destroys state the user cannot get back by toggling off.

## 5 -- Zoom/legend resets (remount beats uirevision)

`uirevision` only survives when the SAME Graph component instance receives the new figure. A `dcc.Graph` inside a children-rebuilt container is a new React node on every rebuild -- zoom/legend state is discarded before uirevision is ever compared. Position-shift trap: conditionally rendered siblings (banners, status rows) shift the Graph's index in the children array, remounting it even when the Graph subtree is unchanged.

Fix: give the Graph a stable id in the static layout and update via `Output(<id>, "figure")` -- never re-create it inside rebuilt children; give conditional siblings stable ids (render them hidden rather than absent). Key `layout.uirevision` on trace identity (preserves legend hides) and `xaxis.uirevision` + every `yaxis*.uirevision` on the data window (`start|end|transform`) so window changes DO reset the view -- see dash-gotchas-review P6 for the keying check.

## 6 -- Last-writer-wins lost updates

Two `allow_duplicate=True` writers that each `State(store)` and return the whole mutated dict: when fires overlap (a debounced text value landing while a control-change response is in flight), the second response was computed from a stale base and silently reverts the first edit. No error, no log -- the edit is just gone.

Detection: add a monotonically increasing `_rev` inside the store payload, bump it in every writer, log it client-visible; a rev that goes backwards or skips = collision. Repro: two rapid edits on controls owned by different writers, then read the store.

Fix: the section-1 single reducer -- one writer, no `allow_duplicate`, no stale base possible. Second best: `Patch()` writers touching strictly disjoint keys, slices documented per callback. Hygiene either way: drop `allow_duplicate=True` wherever the census shows exactly one writer -- the flag is inert today but permanently disables the duplicate-output registration error that would catch the next accidental writer.

## 7 -- Mount-path side effects and polling noise

Related classes the recon usually surfaces alongside the above:

- **Disk writes on the mount path**: callbacks with `prevent_initial_call="initial_duplicate"` or URL Inputs that record history, purge expired files, or bump revision ticks fire on every navigation -- a mere route change mutates user state and re-renders whatever listens on the tick (e.g. a full sidebar rebuild per visit). Fix: skip the write when it is a no-op (revisit == current head), and move deletions/purges off render-path callbacks onto the explicit user actions plus a startup sweep.
- **Revision-tick fan-in sprawl**: N writers bumping one tick store that triggers a full re-render is the same sprawl as section 1 with an extra hop; if the writer census in code disagrees with the census in the repo's invariant docs, fix the doc in the same commit -- the next writer gets justified against a wrong list.
- **`dcc.Interval` polling**: a short-interval poll fires forever on every page, drowning the Network-tab counts you need for sections 2-3. Replace with an event-driven tick Input where one exists, or raise the interval and gate with `max_intervals`; at minimum disable it while measuring.
- **Route callbacks without error boundaries**: under `suppress_callback_exceptions=True`, an exception in the page-builder callback leaves the content container with its previous children -- on fresh navigation, a blank page, error visible only in server logs. Wrap the dispatch in try/except returning a visible error card; keep the suppression flag but add a dev-mode callback-vs-layout ID audit.
- **Inline-compute twins**: when the defect sits in logic written inline in a callback closure, grep for hand-copied siblings of the key expression BEFORE fixing (`rg` the distinctive line -- window arithmetic, `searchsorted`, transform chains). A twin means the same bug lives twice; extract one module-level pure function and call it from both as part of the same fix -- that is the minimal correct diff, not a drive-by refactor.

## 8 -- Verification: one browser-level assert per fix class

Server-side smoke tests cannot see any of these classes. Wire each assert into the dash-ui-verify harness -- its sandboxed state dir plus a request counter added in the test (`page.on("request")` filtered to `_dash-update-component`) give you everything below; promote the asserts to the smoke tier so the bug class stays dead.

| Fix class | Assert that proves it |
|---|---|
| Insert loophole / mount storm | Cold-open a saved view: `_dash-update-component` POST count <= budget; store-writer log empty with zero interaction |
| Lossy normalization | Saved spec file byte-identical after open -> idle -> navigate away (no edits) |
| Echo cascade | One control edit: sequential POST count <= 2; exactly one disk write |
| Zoom/legend reset | Zoom the figure, trigger an unrelated update (panel toggle, store bump, status banner): relayout range and legend hides preserved |
| Lost update | Two rapid edits via different former writers: both values present in the persisted spec |

Numbers beat vibes: record the POST count and file hashes before the fix, assert the improved numbers after. An assert that was `xfail` and now passes graduates to a permanent guard in the same commit.
