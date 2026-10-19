"""One module per applicant tracking system. Milestone 1: detect the system and read job details."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from . import ashby, generic, greenhouse, icims, lever, oracle, rippling, workday
from .common import JobDetails

FETCHERS = {
    "greenhouse": greenhouse.fetch_details,
    "ashby": ashby.fetch_details,
    "lever": lever.fetch_details,
    "workday": workday.fetch_details,
    "icims": icims.fetch_details,
    "oracle": oracle.fetch_details,
    "rippling": rippling.fetch_details,
    "other": generic.fetch_details,
}


def detect_system(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host in ("job-boards.greenhouse.io", "boards.greenhouse.io") or "gh_jid" in parse_qs(parts.query):
        return "greenhouse"
    if host == "jobs.ashbyhq.com":
        return "ashby"
    if host == "jobs.lever.co":
        return "lever"
    if host == "ats.rippling.com":
        return "rippling"
    if host.endswith(".myworkdayjobs.com"):
        return "workday"
    if host.endswith(".icims.com"):
        return "icims"
    if host.endswith(".oraclecloud.com") and "/candidateexperience/" in parts.path.lower():
        return "oracle"
    return "other"


def fetch_details(url: str, render=None) -> JobDetails:
    """Board API first, then the page's JSON-LD, then (with `render`) the page as Chrome shows it.

    `render(url, ready=...)` returns the rendered page and frame HTML (see browser.render_page).
    Network errors are printed and swallowed: whatever is missing gets asked in the terminal.
    """
    system = detect_system(url)
    details = JobDetails()
    try:
        details = FETCHERS[system](url)
    except Exception as exc:  # noqa: BLE001 - any failure just means "ask me"
        print(f"  Could not read {'job page' if system == 'other' else system + ' API'}: {exc}")
    if not (details.complete() and details.description) and system != "other":
        try:
            details = details.merge(generic.fetch_details(url))
        except Exception as exc:  # noqa: BLE001
            print(f"  Could not read job page: {exc}")
    if not (details.complete() and details.description) and render is not None:
        print("  Loading the page in Chrome to read the rest...")
        try:
            pages = render(url, ready=lambda pages: details.merge(generic.parse_pages(pages)).complete())
            rendered = generic.parse_pages(pages)
            details = details.merge(rendered)
            # The rendered page's tags beat the plain download's (often an empty app shell).
            details.company_guess = rendered.company_guess or details.company_guess
            details.position_guess = rendered.position_guess or details.position_guess
        except Exception as exc:  # noqa: BLE001
            print(f"  Could not load the page in Chrome: {exc}")
    return details
