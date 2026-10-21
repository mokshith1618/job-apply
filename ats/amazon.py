"""amazon.jobs: the site's own search JSON, asked for one job.

Job links: https://www.amazon.jobs/{lang}/jobs/{id}/{slug}
GET https://www.amazon.jobs/en/search.json?job_id_icims[]={id}
Fields used (confirmed 2026-10-19): jobs[].id_icims, title, company_name ("Twitch Interactive, Inc. - D48":
the legal entity plus Amazon's unit code, which is removed), posted_date ("December 11, 2025"),
description, basic_qualifications, preferred_qualifications (HTML with <br/>).
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from .common import JobDetails, clean, get_json, html_text

API = "https://www.amazon.jobs/en/search.json?job_id_icims[]={job_id}"
TEXT_FIELDS = ("description", "basic_qualifications", "preferred_qualifications")  # page order


def parse_url(url: str) -> str | None:
    """-> the job id."""
    parts = urlsplit(url.strip())
    if (parts.hostname or "").lower().removeprefix("www.") != "amazon.jobs":
        return None
    m = re.match(r"(?:/[a-z]{2}(?:-[a-z]{2})?)?/jobs/(\d+)(?:/|$)", parts.path, re.I)
    return m.group(1) if m else None


def company_name(value) -> str | None:
    """'Twitch Interactive, Inc. - D48' -> 'Twitch Interactive, Inc.' (Amazon's unit code removed)."""
    value = clean(value)
    return clean(re.sub(r"\s+-\s+[A-Z0-9]{2,5}$", "", value)) if value else None


def _posted(value) -> str | None:
    """'December 11, 2025' -> '2025-12-11'."""
    try:
        return datetime.strptime(clean(value) or "", "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_api(data, job_id: str | None = None) -> JobDetails:
    jobs = data.get("jobs") if isinstance(data, dict) else None
    jobs = [j for j in jobs or [] if isinstance(j, dict) and (job_id is None or str(j.get("id_icims")) == job_id)]
    if not jobs:
        return JobDetails()
    job = jobs[0]
    posted = _posted(job.get("posted_date"))
    text = "\n".join(t for t in (html_text(job.get(f)) for f in TEXT_FIELDS) if t)
    return JobDetails(company=company_name(job.get("company_name")),
                      position=clean(job.get("title")),
                      posted_date=datetime.fromisoformat(posted).date() if posted else None,
                      description=text or None,
                      posted_raw=posted)


def fetch_details(url: str) -> JobDetails:
    job_id = parse_url(url)
    if not job_id:
        return JobDetails()
    return parse_api(get_json(API.format(job_id=job_id)), job_id)
