"""Ashby: public Job Posting API.

GET https://api.ashbyhq.com/posting-api/job-board/{org}  -> {"jobs": [...]}
Fields used (confirmed 2026-10-13): id, title, publishedAt; descriptionPlain (confirmed 2026-10-19).
The API has no display company name; it comes from the job page's JSON-LD.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .common import JobDetails, clean, get_json, html_text, parse_date
from .generic import fetch_details as fetch_jsonld

API = "https://api.ashbyhq.com/posting-api/job-board/{org}"


def parse_url(url: str) -> tuple[str | None, str | None]:
    m = re.match(r"^/([^/]+)/([0-9a-f-]{36})", urlsplit(url).path)
    return (m.group(1), m.group(2)) if m else (None, None)


def parse_api(data: dict, job_id: str) -> JobDetails:
    for job in data.get("jobs", []):
        if job.get("id") == job_id:
            return JobDetails(
                position=clean(job.get("title")),
                posted_date=parse_date(job.get("publishedAt")),
                description=html_text(job.get("descriptionPlain")),
                posted_raw=clean(job.get("publishedAt")),
            )
    return JobDetails()


def fetch_details(url: str) -> JobDetails:
    org, job_id = parse_url(url)
    if not (org and job_id):
        return JobDetails()
    details = parse_api(get_json(API.format(org=org)), job_id)
    try:  # company name lives in the page's JSON-LD
        return details.merge(fetch_jsonld(f"https://jobs.ashbyhq.com/{org}/{job_id}"))
    except Exception as exc:  # noqa: BLE001 - keep the API result, ask for the rest
        print(f"  Could not read job page: {exc}")
        return details
