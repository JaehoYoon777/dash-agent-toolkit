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

Claude Code reads `CLAUDE.md`. Codex and modern Cursor read `AGENTS.md`. Older Cursor reads `.cursor/rules/*.mdc`. If you use more than one agent, maintain ONE source of truth and mirror the invariants + canonical verify commands into the others, each stating "source of truth wins on conflict". An invariant only one agent can see is a rule two agents will break.

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
- When a fix "doesn't take", the model's mental model is wrong — more `!important`/more observers/more guards is never the answer. Demand the agent verify its selectors/assumptions against the live DOM (`dash-gotchas-review` P7/P8).

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

## 12. When to consider leaving Dash

Honest note: Dash is workable with this toolkit, but it fights LLMs more than a typical React/TypeScript stack does (less training data for its callback model, version-sensitive DOM internals, server round-trip interactivity). If the app's scope keeps growing — real-time interactions, complex client state — a rewrite conversation (FastAPI + React, or dash→dmc-native throughout) is legitimate. Run `dash-diagnose`, land Phases 0–2 (git, versions, eyes), and *then* decide with data: if the CSS war and callback sprawl keep generating regressions after the harness is in place, the structural ceiling — not the agent — is the problem.
