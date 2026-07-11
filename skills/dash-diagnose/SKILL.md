---
name: dash-diagnose
description: Audits a Plotly Dash codebase for the structural causes of LLM whack-a-mole (version drift, god modules, store-writer sprawl, uirevision bugs, CSS override wars, verification gaps, hot-path I/O, git health) and writes DIAGNOSIS.md + a sequenced ROADMAP.md with copy-paste-ready fix prompts into the repo. Use when the user asks to diagnose, audit, review, or "figure out why my Dash app keeps breaking", when starting work on an unfamiliar Dash repo, or before planning any refactor of a Dash app.
---

# dash-diagnose

Audit a Dash repo, produce two files **in the target repo root**:
- `DIAGNOSIS.md` — findings with file:line evidence, one section per failure class that applies.
- `ROADMAP.md` — sequenced fix plan; every item a copy-paste-ready prompt sized one-session-one-commit.

Reference: `docs/FAILURE_CATALOGUE.md` in the dash-agent-toolkit repo (symptom → mechanism → detection → fix per class). If it is available (toolkit cloned or skill shipped with `reference/`), read it first.

## Procedure

Run ALL audits below (read-only) before writing anything. Use subagents for the large-file reads if the repo is big. Collect concrete evidence: file:line, counts, versions. No finding without evidence.

### Audit 1 — Version truth
```bash
python -c "import importlib.metadata as m
for p in ('dash','plotly','dash-mantine-components','dash-ag-grid','dash-bootstrap-components','pandas','numpy'):
    try: print(p, m.version(p))
    except Exception: pass"
```
Compare against: pyproject/requirements pins AND version claims in CLAUDE.md/AGENTS.md/README. Flag every mismatch in either direction. Severity: high if major-version drift (Dash 2 vs 3/4 changes DOM internals + callback chaining semantics).
Also record the SERVER BACKEND on Dash ≥4.2 (Flask-decoupled): `python -c "import dash; app=dash.Dash(); print(type(app.server).__module__)"` — Flask vs FastAPI/Quart determines how test harnesses boot the app and whether WSGI-assuming code breaks.

### Audit 2 — Module + callback census
```bash
# largest modules
find . -name "*.py" -not -path "*__pycache__*" | xargs wc -l | sort -rn | head -15
# callbacks per module
rg -c "@callback|@app.callback" --type py | sort -t: -k2 -rn | head
rg -c "clientside_callback" --type py
rg -n "allow_duplicate=True" --type py
```
Then for each `dcc.Store` id that appears in ≥2 `Output(...)` calls, list ALL writers: `rg -n 'Output\("<id>"' --type py`. Red flags: module >800 lines with >8 callbacks; ≥3 writers to one Store; `allow_duplicate` without a justifying comment; invariants ("N places must agree") that exist only in markdown.

### Audit 3 — uirevision keying
```bash
rg -n "uirevision" --type py
```
For each hit: what is the key? Does the figure have a user-controllable date/window control? If the key excludes the data window → the calendar-doesn't-update-the-graph bug class. Also check whether `xaxis.range` is ever set explicitly (it loses to matching uirevision — note it).

### Audit 4 — CSS war metrics
```bash
rg -c "!important" assets/*.css
rg -c "MutationObserver" assets/*.js; rg -c "setProperty" assets/*.js
wc -l assets/*.js assets/*.css
rg -n "MantineProvider|ThemeProvider" --type py; rg -c "dmc\.|dbc\." --type py
```
Questions to answer: is there hand-rolled JS forcing inline styles? Is a native theming provider instantiated but unused (raw dcc/html everywhere)? Are there selectors for component internals that may not exist under the installed version (e.g. `.Select-*` under Dash ≥3)?

### Audit 5 — Verification gap
```bash
rg -l "playwright|selenium|dash.testing|dash_duo"
cat .claude/settings.json 2>/dev/null   # what do hooks run?
ls .github/workflows 2>/dev/null
```
What does the existing smoke/verify script actually check (imports? schemas?) vs what breaks (browser)? Almost always the dominant finding.

### Audit 6 — Perf hot paths
```bash
rg -n "dcc.Interval" --type py
rg -n "write_text|json.dump|\.to_json|open\(" --type py   # writes inside callbacks/services
rg -n "read_hdf|h5py|read_parquet|read_csv|read_excel" --type py
```
Trace the auto-save chain: which Inputs fire the save callback, how many disk writes per routine interaction, are paths under OneDrive/Dropbox (check config constants), any O(N) directory scans per save. Matrix/grid layouts: how many figures per render.

### Audit 7 — Git + agent-visibility health
```bash
git log --oneline | wc -l; git status --porcelain | wc -l
git ls-files "*.pyc" | head -3; test -f .gitignore && echo GITIGNORE_OK || echo GITIGNORE_MISSING
ls AGENTS.md 2>/dev/null; ls .cursor/rules 2>/dev/null; ls CLAUDE.md 2>/dev/null
```
Flag: <5 commits, dirty tree, tracked pyc, missing .gitignore, rules docs visible to only one agent brand.

### Audit 8 — Plotting reinvention
```bash
rg -n "make_subplots" --type py
rg -n "showlegend=False" --type py
rg -n "legend2|legendgroup" --type py
```
Count hand-rolled figure builders per dashboard vs shared factories. Legend suppression + HTML-chip workarounds = the 30-legend pile class.

### Audit 9 — Saved-state destruction chain (catalogue #9)
```bash
rg -n "app.layout" --type py           # static object + data=<loaded state> inside = boot-frozen (catalogue #10)
rg -n 'or ""' --type py                # sync callbacks overwriting with normalized None
rg -n "prevent_initial_call" --type py # which control->store syncs fire on mount?
```
For every dropdown whose value can come from SAVED state: is the options source a superset of every legal saved value? For every Save callback: does it read `State` of a hidden mirror synced by a SERVER callback (race)? Is there a persistence acknowledgment distinct from preview signals?

### Audit 10 — Metadata/store drift (catalogue #11)
Cross-check the ticker/category metadata table's (group, subgroup) pairs against the actual data store's groups (HDF5 `h5py.File(...).keys()`, DB schema, parquet dirs). Report advertised-but-absent leaves — every one is a picker offering data that can never load, and a trap for curated defaults in agent context packs.

### Audit 11 -- Callback cascade + payload
```bash
rg -n 'Output\("[^"]*", ?"children"\)' --type py   # container rebuilds
rg -n 'Input\("[^"]*", ?"data"\)' --type py        # which rebuilds are store-driven (rebuild-all fan-out)
rg -n "options=\w+\(" --type py                    # big option lists embedded per component instance
```
Walk the callback graph for ONE hot interaction (a row/control edit) and count sequential server round-trips: control -> sync writer -> store -> fan-out (children rebuild + figure rebuild + save) -> re-inserted pattern inputs re-fire the sync writer (insert loophole; prevent_initial_call does not stop it) -> echo fan-out. >=3 round-trips per edit is a finding (real case: 5-7 round-trips per edit with double figure rebuilds and double disk writes). A store Input driving a `children` rebuild-all of pattern components is a finding on its own. Any `options=<fn>()` inside a per-row builder means N x list re-serialized per rebuild -- audit the wire payload, not the Python cache. Measure while clicking through each hot interaction (assumes Flask backend -- see Audit 1's server-backend record):
```python
# temporary, do not commit -- paste into app boot
@app.server.after_request
def _sz(r):
    from flask import request
    if r.content_length and r.content_length > 100_000:
        print(f"{r.content_length/1e6:.2f} MB {request.path}")
    return r
```
Findings here map to dash-gotchas-review P16/P17/P18.

### Audit 12 -- Hot-path persistence
```bash
rg -n "write_text|json.dump|\.rename\(" --type py   # every write channel
rg -n "\.glob\(" --type py                          # O(N) dir scans -- flag any reachable from save/get/route
rg -c "os.replace" --type py                        # 0 = no atomic writes anywhere
rg -n "environ" -g "*config*"                       # state dir env-overridable?
```
Trace ONE interaction with auto-save on and count the writers that fire. Is there a dirty-check (diff vs last-persisted snapshot) or debounce before the write, or does every no-op sync write anyway? Flag O(N) scans in save/route paths: a service that globs the state dir and json-parses EVERY file per get/save call turns one dropdown change into 2N reads + 1 write -- the hidden cost usually blamed on plotting (worse on cloud-synced folders, see Audit 6). Atomicity: bare `write_text` corrupts mid-crash, and a reader with silent fallback-to-defaults/empty-list persists the wipe on the next update -- require tmp + `os.replace`. Read paths that WRITE (load-time migrations calling save, boot purging trash) plus a non-overridable state dir mean the smoke/verify script mutates REAL user state while asserting only load-status. Each yes is its own DIAGNOSIS entry.

### Audit 13 -- Enforcement coverage
```bash
cat .claude/settings.json 2>/dev/null               # hook wiring
ls .claude/hooks/ 2>/dev/null
rg -n "matcher|Stop|PreToolUse|PostToolUse" .claude/settings.json 2>/dev/null
python -c "from <app module> import build_app; print(len(build_app().callback_map))"
```
Where guardrails exist, audit coverage, not presence: (a) matchers vs write channels -- Edit|Write matched but Bash unmatched means `echo >> file` / `python -c` bypasses every guard; (b) protected-path patterns -- do they include assets `.js`/`.css` or only `.py`? The CSS/JS override layer is where Dash fixes land; (c) Stop hook -- is "done" gated on the verify script, or is enforcement advisory-only PostToolUse; (d) fail-open branches -- hook scripts with bare `except`/`exit 0` on error enforce nothing exactly when they matter; (e) invariant drift -- recompute every doc-asserted count ("N writers to store X", "M callbacks in module Y") from `app.callback_map` and flag mismatches: a stale census means the next agent justifies its writer against fiction. Gaps here are what the dash-install-guardrails skill's verify checks close -- name each gap so the roadmap can wire it.

### Audit 14 -- Serialization
```bash
python -c "import orjson; print('orjson', orjson.__version__)"  # ImportError on Dash >=4 = slow-path encoder
rg -n "Patch\(" --type py                                       # 0 hits + heavy figure callbacks = full rebuilds
rg -n "dcc.Graph\(" --type py                                   # Graphs delivered inside children without stable id?
rg -n "strftime|astype\(str\)" --type py                        # pre-stringified date axes
```
Four checks: (a) orjson -- Dash >=4 routes every callback response through plotly's to_json_plotly, which uses orjson when importable and a 3-10x slower pure-Python encoder otherwise; a pip install fixes multi-MB responses with zero code changes; (b) unkeyed Graphs inside rebuilt children -- remount on any sibling change discards uirevision (zoom resets) and blocks Patch(); see dash-gotchas-review P18; (c) Patch() adoption -- zero hits plus figure callbacks firing on color/width/range tweaks means whole-figure re-serialization per tweak; (d) date axes -- x-values pre-formatted via strftime/astype(str) risk flipping the axis to category (every label rendered, tick explosion); pass the DatetimeIndex, keep formatting in `tickformat`.

## Writing DIAGNOSIS.md

One section per applicable class (numbered as in FAILURE_CATALOGUE), each with: symptom as the owner experiences it → mechanism → this repo's evidence (file:line, counts) → severity. Lead with a 5-line executive summary naming the top 3 causes. State explicitly which classes did NOT apply.

## Writing ROADMAP.md

Sequence with this dependency logic (proven ordering — do not shuffle):

| Phase | Content | Why this order |
|---|---|---|
| 0.1 | Git baseline: .gitignore, untrack junk, one commit | nothing is safe to change while unrevertable |
| 0.2 | Pin versions to installed reality + fix docs' tech-stack + runtime version gate in verify script | stops agents coding for the wrong framework |
| 0.3 | AGENTS.md + .cursor/rules mirrors of the invariants + canonical commands | all agents, one rulebook |
| 0.4 | Cloud-sync hot-path relocation (read-only data mirror first; state writes only after measuring) | cheap, big latency win |
| 1 | Browser verification harness (dash-ui-verify skill) — smoke tier + hook wiring | everything after this is verifiable |
| 2 | Known-bug patterns found in audits (uirevision axis-scoping, write-behind auto-save, path caches) | highest user-visible value |
| 2.5 | dash-fix playbook classes found in audits 11-14 (cascade reducers, payload diet, persistence hygiene) | user-visible latency + whack-a-mole engine |
| 3 | Executable invariants (single-source key derivations; layout-walk check; store-writer manifest from app.callback_map) | HARD PREREQ for phase 4 |
| 4 | God-module split (mechanical, verbatim moves, 3–5 commits, counts-equal gate) | only behind machine gates |
| 5 | Figure factories + per-subplot legends (plotly ≥5.15 legend refs); migrate hand-rolled builders one per prompt | kills per-view reinvention |
| 6 | Remaining perf items ranked effort→impact | measure before optimizing |
| 7 | LATER, owner sign-off: native-theming migration (dcc→dmc/dbc components), then delete override layers | retires the CSS war structurally |

Every roadmap item MUST be a fenced prompt block following this shape:

```
L1|L2. <one-line what + why>.
<numbered concrete steps with file paths from the audits>
Do not touch: <explicit list>.
Done when: <machine-checkable criterion — a verify-script line, a test, a screenshot assertion>.
Commit as "<message>".
```

Close ROADMAP.md with a risk register: the 2–3 riskiest items, failure mode, mitigation, rollback story (which commit to revert).

## Rules

- Read-only until the two files are written; never fix anything during diagnosis.
- Evidence or it didn't happen: every claim carries file:line or a count.
- Adapt to what you find — the catalogue is a lens, not a script; if the repo has a failure mode not in the catalogue, document it the same way (symptom/mechanism/evidence/fix) and note it as a candidate catalogue addition.
