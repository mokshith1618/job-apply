"""Job Apply Helper entry point.

    python apply.py <job-url> [--source LinkedIn|Tsenta|Other] [--tracker PATH] [--no-sheet] [--no-fill]

Milestone 1: read job details, check for duplicates, wait for me, then add the tracker row.
Milestone 1b: the row goes to the Google Sheet set in config.yaml, then to the local Excel file.
Milestone 2: Greenhouse forms are filled from profile.yaml and answers.yaml before the pause.
This script never submits anything. I submit the application myself.
"""
from __future__ import annotations

import argparse
import functools
import sys
from datetime import date
from pathlib import Path

import yaml

import ats
import sheet_tracker
import tracker
from ats import browser, greenhouse, sites
from sheet_tracker import SheetMismatch, SheetUnavailable

HERE = Path(__file__).resolve().parent
DEFAULT_TRACKER = HERE / "Job Application Tracker.xlsx"
DEFAULT_CONFIG = HERE / "config.yaml"
DEFAULT_PROFILE = HERE / "profile.yaml"
DEFAULT_ANSWERS = HERE / "answers.yaml"
DEFAULT_COMPANIES = HERE / "companies.yaml"
BROWSER_PROFILE = HERE / "browser-profile"
FILLERS = {"greenhouse": greenhouse.open_and_fill}  # system -> form filler; tests replace this
PAUSE_PROMPT = "Review the form and click Submit yourself. Then press Enter = applied, s = skipped. "


def ask_required(label: str, input_fn, suggestion: str | None = None) -> str:
    """A suggestion is a guess from the page's tags: Enter accepts it, typing replaces it."""
    prompt = f"{label} [{suggestion}] (Enter = use this): " if suggestion else f"{label}: "
    while True:
        value = " ".join(input_fn(prompt).split())
        if value:
            return value
        if suggestion:
            return suggestion


def ask_posted_date(input_fn, today: date) -> date | None:
    while True:
        raw = input_fn("Posted date (YYYY-MM-DD, 'today', or blank if unknown): ").strip().lower()
        if not raw:
            return None
        if raw == "today":
            return today
        try:
            return date.fromisoformat(raw)
        except ValueError:
            print("  Use YYYY-MM-DD, e.g. 2026-10-08.")


def show_duplicates(hits) -> None:
    print("\nAlready in the tracker:")
    for row, values in hits:
        company, position, url, posted, applied, outcome = values
        applied = applied.strftime("%m/%d/%Y") if hasattr(applied, "strftime") else applied
        print(f"  row {row}: {company} | {position} | {posted} | {applied} | {outcome}\n           {url}")


def load_config(path: Path) -> dict:
    """config.yaml: sheet_id, sheet_tab, google_key, local_tracker. Missing file = Excel only."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path.name} should hold 'key: value' lines.")
    return data


def _resolve(value) -> Path:
    path = Path(value)
    return path if path.is_absolute() else HERE / path


class Sheet:
    """The Google Sheet side of a run. `ws` is None when the Sheet is off or couldn't be reached."""

    def __init__(self, enabled: bool, ws, pending: Path, backup_dir: Path):
        self.enabled = enabled
        self.ws = ws
        self.pending = pending
        self.backup_dir = backup_dir

    def failed(self, exc: Exception) -> None:
        print(f"Google Sheet unavailable: {exc}")
        self.ws = None

    def flush_pending(self) -> None:
        if self.ws is None or not self.pending.exists():
            return
        try:
            for r, row in tracker.flush_pending(None, self.pending, append=self.append):
                print(f"Wrote pending row {r} to the Google Sheet: {row.company} - {row.position}")
        except (SheetUnavailable, SheetMismatch) as exc:
            self.failed(exc)
            print(f"Note: rows in {self.pending.name} are still waiting for the Google Sheet.")

    def append(self, row: tracker.TrackerRow) -> int:
        return sheet_tracker.append_row(self.ws, row, self.backup_dir)

    def find_duplicates(self, tracker_path: Path, **match) -> list:
        """Check the Sheet; if it can't be reached, check the Excel file instead."""
        if self.ws is not None:
            try:
                return sheet_tracker.find_duplicates(self.ws, **match)
            except (SheetUnavailable, SheetMismatch) as exc:
                self.failed(exc)
                print(f"Checking duplicates in {tracker_path.name} instead.")
        return tracker.find_duplicates(tracker_path, **match)

    def write(self, row: tracker.TrackerRow) -> None:
        if not self.enabled:
            return
        if self.ws is not None:
            try:
                r = self.append(row)
                print(f"Added row {r} to the Google Sheet.")
                return
            except (SheetUnavailable, SheetMismatch) as exc:
                self.failed(exc)
        tracker.save_pending(self.pending, row)
        print(f"Row saved in {self.pending.name}; it goes to the Google Sheet on the next run.")


def write_row(tracker_path: Path, row: tracker.TrackerRow, input_fn) -> int:
    """Keep the row in pending_rows.json until it's in the tracker, so nothing is lost if Excel has it open."""
    pending = tracker.pending_path_for(tracker_path)
    tracker.save_pending(pending, row)
    while True:
        try:
            written = tracker.flush_pending(tracker_path, pending)
            return written[-1][0]
        except tracker.TrackerLocked:
            input_fn(f"\n{tracker_path.name} is open in Excel (row saved in {pending.name}). "
                     "Close Excel, then press Enter to retry. ")


def open_sheet(config: dict, tracker_path: Path, no_sheet: bool, ws=None) -> Sheet:
    """`ws` lets tests pass a fake worksheet instead of opening the real Sheet."""
    enabled = not no_sheet and (ws is not None or bool(config.get("sheet_id")))
    sheet = Sheet(enabled, None, tracker_path.parent / "pending_sheet.json", tracker_path.parent / "backups")
    if not enabled:
        return sheet
    if ws is None:
        try:
            ws = sheet_tracker.open_sheet(config["sheet_id"], config.get("sheet_tab", "Sheet1"),
                                          _resolve(config.get("google_key", "google-key.json")))
        except SheetUnavailable as exc:
            sheet.failed(exc)
            print(f"Checking duplicates in {tracker_path.name}; the row will wait in {sheet.pending.name}.")
            return sheet
    sheet.ws = ws
    return sheet


def open_form(filler, url: str, args, input_fn):
    """Open and fill the form; returns the browser session (or None). Never submits.

    Any failure (Chrome missing, page changed) is printed, and I fill the form by hand.
    """
    if filler is None:
        return None
    if not args.profile.exists():
        print(f"{args.profile.name} not found; not filling the form.")
        return None
    try:
        session = filler(url, profile_path=args.profile, answers_path=args.answers, source=args.source,
                         input_fn=input_fn, user_data_dir=BROWSER_PROFILE)
    except Exception as exc:  # noqa: BLE001 - the tracker flow carries on without the filler
        print(f"Could not fill the form ({type(exc).__name__}: {exc}). Fill it by hand.")
        return None
    print(session.report.summary())
    return session


def get_company(details: ats.JobDetails, url: str, system: str, companies: Path, input_fn) -> str:
    """Read from the job > the name I gave this site before > ask me (and remember it for the site)."""
    if details.company:
        return details.company
    key = sites.site_key(url, system)
    known = sites.load(companies).get(key) if key else None
    if known:
        print(f"  Company from {companies.name}: {known}")
        return known
    company = ask_required("Company", input_fn, details.company_guess or sites.name_from_link(url, system))
    if key:
        sites.remember(companies, key, company)
        print(f"  Saved: {key} = {company} (in {companies.name}; links from this site won't ask again)")
    return company


def read_details(url: str) -> ats.JobDetails:
    """Job APIs and the page's JSON-LD; Chrome (my saved logins) only for what is still missing."""
    return ats.fetch_details(url, render=functools.partial(browser.render_page, user_data_dir=BROWSER_PROFILE))


def main(argv=None, input_fn=input, fetch=read_details, today: date | None = None, sheet_ws=None,
         fill=None) -> int:
    parser = argparse.ArgumentParser(description="Read a job, fill the form, wait for me to apply, then log it.")
    parser.add_argument("url")
    parser.add_argument("--source", choices=["LinkedIn", "Tsenta", "Other"], default="Other")
    parser.add_argument("--tracker", type=Path, help="local Excel tracker (default: local_tracker in config.yaml)")
    parser.add_argument("--no-sheet", action="store_true", help="Excel only; skip the Google Sheet")
    parser.add_argument("--no-fill", action="store_true", help="don't open or fill the form")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument("--companies", type=Path, default=DEFAULT_COMPANIES)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    today = today or date.today()
    url = args.url.strip()
    config = load_config(args.config)
    tracker_path: Path = args.tracker or (_resolve(config["local_tracker"]) if config.get("local_tracker")
                                          else DEFAULT_TRACKER)

    if not tracker_path.exists():
        print(f"Tracker not found: {tracker_path}")
        return 2

    sheet = open_sheet(config, tracker_path, args.no_sheet, sheet_ws)
    sheet.flush_pending()  # rows from a run where the Sheet couldn't be reached

    # Rows left over from a run where Excel had the file open.
    try:
        for r, row in tracker.flush_pending(tracker_path):
            print(f"Wrote pending row {r}: {row.company} - {row.position}")
    except tracker.TrackerLocked:
        print("Note: pending rows are still waiting; close Excel to write them.")

    system = ats.detect_system(url)
    print(f"System: {system}")

    seen = set()
    hits = sheet.find_duplicates(tracker_path, url=url)
    if hits:
        show_duplicates(hits)
        if input_fn("Continue anyway? [y/N] ").strip().lower() != "y":
            return 1
        seen = {r for r, _ in hits}

    print("Reading job details...")
    details = fetch(url)
    company = get_company(details, url, system, args.companies, input_fn)
    position = details.position or ask_required("Position", input_fn, details.position_guess)
    posted_date = details.posted_date if details.posted_date else ask_posted_date(input_fn, today)

    hits = [h for h in sheet.find_duplicates(tracker_path, company=company, position=position)
            if h[0] not in seen]
    if hits:
        show_duplicates(hits)
        if input_fn("Continue anyway? [y/N] ").strip().lower() != "y":
            return 1

    row = tracker.TrackerRow(
        company=company,
        position=position,
        url=url,
        posted=tracker.format_posted(posted_date, args.source, today),
        applied_on=today,
    )
    print(f"\n  Company:  {row.company}\n  Position: {row.position}\n  Posted:   {row.posted}\n  URL:      {row.url}\n")

    session = None if args.no_fill else open_form(fill or FILLERS.get(system), url, args, input_fn)
    try:
        while True:
            answer = input_fn(PAUSE_PROMPT).strip().lower()
            if answer == "s":
                print("Skipped. Tracker not changed.")
                return 0
            if answer == "":
                break
    finally:
        if session is not None:
            session.close()

    sheet.write(row)
    r = write_row(tracker_path, row, input_fn)
    print(f"Added row {r} to {tracker_path.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
