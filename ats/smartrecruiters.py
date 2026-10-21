"""SmartRecruiters: public posting API.

Job links: https://jobs.smartrecruiters.com/{company}/{id} (also careers.smartrecruiters.com, and
/{id}-{slug}). GET https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}
Fields used (confirmed 2026-10-19): name, company.name, releasedDate, and jobAd.sections
(companyDescription, jobDescription, qualifications, additionalInformation: title + HTML text).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .common import JobDetails, clean, get_json, html_text, parse_date

API = "https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}"
SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")  # page order


def parse_url(url: str) -> tuple[str | None, str | None]:
    """-> (company identifier, posting id)."""
    m = re.match(r"/([^/]+)/(\d+)(?:-[^/]*)?/?$", urlsplit(url.strip()).path)
    return (m.group(1), m.group(2)) if m else (None, None)


def description(data) -> str | None:
    sections = ((data.get("jobAd") or {}).get("sections") or {}) if isinstance(data, dict) else {}
    parts = []
    for key in SECTIONS:
        section = sections.get(key) or {}
        text = html_text(section.get("text"))
        if text:
            parts += [p for p in (clean(section.get("title")), text) if p]
    return "\n".join(parts) or None


def parse_api(data) -> JobDetails:
    if not isinstance(data, dict):
        return JobDetails()
    return JobDetails(company=clean((data.get("company") or {}).get("name")),
                      position=clean(data.get("name")),
                      posted_date=parse_date(data.get("releasedDate")),
                      description=description(data),
                      posted_raw=clean(data.get("releasedDate")))


def fetch_details(url: str) -> JobDetails:
    company, job_id = parse_url(url)
    if not (company and job_id):
        return JobDetails()
    return parse_api(get_json(API.format(company=company, job_id=job_id)))
