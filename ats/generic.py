"""Any site: read the page's JobPosting JSON-LD (title, hiringOrganization, datePosted)."""
from __future__ import annotations

import html
import json
import re

from .common import JobDetails, clean, get_text, parse_date

_LD_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I
)


def _postings(data):
    """Yield every JobPosting object in a JSON-LD blob (handles lists and @graph)."""
    if isinstance(data, list):
        for item in data:
            yield from _postings(item)
    elif isinstance(data, dict):
        kind = data.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            yield data
        if "@graph" in data:
            yield from _postings(data["@graph"])


def parse_jsonld(page: str) -> JobDetails:
    for raw in _LD_RE.findall(page):
        try:
            data = json.loads(html.unescape(raw.strip()))
        except ValueError:
            continue
        for posting in _postings(data):
            org = posting.get("hiringOrganization")
            company = org.get("name") if isinstance(org, dict) else org
            return JobDetails(
                company=clean(company),
                position=clean(posting.get("title")),
                posted_date=parse_date(posting.get("datePosted")),
            )
    return JobDetails()


def fetch_details(url: str) -> JobDetails:
    return parse_jsonld(get_text(url))
