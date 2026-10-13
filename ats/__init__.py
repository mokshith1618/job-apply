"""One module per applicant tracking system. Milestone 1: detect the system and read job details."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from . import ashby, generic, greenhouse, lever, workday
from .common import JobDetails

FETCHERS = {
    "greenhouse": greenhouse.fetch_details,
    "ashby": ashby.fetch_details,
    "lever": lever.fetch_details,
    "workday": workday.fetch_details,
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
    if host.endswith(".myworkdayjobs.com"):
        return "workday"
    return "other"


def fetch_details(url: str) -> JobDetails:
    """Board API first, then the page's JSON-LD for anything still missing.

    Network errors are printed and swallowed: whatever is missing gets asked in the terminal.
    """
    system = detect_system(url)
    details = JobDetails()
    try:
        details = FETCHERS[system](url)
    except Exception as exc:  # noqa: BLE001 - any failure just means "ask me"
        print(f"  Could not read {system} API: {exc}")
    if not details.complete() and system != "other":
        try:
            details = details.merge(generic.fetch_details(url))
        except Exception as exc:  # noqa: BLE001
            print(f"  Could not read job page: {exc}")
    return details
