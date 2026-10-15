"""iCIMS: the job page is a company-branded wrapper; the job itself is in an iframe.

GET https://{company}.icims.com/jobs/{id}/{slug}/job?in_iframe=1
That page has JobPosting JSON-LD (confirmed 2026-10-15): title, hiringOrganization.name, datePosted.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from .common import JobDetails, get_text
from .generic import parse_jsonld


def iframe_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "in_iframe=1", ""))


def fetch_details(url: str) -> JobDetails:
    return parse_jsonld(get_text(iframe_url(url)))
