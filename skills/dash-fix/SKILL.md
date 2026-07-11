---
name: dash-fix
description: Front-line procedure for fixing any Plotly Dash front-end problem -- app broken, button/callback doesn't work, blank page, slow or laggy UI, "nothing changed" after an edit, zoom resets, saved state lost. Use when the user says "fix", "broken", "doesn't work", "bug", "debug", "slow", "blank page", or "nothing changed" about a Dash app. Enforces ground-truth checks (versions, stale server, browser reproduction) before any code change, dispatches to a symptom playbook, and requires browser-level proof plus a regression test before reporting done.
---

# dash-fix

The fix loop for any Dash front-end error. Order is mandatory:
STEP 0 (ground truth) -> symptom dispatch -> localize -> minimal fix -> browser proof + regression test -> dash-gotchas-review -> report.

## STEP 0 -- ground truth (mandatory, before touching code)

Three checks, in order, every time. Each takes seconds; skipping any is the top cause of wasted sessions.

### 0a. Version truth

```
python -c "import importlib.metadata as m
for p in ('dash','plotly','dash-mantine-components','dash-ag-grid','dash-bootstrap-components'):
    try: print(p, m.version(p))
    except Exception: pass"
```

Compare against pyproject/requirements pins AND version claims in CLAUDE.md/AGENTS.md/README. Mismatch = its own finding before any debugging: the "bug" may be an idiom written for the wrong version (Dash major versions change DOM internals, callback chaining semantics, and the server backend -- see dash-gotchas-review P9 and FAILURE_CATALOGUE class 3). Never debug behavior against docs describing a version that is not installed.

### 0b. Staleness kill-switch

You may be debugging code that is not running. Before forming any hypothesis:

- Restart the dev server. Hot-reload misses assets edits, module-level constants, and anything imported before the watcher started; a crashed reloader keeps serving old code silently.
- Prove the process serves current source: check a boot stamp (startup log of source mtime / git SHA), or add a throwaway marker string to the layout and confirm it appears in the served page. No stamp mechanism = add one now; it pays for itself immediately.

Evidence this matters: a real session burned 3 full turns "fixing" CSS that was already correct -- the server process predated every edit. Cost of the check: seconds. Cost of skipping: whole turns of fiction.

### 0c. Reproduce in the browser

No reproduction = no fix. "I read the code and see the problem" is a hypothesis, not a diagnosis -- Dash apps break in the browser (CSS specificity, portaled components, Plotly.js state, callback chaining), where server-side reading cannot see.

- Repo has a harness (`tests/ui/` with a conftest booting the app): use it -- dash-ui-verify Mode A. Run the smoke tier, then snapshot the failing state with its `snap.py`.
- No harness: write a throwaway Playwright script. Playwright IS installable (once per machine):

```
<repo-python> -m pip install playwright
<repo-python> -m playwright install chromium
```

```python
# repro.py -- adapt route/selector to the LIVE DOM, never to memory or comments
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("response", lambda r: errs.append(f"{r.status} {r.url}") if r.status >= 500 else None)
    pg.goto("http://127.0.0.1:<port>/<failing-route>")
    pg.wait_for_timeout(3000)  # let the callback waves land
    pg.screenshot(path="repro_before.png", full_page=True)
    print("\n".join(errs) or "no console/network errors")
    b.close()
```

Capture, minimum: a screenshot of the failing state, console errors + pageerrors, and the failing request/response if a callback errors (`/_dash-update-component` bodies name the callback). Read the screenshot. These artifacts are the "before" half of your proof. If you cannot reproduce, say so and stop -- do not ship a speculative fix.

"Intermittent" bugs are state-dependent, not random -- reproduce the state, not just the route:

- Viewport bugs (zoom pins, range ignored) need a PRIOR user interaction: zoom/pan first, then change the control. A fresh page load will never show them.
- Saved-state bugs need a saved artifact: create/save, full reload (F5, not SPA navigation -- client routing masks boot-frozen layouts), then check.
- Theme/palette bugs: reproduce in the palette the user runs, and check portaled surfaces (open the menu/calendar) -- closed-state screenshots hide them.
- Race bugs (fast clicks, save-then-navigate): script the exact interaction speed; human-paced manual clicking can be too slow to hit the window.

## Symptom dispatch

Match the user's complaint to a playbook, load the file, follow it. Do not fix from memory when a playbook exists -- each one encodes bugs that cost real sessions.

| Symptom | Load |
|---|---|
| Looks wrong: colors, dark mode, dropdown/menu styling, spacing, theming, CSS | `reference/visual.md` |
| "Nothing changed" / "my fix didn't take" / same bug after the edit | `reference/stale.md` |
| Wrong behavior on interaction: clicks ignored, state corruption, zoom/legend resets, callbacks firing wrong or twice | `reference/callbacks.md` |
| Slow, laggy, unresponsive, long spinners, freezes while typing, huge payloads | `reference/perf.md` |
| Blank page, route broken, page won't load, stuck on navigation | `reference/routing.md` |
| Saved state lost, reverts on open/reload, corrupted settings/specs | `reference/persistence.md` |
| Numbers look wrong / two panels disagree | no playbook -- localize layer 1 (server): diff the figure-builder's input frame against the expected per-series pipeline (union-index NaN padding, dropna asymmetry between sibling builders, off-by-one windows). Data-correctness bug, not front-end; fix in the compute layer with a numeric test |

Multiple symptoms: dispatch on the one the user reported; log the rest as findings, not scope creep. Symptom fits no row: it is usually callbacks (behavior) or routing (rendering) -- pick by whether the page mounts at all.

## Localize -- bisect the layer before editing anything

A Dash symptom lives in exactly one of four layers. Identify it from the repro artifacts before opening source:

1. **Server** -- callback raised or returned wrong data. Signal: 500 on `/_dash-update-component`, traceback in server log. Note: `suppress_callback_exceptions=True` plus an ID typo fails SILENTLY -- a callback that never fires produces no error anywhere; confirm the callback actually ran (server-side print or the response body) before assuming its logic is wrong.
2. **Wire** -- callback ran but the payload is the problem (multi-megabyte responses, N sequential round-trips per interaction). Signal: DevTools/`page.on("response")` sizes and request count. This layer, not plotting, usually explains "slow" (e.g. one audited app shipped ~33,000 dropdown option dicts, ~2 MB, on every keystroke).
3. **Browser/React** -- payload correct but the DOM is wrong: remounts (unkeyed children shifting position), portal surfaces unstyled, dead selectors. Signal: `document.querySelectorAll(sel).length == 0`, component state resetting.
4. **Plotly.js** -- figure state machine: uirevision swallowing new ranges, WebGL context limits. Signal: data updated but viewport did not (FAILURE_CATALOGUE class 2).

The playbooks assume you know the layer; ten minutes here saves a session of fixing the wrong one.

## Iron rules

1. **Reproduce before fixing.** Applies to bugs you infer from code too -- confirm the inferred bug renders as a real symptom before spending a session on it.
2. **Measure before optimizing.** Every perf claim carries a number: payload bytes, round-trips per interaction, points per trace, ms per render. "The route response is 2 MB because every row embeds a ~3000-option dropdown list" is a diagnosis; "plotly is slow" is a guess and usually wrong -- serialization and callback fan-out dominate more often than plotting. Re-measure after: the fix report states before/after numbers.
3. **When a fix does not take, the MODEL is wrong, not the force.** Never escalate `!important`, add observers, or stack guards. Re-verify the assumption layer: do the selectors match the live DOM (`document.querySelectorAll(sel).length`)? Is the edited file the one being served (0b)? Did the callback fire at all? Rewrite against reality (dash-gotchas-review P1/P2).
4. **One concern per fix, minimal diff.** No drive-by refactors, no "while I'm here". Unrelated defects found en route: report them, do not touch them.
5. **Verify at the browser layer, then ratchet.** After the edit: re-run the repro -- screenshot proves the symptom is gone, console/network net stays clean, and adjacent surfaces sharing the pattern still work (blast radius, dash-gotchas-review P11). Then the ratchet: any user-found bug becomes a FAILING test first (confirm it fails on pre-fix code), the fix makes it pass, and the test stays forever. Use the dash-ui-verify harness for the test; if none exists, this bug is the reason to build Mode B now.
6. **Append new patterns to the target repo's `GOTCHAS.md`** (symptom -> root cause -> rule). If the pattern is generic to Dash, note it as a candidate for FAILURE_CATALOGUE / dash-gotchas-review.
7. **Run dash-gotchas-review before reporting done** -- on the diff you are about to ship, not the whole repo. Its P1-P15 checks catch the classic half-fixes (portal asymmetry, missing state coverage, store-writer collisions, saved-state wipes).
8. **Recurring symptom = structural cause.** If the same class of bug has been "fixed" more than twice in this repo (zoom resets, saved-state loss, slow navigation), stop patching and run dash-diagnose -- store-writer sprawl, god modules, and verification gaps regenerate symptoms faster than you can fix them.
9. **No enforcement gates = a finding.** If the repo has no verify command wired to hooks (no PostToolUse verify, no Stop gate), note it in the report and hand off to dash-install-guardrails after the fix lands -- without gates, this fix's regression test never runs automatically and the whack-a-mole resumes.

## Report format

```
ROOT CAUSE: <one sentence: mechanism, not symptom -- file:line>
FIX: <files touched, one line each: what changed and why it is sufficient>
PROOF: <before artifact> -> <after artifact>   (screenshot/console/measurement paths)
REGRESSION TEST: <tests/ui/test_x.py::test_y> -- confirmed failing pre-fix: yes/no
GOTCHAS: <entry appended to GOTCHAS.md | none new>
REVIEW: dash-gotchas-review -- <clean | findings + how addressed>
```

Every line is required. "PROOF: n/a" is not a valid value -- if the fix cannot be observed in the browser, it is not a front-end fix, and if it cannot be observed at all, it is not done.
