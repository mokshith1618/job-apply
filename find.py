"""Search the tracker and change Outcome or Stage (milestone 7).

    python find.py <text> [--tracker PATH] [--no-sheet]

Finds every row whose Company, Position or URL contains <text>, prints them grouped by company,
and changes Outcome or Stage (plus an optional dated note in Remarks) for the rows I pick.
A Stage pick also sets Outcome to Awaiting reply; an Outcome pick leaves Stage as it is.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from rich.console import Console
from rich.table import Table
from rich.text import Text

import apply
import sheet_tracker
import tracker
from sheet_tracker import SheetMismatch, SheetUnavailable

MAX_SHOWN = 50
OUTCOME_STYLES = {"Rejected": "dim"}
STAGE_STYLES = {"Online Assessment": "yellow", "Initial Screening": "cyan", "Interview": "blue"}
STATUSES = tracker.OUTCOMES + tracker.STAGES  # one menu: an Outcome or a Stage
ROWS_PROMPT = "Rows to update (e.g. 1,2 or 1-3 or all; Enter = done): "
STATUS_PROMPT = "New status: " + "  ".join(f"{i} {o}" for i, o in enumerate(STATUSES, start=1)) + " "
NOTE_PROMPT = "Note for Remarks (optional): "


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


def parse_status(text: str) -> tuple[str, str] | None:
    """'2' or 'rejected' (any case) -> ('Rejected', ''): an Outcome, Stage kept.
    '6' or 'interview' -> ('Awaiting reply', 'Interview'): a Stage. None if it's neither."""
    text = " ".join(text.split()).casefold()
    if text.isdigit() and 1 <= int(text) <= len(STATUSES):
        picked = STATUSES[int(text) - 1]
    else:
        picked = next((o for o in STATUSES if o.casefold() == text), None)
    if picked is None:
        return None
    return (tracker.AWAITING, picked) if picked in tracker.STAGES else (picked, "")


# ---------- table ----------

def order_rows(rows):
    """Group by company (search_key), groups by their newest date, rows newest first; no date last."""
    def newest_first(item):
        r, values, _ = item
        d = tracker.parse_date(values[4])
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
    for name in ("#", "Row", "Date", "Company", "Position", "Outcome", "Stage", "Remarks", "Link"):
        table.add_column(name, overflow="fold", justify="right" if name in ("#", "Row") else "left")
    for i, (r, values, urls) in enumerate(shown, start=1):
        d = tracker.parse_date(values[4])
        outcome, stage = _cell(values[5]), _cell(values[6])
        table.add_row(str(i), str(r), f"{d:%m/%d/%Y}" if d else _cell(values[4]), Text(_cell(values[0])),
                      Text(_cell(values[1])), Text(outcome, style=OUTCOME_STYLES.get(outcome, "")),
                      Text(stage, style=STAGE_STYLES.get(stage, "")), Text(_cell(values[7])), _link(urls))
    console.print(table)
    if len(ordered) > MAX_SHOWN:
        console.print(f"\n{len(ordered) - MAX_SHOWN} more not shown; narrow the search.", highlight=False)
    return shown


# ---------- the run ----------

def _read(sheet: apply.Sheet, tracker_path: Path) -> tuple[list, Path]:
    """Rows from the Sheet if it can be read, else from the Excel file. -> (rows, that store's pending rows file)"""
    if sheet.ws is not None:
        try:
            return sheet_tracker.read_rows(sheet.ws), sheet.pending
        except (SheetUnavailable, SheetMismatch) as exc:
            sheet.failed(exc)
            print(f"Searching {tracker_path.name} instead.")
    return tracker.read_rows(tracker_path), tracker.pending_path_for(tracker_path)


def _waiting(pending_path: Path, text: str) -> int:
    """How many rows still waiting in a pending rows file match the search (they can't be updated yet)."""
    rows = [(0, [r.company, r.position, r.url, r.posted, r.applied_on, tracker.OUTCOME, "", ""], [r.url])
            for r in tracker.load_pending(pending_path)]
    return len(tracker.search_rows(rows, text))


def _ask(input_fn, prompt: str, parse):
    """Ask until `parse` accepts the answer. Enter returns ""."""
    while True:
        answer = input_fn(prompt).strip().lstrip("\ufeff")  # PowerShell pipes start with a BOM
        if not answer:
            return ""
        value = parse(answer)
        if value is not None:
            return value


def _write(sheet: apply.Sheet, tracker_path: Path, updates: list[tracker.OutcomeUpdate], input_fn) -> None:
    """Same order as apply.py: the Google Sheet, then the Excel file. Rows waiting in a pending file go
    in before the updates, so an update to a row that was itself waiting can find it."""
    sheet.flush_pending()
    sheet.write_updates(updates)
    tracker.save_pending_updates(tracker.pending_updates_path_for(tracker_path), updates)
    apply.flush_excel_updates(tracker_path, input_fn)


def main(argv=None, input_fn=input, sheet_ws=None, today: date | None = None, console: Console | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search the tracker by company, position or link; change Outcome.")
    parser.add_argument("text", nargs="+", help="words to find, e.g. acme or s&p global")
    parser.add_argument("--tracker", type=Path, help="local Excel tracker (default: local_tracker in config.yaml)")
    parser.add_argument("--no-sheet", action="store_true", help="Excel only; skip the Google Sheet")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    text = " ".join(args.text)
    today = today or date.today()
    console = console or Console()

    config = apply.load_config(args.config or apply.DEFAULT_CONFIG)
    tracker_path = apply.tracker_path_for(args.tracker, config)
    if not tracker_path.exists():
        print(f"Tracker not found: {tracker_path}")
        return 2
    sheet = apply.open_sheet(config, tracker_path, args.no_sheet, sheet_ws,
                             fallback=f"Searching {tracker_path.name} instead.")
    try:
        return _loop(sheet, tracker_path, text, input_fn, today, console)
    except (EOFError, KeyboardInterrupt):  # Ctrl+Z / Ctrl+C at a question: stop; pending files keep any update
        print("\nStopped.")
        return 0


def _loop(sheet: apply.Sheet, tracker_path: Path, text: str, input_fn, today: date, console: Console) -> int:
    """Search, show, ask, write; again until Enter at the rows question."""
    while True:
        rows, pending_rows = _read(sheet, tracker_path)
        shown = show_table(console, tracker.search_rows(rows, text), text)
        waiting = _waiting(pending_rows, text)
        if waiting:
            print(f"{waiting} matching row{'s' if waiting > 1 else ''} still waiting in {pending_rows.name} "
                  "(not shown; they can be updated once written).")
        if not shown:
            return 0
        print()
        picked = _ask(input_fn, ROWS_PROMPT, lambda answer: parse_selection(answer, len(shown)))
        if not picked:
            return 0
        status = _ask(input_fn, STATUS_PROMPT, parse_status)
        if not status:
            continue
        note = input_fn(NOTE_PROMPT).strip()
        n = len(picked)
        outcome, stage = status
        if input_fn(f"Update {n} row{'s' if n > 1 else ''} to {stage or outcome}? [y/N] ").strip().lower() != "y":
            print("Nothing changed.\n")
            continue
        updates = [tracker.OutcomeUpdate.for_row(*shown[i - 1], outcome=outcome, note=note, noted_on=today,
                                                 stage=stage)
                   for i in picked]
        _write(sheet, tracker_path, updates, input_fn)
        print()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # company names like Nestlé on a cp1252 console
    sys.exit(main())
