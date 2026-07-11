---
name: dash-fix-persistence
description: Debugging procedure for saved-state bugs in Dash apps -- use when "settings don't stick", "F5 reverts my settings", a saved view "changed by itself" or got modified just by opening it, a saved dropdown value vanishes after reload, a state/JSON file got wiped or reset to defaults, auto-save fires too often, or smoke tests pass while user data quietly mutates. Covers mount-echo save chains, dirty-check and debounce hygiene, atomic writes, boot-frozen layout state, options supersets, state sandboxing, and round-trip verification.
---

# dash-fix: saved-state / persistence

Persistence bugs are silent: the app looks right while the file on disk mutates.
Debug from the FILE, not from the UI.

## 0. THE standard test: byte-compare across open-close

Run this before debugging anything else. It answers the central question: does the
app mutate state it merely reads?

```python
import hashlib
from pathlib import Path
snap = lambda d: {p.relative_to(d).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
                  for p in Path(d).rglob("*.json")}
before = snap(state_dir)
# browser: open the saved view / settings page, touch NOTHING, navigate away, close
after = snap(state_dir)
assert after == before, sorted(k for k in before if before[k] != after.get(k))
```

Any diff with zero user edits = the open-mutates-save chain (section 1). Diff the
changed file's content to see exactly which fields the app rewrote. Make this test
a permanent harness case (dash-ui-verify) so it can never regress silently.

## 1. The open-mutates-save chain

Three ingredients, each innocent alone; together they rewrite files on open:

1. **Mount echo.** Opening a view inserts controls; Dash fires callbacks whose
   Inputs were inserted by another callback -- `prevent_initial_call` does NOT
   stop these. Control-to-store sync callbacks fire with whatever the controls
   report at that instant, including not-yet-rendered `None`s.
2. **Lossy normalization inside the sync.** `value or ""` turns transient None
   into a persisted empty string; nearest-snap helpers quantize stored values to
   the widget's grid; `name or "(unnamed)"` in a saver that derives the FILENAME
   from the name renames the file on disk (e.g. a graph view whose row sync wrote
   `ticker=""` into the spec on every open).
3. **Auto-save downstream** persists whatever landed in the store.

Fix at all three links, not just one:
- Syncs skip fields whose incoming value is None -- None means "not rendered yet
  or normalized away", never "user cleared it". Write only the keys belonging to
  `ctx.triggered_id`'s row, not the whole pattern-matched set.
- Normalization must be idempotent and lossless over every legal saved value.
- The saver refuses to write when new state equals the last-persisted snapshot.

## 2. Auto-save hygiene

- **Dirty-check**: compare candidate state against a last-persisted snapshot
  (kept in a Store), deep-equal. "An Input fired" is not evidence of change --
  unconditional `return spec` from a sync callback makes every mount a save.
- **Write-behind debounce**: collapse edit bursts into one write (1-2 s timer or
  interval-flushed pending-write Store). A save per keystroke is a bug even when
  each save is correct.
- **O(1) save path**: no directory scans inside the save chain. Name files by id
  or keep an in-process id-to-path index (e.g. an app doing two full
  read-and-parse scans of the views dir per dropdown change -- the cost hides
  under "plotting is slow").
- **Explicit save acknowledgment**, distinct from any live-preview signal. A body
  class flipping or an optimistic store update proves nothing about disk
  (gotchas-review P13). Tests wait on the ack ("Saved HH:MM:SS"), never on the
  preview.

## 3. Write/read integrity

- **Atomic writes**: tmp file in the same directory, then `os.replace`. Bare
  `write_text` means a crash mid-write leaves corrupt JSON.
- **Never silent fallback-to-defaults on read error.** `except OSError: return
  DEFAULTS` followed by a read-modify-write `update()` is the state-wipe path: a
  transient lock (cloud sync, antivirus) makes load() return defaults, and the
  next save persists them over the user's real settings. Same pattern with
  `return []` truncates favorites/history lists. Instead: quarantine the
  unreadable file to a timestamped `.bak`, surface the error, and refuse to write
  a defaults-shaped payload over a quarantined original.
- **Read paths must not write.** Load-time migrations, `updated_at` bumps, or
  "save missing defaults" inside layout/render functions are mutation bugs --
  they turn every page view into a writer.
- **Cloud-synced state dirs** (OneDrive/Dropbox) amplify all of the above:
  100-500 ms sync latency per write, renames seen as delete+create, transient
  locks triggering the fallback-read wipe. Keep live state on local disk; sync
  only explicit exports.

## 4. Boot-frozen layout state

`app.layout = <static object>` evaluates `dcc.Store(data=load_state())` ONCE at
server boot. Every F5/new tab re-serves the frozen snapshot; SPA navigation masks
it. Symptom: settings save and work -- until a reload reverts them, until the
server restarts. Fix: `app.layout = serve_layout` (a function), so loads run per
page load; or rehydrate the Store from disk in the initial URL callback.
Cross-ref gotchas-review P14.

```bash
rg -n "app.layout" --type py   # not a callable + Store(data=<loaded>) inside = frozen
```

Verify: save -> full browser reload -> effect survives, without a server restart.

## 5. Saved values must survive mount

- **Options superset**: Dash >= 4 normalizes a dropdown value missing from
  `options` to None AT MOUNT. Any dropdown whose value can come from saved state
  needs options built as reference list UNION all values present in saved/live
  data -- otherwise the mount echo (section 1) wipes the saved row.
- **None-preserving syncs**: control-to-store syncs use
  `value if value is not None else existing`, never `value or ""`.
Cross-ref gotchas-review P12 for the pre-ship check of both.

## 6. Sandboxing (non-negotiable)

The state directory MUST be env-overridable:

```python
STATE_DIR = Path(os.environ.get("MYAPP_STATE_DIR", DEFAULT_STATE_DIR))
```

Tests, verify scripts, and every agent-driven boot point it at a tmp copy. A
verify that touches production state is a whack-a-mole amplifier: smoke passes
while it migrates, purges, and rewrites real files, so "verified" state drifts
and the next report reads as a new user-caused bug. Watch for boot side effects
(trash purge, asset regeneration, migration saves) that run inside the app
factory even when imported by a test. This env override is the one production
edit the dash-ui-verify harness requires; its non-negotiables list sandboxed
state first for this reason.

## 7. Round-trip verification scenario

The done-when for any persistence fix -- all five steps, in order:

1. Edit EVERY touched field, not a representative one.
2. Wait for the explicit save acknowledgment (never the preview signal).
3. Navigate away -> back: assert every field restored.
4. F5 (full reload): assert every field again -- catches boot-frozen state
   (section 4).
5. Re-run the section-0 byte-compare across one more open-close of the saved
   item: zero-edit opens must be byte-identical.

Automate as a dash-ui-verify flow test against the sandboxed state dir; wire it
into the repo's verify checks via dash-install-guardrails so it runs before any
"done" report.
