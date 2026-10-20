"""UKG Pro Recruiting (UltiPro): the job is JSON inside the job page.

Job links: https://recruiting{n}.ultipro.com/{tenant}/JobBoard/{board}/OpportunityDetail?opportunityId={id}
(also https://{name}.rec.pro.ukg.net/...). The page has
`new US.Opportunity.CandidateOpportunityDetail({...})` with (confirmed 2026-10-19) Title, PostedDate,
Description (HTML) and EqualOpportunityEmployerDescription (HTML). There is no company name in it;
the name I type is remembered per tenant in companies.yaml.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

from .common import JobDetails, clean, get_text, html_text, parse_date

MARKER = "CandidateOpportunityDetail("


def is_ukg_host(host: str) -> bool:
    return bool(re.fullmatch(r"recruiting\d*\.ultipro\.com", host)) or host.endswith(".ukg.net")


def parse_url(url: str) -> tuple[str | None, str | None]:
    """-> (job page URL without tracking parameters, tenant)."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    m = re.match(r"/([^/]+)/JobBoard/[^/]+/OpportunityDetail/?$", parts.path, re.I)
    job_id = parse_qs(parts.query).get("opportunityId", [None])[0]
    if not (is_ukg_host(host) and m and job_id):
        return (None, None)
    return (f"https://{parts.netloc}{parts.path}?opportunityId={job_id}", m.group(1))


def parse_page(page: str) -> JobDetails:
    start = page.find(MARKER)
    if start < 0:
        return JobDetails()
    try:
        data, _ = json.JSONDecoder().raw_decode(page, start + len(MARKER))
    except ValueError:
        return JobDetails()
    if not isinstance(data, dict):
        return JobDetails()
    text = "\n".join(t for t in (html_text(data.get("Description")),
                                 html_text(data.get("EqualOpportunityEmployerDescription"))) if t)
    return JobDetails(position=clean(data.get("Title")),
                      posted_date=parse_date(data.get("PostedDate")),
                      description=text or None,
                      posted_raw=clean(data.get("PostedDate")))


def fetch_details(url: str) -> JobDetails:
    page_url, _ = parse_url(url)
    if not page_url:
        return JobDetails()
    return parse_page(get_text(page_url))
