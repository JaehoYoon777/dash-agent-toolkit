---
name: notebook-to-dash
description: Convert a Jupyter notebook (pandas/numpy/matplotlib/seaborn/ipynb analysis) into a Dash page whose numbers provably match the notebook and whose build provably honors every explicit instruction. Use when asked to "make a dash page/dashboard from this notebook", port .ipynb/jupyter analysis to an app, or when numbers look wrong/off/different between a Dash page and its source notebook ("dashboard values don't match", "app shows different numbers than jupyter", "figures don't match my ipynb"). Enforces a numeric parity gate (golden outputs from the notebook) and an instruction-fidelity ledger before any UI work.
---

# notebook-to-dash

Why conversions fail, in order of damage:
1. **Silent numeric drift** — the agent rewrites the computation freehand while restructuring for callbacks; a changed `dropna`, resample rule, ddof, or join direction shifts every downstream number. Nothing errors. The user finds it by eye.
2. **Dropped explicit instructions** — the agent exercises discretion on the WHOLE prompt instead of only its gaps; stated requirements get averaged away with the vibes.

Both have mechanical fixes. The notebook is executable ground truth; the prompt is a contract. Treat them that way.

## Iron rules

- **Transplant, don't transcribe.** Compute lines move VERBATIM from notebook cells into pure functions. Only two boundaries may change: data loading (notebook I/O → the app's data layer) and presentation (matplotlib/seaborn → Plotly). Every line you DID change gets listed in the parity report.
- **No UI before the parity gate is green.** Ported compute must reproduce the notebook's golden outputs first. A beautiful page with wrong numbers is worse than no page.
- **Discretion only in the gaps.** Explicit instructions are load-bearing; fill unspecified areas with judgment and FLAG each judgment. Never trade an explicit ask for a "better idea" silently — propose, don't substitute.
- **The notebook is the page's default state.** Interactivity is additive: with default control values, the page must show exactly what the notebook shows. New knobs extend; they never redefine.

## Procedure

### Step 0 — Requirements ledger (before reading any code)
From the user's prompt AND notebook markdown cells, extract a numbered ledger:
- `[E#] explicit` — stated requirements, quoted verbatim. Zero discretion.
- `[I#] inferred` — gaps you will fill; note the choice you intend.
If an explicit item is ambiguous enough to change the numbers or the layout materially, ask ONE focused question now — a wrong guess costs a full rebuild.

Then classify the notebook's **archetype** — it decides what "the page" even means:
- **Linear analysis** (load → transform → figures): one page mirroring it top-to-bottom. The common case; the rest of this skill reads naturally.
- **Library + examples** (cells defining a function library + many demo calls): the compute layer is the library cells transplanted verbatim — the porting work is already half done; the PAGE is one control-driven view whose control defaults reproduce ONE designated example. Ask which example is the flagship, or pick and flag `[I#]`. Simulation/validation/assert cells → `dropped (notebook-only validation)` in the coverage map — but harvest their asserts as goldens (Step 1).
- **Report** (mostly markdown + a few figures): static layout, no controls; the parity gate applies unchanged.

### Step 1 — Harvest golden outputs
The `.ipynb` JSON already stores executed outputs — harvest without re-running when outputs are present and the notebook looks linearly executed (execution_counts monotonic). Use `templates/extract_goldens.py`: per code cell → source + stream/execute_result text. Collect as goldens:
- every printed/displayed scalar and small table,
- shapes + a few exact cells of key DataFrames,
- for each figure: WHAT is plotted — series names, transforms, axis assignment, scale (log?), groupby keys (read the plotting cell's source, not the rendered image).
If outputs are missing/stale or execution order is suspect, execute headless first (`jupyter nbconvert --to notebook --execute`) in an env matching the notebook's — pandas MAJOR version drift between notebook env and app env is itself a numbers-change source; pin or verify. (Field note: quant notebooks are commonly saved with outputs STRIPPED — expect the re-execute branch to be the normal path, not the exception.)
**When re-execution disagrees with stored outputs, STOP.** The user approved the STORED numbers; re-executed values may differ (hidden state, data updated since, env drift). Diff them; on any divergence ask ONE question — "notebook shows X, clean re-run gives Y: which is the truth to match?" — and record the answer in the ledger. Silently goldening re-executed values means "provably matching" a notebook the user has never seen.
**Goldens must originate from the NOTEBOOK** — stored outputs or an nbconvert re-execution of the .ipynb — never from the ported module. Asserting the port against values the port itself produced is circular and permanently green. `goldens.json` (and any golden parquet) exists on disk BEFORE the first line of ported code is written.
CAUTION: displayed values are ROUNDED for display. Golden comparisons against parsed display text need tolerance (`rtol` matched to printed precision); re-executed in-memory values allow exact comparison.
**In-notebook asserts are premium goldens.** If the notebook self-verifies (assert cells, planted ground truth, identity checks), reproduce those asserts in the parity suite CALLING THE PORTED MODULE — exact, semantic, immune to display rounding. Rank them above anything parsed from output text.
**Moving inputs (API fetches, "last N days" slices, DB queries that update daily):** goldens against live inputs go red tomorrow by design — that red says nothing about the port. Freeze: snapshot the notebook's exact inputs to a file at harvest time (parquet/CSV, as-of date in the filename); the parity gate runs on the SNAPSHOT forever. The page's live path is covered by loader parity on SCHEMA (shape, dtypes, column set, index monotonicity/tz) rather than values. Any `today`/`tail(N)` anchoring in the compute becomes an explicit parameter — snapshot's as-of date in the gate, live today in the app — with a ledger entry.

### Step 2 — Port compute into a pure layer
One module, no Dash imports (mirror the app's layer rules: compute ≙ services/plotting layer). Functions take data in, return DataFrames/Series/scalars. Cell-to-function mapping stays 1:1 where possible. Keep a **cell coverage map**: every notebook code cell → `ported to <func>` | `dropped (<reason>)` | `deferred (<reason>)`. Silent omission of a cell is how "key instructions" vanish — the map makes omission a visible decision.

### Step 3 — PARITY GATE (mandatory, blocking)
Write the parity test from `templates/test_parity.py`: run ported functions on the SAME inputs the notebook used; assert against goldens (`assert_frame_equal`, `np.allclose` with stated tolerances; check index alignment, dtypes, tz). Run it. Red = fix the port, not the tolerance. State every tolerance and why. Only a green parity run unlocks Step 4.
**Loader parity is part of the gate.** The data-loading boundary is the one place the skill PERMITS a rewrite — so it gets its own check: the APP data layer's output vs the frame the NOTEBOOK loaded (shape, index min/max, dtypes, N spot values). Compute parity against the notebook's CSV while the app silently loads a different date range / adjusted series from its DB is the classic way every number ends up wrong with a green gate.
Common drift sources to check when red: dropna/fillna defaults, `ddof` (pandas std=1, numpy std=0), resample rule + label/closed, merge how= + duplicated keys, sort stability, groupby observed=, pct_change fill_method, datetime tz/normalization, seeds.

### Step 4 — Translate figures (arrays, not pixels)
For each notebook figure, feed the SAME series arrays (from the verified compute layer) into Plotly. Use `reference/mpl_plotly_map.md` for construct mapping (twinx→secondary_y, sns.heatmap→go.Heatmap, hue→per-group traces, etc.) and its trap list (mpl silently drops NaN; seaborn estimators default to mean+CI — reproduce or consciously drop WITH a ledger entry). Parity check: the arrays handed to Plotly equal the arrays the notebook plotted.

### Step 5 — Assemble the page
Now Dash: layout, controls, callbacks — controls' DEFAULT values = the notebook's parameter values. Follow the host app's conventions (palette/theme, figure factories, layer rules, uirevision) — if the repo has agent docs (CLAUDE.md/AGENTS.md), they win on style.
**Iron rule for callbacks: zero compute expressions in callback bodies.** Callbacks may only CALL functions from the parity-tested module — a freehand `df[df.date >= start].std()` inside a callback reintroduces the drift the gate just eliminated, with ddof/dropna choices made a second time. If a control needs a new computation, add it to the compute module and extend the parity test (at least one assertion at a NON-default control value, so interactivity paths are covered, not just the notebook's defaults).
**Runtime triage per ported function — measure, don't guess.** Time each on realistic data, then route: **interactive** (≲1s: callable per control change), **precompute** (slow batch — grid searches, walk-forward sweeps, heavy fits → a generation script writing a parquet artifact the page loads; the script lives next to the page and its outputs are parity-tested like any compute), **exclude** (research-only cells → coverage map `dropped (offline analysis)`). A page that reruns a five-minute cell on every slider tick fails as surely as one with wrong numbers; a page that silently swaps the slow exact method for a fast approximation fails worse — that swap is a ledger item, never a default.

### Step 6 — Fidelity walk (before reporting done)
Walk the ledger item by item: `[E1] <quote> → implemented at <file:line/place>, verified by <parity test / screenshot / value>`. Any `[E#]` not implemented = say so explicitly and why — never silently. List every `[I#]` judgment made. Attach the cell coverage map. This walk IS the deliverable's receipt; a conversion without it is unreviewable.

### Step 7 — Verify in the browser
Hand off to `dash-ui-verify` (or the repo's harness): page renders, key numbers visible on the page spot-match goldens, controls at defaults reproduce the notebook. Screenshot for the visual claim.

## Output contract

End with a **PARITY REPORT** block: the LITERAL pytest command and its result line (`12 passed in 3.1s`) as the receipt — "N checks green" without the command output is an unverifiable claim; tolerances with justification; lines changed vs notebook (the two boundaries only, or justified); cell coverage map; fidelity walk (E-items with evidence, I-judgments); deviations. If the user asked for it as a file, write `PARITY.md` next to the page module.

## When the page later "doesn't match"

Regression path: re-run the parity test first. Three branches, not two:
- **Red parity** = compute drifted (env change, edited function).
- **Green parity + wrong page**: check the DATA LAYER first (app loader returning different range/adjustments/NaN handling than the parity inputs — re-run the loader-parity check), THEN the UI/callback layer (stale Store, wrong control default, transform applied twice, freehand compute in a callback body).
The test bisects the search space in one run — that's why it stays in the repo, not in the chat.
