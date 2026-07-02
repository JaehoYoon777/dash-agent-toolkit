"""Template: CLI screenshot tool — the agent's eyes for visual claims.

Usage:
    <repo-python> tests/ui/snap.py --route /views/uitest0001 --palette terminal \
        --out tests/ui/artifacts/claim.png

Boots the sandboxed app in-process (reusing conftest logic), navigates,
screenshots, prints the absolute path. The agent must then Read the PNG and
LOOK at it before reporting any visual outcome.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="/")
    ap.add_argument("--palette", default=None, help="switch palette via settings before shooting")
    ap.add_argument("--out", default="tests/ui/artifacts/snap.png")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--full", action="store_true", help="full-page screenshot")
    args = ap.parse_args()

    # Reuse the conftest boot path manually (no pytest).
    import conftest as cft

    class _TmpFactory:  # minimal stand-in for tmp_path_factory
        def mktemp(self, name: str) -> Path:
            import tempfile

            return Path(tempfile.mkdtemp(prefix=name))

    gen = cft.app_server.__wrapped__(_TmpFactory())
    base = next(gen)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": args.width, "height": args.height})
            if args.palette:
                page.goto(f"{base}/settings")
                page.locator(f"input[value='{args.palette}']").first.check()
                page.click("#settings-save")
                page.wait_for_function(
                    f"() => document.body.classList.contains('palette-{args.palette}')"
                )
            page.goto(f"{base}{args.route}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(500)
            out = Path(args.out).resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out), full_page=args.full)
            browser.close()
            print(out)
    finally:
        try:
            next(gen)  # run fixture teardown (server shutdown)
        except StopIteration:
            pass


if __name__ == "__main__":
    main()
