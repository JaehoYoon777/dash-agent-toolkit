"""Template: the uirevision executable repro — date change must move the
RENDERED viewport, even after prior user zoom.

Ship with xfail while the bug exists; on XPASS remove the marker in the same
commit as the fix — the test then becomes the permanent guard.
"""
from __future__ import annotations

import pandas as pd
import pytest

from .helpers import FIG, wait_fig, x_range

# --- CONFIG (adapt per repo) -------------------------------------------------
VIEW_ROUTE = "/views/uitest0001"     # fixture saved-view route
PRESET_BTN = "#gx-date-1y"           # a "last 1 year" preset button — VERIFY live DOM
# ------------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.xfail(strict=False, reason="uirevision swallows date change — remove marker when fixed")
def test_date_preset_changes_viewport(page, app_server):
    page.goto(f"{app_server}{VIEW_ROUTE}")
    wait_fig(page)

    # 1. Simulate prior interaction: drag-zoom into a sub-window. Without this
    #    the bug does not reproduce (uirevision only restores a touched axis).
    box = page.locator(FIG + " .nsewdrag").first.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * 0.30, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.60, y, steps=8)
    page.mouse.up()
    page.wait_for_function(
        f"() => document.querySelector('{FIG}')._fullLayout.xaxis.range != null"
    )

    # 2. Change the date range through the app's real control path
    #    (preset -> debounce -> spec store -> figure rebuild).
    page.click(PRESET_BTN)

    # 3. The RENDERED x-axis must now show ~the requested window, not the
    #    restored zoom.
    def ok() -> bool:
        rng = x_range(page)
        if not rng:
            return False
        lo, hi = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
        return 300 <= (hi - lo).days <= 430

    deadline = page.evaluate("() => Date.now()") + 10_000
    while not ok():
        assert page.evaluate("() => Date.now()") < deadline, (
            f"viewport stuck at {x_range(page)} after 1Y preset — uirevision regression"
        )
        page.wait_for_timeout(200)
