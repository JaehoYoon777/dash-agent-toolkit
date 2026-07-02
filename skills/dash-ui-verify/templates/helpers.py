"""Template: shared assertions — rendered viewport, palette colors, contrast.

Adapt the CONFIG block per repo.
"""
from __future__ import annotations

import re

# --- CONFIG (adapt per repo) -------------------------------------------------
FIG = "#main-fig .js-plotly-plot"   # figure container selector — VERIFY against live DOM
THEME_MODULE = "core.layout.theme"  # module exposing PALETTES + css_variables()
# ------------------------------------------------------------------------------


def x_range(page, selector: str = FIG) -> list[str] | None:
    """Rendered x-axis range from Plotly's _fullLayout — the value uirevision
    corrupts; asserting on data instead of this misses the bug entirely."""
    return page.evaluate(
        f"""() => {{ const gd = document.querySelector('{selector}');
             return gd && gd._fullLayout && gd._fullLayout.xaxis.range
                    ? gd._fullLayout.xaxis.range.map(String) : null; }}"""
    )


def wait_fig(page, selector: str = FIG) -> None:
    page.wait_for_selector(selector)
    page.wait_for_function(
        f"() => {{ const gd = document.querySelector('{selector}'); return !!(gd && gd._fullLayout); }}"
    )


def palette_rgb_set(name: str) -> set[str]:
    """All colors a palette declares, as getComputedStyle-style 'rgb(r, g, b)'.
    Source of truth is the app's theme module — no hardcoded hex in tests."""
    import importlib

    theme = importlib.import_module(THEME_MODULE)
    hexes = set(re.findall(r"#[0-9a-fA-F]{6}", theme.css_variables(theme.PALETTES[name])))
    return {f"rgb({int(h[1:3], 16)}, {int(h[3:5], 16)}, {int(h[5:7], 16)})" for h in hexes}


def bg(page, selector: str) -> str:
    return page.eval_on_selector(selector, "el => getComputedStyle(el).backgroundColor")


CONTRAST_JS = """
() => {
  const lum = (r, g, b) => {
    const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const parse = (s) => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(',').map(Number); return p[3] === 0 ? null : p.slice(0, 3); };
  const effBg = (el) => { for (let n = el; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor); if (c) return c; } return [255, 255, 255]; };
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!el.innerText || !el.innerText.trim() || el.children.length) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const fg = parse(getComputedStyle(el).color); if (!fg) continue;
    const bgc = effBg(el);
    const l1 = lum(...fg), l2 = lum(...bgc);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    if (ratio < 1.6) bad.push(`${el.tagName}.${el.className}: ${el.innerText.slice(0, 30)} (ratio ${ratio.toFixed(2)})`);
  }
  return bad.slice(0, 20);
}
"""


def invisible_text(page) -> list[str]:
    """White-on-white heuristic: visible leaf text with WCAG contrast < 1.6."""
    return page.evaluate(CONTRAST_JS)
