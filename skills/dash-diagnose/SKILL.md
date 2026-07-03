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
