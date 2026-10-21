"""Shared types and HTTP helpers for the ATS modules. Plain HTTP only, no AI."""
from __future__ import annotations

import html
import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) job-apply-helper"
TIMEOUT = 20


@dataclass
class JobDetails:
    company: str | None = None
    position: str | None = None
    posted_date: date | None = None
    # Read from page tags/title, not job data: only offered to me as a default, never used silently.
    company_guess: str | None = field(default=None, compare=False)
    position_guess: str | None = field(default=None, compare=False)
    # For the job facts card: the description as lines of text, and the posted date as the board wrote it.
    description: str | None = field(default=None, compare=False)
    posted_raw: str | None = field(default=None, compare=False)

    def merge(self, other: "JobDetails") -> "JobDetails":
        """Fill fields that are still missing from another result."""
        return JobDetails(
            company=self.company or other.company,
            position=self.position or other.position,
            posted_date=self.posted_date or other.posted_date,
            company_guess=self.company_guess or other.company_guess,
            position_guess=self.position_guess or other.position_guess,
            description=self.description or other.description,
            posted_raw=self.posted_raw or other.posted_raw,
        )

    def complete(self) -> bool:
        return bool(self.company and self.position and self.posted_date)


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def get_json(url: str):
    return json.loads(get_text(url))


def parse_date(value) -> date | None:
    """Parse '2026-09-09T10:50:29-04:00' or '2026-04-07' to a date (posting's own day)."""
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


_BLOCK_TAGS = {"address", "article", "blockquote", "br", "dd", "div", "dl", "dt", "footer", "h1", "h2", "h3",
               "h4", "h5", "h6", "header", "hr", "li", "main", "ol", "p", "pre", "section", "table", "td",
               "th", "tr", "ul"}
_SKIP_TAGS = {"head", "noscript", "script", "style", "template", "title"}
_TAG_RE = re.compile(r"<[a-zA-Z/!]")


class _Text(HTMLParser):
    """Text of an HTML fragment: block tags become line breaks, scripts and styles are dropped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data.replace("\n", " "))


def html_text(markup) -> str | None:
    """Job description HTML (or plain text) -> lines of text. Only mechanical changes: tags removed,
    entities decoded, spaces collapsed. Escaped HTML (Greenhouse's `content`) is unescaped first."""
    if not isinstance(markup, str):
        return None
    if not _TAG_RE.search(markup) and "&lt;" in markup:
        markup = html.unescape(markup)
    if _TAG_RE.search(markup):
        parser = _Text()
        parser.feed(markup)
        parser.close()
        text = "".join(parser.parts)
    else:
        text = html.unescape(markup)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line) or None
