"""The report page (milestone 9): a calm, read-only view of the tracker.

    python report.py [--sheet] [--out PATH] [--no-open] [--today YYYY-MM-DD] [--tracker PATH]

Reads the Excel tracker (or the Google Sheet with --sheet), never writing to it, and writes one
self-contained report.html, then opens it in the default browser unless --no-open.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import apply
import sheet_tracker
import tracker
from reporting import derive, load, render
from sheet_tracker import SheetMismatch, SheetUnavailable

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "report.html"
DEFAULT_SETTINGS = HERE / "report.yaml"


def _sheet_jobs(config: dict, ws) -> list[load.Job] | None:
    """The Sheet's rows, or None (with the reason printed) if it isn't set up or can't be read."""
    if ws is None:
        if not config.get("sheet_id"):
            print("No sheet_id in config.yaml, so there is no Google Sheet to read. Run without --sheet.")
            return None
        try:
            ws = sheet_tracker.open_sheet(config["sheet_id"], config.get("sheet_tab", "Sheet1"),
                                          apply._resolve(config.get("google_key", "google-key.json")))
        except SheetUnavailable as exc:
            print(f"Google Sheet unavailable: {exc}")
            return None
    try:
        return load.sheet_rows(ws)
    except (SheetUnavailable, SheetMismatch) as exc:
        print(f"Can't read the Google Sheet: {exc}")
        return None


def _excel_jobs(path: Path) -> list[load.Job] | None:
    """The Excel tracker's rows, or None (with the reason printed). Opened to read only."""
    if not path.exists():
        print(f"Tracker not found: {path}")
        return None
    try:
        return load.excel_rows(path)
    except tracker.TrackerLayoutError as exc:
        print(f"{path.name}: {exc}. Fix the header row; no report was made.")
    except PermissionError:
        print(f"{path.name} can't be read right now (open in another program?). Close it and run again.")
    return None


def main(argv=None, sheet_ws=None) -> int:
    parser = argparse.ArgumentParser(description="Make a read-only report page of the tracker.")
    parser.add_argument("--sheet", action="store_true", help="read the Google Sheet instead of the Excel file")
    parser.add_argument("--out", type=Path, help="where to write the page (default: report.html here)")
    parser.add_argument("--no-open", action="store_true", help="don't open the page in the browser")
    parser.add_argument("--today", type=date.fromisoformat, help="YYYY-MM-DD; for tests and past weeks")
    parser.add_argument("--tracker", type=Path, help="local Excel tracker (default: local_tracker in config.yaml)")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    out = args.out or DEFAULT_OUT
    if out.suffix.lower() != ".html":  # so a mistyped --out can never overwrite the tracker
        print(f"--out must be an .html file, not {out.name}.")
        return 2
    today = args.today or date.today()
    config = apply.load_config(args.config or apply.DEFAULT_CONFIG)
    settings = load.load_settings(DEFAULT_SETTINGS)

    if args.sheet:
        jobs, source_name, excel = _sheet_jobs(config, sheet_ws), "the Google Sheet", False
    else:
        path = apply.tracker_path_for(args.tracker, config)
        jobs, source_name, excel = _excel_jobs(path), path.name, True
    if jobs is None:
        return 2

    rows = [derive.facts(job, settings, today) for job in jobs]
    out.write_text(render.page(rows, settings, today, excel=excel, source_name=source_name,
                               generated=datetime.now()), encoding="utf-8")
    print(f"Report written to {out}")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # company names like Nestlé on a cp1252 console
    sys.exit(main())
