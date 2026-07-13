# dash-agent-toolkit

Skills + playbook for building and maintaining **highly interactive Plotly Dash apps with LLM coding agents** (Claude Code, Cursor, Codex) without the whack-a-mole: buttons that break, margins that drift, multi-axis charts that misrender, calendars that don't update graphs, saved state that doesn't stick, and fixes that break something else.

Distilled from a deep multi-agent audit of a real production Dash app (a quant research portal) that exhibited every one of those failure modes. The root causes turned out to be structural and generic — they will exist in any LLM-built Dash app of nontrivial size. This toolkit packages the diagnosis procedure, the verification harness, and the review checklist so they can be applied to **any** Dash repo.

**Field-validated (2026-07):** the toolkit was dogfooded on a lab copy of the source app — the harness went up in ~2 hours and immediately caught three real production bugs invisible to import-level tests (a saved-view wipe chain, a save race, boot-frozen settings → catalogue classes 9–10), then a 10-agent fan-out built 10 interactive dashboards (10/10 shipped) using the PLAYBOOK §11 recipe, surfacing catalogue class 11 and the Dash-4 landmine list along the way.

## What's inside

```
dash-agent-toolkit/
  README.md                        <- you are here
  install.ps1                      <- user-level installer (Windows): skills/* -> ~/.claude/skills
  install.sh                       <- same for bash (rsync -a --delete; cp -r fallback)
  docs/
    PLAYBOOK.md                    <- human-side methodology: how to run agents on a Dash app
    FAILURE_CATALOGUE.md           <- the 16 failure classes: symptom -> mechanism -> detection -> fix
    PROMPTS.md                     <- copy-paste prompt cookbook: per-skill + combos + the sweep-then-fix pattern
  skills/
    dash-diagnose/
      SKILL.md                     <- audits a Dash repo, writes DIAGNOSIS.md + ROADMAP.md into it
    dash-ui-verify/
      SKILL.md                     <- browser-verification workflow ("give the model eyes")
      reference/harness_spec.md    <- full design spec for the Playwright harness
      templates/                   <- conftest.py, helpers.py, test templates, snap.py, Stop hook
    dash-gotchas-review/
      SKILL.md                     <- pre-ship review checklist for any Dash UI change
    notebook-to-dash/
      SKILL.md                     <- notebook -> Dash conversion with a numeric parity gate
      reference/mpl_plotly_map.md  <- matplotlib/seaborn -> Plotly mapping + number-changing traps
      templates/                   <- goldens extractor + parity test template
    dash-fix/
      SKILL.md                     <- symptom-dispatched fix loop for any Dash bug; browser proof before done
      reference/                   <- six playbooks: visual, stale, callbacks, perf, routing, persistence
    dash-install-guardrails/
      SKILL.md                     <- wires the enforcement layer (verify checks + hooks) into a target repo
      templates/                   <- PostToolUse + Stop hook scripts, invariant checks, settings.json fragment,
                                      git pre-commit gate + verify.ps1 entrypoint + AGENTS.md/.cursor mirrors (Cursor/Codex)
```

## Install (user-level)

Clone once per machine, run the installer, done -- every skill becomes available in every repo Claude Code opens.

```
git clone <this-repo-url> dash-agent-toolkit
cd dash-agent-toolkit
.\install.ps1     # Windows (PowerShell 5.1+; supports -WhatIf)
./install.sh      # macOS / Linux / Git Bash
```

Each `skills/*` directory is mirrored to `~/.claude/skills/<name>` (robocopy `/MIR` on Windows, `rsync -a --delete` elsewhere), so renames and deletions propagate and the installed set always matches the repo exactly. Idempotent: re-run after every `git pull` to pick up updates. Claude Code auto-discovers user-level skills; no per-repo setup needed.

**Cursor 2.4+ (Jan 2026) discovers the same install:** Cursor supports the Agent Skills standard natively and reads `~/.claude/skills/` for compatibility — so `install.ps1` makes every skill available in Cursor too (restart Cursor after installing). Skills in Cursor are advisory context, not enforcement: Cursor has no PostToolUse/Stop hooks, so pair with the section-8 git gate below.

## Install (per-repo alternative)

Prefer the user-level installer above. To pin skills to one repo instead (versioned with the code), copy any `skills/*` folder into `<target-repo>/.claude/skills/<name>/`. Claude Code picks both locations up automatically.

## Using with Cursor / Codex (no Claude Code hooks)

Cursor and Codex never fire the toolkit's PostToolUse/Stop hooks — in those agents the enforcement layer must live in layers every agent hits. `dash-install-guardrails` **section 8** ships it: a **git pre-commit gate** (`.githooks/pre-commit` runs the one canonical `scripts/verify.ps1`; red verify blocks the commit, broken toolchain blocks loudly — never fail-open) plus **rulebook mirrors** (`AGENTS.md` for Codex + modern Cursor, `.cursor/rules/dash-guardrails.mdc` with `alwaysApply: true` for older Cursor), all generated from `skills/dash-install-guardrails/templates/`. Field origin: a Cursor-auto session claimed "smoke test passed" three turns running while the smoke stack couldn't execute at all (wrong interpreter + pytest plugin clash) — a gate the agent cannot skip is the fix, not a better prompt. The `dash-diagnose` roadmap (item 0.3) points at the same section.

## Order of operations on a new (or ailing) Dash repo

1. **`dash-diagnose`** — run first. Audits the repo (version drift, callback/store census, uirevision keying, CSS-war metrics, verification gap, git health, perf hot paths) and writes `DIAGNOSIS.md` + a sequenced `ROADMAP.md` **into the target repo**, with every fix item as a copy-paste-ready one-session prompt.
2. **`dash-ui-verify`** — the highest-leverage fix. Stands up a Playwright smoke suite so agents *see* broken UI (screenshots, console errors, computed styles, rendered viewports) instead of guessing. Usually Phase 1 of the generated roadmap.
3. **`dash-gotchas-review`** — run before shipping any UI change, forever. Makes the classic Dash/CSS failure patterns an executable checklist instead of tribal knowledge.
4. **`dash-install-guardrails`** — after the harness exists: converts the rules into machine gates (PostToolUse + Stop hooks covering Bash writes and JS assets, version gate, store-writer manifest, layout walk, state sandbox, build stamp). From here on, skipped smoke tests block the turn instead of shipping.
5. **`dash-fix`** — the day-to-day entry point once the above are in place: any single bug ("broken", "slow", "blank page", "nothing changed") dispatches to a symptom playbook, with ground-truth checks first and browser proof + a regression test required before done.
6. **`notebook-to-dash`** — whenever porting a Jupyter analysis into the app. Harvests golden outputs from the notebook, transplants (not transcribes) the compute, and blocks UI work behind a numeric parity test — plus an instruction-fidelity ledger so explicit asks can't silently vanish into "discretion".

**Why an enforcement layer at all:** prose rules drift. A checklist in CLAUDE.md gets skipped exactly when it matters most -- long sessions, big diffs, an agent that never re-read the doc. What survives is what the machine executes: invariants converted into verify-script checks, and hooks that run them after every edit (PLAYBOOK section 4). `dash-install-guardrails` installs that layer into a target repo; from then on "the app still works" is a command's exit code, not an agent's recollection.

**Starting from scratch instead of rescuing?** Skip diagnosis and build the app *born immune*: `docs/PLAYBOOK.md` §13 is the validated greenfield checklist (version-truth pins, env-sandboxable data/state paths, store-derived catalogs, single color source + native theming, layout-as-function, pure compute layer, blessed factories, same-day harness). A five-page portal built off that list went 9/9 green on its browser suite the same day it was started.

Read `docs/PLAYBOOK.md` once yourself — it is the 10-minute version of everything the skills enforce.

## Requirements

- Python 3.10+ environment that can import the target app.
- For `dash-ui-verify`: `pip install pytest playwright pytest-playwright && playwright install chromium`.
- Keep browser binaries, venvs, and test artifacts **outside** cloud-synced folders (OneDrive/Dropbox) — see PLAYBOOK.md "Cloud-sync hygiene".
