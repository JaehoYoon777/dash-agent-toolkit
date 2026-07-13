---
name: dash-install-guardrails
description: One-command wiring of the enforcement layer into a Dash repo -- installs PostToolUse + Stop hook gates (covering Bash-mediated writes and JS/CSS assets, never fail-open), adds executable invariants to the verify script (version gate, store-writer manifest vs callback_map, layout walk, payload budget), sandboxes verify away from real user state, and adds a build stamp. Section 8 covers repos driven by Cursor/Codex where Claude Code hooks never fire -- installs the agent-agnostic git pre-commit gate plus AGENTS.md/.cursor-rules mirrors. Use when asked to "install guardrails", "set up hooks", "enforce verification", "wire up verify", "stop the agent skipping smoke tests", "make verification mandatory", "make Cursor run the smoke test", "enforce verification outside Claude Code", or after dash-diagnose flags a verification gap (its ROADMAP Phase 3 lands here).
---

# dash-install-guardrails

Convert prose rules into machine gates on a target repo. Prose invariants rot (a documented store-writer census drifted 11 claimed vs 12 real within weeks, e.g. podos); advisory hooks get routed around; docs claim versions two majors stale. Every step below closes a bypass observed in a real repo. One commit per step.

Division of labor across the toolkit: `dash-gotchas-review` is the judgment layer (prose checklist), `dash-ui-verify` is the evidence layer (browser harness), THIS skill is the enforcement layer that makes both non-optional. `dash-fix` sessions assume these gates are already in place.

## 0 -- Git baseline gate (refuse to skip)

Do NOT finish this install on an unrevertable tree. Check:
```
git log --oneline | wc -l ; git status --porcelain | wc -l ; test -f .gitignore && echo OK
```
If <5 commits, no .gitignore, or junk tracked (pyc, logs, user-state files): hygiene commit FIRST (PLAYBOOK section 3) -- write .gitignore (`__pycache__/`, `*.pyc`, `*.log`, the user-state dir, `tests/ui/artifacts/`), `git rm --cached` the junk, commit a baseline. Hooks that auto-run scripts against a tree with no known-good state amplify agent damage instead of containing it.

## 1 -- Detect repo shape

Fill this table before copying anything; every template CONFIG block needs it.

| Fact | How to find |
|---|---|
| Verify command | `verify.py` / `scripts/verify.py` / `pytest -m smoke` -- grep hooks AND agent docs for the canonical command; if they disagree, unify NOW (two canonical commands = agents run the weaker one) |
| App interpreter | the launcher (`.bat`/Makefile/compose), NOT `which python` -- conda/venv apps break PATH assumptions |
| State dir | grep the config module for the saved-state path constant; note whether it is env-overridable |
| Hook state | `cat .claude/settings.json` -- existing hooks, matchers, permission allowlists |
| Hot Stores | every Store id with >=2 writers: `rg -n 'Output\("<id>"' --type py` per candidate |

## 2 -- Install the hook templates

Copy from this skill's `templates/` into `.claude/hooks/`, fill the `# --- CONFIG` block at the top of each.

**`post_edit_verify.py`** (PostToolUse) -- runs the verify command after any protected write. Non-negotiables baked in:
- Matcher includes **Bash**, not just `Edit|Write|MultiEdit|NotebookEdit`. Observed bypass: editor-tools-only matcher plus a `Bash(*)` allowlist meant any `python -c` / `sed -i` / `>>` write modified protected files with zero verification and zero prompt. The template treats any write-shaped Bash command as a protected touch -- conservative by design; a spurious verify run costs seconds, a missed one ships a regression.
- Protected globs include `assets/*.js` and `assets/*.css`. Dash failure logs typically name the JS observer/palette files as the highest-risk surface (e.g. `palette_sync.js`); a hook that skips `.js` protects everything except where the bugs live.
- **Never fail-open.** Missing interpreter, timeout, unparseable payload: exit 2 with a loud stderr line. The observed anti-pattern -- `except FileNotFoundError: return 0` -- makes the gate evaporate exactly when the environment breaks.
- Touches a dirty flag consumed by the Stop gate, so per-edit runs stay cheap while turn-end gets the full tier.

**`stop_smoke_gate.py`** (Stop) -- blocks turn end while the smoke command is red. PostToolUse exit 2 is post-hoc advice: the edit already landed, nothing reverts it, and with no Stop hook the agent reports done with red checks (observed). This is the actual gate. It runs only when the dirty flag says watched paths changed this session (clean turns end instantly), holds a ~90s budget (slower gates get disabled or routed around), and honors `stop_hook_active` so a red run blocks once with feedback instead of looping. Once the `dash-ui-verify` harness exists, add its smoke tier (`pytest tests/ui -m smoke -q`) to `SMOKE_CMD`.

## 3 -- Wire .claude/settings.json (merge, don't clobber)

Read the existing file; merge the `hooks` block from `templates/settings_hooks.json` (PostToolUse matcher `Edit|Write|MultiEdit|NotebookEdit|Bash` + Stop gate), preserving everything already there -- that template is the single canonical snippet; see its `_comment` key for the interpreter choice. The hook launcher python only needs to resolve on PATH; the scripts validate the app's own interpreter internally and fail loudly if it is missing. While in this file, audit `permissions.allow`: a blanket `Bash(*)` in a low-commit repo is maximal blast radius with minimal recoverability. **Report it to the owner with a suggested narrow allowlist (read-only commands + the specific verify/restart invocations). Do not silently change permissions.**

## 4 -- Executable invariants in the verify script

Copy `templates/verify_invariants.py` next to the repo's verify script, fill CONFIG, call each check from its main (each returns a list of failure strings; empty = pass). What each kills:

- **Version gate** -- `importlib.metadata` versions vs `==` pins. Agents write code for the version the docs claim, not the one that runs; observed two-major drift (docs said Dash 2.17, runtime ran 4.x) shipped the same dropdown bug twice against a DOM that no longer existed. Failure message demands pyproject + agent-doc tech stack + pin updated in the same commit.
- **Store-writer manifest** -- writers per hot Store counted from `app.callback_map` vs a declared manifest dict. Fail on ANY diff, either direction: lower = a writer silently removed or dead, higher = unreviewed sprawl. Message instructs updating manifest + doc census together and justifying coexistence next to the new `Output` (`dash-gotchas-review` P7 thresholds still apply at review time).
- **Layout walk** -- render the layout (call it if callable), serialize the component tree, assert every derived key/id appears. This mechanizes the "N places must agree" prose invariants that fail precisely during long sessions.
- **Payload budget** (optional) -- serialized layout under a byte cap; catches the giant-options-list / eagerly-mounted-grid class before the user reports lag.

Then make the verify command the ONLY smoke command in the agent docs. Observed: a repo's CLAUDE.md carried an inline "paste before done" snippet that was a stale 2-check subset of its verify script, and the verify script was referenced in no agent-facing doc at all -- an agent following the docs to the letter ran the weaker check and reported green. One canonical command, identical in hooks, CLAUDE.md/AGENTS.md, and prompt templates.

## 5 -- State sandbox (verify must NEVER mutate real user state)

Observed: a verify script's view-load check persisted migrated specs back into the real state dir -- so the post-edit hook rewrote every real saved view with the working tree's possibly-buggy migration, on every edit, before review. Check whether the state dir is env-overridable; if not, make the ONE production edit (identical to the `dash-ui-verify` harness spec):
```python
STATE_DIR = Path(os.environ.get("APP_STATE_DIR", _DEFAULT_STATE_DIR))
```
Then verify/tests copy the real state to a temp dir and set `APP_STATE_DIR` before importing any app module. Prove the seal: hash the real state dir before and after a verify run -- byte-identical, or the sandbox leaks.

## 6 -- Build stamp

Stale-server debugging burns whole turns ("nothing has changed" repeated across three turns while an old process kept serving -- observed). Check the app surfaces a build identity at boot; if absent, add:
```python
# version.py
try:
    BUILD = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
except Exception:
    BUILD = "nogit"
STAMP = f"{BUILD} {datetime.now():%H:%M:%S}"
```
Render STAMP in the app footer (`html.Small`) and print it at boot. "Is my edit actually running?" becomes a glance instead of a three-turn investigation.

## 7 -- Done-when: break every layer once

The install is unverified until each gate has been seen firing. Break deliberately, observe, revert:

| Deliberate break | Gate that must fire |
|---|---|
| Append junk to a protected `.js` via Bash (`echo x >> assets/foo.js`) | PostToolUse verify runs (Bash matcher + JS glob) |
| Add an `Output` to a hot Store without touching the manifest | writer-manifest check fails, message names both files to update |
| Change one `==` pin to a wrong version | version gate fails |
| Rename a derived key in one of its N places | layout walk fails |
| End the turn while verify is red | Stop gate blocks with the failure tail |
| Point `PYTHON` (hook CONFIG) at a nonexistent path | hook exits 2 LOUDLY -- silence here means the install failed |
| Hash the real state dir, run verify, hash again | byte-identical -- any diff means the sandbox leaks (step 5 failed) |

All seven fired and reverted -> commit the install as one change. If the repo has no browser harness yet, hand off to `dash-ui-verify` Mode B next: these gates enforce whatever tier exists, and an import-layer verify alone still misses the browser bug class entirely.

Ongoing discipline the gates should keep enforcing: one commit per verified change. Optional but recommended -- extend the Stop gate with a git-status check that warns when the turn ends green but the tree carries uncommitted changes beyond the current fix's files; an unrevertable tree is how repos drift back to whack-a-mole (PLAYBOOK section 3).

## 8 -- Multi-agent mirrors + git gate (Cursor / Codex: enforcement without Claude Code hooks)

Sections 2-3 fire only inside Claude Code. A repo driven by Cursor or Codex has NO PostToolUse/Stop layer -- prose rules are all it sees, and prose is exactly what drifts. Observed (Cursor auto, production quant portal): three consecutive turns each claiming "smoke test passed" while the smoke stack could not even run -- wrong interpreter (base Anaconda instead of the app env) plus a pytest-playwright plugin clash meant the tests never executed; zero gates fired, three regressions shipped, the app crashed at boot on turn 3. The agent-agnostic gate is git itself: every agent's work funnels through `git commit`, so a pre-commit hook running the canonical verify blocks red work regardless of IDE. Install:

1. **Canonical entrypoint** -- copy `templates/verify.ps1.template` to `scripts/verify.ps1`, fill CONFIG (app interpreter from the section-1 table, smoke args, optional invariants script from section 4). This becomes THE one verify command; the hook and every agent doc reference it and nothing else.
2. **Git gate** -- copy `templates/pre_commit.template` to `.githooks/pre-commit` (no extension), then:
   ```
   git config core.hooksPath .githooks
   git add .githooks/pre-commit
   git update-index --chmod=+x .githooks/pre-commit
   ```
   `.githooks/` is versioned so the gate survives clones; `core.hooksPath` is per-machine -- put the config line in the repo's setup doc. Fail-closed like the Claude hooks: missing `scripts/verify.ps1` or a missing interpreter BLOCKS the commit loudly, never skips.
3. **Rulebook mirrors** -- copy `templates/AGENTS.md.template` to repo-root `AGENTS.md` (Codex + modern Cursor read it natively) and `templates/dash-guardrails.mdc.template` to `.cursor/rules/dash-guardrails.mdc` (frontmatter `alwaysApply: true`; how older Cursor sees rules). Fill every `<...>`: interpreter path, pins, boot command, state-dir env var. Both carry "AGENTS.md wins on conflict" (PLAYBOOK section 6).
4. **One-command audit** -- grep CLAUDE.md, AGENTS.md, and the `.mdc` for the verify invocation: all must carry the IDENTICAL command from step 1. Two canonical commands = agents run the weaker one (section 4, observed).

### 8.1 -- Done-when: break the git gate once per failure mode

| Deliberate break | Gate that must fire |
|---|---|
| Force smoke red (temporary `assert False` in a smoke test), `git commit` | commit BLOCKED, pytest failure tail printed |
| Point verify.ps1 `$Python` at a nonexistent path, `git commit` | commit BLOCKED loudly -- silence here means fail-open, install failed |
| Rename `scripts/verify.ps1` away, `git commit` | commit BLOCKED (missing entrypoint is not a pass) |
| `git commit --no-verify` while red | commit LANDS -- expected: the human escape. It leaves no marker, so the owner treats any red-landed commit as an audit item |

All four fired -> revert the breaks, commit the install as one change.

### 8.2 -- Limits (what this layer cannot do)

- Fires only on commit; there is no per-edit feedback (that is the Claude-hooks layer). On repos where both agents run, keep both: hooks give in-session feedback, the git gate catches whatever slips past.
- An agent that never commits ships nothing through the gate -- the mirrors' "one commit per verified change" rule funnels work into it. The owner-side audit stays regardless: agent says done -> owner runs `scripts/verify.ps1` (seconds) before believing it.
- `--no-verify` / `SKIP_VERIFY=1` are deliberate human escapes for mid-incident commits. The mirrors forbid agents from using them; their appearance in an agent transcript is itself a finding.
