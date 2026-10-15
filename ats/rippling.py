"""Rippling: the job page carries its data in Next.js's __NEXT_DATA__ script (no JSON-LD).

Page: https://ats.rippling.com/{board}/jobs/{uuid}
Fields used (confirmed 2026-10-15) under props.pageProps.apiData.jobPost:
name (title), companyName, createdOn ("2026-10-15T07:54:57.425000-07:00").
og:site_name is "Rippling Recruiting" (the software, not the employer), so it is not used.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from .common import JobDetails, clean, get_text, parse_date

PAGE = "https://ats.rippling.com/{board}/jobs/{job_id}"
_NEXT_RE = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def parse_url(url: str) -> tuple[str | None, str | None]:
    m = re.match(r"^/([^/]+)/jobs/([0-9a-f-]{36})", urlsplit(url).path)
    return (m.group(1), m.group(2)) if m else (None, None)


def parse_page(page: str) -> JobDetails:
    m = _NEXT_RE.search(page)
    if not m:
        return JobDetails()
    try:
        api = json.loads(m.group(1))["props"]["pageProps"]["apiData"]
    except (ValueError, KeyError, TypeError):
        return JobDetails()
    post = api.get("jobPost") or {}
    board = api.get("jobBoard") or {}
    return JobDetails(
        company=clean(post.get("companyName")) or clean(board.get("companyName")),
        position=clean(post.get("name")),
        posted_date=parse_date(post.get("createdOn")),
    )


def fetch_details(url: str) -> JobDetails:
    board, job_id = parse_url(url)
    if not (board and job_id):
        return JobDetails()
    return parse_page(get_text(PAGE.format(board=board, job_id=job_id)))  # /apply page -> job page
