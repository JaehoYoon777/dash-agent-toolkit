---
name: dash-fix-stale
description: '"My fix didn''t take / nothing changed" playbook for Dash apps. Load when an edit produces no visible effect and the user says "still looks the same", "the change did nothing", "CSS not applying", "I restarted and nothing happened", "the callback still has the old behavior", or when you are about to retry an edit that already failed once. Ordered delivery checks: stale server process (plus the build-stamp pattern), import/pyc cache, browser cache, wrong file copy, Dash version drift, silently blocked writes.'
---

# Stale - "my fix didn't take"

Rule: **prove the new code is RUNNING before debugging its behavior.** An edit with no visible effect is almost never subtle logic - it is one of the six delivery failures below. Run the checks in order; each takes under a minute. Never iterate blind more than once: if attempt 2 also "does nothing", stop editing and run this list top to bottom. (Real cost of skipping: three full turns burned against a stale dev-server process.)

## 1. Stale server process - the usual culprit

Hot reload only exists with `debug=True`; anything else (production-ish launch, background runner, a second instance still holding the port) serves the code from process start, forever.

```
# Windows
Get-NetTCPConnection -LocalPort <port> -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
# POSIX
lsof -ti :<port> | xargs kill -9
```

Relaunch, then confirm via the build stamp.

**The build-stamp pattern - install once, kills this failure class permanently.** If the app has no stamp, add one now as part of the fix:

```python
BUILD_STAMP = time.strftime("%m%d-%H%M%S")  # import time == process start; git SHA if repo
print(f"[boot] build {BUILD_STAMP}", flush=True)
# shell layout footer:
html.Div(f"build {BUILD_STAMP}", id="build-stamp", style={"opacity": 0.4, "fontSize": 10})
```

"Did my change land?" reduces to: stamp in the page == stamp printed by the relaunch you just did. If they differ, you are looking at an old process - nothing you observe means anything yet.

## 2. Python import / pyc cache

Long-lived hosts (Jupyter kernels, REPLs, watch runners) hold old modules across page reloads; stale `.pyc` can shadow source when mtimes get mangled (cloud-sync tools do this).

```
# Windows
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
# POSIX
find . -name __pycache__ -type d -exec rm -rf {} +
```

Restart the PROCESS, not the page. In notebooks: restart the kernel - `importlib.reload` misses transitive imports.

## 3. Browser cache / service worker

Dash serves `assets/` with cache headers; a plain reload can replay old CSS/JS.
- Hard reload: Ctrl+Shift+R, with DevTools open and Network > "Disable cache" checked.
- DevTools > Application > Service Workers: unregister anything registered.
- Confirm delivery, not hope: Network tab, click the asset, check the response body contains your new rule/string.

## 4. Editing the wrong copy

Repo clones, cloud-synced twins (a stale local copy vs the real synced dir), and installed-package-vs-source-tree splits all produce perfect edits to files nobody imports.

```python
import <app_module>; print(<app_module>.__file__)   # run in the SERVER's interpreter/env
```

That path must be the file you edited; compare mtimes if unsure. If it resolves into `site-packages`, you edited source but run an install - `pip install -e .` or launch from the source tree.

## 5. Version drift - the code targets a different Dash

Selectors and idioms written for another Dash generation apply cleanly and do nothing (e.g. `.Select-*` CSS under Dash >= 4, where dropdowns render as Radix popovers with entirely different class names). Before concluding "the CSS is wrong", verify EVERY selector against the live DOM:

```js
document.querySelectorAll('<selector>').length   // 0 = dead rule, not a specificity war
```

Zero matches means rewrite against reality - do NOT add `!important`, observers, or guards to a selector that matches nothing. Full checks: dash-gotchas-review P1 (live DOM before CSS) and P2 (the model is wrong, not the force); confirm the installed version with `python -c "import dash; print(dash.__version__)"` (P9).

## 6. The write never happened

Hooks, permission gates, sandboxes, and sync conflicts can silently drop a file write. Verify the mtime moved and the content is there:

```
# Windows
(Get-Item <file>).LastWriteTime
# POSIX
stat -c %y <file>
```

Then grep the file for the exact new string. Old mtime or missing string = the write was blocked; fix the blocker before touching the code again.

## 7. Discipline

1. Prove-it-ran FIRST: stamp visible and matching the relaunch. Only then debug behavior.
2. One blind retry maximum; the second no-effect triggers checks 1-6 in full.
3. Any visual claim after the fix goes through the dash-ui-verify harness (screenshot, then Read and look at it) - never through memory of what the change should do.
