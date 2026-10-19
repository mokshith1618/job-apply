"""Job facts card (milestone 1d): what the job description says about sponsorship, citizenship
and seniority, printed word for word so I can decide whether to apply.

Rules only, no AI. Nothing is reworded, shortened or scored: every sentence printed is a slice
of the description text (tags removed, entities decoded and spaces collapsed by ats.common.html_text).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from ats.common import JobDetails

SYSTEM_NAMES = {"greenhouse": "Greenhouse", "ashby": "Ashby", "lever": "Lever", "workday": "Workday",
                "icims": "iCIMS", "oracle": "Oracle Cloud", "rippling": "Rippling", "other": "Other site"}
DEGREE_WORDS = ["Bachelor", "Bachelors", "BS", "B.S.", "Master", "Masters", "MS", "M.S.", "PhD", "Ph.D.",
                "degree", "degrees"]
# "2+ years", "3-5 years", "3 to 5 years", "at least 4 years", "minimum (of) 6 years", "5 or more years", "1 year"
YEARS_RE = re.compile(r"\b\d+\s*\+?\s*(?:(?:-|–|—|to)\s*\d+\s*\+?\s*)?(?:or more\s+)?years?\b", re.I)

# A sentence ends at . ! or ? (plus closing quotes/brackets), then a space and a capital or digit.
_END_RE = re.compile(r"[.!?][\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9])")
_ABBREVIATIONS = {"approx", "co", "corp", "dept", "dr", "etc", "inc", "jr", "ltd", "mr", "mrs", "ms", "no", "sr",
                  "st", "vs"}


@dataclass
class Keywords:
    """The keywords: lists in matching.yaml."""
    sponsorship: list[str]
    citizenship: list[str]
    citizenship_ignore: list[str]


@dataclass
class Facts:
    sponsorship: list[str] = field(default_factory=list)
    citizenship: list[str] = field(default_factory=list)
    seniority: list[str] = field(default_factory=list)


def load_keywords(path) -> Keywords:
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"{path.name} not found ({path}); it holds the keyword lists for the job facts card.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    lists = data.get("keywords") if isinstance(data, dict) else None
    if not isinstance(lists, dict):
        raise SystemExit(f"{path.name} needs a 'keywords:' section.")

    def words(name):
        value = lists.get(name) or []
        if not isinstance(value, list):
            raise SystemExit(f"{path.name}: keywords.{name} should be a list like [sponsor, visa].")
        return [str(v) for v in value]

    return Keywords(words("sponsorship"), words("citizenship"), words("citizenship_ignore"))


def _pattern(word: str) -> re.Pattern:
    """Whole words. ALL-CAPS keywords (OPT, ITAR, BS) match only in capitals, so 'opt out' isn't OPT."""
    body = r"\s+".join(re.escape(w) for w in word.split())
    return re.compile(rf"(?<!\w){body}(?!\w)", 0 if word.isupper() else re.I)


def _any(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _is_abbreviation(before: str) -> bool:
    """'U.S' / 'e.g' / 'Inc' / a single initial before a period: not the end of a sentence."""
    words = before.split()
    word = words[-1].lstrip("\"'“‘([").lower() if words else ""
    return "." in word or word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha())


def units(description: str):
    """Each line (a bullet stays whole), split into sentences. Text is sliced, never changed."""
    for line in description.splitlines():
        line = " ".join(line.split())
        start = 0
        for m in _END_RE.finditer(line):
            if line[m.start()] == "." and _is_abbreviation(line[start:m.start()]):
                continue
            yield line[start:m.end()].rstrip()
            start = m.end()
        if line[start:]:
            yield line[start:]


def find_facts(description: str, keywords: Keywords) -> Facts:
    sponsorship = [_pattern(w) for w in keywords.sponsorship]
    citizenship = [_pattern(w) for w in keywords.citizenship]
    ignore = [_pattern(w) for w in keywords.citizenship_ignore]
    degree = [_pattern(w) for w in DEGREE_WORDS]
    facts = Facts()
    for unit in units(description):
        if _any(sponsorship, unit) and unit not in facts.sponsorship:
            facts.sponsorship.append(unit)
        if _any(citizenship, unit) and not _any(ignore, unit) and unit not in facts.citizenship:
            facts.citizenship.append(unit)
        if (YEARS_RE.search(unit) or _any(degree, unit)) and unit not in facts.seniority:
            facts.seniority.append(unit)
    return facts


def _ago(n: int, unit: str) -> str:
    return f"{n} {unit}{'' if n == 1 else 's'} ago"


def _age(raw: str, now: datetime) -> str | None:
    text = raw.strip()
    try:
        if len(text) == 10:
            return _ago(max(0, (now.date() - date.fromisoformat(text)).days), "day")
        posted = datetime.fromisoformat(text)
    except ValueError:
        return None
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=now.tzinfo)
    seconds = max(0.0, (now - posted).total_seconds())
    if seconds < 86400:
        return _ago(int(seconds // 3600), "hour")
    return _ago(int(seconds // 86400), "day")


def posted_line(raw: str | None, now: datetime) -> str:
    """The date exactly as the board returned it, then its age. `now` must carry a time zone."""
    if not raw:
        return "unknown"
    age = _age(raw, now)
    return f"{raw} ({age})" if age else raw


def _section(name: str, lines: list[str]) -> str:
    return f"{name}:\n" + "\n".join(f"  {line}" for line in lines or ["not mentioned"])


def card(details: JobDetails, system: str, keywords: Keywords, now: datetime) -> str:
    """The card's text. A missing company or title is left out, never guessed."""
    header = " · ".join(p for p in (details.company, details.position, SYSTEM_NAMES.get(system, system)) if p)
    title = f"Title: {details.position or 'unknown'}"
    blocks = [header]
    if details.description:
        facts = find_facts(details.description, keywords)
        blocks += [_section("Sponsorship", facts.sponsorship), _section("Citizenship", facts.citizenship),
                   _section("Seniority", [title] + (facts.seniority or ["not mentioned"]))]
    else:
        blocks += ["Description: not available", _section("Seniority", [title])]
    blocks.append(_section("Posted", [posted_line(details.posted_raw, now)]))
    return "\n\n".join(blocks)
