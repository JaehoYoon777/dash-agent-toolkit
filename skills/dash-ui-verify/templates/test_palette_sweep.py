"""Template: N-palette computed-style sweep — trigger + portaled menu +
calendar popup (the classic asymmetric-coverage trio), per palette.

Selectors below are best-known for Dash >=3 (Radix-based dcc.Dropdown).
VERIFY EVERY SELECTOR against the live DOM before trusting — comments and
training data lie; the rendered tree is authoritative.
"""
from __future__ import annotations

import pytest

from .conftest import ARTIFACTS
from .helpers import bg, invisible_text, palette_rgb_set, wait_fig

# --- CONFIG (adapt per repo) -------------------------------------------------
PALETTES = ["slate-dark", "terminal", "slate-light", "paper"]
DARK = {"slate-dark", "terminal"}
VIEW_ROUTE = "/views/uitest0001"
SETTINGS_ROUTE = "/settings"
PALETTE_INPUT = "input[value='{name}']"          # settings radio — verify live DOM
SETTINGS_SAVE = "#settings-save"
BODY_CLASS = "palette-{name}"                    # class the theme JS puts on <body>
TRIGGER = ".dash-dropdown"                       # dropdown trigger
MENU = "body .dash-dropdown-content"             # Radix popover, PORTALED to <body>
DATE_INPUT = "#gx-date input"
CALENDAR = "[class*='DayPicker']"                # date popup, also portaled
# ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", PALETTES)
def test_palette_sweep(page, app_server, name):
    allowed = palette_rgb_set(name)

    # 1. Switch palette through the real settings flow (sandboxed state).
    page.goto(f"{app_server}{SETTINGS_ROUTE}")
    page.locator(PALETTE_INPUT.format(name=name)).first.check()
    page.click(SETTINGS_SAVE)
    # Portaled components depend on the body class — wait for it.
    page.wait_for_function(
        f"() => document.body.classList.contains('{BODY_CLASS.format(name=name)}')"
    )

    # 2. The trio: trigger, open menu, calendar popup.
    page.goto(f"{app_server}{VIEW_ROUTE}")
    wait_fig(page)

    t_bg = bg(page, TRIGGER)
    assert t_bg in allowed, f"[{name}] trigger bg {t_bg} not a palette color"

    page.locator(TRIGGER).first.click()
    page.wait_for_selector(MENU, state="visible")
    m_bg = bg(page, MENU)
    assert m_bg in allowed, f"[{name}] OPEN MENU bg {m_bg} not a palette color (portal coverage gap)"
    if name in DARK:
        assert m_bg != "rgb(255, 255, 255)", f"[{name}] menu is default white — inline-style layer lost"
    page.keyboard.press("Escape")

    page.locator(DATE_INPUT).first.click()
    page.wait_for_selector(CALENDAR, state="visible")
    c_bg = bg(page, CALENDAR)
    assert c_bg in allowed, f"[{name}] calendar popup bg {c_bg} not a palette color (portal coverage gap)"

    # 3. Visual record every run — agents Read these to self-verify claims.
    page.screenshot(path=str(ARTIFACTS / f"palette_{name}.png"), full_page=True)


@pytest.mark.parametrize("name", sorted(DARK) + [p for p in PALETTES if p not in DARK][:1])
def test_no_invisible_text(page, app_server, name):
    page.goto(f"{app_server}{VIEW_ROUTE}")
    wait_fig(page)
    bad = invisible_text(page)
    assert not bad, f"[{name}] low-contrast text found:\n" + "\n".join(bad)
