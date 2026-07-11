---
name: dash-fix-visual
description: Live-DOM debugging procedure for Dash visual/CSS/theming bugs -- use when a style "isn't taking effect", a fix "didn't take", a dropdown/menu/tooltip/calendar renders white-on-white or unstyled, dark mode or a theme switch half-applies, colors don't follow the palette, spacing is off, or a Plotly figure ignores the app theme. This is the mid-fix debug loop; dash-gotchas-review is the pre-ship checklist.
---

# dash-fix: visual / CSS / theming

This is the DEBUG procedure you run while fixing. `dash-gotchas-review` (P1-P5, P15)
is the pre-ship CHECKLIST you run after. Every step below reads the live DOM first;
never restyle from memory, source comments, or prior sessions.

## 0. Rule zero: live DOM before any selector

Boot the app before writing or blaming a single selector. Use the dash-ui-verify
harness `page` fixture if the repo has one; otherwise a throwaway Playwright script
against an in-process boot on a free port.

Every selector you are about to write, and every selector in the rule you suspect:

```python
page.evaluate("document.querySelectorAll('<sel>').length")
```

Zero matches = dead rule. Do not strengthen it -- re-derive it. Get the element's
real identity and current values from the browser, not by reading CSS files (files
say what you hope; computed style says what is):

```python
page.evaluate("""(() => {
  const el = document.querySelector('<sel>');
  const cs = getComputedStyle(el);
  return { cls: el.className, inline: el.getAttribute('style'),
           bg: cs.backgroundColor, color: cs.color };
})()""")
```

## 1. Locate the winning rule before writing a competing one

For the wrong-looking property, identify what currently wins -- in this order:

1. **Inline `style=`** written by the component library (React rewrites it every
   render). Non-empty `el.getAttribute('style')` means you are fighting inline
   styles: prefer the library's native prop; else `!important` on an
   exactly-matching selector. Higher specificity alone cannot win.
2. **JS re-appliers.** An observer calling `setProperty(..., 'important')` beats
   even your `!important`. Before concluding "specificity issue":
   ```bash
   rg -n "setProperty|MutationObserver" assets/*.js
   ```
3. **Stylesheet cascade.** Only now compare selectors. If you cannot name the
   losing-vs-winning pair explicitly, you are guessing -- go back to step 0.

## 2. Portal check (menus, tooltips, calendars, modals)

Anything that appears on open/hover likely mounts to `<body>` (Radix-based
components always portal) -- outside the app shell, so shell-scoped rules
(`.my-app .dropdown ...`) never reach it. Cross-ref gotchas-review P3.

```python
page.locator("<trigger>").click()   # REAL click; synthetic el.click() does not open Radix popovers
page.evaluate("""(() => {
  const pop = document.querySelector('<popup-sel>');
  const shell = document.querySelector('<app-shell-sel>');
  return { exists: !!pop, portaled: !!pop && !shell.contains(pop) };
})()""")
```

If `portaled`: write the rule UNSCOPED, and verify computed style ON THE PORTALED
NODE while it is open -- not on the trigger, not on a closed menu.

## 3. Style by state attribute, not guessed class

Libraries express open/focus/selected/highlighted/disabled via `data-*`/`aria-*`
attributes and inline style flips, not stable class names. Dump the live node's
attributes in EACH state and target what actually changes:

```python
page.evaluate("""[...document.querySelector('<sel>').attributes]
  .map(a => `${a.name}=${a.value}`)""")
```

Prefer `[aria-selected="true"]`, `[data-highlighted]`, `[data-state="open"]` over
`.is-open`-style guesses. Cross-ref gotchas-review P5.

## 4. Theme layering (fix at the highest layer that owns the pixel)

1. **One token source.** Palette colors live as CSS variables defined once
   (`:root` / body class); everything references `var(--token)`. A hardcoded hex
   in a component `style=` or figure builder is a future theme bug -- hunt them:
   ```bash
   rg -n "#[0-9a-fA-F]{3,8}" assets/*.css --type py
   ```
2. **Native provider before override CSS.** Components owned by the theming
   provider (e.g. `dmc.MantineProvider` theme, dbc themes) follow the theme with
   zero CSS. Override CSS is only for what the provider cannot reach.
3. **Plotly figures are canvas/SVG -- CSS cannot restyle them, and the default
   template does NOT follow a runtime theme flip.** Set explicit `paper_bgcolor`,
   `plot_bgcolor`, `font.color`, and axis `gridcolor` per palette in the figure
   factory, and rebuild the figure when the palette changes.
4. **Override CSS last**, with unscoped variants for portal surfaces (section 2).

## 5. Anti-escalation rule (hard)

A fix with no visible effect means your model of the DOM is wrong -- not that the
force was insufficient. FORBIDDEN next moves: more `!important`, a MutationObserver,
a broader selector, a JS setProperty loop. REQUIRED next move: rule zero on the
exact selector. After two failed fixes on the same element: stop, dump the subtree's
`outerHTML`, and read it before touching CSS again.

```python
page.evaluate("document.querySelector('<container-sel>').outerHTML")
```

## 6. Verify (no claim without eyes)

Every visual claim needs a screenshot per palette PLUS a computed-style assert on
the exact property you fixed -- hand off to dash-ui-verify (`snap.py` per
route/palette, palette-sweep test). READ the screenshot before claiming success;
if the PNG does not show it, it is not fixed. Then add the computed-style assert
to the palette sweep so the fix becomes a permanent guard (dash-install-guardrails
wires the sweep into the repo's verify checks).
