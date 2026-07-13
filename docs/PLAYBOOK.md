# PLAYBOOK.md — running LLM agents on a highly interactive Dash app

The 10-minute methodology. The skills enforce most of this mechanically; this is the *why* and the human side. Written for an owner who is strong in Python/quant but not frontend — which is exactly the profile that gets hurt worst by these apps, because you can't eyeball-review the generated UI code.

---

## 0. The core insight

A static page (Streamlit dashboard, report generator) is *write-only*: the LLM emits code, you look at the result, done. A highly interactive Dash app is a **distributed system**: server callbacks, clientside JS, browser CSS engine, Plotly.js state, persisted specs — all sharing mutable state. LLMs handle write-only generation brilliantly and distributed shared-state edits poorly, *unless* every edit is verified by machine feedback at the same layer where the bugs live: **the browser**.

Every rule below is a corollary.

## 1. Give the model eyes before asking for visual fixes

Never ask an agent to fix a margin, a legend, a palette, or a "button doesn't work" without a browser feedback loop in place (`dash-ui-verify`). Without it you are the feedback loop, at ~minutes per cycle, and the agent's "done" means "compiles".

- Fast smoke tier (<40s) runs automatically via hook when UI files changed.
- Any visual claim ("legend no longer overlaps") requires the agent to take a screenshot **and look at it** before reporting done.
- Console-error capture is the universal net: a huge share of Dash breakage surfaces as a browser console error or an HTTP 500 on a callback — free to catch, catches classes of bugs you didn't write tests for.

## 2. One concern per prompt; five answers per prompt

Bundled prompts ("fix the calendar, also the shade bug, also add a theme") are the #1 regression source: shared Stores collide, the agent context-switches, and you spend three turns re-fixing collateral damage. Send N prompts for N concerns; verify each.

Every prompt should answer, from its text alone:
1. **What** — one verb, one object.
2. **Where** — file(s)/UI surface, unambiguous locator ("Views > graph > row editor, NOT the shade overlay panel").
3. **Why** — the symptom/user story (agents make better judgment calls knowing the problem).
4. **Not-where** — the don't-touch list (services, schema/version files, shared Store shapes).
5. **Done-when** — a machine-checkable criterion (test passes, screenshot shows X), not "looks good".

Use initiative levels: `L1` = exactly what I asked, `L2` = plus tightly related edge cases (default), `L3/L4` = only when you want proposals.

## 3. Commit per verified change; baseline before anything

- Before the first fix session on any repo: `.gitignore` (pyc, logs, user-state), untrack junk, one baseline commit. **No refactor starts on a dirty tree.**
- Then: one prompt = one verified change = one commit. Never commit with the verify script red. Never bundle two prompts into one commit.
- This is what makes agent damage cheap: `git revert` beats three turns of "fix forward". If you can't revert, every regression is an archaeology dig.

## 4. Executable invariants beat prose rules

Documentation-only invariants ("these 5 places must agree", "max 4 writers per Store") fail exactly when needed: long sessions, big files, agents that never read the doc. Convert each one into a check in the repo's verify script:

- Derive repeated key-lists from a single source (dict comprehension from the defaults dict), so drift is impossible by construction.
- Walk the rendered layout (`render({})` component tree) and assert the derived keys all appear.
- Count writers per hot `Output` from `app.callback_map` against a declared manifest; **fail on any diff, higher or lower**, with a message telling the agent to update the doc + manifest together with justification.
- Assert installed package versions match pyproject `==` pins.

Then wire the verify script into the post-edit hook. Rules the machine enforces survive; rules the model must remember don't.

## 5. Version truth

Agents write code for the version your docs claim, not the one you run. After any environment change: pin `==` to installed reality, update the tech-stack section of the agent docs, and keep the runtime-version gate green. Include version-specific warnings for known landmines (e.g. Dash 4: Radix-based dropdown DOM; mount-triggered `allow_duplicate` URL writes don't chain).

## 6. All agents, one rulebook

Claude Code reads `CLAUDE.md`. Codex and modern Cursor read `AGENTS.md`. Older Cursor reads `.cursor/rules/*.mdc`. If you use more than one agent, maintain ONE source of truth and mirror the invariants + canonical verify commands into the others, each stating "source of truth wins on conflict". An invariant only one agent can see is a rule two agents will break. `dash-install-guardrails` section 8 ships the mirror templates plus the agent-agnostic git pre-commit gate — the enforcement layer for agents whose hooks never fire.

## 7. God modules: gate, then split

Don't let the main view file grow past ~800 lines / ~8 callbacks. If it already has (they always have), the order is non-negotiable: **executable invariants first** (§4), *then* mechanical split (package conversion → pure functions → layout → callbacks-by-concern), bodies verbatim, IDs and callback signatures frozen, verify green per step, one commit per step.

## 8. Blessed factories over per-view reinvention

One `plotting/factories.py` owns figure assembly (multi-axis lines, subplot grids with per-subplot legends via plotly ≥5.15 legend refs, axis-scoped `uirevision` threading). Views and dashboards call factories; they do not hand-roll `make_subplots` + layout dicts. When an agent adds a new chart, the prompt says "use the factory; if it can't express X, extend the factory — don't inline". This is how a legend fix lands everywhere at once.

## 9. Cloud-sync hygiene (OneDrive/Dropbox machines)

- Source code syncing is fine. **Hot-path I/O is not**: per-interaction state writes and GB-scale data reads through a synced folder add 100–500ms each and occasionally corrupt things.
- Local mirror for read-only data (copy-if-newer on launch, env-var override for the path).
- Debounce/batch state writes (write-behind auto-save) before considering moving user state off the sync channel — the sync may be your home↔work transport, so measure first.
- Never put venvs, Playwright browsers, or test artifacts inside the synced tree.

## 10. Session hygiene

- Fresh agent session at every natural seam (feature → bug → new feature). Stale context biases more than it helps.
- Paste tracebacks and DOM dumps verbatim; never summarize them.
- For UI bugs, give the reproduction path, not the diagnosis ("click X, then Y — the graph keeps the old range"), and let the harness confirm the fix.
- When a fix "doesn't take", the model's mental model is wrong — more `!important`/more observers/more guards is never the answer. Demand the agent verify its selectors/assumptions against the live DOM (`dash-gotchas-review` P1/P2).

## 11. Fanning out builders (validated recipe)

Ten Sonnet-class agents each shipped a working ~400-LOC interactive dashboard module in one pass (10/10) when given this context pack — and reliability collapses when parts are missing:

1. **One exemplar file** to imitate (the best existing module — contract, load pattern, palette handling).
2. **The blessed factory** they must use (no hand-rolled grids).
3. **A hard contract**: exactly one new file; unique ID prefix; don't-touch list; registry wired centrally by the orchestrator, never by agents.
4. **A version-specific landmine list** (e.g. "Dash 4: Slider has no style prop; wrap in html.Div"). Without it, 7 of 10 agents burned a debug loop on the same removed prop; a second fan-out (4 agents, deeper modules) WITH the list hit zero traps.
5. **Store-validated data samples** — curated tickers/IDs verified against the actual data store, not the metadata table (see catalogue #11).
6. **A mandatory self-run smoke command** with seeded synthetic data; "do not report success with a failing smoke".
7. **Structured friction harvest**: require `errors_encountered` (symptom→cause→fix) and `api_gaps` in every agent's report. Convergent complaints across agents are your genuine API/docs backlog — six of ten independently flagged the same cache-API ambiguity; that's a roadmap item, not noise. Agents also catch the ORCHESTRATOR's blind spots ("my module is unreachable until X is wired").
8. **Copy, don't describe, subtle contracts**: for invariants like save/auto-save guard chains, instruct "copy the exemplar's function structure EXACTLY and adapt fields" — imitation of verified code transfers subtle guards reliably; prose specifications of the same rules don't.
9. **Grep for hardcoded dispatch outside the registry before adding plugins** (`rg 'fw_id ==|framework =='`). A plugin registry coexisting with a hardcoded if/elif dispatch somewhere else means every new plugin dead-clicks with zero error — the modules were fine, the integration point was the bug.

Windows agent environments additionally need: `encoding="utf-8"` on every `open()`, `PYTHONIOENCODING=utf-8` in shells (cp949 consoles), and scratch `.py` files instead of PowerShell here-string inline scripts.

10. **Forbid re-delegation, in bold, in the pack.** A third fan-out (10 background builder agents with sub-agent-spawning ability) had ALL TEN immediately delegate the build to a sub-agent of their own and stop with "waiting for the background agent" — trigger phrase was the pack's "you are one agent in a fan-out" framing. The orphaned grandchildren then raced their corrected parents for the same file, and agents received cross-agent abort messages they (correctly) refused as unverifiable. The fix that worked: a bold first-paragraph rule — "YOU do the work yourself, with your own tools, synchronously. NEVER spawn another agent, NEVER wait for a background agent — there is no other agent." Orchestrator side: treat any builder reply of the form "the build agent is running, I'll wait" as a FAILURE and immediately resume that agent with the correction; audit final file state centrally regardless, since two writers may have touched it.
11. **Expect duplicated-writer convergence, not corruption.** When a parent and its orphan child both built the same module from the same pack, both produced spec-compliant files and the survivor passed the strengthened smoke — packs with exemplar + contract + smoke make double-builds converge. The audit is still mandatory: the parent must re-verify the on-disk state it did not fully write (line-by-line vs spec + its own smoke run).

### 11a. Scaling the fan-out: 6 waves, ~60 modules (validated 2026-07-05)

A single session grew a Dash research app by 30 monitor dashboards + 30 interactive view-frameworks + 90 example saved views, ten agents per wave. What the scale-up taught:

12. **Use the Workflow tool, not raw Agent-tool fan-out, for builders.** The Agent-tool wave hit the re-delegation cascade (item 10). The five Workflow-tool waves that followed (50 agents) had ZERO re-delegations — the Workflow runtime frames each agent's final text as the return value, which structurally suppresses the coordinate-instead-of-build mode. A JSON return-schema on each agent also forces completion and gives a clean structured harvest. Keep the bold anti-delegation rule in the pack anyway (belt-and-suspenders).
13. **Reconcile from DISK, not from the report.** ~1 in 3 agents of a large wave can die with "connection closed mid-response" — and it happens during FINAL report emission, i.e. AFTER the module + artifacts + smoke already landed on disk. Never treat the report count as the delivery count. After every wave: `grep` each expected file for its contract symbols, run one boot smoke (registry collision check + construct/render each new unit), and count persistent artifacts. The "failed" agents' work is usually complete and correct — verify it live rather than rebuilding.
14. **Name the expected pre-wiring failure state for orchestrator-owned files.** If agents build modules but a central protected file (schema-version registry, plugin registry, central dispatch) is orchestrator-owned, the agent's own artifacts will read as broken until you wire them (e.g. a saved view reports `incompatible` until `SCHEMA_VERSIONS[fw]` exists). Tell agents this is EXPECTED and forbid "fixing" it (no monkeypatching the protected file). The orchestrator then wires all N entries in one pass and a single boot smoke flips everything green.
15. **Idempotent side-effect artifacts.** If the build creates persistent artifacts with non-deterministic ids (saved views via a fresh-UUID factory, generated files), a re-run leaves duplicates. Instruct agents to create their set once and delete first-run extras, or dedup centrally by id after integration. Verify with a per-type count.
16. **Grep-your-prefix catches the ORCHESTRATOR's mistakes too.** The "grep your unique prefix repo-wide before finalizing" rule (item 8's cousin) caught a case where the orchestrator assigned the SAME id-prefix to a dashboard in one wave and a framework in a later wave — a silent cross-firing bug (pattern-matching ids are global). The agent self-corrected and flagged it. Keep the rule mandatory even when you believe the roster is collision-free, and record the ACTUAL shipped prefix in docs, not the assigned one.

The residual cost at scale is entirely in central INTEGRATION (serial, orchestrator-owned: wire registry + version + docs, boot smoke, browser spot-check, commit per wave) — the parallel BUILD is cheap and reliable once the pack is right.

## 12. When to consider leaving Dash

Honest note: Dash is workable with this toolkit, but it fights LLMs more than a typical React/TypeScript stack does (less training data for its callback model, version-sensitive DOM internals, server round-trip interactivity). If the app's scope keeps growing — real-time interactions, complex client state — a rewrite conversation (FastAPI + React, or dash→dmc-native throughout) is legitimate. Run `dash-diagnose`, land Phases 0–2 (git, versions, eyes), and *then* decide with data: if the CSS war and callback sprawl keep generating regressions after the harness is in place, the structural ceiling — not the agent — is the problem.

## 13. Greenfield: build it un-diagnosable (validated day-one checklist)

The catalogue describes diseases; a new app can be born immune to all of them. A full portal (5 pages, data layer over a 200-leaf HDF5, light/dark theming, persisted watchlist/settings, Playwright harness) built with this checklist went 9/9 green on its browser suite the same day, with exactly two test-side fixes and zero app-side debugging:

- **git init before the first module; version-truth table (installed reality) in AGENTS.md + pyproject in the same commit** (kills catalogue #3).
- **Env-overridable data path AND state dir from the first line of config** (`APP_DB`, `APP_STATE_DIR`) — the harness sandbox is a design input, not a retrofit (kills the harness's only production-edit).
- **Pickers fed from the STORE's own catalog** (walk the actual HDF5/DB), never from a metadata sheet — advertised-but-absent leaves become structurally impossible (kills #11).
- **One color source** (a tokens module); component library themes natively (dmc `MantineProvider forceColorScheme`); Plotly gets an EXPLICIT template (paper/plot/font/grid) derived from the same tokens. No CSS file carries color → the override war can never start (kills #5). Runtime theme toggles need those explicit template colors — default-template figures won't follow.
- **`app.layout` is a function from day one** (kills #10).
- **One writer per Store, enforced at design time** — merge "N buttons feed one control" into one callback with `ctx.triggered_id` instead of N `allow_duplicate` writers (kills #7's sprawl).
- **Pure compute module; callbacks contain zero compute expressions** — every number on a page is testable without a browser (imports the notebook-to-dash iron rule into app code).
- **Blessed factories before the second page exists**, including the ones fan-out agents converge on asking for: multi-line, ranked bar, heatmap, sparkline, empty-note placeholder — all setting `uirevision`, window-keyed `revision` param (kills #2, #8).
- **Range/window helper in the compute layer** ("1Y/3Y/MAX" → clipped frame, anchored on the DATA's last date, not wall clock — see catalogue #12) — in one fan-out, 5 of 10 agents independently hand-rolled this mapping.
- **Harness lands the same day**: synthetic fixture data mirroring the real store's PHYSICAL layout (same group/dataset schema) so the data layer needs zero test-only branches; sandboxed state dir; console-error/pageerror/5xx net autouse on every test; smoke marker tier wired to hooks.
- **Pattern-matching callbacks that write state guard the all-None mount firing** (`PreventUpdate`) at first writing (kills #9).

## 14. Deployment + enforcement model

A toolkit that lives only in its own repo is invisible: an audited app shipped five browser-class regressions while the verify harness sat uninstalled one directory away. Deployment and enforcement are part of the methodology, not an afterthought.

- **Skills install at user level, per machine.** Run `install.ps1` once per machine (copies the skills into `~/.claude/skills/`); re-run it after every toolkit pull -- installed copies do not track the repo. Browser binaries and venvs never sync between machines either; reinstall those per machine too (see `dash-ui-verify`).
- **The enforcement stack is `dash-install-guardrails`, applied per app repo:** hooks (post-edit smoke + a Stop gate; match Bash-mediated writes as well as Edit/Write, or the gate has a silent bypass), executable invariants in the verify script (installed-vs-pinned version gate, store-writer manifest counted from `app.callback_map`, rendered-layout key walk), a build stamp (footer hash so a stale server is self-evident -- catalogue #16), and a sandboxed, env-overridable state dir so verification can never mutate production state. `dash-ui-verify`'s smoke tier runs on top of these checks.
- **Escalation rule of thumb.** Said once: put it in the prompt. Said twice: write it in the repo docs (GOTCHAS/AGENTS). Said three times: machine-enforce it via guardrails -- a hook, a verify check, or a ratchet test. A rule you keep repeating is an enforcement gap, not a communication problem.
- **PROMPTING templates never repeat a rule a hook already enforces.** If a template still says "run the smoke test before reporting done", the hook is missing, not the sentence. Prompt text is for judgment and context; the machine handles compliance (section 4: rules the machine enforces survive; rules the model must remember don't).

