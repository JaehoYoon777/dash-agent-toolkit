# PROMPTS.md -- copy-paste prompt cookbook for the toolkit skills

Ready-to-paste prompts, all following the PLAYBOOK section 2 shape (what /
where / why / not-where / done-when). Rule of thumb: **one driver skill per
prompt** -- the others chain through done-when criteria and the skills' own
handoffs (dash-fix runs gotchas-review + ui-verify as exit conditions;
guardrails hands off to ui-verify Mode B; diagnose emits a roadmap dash-fix
executes). Naming two peer skills as co-drivers invites context-switching;
sequence them as numbered phases instead.

Replace `<id>`, routes, interpreter names, and store ids with your repo's.

---

## The headline case: many little bugs, can't list them all

Sweep finds, loop fixes. Never "test everything and fix everything" in one
breath -- bundled fixes are the #1 regression source (PLAYBOOK section 2).

**Optimal short prompt:**

```
On /views/<id>: use dash-ui-verify to exercise every interactive control once
and list all findings (errors, no-effect controls, state resets, saved-file
mutations) with repro steps -- fix nothing yet. Then fix findings one at a time
with dash-fix: worst first, one commit each with browser proof + regression
test. Stop and ask before touching shared stores. Finish by committing the
sweep as a permanent smoke test.
```

**Ultra-short (the skills carry the rest of the discipline):**

```
Sweep /views/<id> with dash-ui-verify: exercise every control, list findings,
no fixes. Then dash-fix each one -- one commit per fix, worst first, stop
before shared-store changes. Commit the sweep as a permanent test.
```

Why each clause survives compression: "list, no fixes" prevents the
bundled-fix spiral; "one commit each" makes any bad fix a one-revert undo;
"worst first" gets data-destroyers before cosmetics; "stop before shared
stores" is the blast-radius fuse; "commit the sweep" makes the class
self-catching next time. Everything else (screenshots, console net, budgets,
review) the skills enforce on their own.

**Expanded two-stage version** (when you want explicit control):

Stage 1 -- enumerate, no fixing:

```
On /views/<id>: enumerate every interactive control on the page (buttons,
dropdowns, text inputs, date pickers, checkboxes, panel toggles, row
add/delete). Using the dash-ui-verify harness (build Mode B first if
tests/ui doesn't exist), exercise each control once and record:
- console errors / pageerrors / 500s (the harness net catches these free)
- controls that produce NO observable change after firing
- zoom/legend state lost after an unrelated control fires
- saved-view file mutated on open or by a cosmetic control (byte-compare)
- payload > 200KB for a cosmetic tweak (Network log)
Output a numbered findings list with exact repro steps per item.
DO NOT fix anything yet.
```

Stage 2 -- fix loop:

```
Fix the findings one at a time using dash-fix: for each -- reproduce,
minimal fix, browser proof, regression test, dash-gotchas-review on the
diff, one commit. Order: data-destroying first, then broken, then slow,
then cosmetic. If any fix requires touching shared stores or their writers,
stop and report before proceeding. After each fix re-run the Stage-1 sweep
on that control's neighbors (blast radius).
```

---

## Single-skill prompts

### dash-fix -- behavior bug

```
Use dash-fix. The delete-row button in the graph view row editor does nothing
(no error, row stays). Route /views/<id>, row editor panel, NOT the sidebar
delete. Started after yesterday's spec-store change. Don't touch:
view_store.py, schema version. Done when: click deletes the row in the
browser, regression test committed, gotchas-review clean.
```

### dash-fix -- slow/laggy

```
Use dash-fix, perf playbook. Changing line color takes ~2s; typing in the name
field freezes the page. Route /views/<id>. Measure first and show me the four
bucket numbers BEFORE fixing anything; then fix only the winning bucket.
Don't touch: figure factories used by other views. Done when: before/after
numbers in the report + latency budget test committed.
```

### dash-fix -- "nothing changed"

```
Your last fix shows no effect in my browser. Run dash-fix stale playbook
top to bottom before editing anything else. Done when: build stamp proves
the served process runs current code AND the original symptom is re-judged
against that proof.
```

### dash-fix -- saved state corrupted

```
Use dash-fix, persistence playbook. Opening my saved view changes it somehow
-- colors got wiped and line widths changed with zero edits from me.
Done when: the saved file is byte-identical after open -> idle -> navigate
away, and that check is a committed test.
```

### dash-ui-verify -- Mode B, build the harness (one-time)

```
Use dash-ui-verify Mode B: build the browser harness for this repo.
Interpreter <env-python>, state dir must be sandboxed (env override), seed
synthetic data -- never the real DB. Done when: smoke tier green under 40s
and one screenshot per route in artifacts/.
```

### dash-ui-verify -- Mode A, verify a visual claim

```
Use dash-ui-verify: prove the dropdown menu is readable in all palettes,
open state included (it portals to body). Screenshots per palette, and Read
them before claiming success.
```

### dash-install-guardrails (one-time per repo)

```
Use dash-install-guardrails on this repo. Verify command: python verify.py
(<env-python>). Hot stores: <store-id-1>, <store-id-2>. Do the git hygiene
commit first if the tree is dirty. Done when: all 7 deliberate breaks fire
their gates and the install is one commit.
```

### dash-diagnose (unfamiliar or ailing repo)

```
Use dash-diagnose on this repo. Read-only. Done when: DIAGNOSIS.md +
ROADMAP.md exist in repo root with file:line evidence and every roadmap
item is a one-session copy-paste prompt.
```

### dash-gotchas-review (pre-ship, standalone)

```
Run dash-gotchas-review on the current diff only. Report
location -- problem -- fix lines; do not fix anything.
```

### notebook-to-dash

```
Use notebook-to-dash: port <path/to/notebook>.ipynb into a new view
framework. Numbers must match the notebook via the parity gate BEFORE any
UI work. Don't touch existing frameworks.
```

---

## Multi-skill combos (numbered phases, one commit each)

### New repo, first session: guardrails -> harness -> diagnose

```
Three phases, one commit each, in order:
1. dash-install-guardrails (verify command python verify.py, <env-python>).
2. dash-ui-verify Mode B -- wire its smoke tier into the guardrails Stop
   gate's SMOKE_CMD (one Stop gate only).
3. dash-diagnose -- write DIAGNOSIS.md + ROADMAP.md.
Stop after phase 3 and show me the roadmap before fixing anything.
```

### Feature build with built-in QA (no skill named -- done-when pulls them in)

```
Add a "download CSV" button to the <X> view, below the <Y> table. L2.
Don't touch: <compute module>, other views' stores. Done when: clicking
downloads correct CSV in the harness browser test, gotchas-review clean
on the diff, smoke green.
```

### Diagnose-then-execute

```
Run dash-diagnose. Then execute ROADMAP Phase 0 and Phase 1 items only,
one item = one commit, using dash-fix discipline per item (repro, minimal
diff, browser proof). Stop before Phase 2 and report.
```

### Notebook port + perf budgets + review chain

```
notebook-to-dash on <notebook>.ipynb -> new view. After parity gate passes:
apply dash-fix perf playbook budgets (route payload < 500KB, control tweak
< 800ms -- commit the budget tests), then dash-gotchas-review before done.
```

### Escalation: recurring bug -> structural cause

```
This is the third time <symptom> came back. Stop patching: run dash-diagnose
scoped to callbacks/stores/uirevision only, show me the findings, and propose
which ROADMAP item kills the class. Do not fix yet.
```

---

## Recommended order on a new (or ailing) repo

1. `dash-install-guardrails` -- includes the git baseline gate the repo
   probably needs.
2. `dash-ui-verify` Mode B -- the eyes (~1-2 sessions, one-time).
3. The sweep-then-fix pair above -- clear the backlog.
4. `dash-fix` forever after, per bug; `dash-gotchas-review` stays the
   pre-ship gate; `dash-diagnose` when a symptom class recurs 3+ times.
