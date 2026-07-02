"""Template: in-process Dash app boot with sandboxed state + console-error net.

Adapt the CONFIG block, then delete this docstring's first line.
Requires: pytest, playwright, pytest-playwright (`playwright install chromium`).
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

# --- CONFIG (adapt per repo) -------------------------------------------------
REPO = Path(__file__).resolve().parents[2]          # tests/ui/ -> repo root
STATE_ENV_VAR = "APP_STATE_DIR"                     # env override added to the app's config module
APP_FACTORY = "core.app:build_app"                  # module:callable returning the Dash app
DATA_CACHE_MODULE = "core.services.data_cache"      # in-process cache to seed (or None)
SYNTHETIC_TICKERS = ("TEST1 Index", "TEST2 Index")  # keys the fixture view references
CACHE_KEY = ("local", "PX_LAST")                    # (group, field) — match the app's key shape
# ------------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
ARTIFACTS = Path(os.environ.get("APP_TEST_ARTIFACTS", Path(__file__).parent / "artifacts"))
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def app_server(tmp_path_factory) -> str:
    # 1. Sandbox user state BEFORE any app import — config constants are
    #    copied at import time by service modules.
    state = tmp_path_factory.mktemp("app_state")
    (state / "views").mkdir()
    for f in FIXTURES.glob("*.json"):
        dest = state / ("views" if "view" in f.stem else ".") / f.name
        shutil.copy(f, dest)
    os.environ[STATE_ENV_VAR] = str(state)

    sys.path.insert(0, str(REPO))
    mod_name, factory_name = APP_FACTORY.split(":")
    import importlib

    factory = getattr(importlib.import_module(mod_name), factory_name)

    # 2. Seed deterministic synthetic data — tests never read the real DB.
    if DATA_CACHE_MODULE:
        import numpy as np
        import pandas as pd

        data_cache = importlib.import_module(DATA_CACHE_MODULE)
        idx = pd.bdate_range("2016-01-04", "2026-06-30")
        rng = np.random.default_rng(0)
        for t in SYNTHETIC_TICKERS:
            s = pd.Series(100 * np.exp(np.cumsum(rng.normal(2e-4, 0.01, len(idx)))), index=idx)
            data_cache.put(*CACHE_KEY, t, s)

    # 3. Serve on a free port — the owner's live app may hold the default one.
    app = factory()
    port = _free_port()
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", port, app.server, threaded=True)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while True:
        try:
            if urllib.request.urlopen(base, timeout=2).status == 200:
                break
        except Exception:
            if time.time() > deadline:
                raise RuntimeError("app did not boot in 30s")
            time.sleep(0.25)
    yield base
    srv.shutdown()
    th.join(timeout=5)


BENIGN = [r"favicon", r"Download the React DevTools", r"third-party cookie"]


@pytest.fixture()
def page(app_server, browser):
    """Page with the universal regression net: any console error, pageerror,
    or HTTP 5xx (Dash callback exception) fails the test in teardown."""
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    pg = ctx.new_page()
    errs: list[str] = []
    pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.on("response", lambda r: errs.append(f"HTTP {r.status} {r.url}") if r.status >= 500 else None)
    yield pg
    real = [e for e in errs if not any(re.search(b, e) for b in BENIGN)]
    if real:
        shot = ARTIFACTS / "console_fail.png"
        pg.screenshot(path=str(shot), full_page=True)
        ctx.close()
        pytest.fail(f"Browser errors (screenshot: {shot}):\n" + "\n".join(real[:15]))
    ctx.close()
