"""Fields the report works out from each tracker row (SPEC "Derived fields"). Computed in memory,
never written back. Small pure functions; `facts` puts them together for one row."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import ats
import tracker
from reporting.load import Job, Settings

OTHER = "Other"
EARLY_CAREER = "Early career"
IN_PROGRESS, AWAITING, REJECTED = "In progress", "Awaiting reply", "Rejected"
REJECTED_AFTER = "Rejected after response"
NO_NEWS = "No news"
SYSTEM_NAMES = {"greenhouse": "Greenhouse", "ashby": "Ashby", "lever": "Lever", "rippling": "Rippling",
                "workday": "Workday", "icims": "iCIMS", "oracle": "Oracle Cloud",
                "smartrecruiters": "SmartRecruiters", "ukg": "UKG", "adp": "ADP", "amazon": "Amazon",
                "workable": "Workable", "successfactors": "SAP SuccessFactors", "other": OTHER}


def has_word(text: str, word: str, prefix: bool = False) -> bool:
    """`word` in `text` as a whole word (or phrase), ignoring case; with `prefix`, as the start of a
    word ("citizen" finds "Citizens"). A word written with a leading space (" I", " 1") counts only as
    the last word: "Software Engineer I"."""
    if word.startswith(" "):
        return re.search(r"\s" + re.escape(word.strip()) + r"\s*$", text, re.IGNORECASE) is not None
    end = "" if prefix else r"(?!\w)"
    return re.search(r"(?<!\w)" + re.escape(word.strip()) + end, text, re.IGNORECASE) is not None


def _any_word(text: str, words, prefix: bool = False) -> bool:
    return any(has_word(text, w, prefix) for w in words)


def source(posted: str, sources) -> str:
    """The first of `sources` named in Posted date/ Source; else Other."""
    return next((s for s in sources if has_word(posted, s)), OTHER)


def source_named(posted: str, sources) -> bool:
    """Whether D names a source at all; 'Other', as apply.py writes it, counts."""
    return _any_word(posted, [*sources, OTHER])


def job_system(url: str) -> str:
    return SYSTEM_NAMES.get(ats.detect_system(url), OTHER) if url else "Unknown"


def title_level(position: str, words) -> str:
    return EARLY_CAREER if _any_word(position, words) else OTHER


def title_type(position: str, types: dict) -> str:
    return next((name for name, words in types.items() if _any_word(position, words)), OTHER)


def status_group(outcome: str, stage: str) -> str:
    """In progress / Awaiting reply / Rejected after response / Rejected / No news. Applied with a
    Stage is the old model, where a Stage meant waiting on them (the data check lists those rows)."""
    if outcome == IN_PROGRESS:
        return IN_PROGRESS
    if outcome == REJECTED:
        return REJECTED_AFTER if stage else REJECTED
    if outcome == AWAITING or stage:
        return AWAITING
    return NO_NEWS


def remark_tags(remarks: str, tags: dict) -> list[str]:
    """Remarks are my own free notes, so a tag word may start a longer word (sponsor -> sponsorship)."""
    return [name for name, words in tags.items() if _any_word(remarks, words, prefix=True)]


def days_since(day: date | None, today: date) -> int | None:
    return (today - day).days if day else None


@dataclass
class Facts:
    """A row with everything the report works out from it."""
    job: Job
    source: str
    system: str
    level: str
    kind: str  # title type
    responded: bool
    group: str
    age: int | None  # days since Date
    since_update: int | None  # days since Last Updated
    tags: list[str]
    company_key: str


def facts(job: Job, settings: Settings, today: date) -> Facts:
    return Facts(job=job, source=source(job.posted, settings.sources), system=job_system(job.url),
                 level=title_level(job.position, settings.early_career_words),
                 kind=title_type(job.position, settings.title_types), responded=bool(job.stage),
                 group=status_group(job.outcome, job.stage), age=days_since(job.applied, today),
                 since_update=days_since(job.last_updated, today), tags=remark_tags(job.remarks, settings.remark_tags),
                 company_key=tracker.search_key(job.company))
