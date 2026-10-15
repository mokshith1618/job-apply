"""Shared types and HTTP helpers for the ATS modules. Plain HTTP only, no AI."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import date

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

    def merge(self, other: "JobDetails") -> "JobDetails":
        """Fill fields that are still missing from another result."""
        return JobDetails(
            company=self.company or other.company,
            position=self.position or other.position,
            posted_date=self.posted_date or other.posted_date,
            company_guess=self.company_guess or other.company_guess,
            position_guess=self.position_guess or other.position_guess,
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
