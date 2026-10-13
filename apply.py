"""Job Apply Helper entry point.

    python apply.py <job-url> [--source LinkedIn|Tsenta|Other] [--tracker PATH]

Milestone 1: read job details, check for duplicates, wait for me, then add the tracker row.
This script never submits anything. I submit the application myself.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import ats
import tracker

HERE = Path(__file__).resolve().parent
DEFAULT_TRACKER = HERE / "Job Application Tracker.xlsx"
PAUSE_PROMPT = "Review the form and click Submit yourself. Then press Enter = applied, s = skipped. "


def ask_required(label: str, input_fn) -> str:
    while True:
        value = " ".join(input_fn(f"{label}: ").split())
        if value:
            return value


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


def main(argv=None, input_fn=input, fetch=ats.fetch_details, today: date | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read a job, wait for me to apply, then log it.")
    parser.add_argument("url")
    parser.add_argument("--source", choices=["LinkedIn", "Tsenta", "Other"], default="Other")
    parser.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER)
    args = parser.parse_args(argv)
    today = today or date.today()
    url = args.url.strip()
    tracker_path: Path = args.tracker

    if not tracker_path.exists():
        print(f"Tracker not found: {tracker_path}")
        return 2

    # Rows left over from a run where Excel had the file open.
    try:
        for r, row in tracker.flush_pending(tracker_path):
            print(f"Wrote pending row {r}: {row.company} - {row.position}")
    except tracker.TrackerLocked:
        print("Note: pending rows are still waiting; close Excel to write them.")

    system = ats.detect_system(url)
    print(f"System: {system}")

    seen = set()
    hits = tracker.find_duplicates(tracker_path, url=url)
    if hits:
        show_duplicates(hits)
        if input_fn("Continue anyway? [y/N] ").strip().lower() != "y":
            return 1
        seen = {r for r, _ in hits}

    print("Reading job details...")
    details = fetch(url)
    company = details.company or ask_required("Company", input_fn)
    position = details.position or ask_required("Position", input_fn)
    posted_date = details.posted_date if details.posted_date else ask_posted_date(input_fn, today)

    hits = [h for h in tracker.find_duplicates(tracker_path, company=company, position=position)
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

    while True:
        answer = input_fn(PAUSE_PROMPT).strip().lower()
        if answer == "s":
            print("Skipped. Tracker not changed.")
            return 0
        if answer == "":
            break

    r = write_row(tracker_path, row, input_fn)
    print(f"Added row {r} to {tracker_path.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
