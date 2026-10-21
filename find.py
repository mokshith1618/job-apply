"""Search the tracker and change Outcome (milestone 7).

    python find.py <text> [--tracker PATH] [--no-sheet]

Finds every row whose Company, Position or URL contains <text>, prints them grouped by company,
and changes Outcome (plus an optional dated note in Remarks) for the rows I pick.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlsplit

from rich.console import Console
from rich.table import Table
from rich.text import Text

import tracker

MAX_SHOWN = 50
OUTCOME_STYLES = {"Online Assessment": "yellow", "Interview": "blue", "Rejected": "dim"}


# ---------- input parsing ----------

def parse_selection(text: str, n: int) -> list[int] | None:
    """'1,3' / '2-4' / 'all' -> sorted row numbers in 1..n; None if anything is invalid."""
    text = text.strip().lower()
    if text == "all":
        return list(range(1, n + 1))
    picked = set()
    for part in text.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not m:
            return None
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if not 1 <= lo <= hi <= n:
            return None
        picked.update(range(lo, hi + 1))
    return sorted(picked)


def parse_status(text: str) -> str | None:
    """'2' or 'rejected' (any case) -> 'Rejected'; None if it isn't one of tracker.OUTCOMES."""
    text = " ".join(text.split()).casefold()
    if text.isdigit() and 1 <= int(text) <= len(tracker.OUTCOMES):
        return tracker.OUTCOMES[int(text) - 1]
    return next((o for o in tracker.OUTCOMES if o.casefold() == text), None)


def format_note(day: date, note: str, existing) -> str:
    """Remarks after adding `note`: 'existing | MM/DD/YYYY note'. No note = Remarks unchanged."""
    existing = "" if existing is None else str(existing).strip()
    note = note.strip()
    if not note:
        return existing
    dated = f"{day:%m/%d/%Y} {note}"
    return f"{existing} | {dated}" if existing else dated


# ---------- table ----------

def parse_date(value) -> date | None:
    """Column E as a date: an Excel date, or Sheet text like '6/20/2026'. Anything else: None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def order_rows(rows):
    """Group by company (search_key), groups by their newest date, rows newest first; no date last."""
    def newest_first(item):
        r, values, _ = item
        d = parse_date(values[4])
        return (d is None, -(d.toordinal() if d else 0), -r)

    groups: dict[str, list] = {}
    for item in sorted(rows, key=newest_first):
        groups.setdefault(tracker.search_key(item[1][0]), []).append(item)
    return [item for group in groups.values() for item in group]  # dicts keep the first-seen order


def _link(urls: list[str]) -> Text:
    """The domain, clickable (OSC 8) where the terminal supports it; plain link text otherwise."""
    url = next((u for u in reversed(urls) if urlsplit(u).hostname), None)
    if url is None:
        return Text(urls[0] if urls else "")
    return Text(urlsplit(url).hostname.removeprefix("www."), style=f"link {url}")


def _cell(value) -> str:
    return "" if value is None else str(value)


def show_table(console: Console, hits, text: str) -> list:
    """Print the matches (at most MAX_SHOWN) and return the shown rows in their numbered order."""
    if not hits:
        console.print(f'No jobs found for "{text}".', markup=False, highlight=False)
        return []
    ordered = order_rows(hits)
    shown = ordered[:MAX_SHOWN]
    console.print(f'{len(hits)} job{"" if len(hits) == 1 else "s"} found for "{text}"\n',
                  markup=False, highlight=False)
    table = Table(box=None, header_style="bold", pad_edge=False)
    for name in ("#", "Row", "Date", "Company", "Position", "Outcome", "Remarks", "Link"):
        table.add_column(name, overflow="fold", justify="right" if name in ("#", "Row") else "left")
    for i, (r, values, urls) in enumerate(shown, start=1):
        d = parse_date(values[4])
        outcome = _cell(values[5])
        table.add_row(str(i), str(r), f"{d:%m/%d/%Y}" if d else _cell(values[4]), Text(_cell(values[0])),
                      Text(_cell(values[1])), Text(outcome, style=OUTCOME_STYLES.get(outcome, "")),
                      Text(_cell(values[6])), _link(urls))
    console.print(table)
    if len(ordered) > MAX_SHOWN:
        console.print(f"\n{len(ordered) - MAX_SHOWN} more not shown; narrow the search.", highlight=False)
    return shown
