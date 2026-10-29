"""Read the tracker for the report, never writing to it, and the report settings (report.yaml).

Rows come from tracker.read_rows (Excel) or sheet_tracker.read_rows (the Sheet), so columns are
found by header name exactly as apply.py and find.py find them. Neither saves anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import yaml

import sheet_tracker
import tracker


@dataclass
class Settings:
    """report.yaml; every key left out keeps the default below (the same values as the file in git)."""
    weekly_target: int = 25
    follow_up_days: int = 14
    no_reply_days: int = 30
    many_applications: int = 5
    min_group: int = 20
    weeks_shown: int = 12
    sources: list[str] = field(default_factory=lambda: ["Jobright", "Tsenta", "LinkedIn"])
    early_career_words: list[str] = field(default_factory=lambda: [
        "new grad", "graduate", "grad", "early career", "entry", "junior", "jr", "residency",
        "associate", "university", " I", " 1", "intern"])
    title_types: dict[str, list[str]] = field(default_factory=lambda: {
        "Backend": ["backend", "back-end", "back end", "api"],
        "DevOps/Cloud/SRE/Platform": ["devops", "sre", "reliability", "platform", "infrastructure", "cloud"],
        "AI/ML/Data": ["ai", "machine learning", "ml", "data"],
        "Software (general)": ["software", "developer", "sde", "swe", "engineer"],
    })
    remark_tags: dict[str, list[str]] = field(default_factory=lambda: {
        "No sponsorship": ["sponsor", "visa"],
        "Clearance/citizenship": ["clearance", "citizen"],
        "Referral": ["referral", "referred"],
    })


def load_settings(path) -> Settings:
    path = Path(path)
    if not path.exists():
        return Settings()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path.name} should hold 'key: value' lines.")
    known = {f.name for f in fields(Settings)}
    unknown = [k for k in data if k not in known]
    if unknown:
        raise SystemExit(f"{path.name}: unknown setting {', '.join(map(str, unknown))}")
    return Settings(**data)


@dataclass
class Job:
    """One tracker row as the report sees it: text stripped, dates as dates (None when unreadable)."""
    row: int
    company: str
    position: str
    url: str
    posted: str  # Posted date/ Source
    applied: date | None
    outcome: str
    stage: str
    last_updated: date | None
    remarks: str
    url_is_formula: bool = False  # the Excel cell holds =HYPERLINK(...) instead of text + hyperlink


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _url(urls: list[str]) -> tuple[str, bool]:
    """The job link of a URL cell: a =HYPERLINK target, else the hyperlink target, else the text."""
    for u in urls:
        m = sheet_tracker.HYPERLINK_TARGET.match(u.strip())
        if m:
            return m.group(1).replace('""', '"'), True
    links = [u for u in urls if urlsplit(u.strip()).hostname]
    return (links[-1] if links else urls[0] if urls else "").strip(), False


def _job(r: int, values: dict, urls: list[str], formulas: bool) -> Job:
    url, is_formula = _url(urls)
    return Job(row=r, company=_text(values["Company"]), position=_text(values["Position"]), url=url,
               posted=_text(values["Posted date/ Source"]), applied=tracker.parse_date(values["Date"]),
               outcome=_text(values["Outcome"]), stage=_text(values["Stage"]),
               last_updated=tracker.parse_date(values["Last Updated"]), remarks=_text(values["Remarks"]),
               url_is_formula=is_formula and formulas)


def excel_rows(path) -> list[Job]:
    """Every job row of the Excel tracker. Opens the file only to read; never saves it."""
    return [_job(r, values, urls, formulas=True) for r, values, urls in tracker.read_rows(path)]


def sheet_rows(ws) -> list[Job]:
    """Every job row of the Google Sheet. Its URL formulas are by design, so they aren't flagged."""
    return [_job(r, values, urls, formulas=False) for r, values, urls in sheet_tracker.read_rows(ws)]
