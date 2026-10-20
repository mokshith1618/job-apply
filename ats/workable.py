"""Workable: public job and account APIs.

Job links: https://apply.workable.com/{account}/j/{shortcode}/
GET https://apply.workable.com/api/v2/accounts/{account}/jobs/{shortcode}
    -> title, published ("2026-08-12T00:00:00.000Z": the day only), description, requirements, benefits (HTML)
GET https://apply.workable.com/api/v1/accounts/{account} -> name (the company)
Confirmed 2026-10-19. A link without the account (apply.workable.com/j/{shortcode}) is read as an
ordinary page.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .common import JobDetails, clean, get_json, html_text, parse_date

JOB_API = "https://apply.workable.com/api/v2/accounts/{account}/jobs/{shortcode}"
ACCOUNT_API = "https://apply.workable.com/api/v1/accounts/{account}"
TEXT_FIELDS = ("description", "requirements", "benefits")  # page order


def parse_url(url: str) -> tuple[str | None, str | None]:
    """-> (account, shortcode)."""
    parts = urlsplit(url.strip())
    if (parts.hostname or "").lower() != "apply.workable.com":
        return (None, None)
    m = re.match(r"/([^/]+)/j/([A-Za-z0-9]+)(?:/|$)", parts.path)
    if not m or m.group(1) in ("j", "api"):
        return (None, None)
    return (m.group(1), m.group(2))


def parse_api(job, account=None) -> JobDetails:
    if not isinstance(job, dict):
        return JobDetails()
    day = (clean(job.get("published")) or "")[:10] or None  # midnight UTC stands for the day itself
    text = "\n".join(t for t in (html_text(job.get(f)) for f in TEXT_FIELDS) if t)
    return JobDetails(company=clean(account.get("name")) if isinstance(account, dict) else None,
                      position=clean(job.get("title")),
                      posted_date=parse_date(day),
                      description=text or None,
                      posted_raw=day)


def fetch_details(url: str) -> JobDetails:
    account, shortcode = parse_url(url)
    if not (account and shortcode):
        return JobDetails()
    job = get_json(JOB_API.format(account=account, shortcode=shortcode))
    try:  # the company name; the job is still useful without it
        info = get_json(ACCOUNT_API.format(account=account))
    except Exception as exc:  # noqa: BLE001
        print(f"  Could not read the Workable account name: {exc}")
        info = None
    return parse_api(job, info)
