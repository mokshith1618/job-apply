"""Lever: public Postings API.

GET https://api.lever.co/v0/postings/{company}/{id}
Fields used (confirmed 2026-10-13): text (title), createdAt (epoch ms);
descriptionPlain, lists (text + HTML content), additionalPlain (confirmed 2026-10-19).
The API has no display company name; it comes from the job page's JSON-LD.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .common import JobDetails, clean, get_json, html_text
from .generic import fetch_details as fetch_jsonld

API = "https://api.lever.co/v0/postings/{company}/{job_id}"


def parse_url(url: str) -> tuple[str | None, str | None]:
    m = re.match(r"^/([^/]+)/([0-9a-f-]{36})", urlsplit(url).path)
    return (m.group(1), m.group(2)) if m else (None, None)


def description(data: dict) -> str | None:
    """descriptionPlain, then each list (heading + HTML items), then additionalPlain (often the visa lines)."""
    parts = [html_text(data.get("descriptionPlain"))]
    for item in data.get("lists") or []:
        if isinstance(item, dict):
            parts += [html_text(item.get("text")), html_text(item.get("content"))]
    parts.append(html_text(data.get("additionalPlain")))
    return "\n".join(p for p in parts if p) or None


def parse_api(data: dict) -> JobDetails:
    created = data.get("createdAt")
    timed = isinstance(created, (int, float))
    posted = datetime.fromtimestamp(created / 1000).date() if timed else None
    raw = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat(timespec="seconds") if timed else None
    return JobDetails(position=clean(data.get("text")), posted_date=posted, description=description(data),
                      posted_raw=raw)


def fetch_details(url: str) -> JobDetails:
    company, job_id = parse_url(url)
    if not (company and job_id):
        return JobDetails()
    details = parse_api(get_json(API.format(company=company, job_id=job_id)))
    try:  # company name lives in the page's JSON-LD
        return details.merge(fetch_jsonld(f"https://jobs.lever.co/{company}/{job_id}"))
    except Exception as exc:  # noqa: BLE001 - keep the API result, ask for the rest
        print(f"  Could not read job page: {exc}")
        return details
