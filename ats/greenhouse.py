"""Greenhouse: public Job Board API.

GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}
Fields used (confirmed 2026-10-13): title, company_name, first_published.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from .common import JobDetails, clean, get_json, parse_date

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"


def parse_url(url: str) -> tuple[str | None, str | None]:
    """Return (board, job_id). Board is None for custom career sites using ?gh_jid=."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    m = re.match(r"^/([^/]+)/jobs/(\d+)", parts.path)
    if m and m.group(1) != "embed":
        return m.group(1), m.group(2)
    if "for" in query and "token" in query:  # /embed/job_app?for=board&token=id
        return query["for"][0], query["token"][0]
    if "gh_jid" in query:
        return None, query["gh_jid"][0]
    return None, None


def parse_api(data: dict) -> JobDetails:
    return JobDetails(
        company=clean(data.get("company_name")),
        position=clean(data.get("title")),
        posted_date=parse_date(data.get("first_published")),
    )


def fetch_details(url: str) -> JobDetails:
    board, job_id = parse_url(url)
    if not (board and job_id):
        return JobDetails()  # caller falls back to the page's JSON-LD, then asks me
    return parse_api(get_json(API.format(board=board, job_id=job_id)))
