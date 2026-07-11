"""Template: importable invariant checks for a Dash repo's verify script.

Prose invariants rot: writer censuses drift the first time an agent adds a
callback, docs claim versions that stopped being installed months ago, and
"these N places must agree" survives exactly one long session. Each check
below converts one prose rule into a machine gate.

Wire into the repo's verify.py:

    from core.app import build_app            # the repo's app factory
    import verify_invariants as vi

    app = build_app()
    failures: list[str] = []
    failures += vi.check_versions({"dash": "3.0.4", "plotly": "6.1.0"})
    failures += vi.check_store_writers(app, STORE_WRITER_MANIFEST,
                                       id_filter=lambda cid: cid.endswith("-store"))
    failures += vi.check_layout_keys(app.layout, ["app-shell", "main-url"])
    if failures:
        print("\\n".join(failures))
        sys.exit(1)

Every check returns list[str] of failure messages (empty == pass) so the
caller aggregates and reports ALL problems in one run instead of dying on the
first. All checks are READ-ONLY; if building the app loads saved user state,
point the app's state dir at a temp copy first - verification must never
mutate real user state.

Run `python verify_invariants.py` for a self-contained demo (needs dash +
plotly installed; each check is shown intentionally failing).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable

# --- CONFIG (used by the __main__ demo only; real repos pass args) ------------
DEMO_PINS = {"dash": "0.0.0", "package-that-is-not-installed": "1.0.0"}
DEMO_MAX_FIG_MB = 1.0
# ------------------------------------------------------------------------------


# --- versions -----------------------------------------------------------------

def check_versions(pins: dict[str, str]) -> list[str]:
    """Exact-match pins via installed package metadata.

    importlib.metadata, not module __version__: __version__ lies under
    editable installs and stale .pth files. Pins are the INSTALLED reality,
    not aspirational floors - agents write code for the version the docs
    claim, so keep pyproject, the agent-doc tech stack, and these pins in
    lockstep. Reports ALL mismatches, not just the first.
    """
    from importlib.metadata import PackageNotFoundError, version

    failures: list[str] = []
    for pkg, want in sorted(pins.items()):
        try:
            got = version(pkg)
        except PackageNotFoundError:
            failures.append(f"version: {pkg} pinned {want} but NOT INSTALLED")
            continue
        if got != want:
            failures.append(
                f"version: {pkg}=={got} installed, pinned {want} - "
                "update the pin AND the agent-doc tech stack in the same commit"
            )
    return failures


# --- store writers --------------------------------------------------------------

def _canonical_id(comp_id: Any) -> str:
    """Stable string form for both plain and pattern-matching (dict) ids.

    Pattern ids appear in callback_map keys as JSON with dash's own key order;
    re-dump sorted so {"type":..,"index":..} and {"index":..,"type":..} agree.
    """
    if isinstance(comp_id, dict):
        return json.dumps(comp_id, sort_keys=True, separators=(",", ":"))
    s = str(comp_id)
    if s.startswith("{"):
        try:
            return json.dumps(json.loads(s), sort_keys=True, separators=(",", ":"))
        except ValueError:
            pass
    return s


def _iter_output_ids(app: Any):
    """Yield the canonical component id of every Output declaration.

    callback_map keys: "id.prop" (single) or "..id.prop...id2.prop.." (multi);
    allow_duplicate outputs carry a "@<hash>" suffix on the prop; pattern ids
    are JSON strings that themselves contain dots - split on the LAST dot.
    """
    for key in getattr(app, "callback_map", {}):
        specs = key.strip(".").split("...") if key.startswith("..") else [key]
        for spec in specs:
            comp_id, sep, _prop = spec.rpartition(".")
            if sep:
                yield _canonical_id(comp_id)


def check_store_writers(
    app: Any,
    manifest: dict[str, int],
    id_filter: Callable[[str], bool] | None = None,
) -> list[str]:
    """Writer census: Output declarations per component id vs the manifest.

    Fails on ANY diff, either direction: fewer writers than the manifest says
    (writer silently removed / dead) or more (unreviewed sprawl - see the
    dash-gotchas-review skill, store-writer audit). Each allow_duplicate
    Output counts separately; MATCH vs ALL pattern variants stringify to
    distinct ids, which is correct - they are distinct writer declarations.

    id_filter (optional): predicate over canonical id strings, e.g.
    `lambda cid: cid.endswith("-store")`. Ids passing the filter that are
    MISSING from the manifest also fail, so new stores cannot appear
    unmanifested. On any failure the message ends with a corrected manifest
    ready to paste over the old one.
    """
    observed: Counter[str] = Counter(_iter_output_ids(app))
    canon_manifest = {_canonical_id(k): v for k, v in manifest.items()}

    failures: list[str] = []
    for cid, want in sorted(canon_manifest.items()):
        got = observed.get(cid, 0)
        if got != want:
            failures.append(
                f"store-writers: {cid}: manifest says {want}, app has {got} - "
                "justify the new writer in a comment naming the others, or hunt the removed one"
            )
    extra: list[str] = []
    if id_filter is not None:
        extra = sorted(cid for cid in observed if cid not in canon_manifest and id_filter(cid))
        for cid in extra:
            failures.append(
                f"store-writers: {cid}: {observed[cid]} writer(s) but id is not in the manifest"
            )
    if failures:
        keys = sorted(set(canon_manifest) | set(extra))
        body = "\n".join(f"    {json.dumps(k)}: {observed.get(k, 0)}," for k in keys)
        failures.append(
            "store-writers: corrected manifest (copy-paste after reviewing each diff):\n"
            "STORE_WRITER_MANIFEST = {\n" + body + "\n}"
        )
    return failures


# --- layout ids -----------------------------------------------------------------

def _walk_components(node: Any):
    """Yield every Dash component reachable from node.

    Iterative (no recursion limit), cycle-safe, and traverses ALL component
    props - not just children - because dmc/daq components nest components in
    arbitrary props that Dash's own _traverse misses.
    """
    stack = [node]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if cur is None or isinstance(cur, (str, bytes, int, float, bool)):
            continue
        if isinstance(cur, (list, tuple)):
            stack.extend(cur)
            continue
        if isinstance(cur, dict):
            stack.extend(cur.values())
            continue
        if id(cur) in seen or not hasattr(cur, "to_plotly_json"):
            continue
        seen.add(id(cur))
        yield cur
        prop_names = getattr(cur, "_prop_names", None) or ["children"]
        for p in prop_names:
            if p == "id":
                continue
            v = getattr(cur, p, None)
            if v is not None:
                stack.append(v)


def check_layout_keys(layout_or_fn: Any, required_ids: list[str]) -> list[str]:
    """Every required id must exist in the rendered component tree.

    Accepts app.layout directly or a layout function (called with no args -
    app.layout SHOULD be callable: a static layout freezes boot-time Store
    data, see the dash-gotchas-review skill). Pattern-matching dict ids may be
    required as their canonical JSON string (sorted keys, compact separators).
    """
    try:
        layout = layout_or_fn() if callable(layout_or_fn) else layout_or_fn
    except Exception as e:  # report, never crash the gate
        return [f"layout: layout function raised: {e!r}"]
    found = {
        _canonical_id(cid)
        for comp in _walk_components(layout)
        if (cid := getattr(comp, "id", None)) is not None
    }
    return [
        f"layout: required id missing from rendered tree: {rid}"
        for rid in required_ids
        if _canonical_id(rid) not in found
    ]


# --- payload budget ---------------------------------------------------------------

def check_payload_budget(figure_or_obj: Any, max_mb: float, label: str = "payload") -> list[str]:
    """Serialized-JSON size gate for a figure, layout, or Store payload.

    Uses plotly's serializer (plotly.io.json.to_json_plotly) so numpy arrays
    and go.Figure objects measure what Dash actually ships over the wire.
    Catches 200k-point traces and eagerly mounted option lists before the
    user reports lag. max_mb in decimal MB (1e6 bytes) of UTF-8 JSON.
    """
    try:
        from plotly.io.json import to_json_plotly
    except ImportError:
        return [f"payload-budget: plotly not importable; cannot measure {label} - fix the env"]
    try:
        size = len(to_json_plotly(figure_or_obj).encode("utf-8"))
    except Exception as e:
        return [f"payload-budget: {label} failed to serialize: {e!r}"]
    mb = size / 1e6
    if mb > max_mb:
        return [
            f"payload-budget: {label} = {mb:.2f} MB > {max_mb} MB budget - "
            "downsample, virtualize, or lazy-load"
        ]
    return []


# --- demo ---------------------------------------------------------------------

if __name__ == "__main__":
    # Self-contained demo: toy app, every check intentionally failing so the
    # message formats (incl. the corrected manifest) are visible.
    results: dict[str, list[str]] = {}

    results["check_versions"] = check_versions(DEMO_PINS)

    try:
        from dash import MATCH, Dash, Input, Output, dcc, html

        app = Dash(__name__)
        app.layout = html.Div(
            [
                dcc.Store(id="demo-spec-store"),
                dcc.Store(id="demo-ui-store"),
                dcc.Input(id="demo-in"),
                html.Div(id="demo-out"),
                html.Div([html.Span(id={"type": "demo-cell", "index": 1})]),
            ],
            id="demo-shell",
        )

        @app.callback(Output("demo-spec-store", "data"), Input("demo-in", "value"))
        def _w1(v):
            return v

        @app.callback(
            Output("demo-spec-store", "data", allow_duplicate=True),
            Input("demo-out", "n_clicks"),
            prevent_initial_call=True,
        )
        def _w2(n):
            return n

        @app.callback(Output("demo-ui-store", "data"), Input("demo-in", "n_submit"))
        def _w3(n):
            return n

        @app.callback(
            Output({"type": "demo-cell", "index": MATCH}, "children"),
            Input({"type": "demo-cell", "index": MATCH}, "n_clicks"),
        )
        def _w4(n):
            return n

        # Stale on purpose: wrong count for demo-spec-store, demo-ui-store absent.
        results["check_store_writers"] = check_store_writers(
            app,
            {"demo-spec-store": 1},
            id_filter=lambda cid: "store" in cid,
        )
        results["check_layout_keys"] = check_layout_keys(
            app.layout,
            ["demo-shell", "demo-spec-store", "id-that-does-not-exist"],
        )
    except ImportError as e:
        print(f"(dash not importable - skipping store/layout demos: {e})")

    try:
        import plotly.graph_objects as go

        fig = go.Figure(go.Scatter(y=list(range(300_000))))
        results["check_payload_budget"] = check_payload_budget(
            fig, max_mb=DEMO_MAX_FIG_MB, label="demo 300k-point scatter"
        )
    except ImportError as e:
        print(f"(plotly not importable - skipping payload demo: {e})")

    for name, fails in results.items():
        print(f"[{name}] {len(fails)} failure(s)")
        for f in fails:
            print("  " + f.replace("\n", "\n  "))
