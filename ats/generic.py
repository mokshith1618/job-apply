"""Any site: read the page's JobPosting JSON-LD (title, hiringOrganization, datePosted).

When a page has no JSON-LD, its share tags (og:site_name, og:title), <title> and <h1> give
guesses for company and position. Guesses are only offered to me as defaults in the terminal.
"""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser

from .common import JobDetails, clean, get_text, parse_date

_LD_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I
)
_TITLE_SPLIT_RE = re.compile(r"\s+(?:\||-|–|—|·|:|at)\s+", re.I)
# "Careers at Acme", "Acme Careers", "JPMC Candidate Experience page", "2100 NVIDIA USA" (Workday entity code)
_COMPANY_NOISE_RE = re.compile(
    r"^\d+\s+|^(?:careers|jobs)\s+(?:at|with)\s+|\s+(?:careers?|jobs|job board|candidate experience)(?:\s+(?:page|site))?$",
    re.I,
)
_NOT_A_TITLE_RE = re.compile(r"\b(?:careers?|jobs|job search|home|candidate experience)\b", re.I)


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
            company = clean(org.get("name") if isinstance(org, dict) else org)
            tidy = _clean_company(company)
            # "JPMC Candidate Experience page" is a site name, not a company: offer "JPMC" as a guess.
            return JobDetails(
                company=company if tidy == company else None,
                position=clean(posting.get("title")),
                posted_date=parse_date(posting.get("datePosted")),
                company_guess=tidy if tidy != company else None,
            )
    return JobDetails()


class _Tags(HTMLParser):
    """Collects <meta property/name=... content=...>, the <title> text and the first <h1> text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.h1 = ""
        self._in = None  # "title" / "h1" while inside one
        self._h1_done = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta" and a.get("content"):
            key = (a.get("property") or a.get("name") or "").lower()
            if key:
                self.meta.setdefault(key, a["content"])
        elif tag == "title" and not self.title:
            self._in = "title"
        elif tag == "h1" and not self._h1_done:
            self._in = "h1"

    def handle_endtag(self, tag):
        if tag == self._in:
            if tag == "h1":
                self._h1_done = True
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "h1":
            self.h1 += data


def _clean_company(value) -> str | None:
    value = clean(value)
    if not value:
        return None
    return clean(_COMPANY_NOISE_RE.sub("", value))


def _title_part(value, company: str | None) -> str | None:
    """'Cloud Analyst | Acme Careers' -> 'Cloud Analyst' (drops the company and careers-site parts)."""
    value = clean(value)
    if not value:
        return None
    company_cf = (company or "").casefold()
    for part in _TITLE_SPLIT_RE.split(value):
        part = clean(part)
        if part and part.casefold() != company_cf and not _NOT_A_TITLE_RE.search(part):
            return part
    return None


def parse_hints(page: str) -> JobDetails:
    """Company and position guesses from share tags, <h1> and <title>. Never a posted date."""
    tags = _Tags()
    try:
        tags.feed(page)
    except Exception:  # noqa: BLE001 - malformed HTML just means fewer guesses
        pass
    company = _clean_company(tags.meta.get("og:site_name") or tags.meta.get("application-name"))
    h1 = clean(tags.h1)
    position = None
    if h1 and len(h1) <= 120 and h1.casefold() != (company or "").casefold() and not _NOT_A_TITLE_RE.search(h1):
        position = h1  # a job page's heading is usually the whole title, dashes and all
    position = (position or _title_part(tags.meta.get("og:title"), company)
                or _title_part(tags.meta.get("twitter:title"), company) or _title_part(tags.title, company))
    return JobDetails(company_guess=company, position_guess=position)


def parse_page(page: str) -> JobDetails:
    return parse_jsonld(page).merge(parse_hints(page))


def parse_pages(pages: list[str]) -> JobDetails:
    """A rendered page and its frames: JSON-LD from any of them, guesses from the main page only."""
    details = JobDetails()
    for page in pages:
        details = details.merge(parse_jsonld(page))
    return details.merge(parse_hints(pages[0])) if pages else details


def fetch_details(url: str) -> JobDetails:
    return parse_page(get_text(url))
