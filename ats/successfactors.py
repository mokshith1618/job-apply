"""SAP SuccessFactors Recruiting (classic career site): the job is in the plain job page.

Job links: https://{host}.sapsf.eu/career?career_job_req_id={id}&company={code}&career_ns=job_listing
(also *.sapsf.com, *.successfactors.com, *.successfactors.eu). Read from the page (confirmed 2026-10-19):
- title: <h1>Career Opportunities: {title} ({id})</h1>
- posted: <input id="postedOnFastDate" value="{milliseconds}"> (the page's JavaScript formats it)
- description: <div class="joqReqDescription"> ... </div>
There is no company name on the page; the name I type is remembered per host + company code.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from .common import JobDetails, clean, get_text, html_text

HOST_SUFFIXES = (".sapsf.com", ".sapsf.eu", ".successfactors.com", ".successfactors.eu")


def is_job_link(url: str) -> bool:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    return host.endswith(HOST_SUFFIXES) and bool(parse_qs(parts.query).get("career_job_req_id"))


def _title(page: str) -> str | None:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I)
    if not m:
        return None
    text = clean(html.unescape(re.sub(r"<[^>]+>", "", m.group(1))))
    if not text:
        return None
    text = re.sub(r"^Career Opportunities:\s*", "", text)
    return clean(re.sub(r"\s*\(\d+\)$", "", text))


def _posted(page: str) -> str | None:
    m = re.search(r'id="postedOnFastDate"\s+value="(\d+)"', page)
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _description(page: str) -> str | None:
    """The joqReqDescription div up to its own closing tag (the buttons after it are not part of it)."""
    start = page.find('class="joqReqDescription"')
    if start < 0:
        return None
    start = page.rfind("<div", 0, start)
    depth = 0
    for m in re.finditer(r"<(/?)div\b[^>]*>", page[start:], re.I):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return html_text(page[start:start + m.end()])
    return html_text(page[start:])


def parse_page(page: str) -> JobDetails:
    posted = _posted(page)
    return JobDetails(position=_title(page),
                      posted_date=datetime.fromisoformat(posted).date() if posted else None,
                      description=_description(page),
                      posted_raw=posted)


def fetch_details(url: str) -> JobDetails:
    if not is_job_link(url):
        return JobDetails()
    return parse_page(get_text(url.strip()))
