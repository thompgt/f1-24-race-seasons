"""Capture README screenshots from the running dev server.

Not part of the build. Run it with both servers up:

    uvicorn app.main:app --reload
    cd frontend && npm run dev
    python scripts/capture_screenshots.py

Requires ``playwright`` and its chromium build (``playwright install chromium``).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

VIEWPORT = {"width": 1360, "height": 1000}


@dataclass(frozen=True)
class Shot:
    name: str
    path: str
    wait_for: str
    full_page: bool = False
    #: Optional interaction run after load — used where the control is local
    #: component state rather than a URL parameter.
    setup: Callable[[object], None] | None = field(default=None)


def _group_by_constructor(page) -> None:
    page.select_option("#group-by", "constructor")


SHOTS = [
    Shot("seasons-1958.png", "/seasons/1958", ".standings-table tbody tr"),
    Shot("historical-drivers.png", "/historical", ".leaderboard tbody tr"),
    Shot(
        "historical-constructors.png",
        "/historical",
        ".leaderboard tbody tr",
        setup=_group_by_constructor,
    ),
    Shot("driver-fangio.png", "/drivers/579", ".dchart-median", full_page=True),
    Shot("method.png", "/method", ".app", full_page=True),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:5173")
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots"))
    parser.add_argument(
        "--theme", choices=["light", "dark"], default="light", help="which token set to render"
    )
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport=VIEWPORT,
            device_scale_factor=2,
            color_scheme=args.theme,
        )
        # The tokens honour a data-theme override on <html>; set it so a shot is
        # deterministic rather than dependent on the host OS preference.
        page.add_init_script(
            f"document.documentElement.setAttribute('data-theme', {args.theme!r})"
        )

        for shot in SHOTS:
            url = f"{args.base_url}{shot.path}"
            page.goto(url, wait_until="networkidle")
            try:
                page.wait_for_selector(shot.wait_for, timeout=15_000)
                if shot.setup is not None:
                    shot.setup(page)
                    page.wait_for_load_state("networkidle")
                    page.wait_for_selector(shot.wait_for, timeout=15_000)
            except Exception as exc:
                print(f"  !! {url}: {exc}", file=sys.stderr)
                browser.close()
                return 1
            # Let bars finish their width transition before freezing the frame.
            page.wait_for_timeout(500)
            target = args.out / shot.name
            page.screenshot(path=str(target), full_page=shot.full_page)
            print(f"  {target}  <-  {shot.path}")

        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
