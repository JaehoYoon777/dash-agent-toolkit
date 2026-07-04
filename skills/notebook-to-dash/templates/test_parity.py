"""Template: numeric parity gate — ported compute vs notebook goldens.

Adapt the CONFIG block. The pattern per check:
  1. call the PORTED pure function on the SAME inputs the notebook used
  2. assert against the golden value with a STATED tolerance and a comment
     saying where the golden came from (cell index / re-executed value)

Red parity = fix the port, never the tolerance.
This file stays in the repo: when the page "doesn't match" months later,
green parity here means the bug is in the UI layer; red means compute drifted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# --- CONFIG (adapt per conversion) -------------------------------------------
# from myapp.compute import notebook_port as npc     # the ported pure module
# GOLDENS = json.loads(Path("goldens.json").read_text(encoding="utf-8"))
# DATA = <load the exact inputs the notebook used — same file/query/date range>
# ------------------------------------------------------------------------------


# Function scope + defensive copy ON PURPOSE: verbatim-transplanted notebook
# code routinely mutates inputs in place (dropna(inplace=True), column
# assignment, sort_index(inplace=True)). A module-scoped shared frame makes
# parity results depend on test execution order — the exact hidden-state
# pathology this skill exists to kill.
@pytest.fixture()
def data():
    raise NotImplementedError("load the notebook's exact input data here; return raw.copy()")


# -- loader parity: the ONE rewritten boundary gets its own gate --------------
def test_app_loader_matches_notebook_inputs(data):
    # `data` above = what the NOTEBOOK loaded. This check: the APP's data
    # layer returns the same frame (compute parity is meaningless if the app
    # feeds the verified functions a different range/adjustment/NaN profile).
    got = ...  # app_data_layer.load_for_page(...)
    assert got.shape == data.shape
    assert got.index.min() == data.index.min() and got.index.max() == data.index.max()
    # + N spot values and dtypes


# -- scalar golden (from a printed value; display precision -> tolerance) -----
def test_summary_stat_matches(data):
    # golden from cell 12 output: "annualized vol: 15.4481" — printed to 4dp,
    # so tolerance derives from display precision: |err| <= 5e-5.
    got = ...  # npc.annualized_vol(data)
    assert np.isclose(got, 15.4481, atol=5e-5), f"vol drifted: {got}"


# -- frame golden (re-executed exact values preferred) -------------------------
def test_key_frame_matches(data):
    got = ...  # npc.build_summary_table(data)
    # golden: shape + spot cells from cell 18; full-frame compare when a
    # re-executed pickle/parquet golden exists:
    # pd.testing.assert_frame_equal(got, expected, rtol=1e-10)
    assert got.shape == (24, 6)
    assert np.isclose(got.loc["2024-01-31", "ret"], -0.0123, atol=5e-5)


# -- figure golden: the ARRAYS handed to the figure, not pixels ---------------
def test_figure_series_match(data):
    x, y = ...  # npc.drawdown_series(data)  — what the notebook's cell 21 plotted
    assert len(y) == 2870                      # golden length from notebook
    assert np.isclose(float(np.min(y)), -0.3389, atol=1e-4)  # golden min drawdown


# -- alignment / dtype guards (classic silent-drift sources) -------------------
def test_index_alignment(data):
    got = ...  # npc.joined_frame(data)
    assert got.index.is_monotonic_increasing
    assert got.index.tz is None                # notebook was tz-naive
    assert not got.index.has_duplicates
