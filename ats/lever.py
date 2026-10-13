"""Lever: public Postings API.

GET https://api.lever.co/v0/postings/{company}/{id}
Fields used (confirmed 2026-10-13): text (title), createdAt (epoch ms).
The API has no display company name; it comes from the job page's JSON-LD.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from .common import JobDetails, clean, get_json
from .generic import fetch_details as fetch_jsonld

API = "https://api.lever.co/v0/postings/{company}/{job_id}"


def parse_url(url: str) -> tuple[str | None, str | None]:
    m = re.match(r"^/([^/]+)/([0-9a-f-]{36})", urlsplit(url).path)
    return (m.group(1), m.group(2)) if m else (None, None)


def parse_api(data: dict) -> JobDetails:
    created = data.get("createdAt")
    posted = datetime.fromtimestamp(created / 1000).date() if isinstance(created, (int, float)) else None
    return JobDetails(position=clean(data.get("text")), posted_date=posted)


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
