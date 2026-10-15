"""Load a job page in Chrome (persistent profile, so my logins apply) and return its HTML.

Used only to read job details when the plain download is missing them: pages built by
JavaScript, jobs inside iframes, pages behind a login. It only loads and reads; no clicks.
"""
from __future__ import annotations

import time

LOAD_TIMEOUT_MS = 30_000
SETTLE_SECONDS = 10  # how long to wait for JavaScript to put the job data on the page


def _frames_html(page) -> list[str]:
    """Main page first, then every frame. Frames that vanish mid-read are skipped."""
    pages = []
    for frame in page.frames:
        try:
            pages.append(frame.content())
        except Exception:  # noqa: BLE001
            continue
    return pages


def render_page(url: str, *, user_data_dir, ready=None, headless: bool = True) -> list[str]:
    """-> [main page HTML, frame HTML, ...]. Stops waiting early once `ready(pages)` is true."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(user_data_dir), channel="chrome", headless=headless)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)
            deadline = time.monotonic() + SETTLE_SECONDS
            pages = _frames_html(page)
            while not (ready and ready(pages)) and time.monotonic() < deadline:
                page.wait_for_timeout(1000)
                pages = _frames_html(page)
            return pages
        finally:
            context.close()
