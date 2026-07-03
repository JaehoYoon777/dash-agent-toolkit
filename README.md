# dash-agent-toolkit

Skills + playbook for building and maintaining **highly interactive Plotly Dash apps with LLM coding agents** (Claude Code, Cursor, Codex) without the whack-a-mole: buttons that break, margins that drift, multi-axis charts that misrender, calendars that don't update graphs, saved state that doesn't stick, and fixes that break something else.

Distilled from a deep multi-agent audit of a real production Dash app (a quant research portal) that exhibited every one of those failure modes. The root causes turned out to be structural and generic — they will exist in any LLM-built Dash app of nontrivial size. This toolkit packages the diagnosis procedure, the verification harness, and the review checklist so they can be applied to **any** Dash repo.

**Field-validated (2026-07):** the toolkit was dogfooded on a lab copy of the source app — the harness went up in ~2 hours and immediately caught three real production bugs invisible to import-level tests (a saved-view wipe chain, a save race, boot-frozen settings → catalogue classes 9–10), then a 10-agent fan-out built 10 interactive dashboards (10/10 shipped) using the PLAYBOOK §11 recipe, surfacing catalogue class 11 and the Dash-4 landmine list along the way.

## What's inside

```
dash-agent-toolkit/
  README.md                        <- you are here
  docs/
    PLAYBOOK.md                    <- human-side methodology: how to run agents on a Dash app
    FAILURE_CATALOGUE.md           <- the 8 failure classes: symptom -> mechanism -> detection -> fix
  skills/
    dash-diagnose/
      SKILL.md                     <- audits a Dash repo, writes DIAGNOSIS.md + ROADMAP.md into it
    dash-ui-verify/
      SKILL.md                     <- browser-verification workflow ("give the model eyes")
      reference/harness_spec.md    <- full design spec for the Playwright harness
      templates/                   <- conftest.py, helpers.py, test templates, snap.py, Stop hook
    dash-gotchas-review/
      SKILL.md                     <- pre-ship review checklist for any Dash UI change
```

## Install (work PC or anywhere)

1. Clone this repo.
2. Copy the three skill folders into the **target repo**:
   ```
   <target-repo>/.claude/skills/dash-diagnose/
   <target-repo>/.claude/skills/dash-ui-verify/
   <target-repo>/.claude/skills/dash-gotchas-review/
   ```
   (Or into `~/.claude/skills/` to make them available in every project.)
3. Claude Code picks them up automatically. For **Cursor** and **Codex**, the skills' outputs (canonical verify commands, invariants) get mirrored into `AGENTS.md` and `.cursor/rules/` — the `dash-diagnose` roadmap includes a step that creates those mirrors.

## Order of operations on a new (or ailing) Dash repo

1. **`dash-diagnose`** — run first. Audits the repo (version drift, callback/store census, uirevision keying, CSS-war metrics, verification gap, git health, perf hot paths) and writes `DIAGNOSIS.md` + a sequenced `ROADMAP.md` **into the target repo**, with every fix item as a copy-paste-ready one-session prompt.
2. **`dash-ui-verify`** — the highest-leverage fix. Stands up a Playwright smoke suite so agents *see* broken UI (screenshots, console errors, computed styles, rendered viewports) instead of guessing. Usually Phase 1 of the generated roadmap.
3. **`dash-gotchas-review`** — run before shipping any UI change, forever. Makes the classic Dash/CSS failure patterns an executable checklist instead of tribal knowledge.

Read `docs/PLAYBOOK.md` once yourself — it is the 10-minute version of everything the skills enforce.

## Requirements

- Python 3.10+ environment that can import the target app.
- For `dash-ui-verify`: `pip install pytest playwright pytest-playwright && playwright install chromium`.
- Keep browser binaries, venvs, and test artifacts **outside** cloud-synced folders (OneDrive/Dropbox) — see PLAYBOOK.md "Cloud-sync hygiene".
