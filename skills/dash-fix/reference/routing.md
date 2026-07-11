---
name: dash-fix-routing
description: Blank page / broken navigation playbook for Plotly Dash apps. Load when the user says "the page is blank", "white screen after clicking a link", "stuck on a loading spinner", "navigation shows an empty page", "the app takes seconds to paint after switching pages", or "clicking create leaves me on an empty route". Covers two-stage skeleton renders, missing error boundaries, route-payload bloat, redirect double-builds, navigation callback waterfalls, heavy I/O in route callbacks, and the Dash >=4 mount-bootstrap URL-write trap.
---

# Routing - blank page / broken navigation

Work the items in order; each is symptom -> 2-minute diagnosis -> fix -> browser-level verification. Verify through the dash-ui-verify harness where one exists; never close on "should be fixed" without eyes on the rendered page.

**30-second triage** - open DevTools on the blank page:
- Content containers EMPTY in the Elements panel -> items 1, 2, 7 (nothing was delivered).
- Content present in the DOM but invisible -> not routing; see dash-gotchas-review P1-P5 (CSS/portal coverage).
- Content arrives, but seconds late -> items 3, 4, 5, 6 (payload / waterfall / I-O).
- Compare view-source (server-shipped HTML) vs Elements (post-callback DOM): Dash ships a near-empty shell by design, so ALL content is callback-delivered - the Network tab, not view-source, tells you which wave failed.

## 1. Two-stage render trap

**Symptom:** navigation shows an empty shell with small spinner circles for seconds, then content pops in. Root cause: the router callback returns a skeleton whose inner containers (e.g. `html.Div(id="gx-rows")`, `html.Div(id="db-tab-content")`) are empty and get filled by a SECOND serial wave of callbacks.

**Diagnose:** Elements panel shows page chrome present, content containers childless. Network tab shows one `_dash-update-component` POST for the route, then a later wave carrying the actual content. Count the serial rounds - each costs a full RTT plus server build time.

**Fix** (strongest first):
- Persistent containers: mount every page once inside `app.layout`, toggle `style.display` clientside from pathname. No teardown, no refill wave, instant back-navigation.
- If the router must rebuild: return the skeleton WITH previous content preserved and an overlay spinner on the page container - never ship blank primary containers.
- `dcc.Loading` at component level (per figure / per table), never wrapping the page - page-level Loading guarantees the all-blank frame.

**Verify:** navigate in the browser; old content stays visible until new content paints. No frame in which the main container is empty (screenshot mid-navigation if unsure).

## 2. No error boundary - blank forever

**Symptom:** a container stays empty permanently. No spinner, no error, no log line. A layout builder raised, and `suppress_callback_exceptions=True` additionally hides mis-wired IDs (typo'd Output target = callback silently never fires).

**Diagnose:** relaunch with `debug=True`, reproduce - traceback appears in the server log or the in-page dev-tools toast. If still silent: browser console + Network 500s on `_dash-update-component`. Empty + silent + no failing request = the callback was never dispatched (wiring error swallowed by suppress).

**Fix:** try/except in the route resolver; a visible error card beats an empty div in every environment:

```python
def _route(pathname):
    try:
        return _resolve_page(pathname or "/")
    except Exception:
        return html.Pre(traceback.format_exc(), className="route-error")
```

Dev servers always run `debug=True`. Keep `suppress_callback_exceptions` if you must, but compensate with a route-walk test that visits every page and asserts the inner containers are non-empty (see dash-ui-verify).

**Verify:** raise deliberately inside one page builder; confirm the traceback card renders instead of a blank page, then remove the raise.

## 3. Route-payload bloat

**Symptom:** first paint after navigation is slow; the spinner phase scales with page complexity. Cross-ref: perf.md (sibling reference) for the full treatment.

**Diagnose:** Network tab -> size column of the route's `_dash-update-component` response. Megabytes = data embedded in layout (e.g. a ~3000-entry ticker options list copied into every row card = tens of thousands of option dicts per response).

**Fix:** never embed large option lists or data blobs in returned layout. Dropdowns: dynamic options (callback on `search_value` returning top-N) or clientside filtering from a static asset the browser caches. Row edits: `dash.Patch` / MATCH-scoped callbacks instead of rebuilding the whole container.

**Verify:** route response back to KB range; typing in one row no longer re-ships every row.

## 4. Redirect double-build

**Symptom:** cold boot flashes one page, then swaps to another; boot does double the callback traffic.

**Diagnose:** log `pathname` at router entry. Two invocations per cold load = some callback rewrites the URL after first render (e.g. a default-tab redirect that reads settings and returns a new pathname).

**Fix:** resolve the redirect INSIDE the route resolver - for "/" render the target page directly, no URL write - or redirect clientside before the first server render. Never bounce the URL through a server callback after a full page build.

**Verify:** boot log shows exactly one router invocation; no visible flash of the intermediate page.

## 5. Navigation waterfalls

**Symptom:** every route change is slow even for cheap pages; the sidebar/shell flickers on each click.

**Diagnose:** `rg -n 'Input\("<url-id>", "pathname"\)' --type py` - pathname fanning into N callbacks, including full shell rebuilds (e.g. a history-tick chain that re-renders the entire sidebar per navigation). Network tab shows the rounds serializing.

**Fix:** the shell (sidebar, header, nav links) lives in `app.layout`, built once, never returned by a route callback; flip the active link's className clientside from pathname; re-render only the genuinely dynamic child (e.g. a history list). Hunt shared-Input amplifiers: a store written on every navigation - even None -> None, Dash fires downstream on any prop WRITE, not value change - that re-feeds a theme provider forces a whole-tree React re-render per click. Guard with `State` + `PreventUpdate` when the value is unchanged.

**Verify:** Network shows one content round per navigation. Shell keeps DOM identity: in the console set `document.querySelector('<sidebar>').dataset.probe = '1'`, navigate, confirm the attribute survives.

## 6. Heavy synchronous work in route callbacks

**Symptom:** first visit to a page hangs for seconds; much worse on cloud-synced disks (OneDrive/Dropbox hydration stalls reads).

**Diagnose:** grep route resolver + layout builders for I/O in the hot path - `rg -n "read_excel|read_csv|read_hdf|read_parquet|glob|json.load" <pages/services>` - then wrap the resolver in `time.perf_counter()` and log per-route timings. Also flag WRITES (e.g. a migration write-back) inside the route path.

**Fix:** warm caches in a background daemon thread started after the server binds (not synchronously at boot - that just moves the stall to cold start); replace O(N) directory scans with an lru-cached id -> path index invalidated on save/delete; read shared files (favorites, settings) ONCE per layout build and pass values down. Disk writes inside a route resolver are forbidden - move them to a fire-once callback after render.

**Verify:** second visit to the page is near-instant; boot-to-first-request time did not regress.

## 7. Mount-bootstrap URL-write trap (Dash >= 4)

Cross-ref: dash-gotchas-review P8. Flows that create a resource then navigate to it must create on the USER EVENT (click/submit), not on a placeholder route's layout mount. Under Dash 4, a `prevent_initial_call="initial_duplicate"` callback writing the URL via `allow_duplicate=True` updates the location bar but does NOT re-fire callbacks reading the URL as Input - the user is stranded on a blank or half-mounted route, and keystrokes into editors mounted before their persistence ID exists get silently dropped.

**Diagnose:** `rg -n 'initial_duplicate' --type py` combined with any URL Output; any `dcc.Link` pointing at a route whose backing data does not exist yet.

**Fix:** create the resource in the click handler, persist it, THEN return the new URL from that same handler.

**Verify:** click through the create flow in a real browser: the destination renders populated, edits stick, and F5 on the new URL also renders.
