"""Pull changes from the Google Sheet into the local Excel tracker.

    python pull_sheet.py [--tracker PATH] [--config PATH] [--dry-run] [--yes]

Reads every row from the configured Google Sheet, compares with the local
Excel tracker, displays all differences at once, and merges: edits to existing
rows are applied (Enter or 'y' accepts all; 'e' allows selecting specific conflicts),
and rows only in the Sheet are appended. A backup is made before any write.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from copy import copy
from pathlib import Path

from openpyxl import load_workbook

import apply
import sheet_tracker
import tracker
from sheet_tracker import SheetMismatch, SheetUnavailable

HERE = Path(__file__).resolve().parent


# ---------- normalisation for comparison ----------

def _norm_date(value) -> str:
    """A date value (date object or string like '6/20/2026') as 'YYYY-MM-DD' for comparison."""
    parsed = tracker.parse_date(value)
    if parsed is not None:
        return parsed.isoformat()
    return ""


def _norm_field(field: str, value) -> str:
    """Comparable form of a cell value, aware of date and URL formulas."""
    if field == "URL":
        m = sheet_tracker.HYPERLINK_TARGET.match(str(value or ""))
        if m:
            value = m.group(1).replace('""', '"')
        return tracker.normalize_url(str(value or ""))
    parsed = tracker.parse_date(value)
    if parsed is not None:
        return parsed.isoformat()
    return " ".join(str(value or "").strip().split()).casefold()


def _display(value) -> str:
    """Human-readable form of a cell value."""
    if value is None:
        return "(empty)"
    text = str(value).strip()
    return text if text else "(empty)"


# ---------- indexing ----------

def _index_by_url(rows):
    """normalized-URL → item, only where the URL points to exactly one row."""
    by_url: dict[str, list] = defaultdict(list)
    for item in rows:
        _, _, urls = item
        seen_norms = set()
        for u in urls:
            norm = tracker.normalize_url(u)
            if norm and norm not in seen_norms:
                seen_norms.add(norm)
                by_url[norm].append(item)
    return {u: items[0] for u, items in by_url.items() if len(items) == 1}


def _norm_pair(values: dict) -> tuple[str, str]:
    return (
        " ".join(str(values.get("Company") or "").casefold().split()),
        " ".join(str(values.get("Position") or "").casefold().split()),
    )


def _index_by_pair(rows):
    """(norm_company, norm_position) → item, only for unique pairs."""
    by_pair: dict[tuple, list] = defaultdict(list)
    for item in rows:
        _, values, _ = item
        key = _norm_pair(values)
        if key != ("", ""):
            by_pair[key].append(item)
    return {k: items[0] for k, items in by_pair.items() if len(items) == 1}


# ---------- matching and diffing ----------

def find_match(sheet_item, e_rows_by_row, excel_url_index, excel_pair_index):
    """Find the Excel row that matches a Sheet row. Returns (excel_row, excel_values) or None."""
    s_row, s_values, s_urls = sheet_item

    # 1. Hinted row: check if the exact same row number in Excel holds this job
    if s_row in e_rows_by_row:
        er, ev, e_urls = e_rows_by_row[s_row]
        s_norm_urls = {tracker.normalize_url(u) for u in s_urls if tracker.normalize_url(u)}
        e_norm_urls = {tracker.normalize_url(u) for u in e_urls if tracker.normalize_url(u)}
        same_url = bool(s_norm_urls & e_norm_urls)
        same_pair = _norm_pair(s_values) == _norm_pair(ev) and _norm_pair(s_values) != ("", "")
        if same_url or same_pair:
            return er, ev

    # 2. Unique URL match across the whole tracker
    for u in s_urls:
        norm = tracker.normalize_url(u)
        if norm and norm in excel_url_index:
            er, ev, _ = excel_url_index[norm]
            return er, ev

    # 3. Unique Company + Position match across the whole tracker
    key = _norm_pair(s_values)
    if key != ("", "") and key in excel_pair_index:
        er, ev, _ = excel_pair_index[key]
        return er, ev

    return None


def diff_fields(sheet_values: dict, excel_values: dict) -> dict[str, tuple]:
    """Return {field: (excel_val, sheet_val)} for fields that differ."""
    diffs = {}
    for f in tracker.FIELDS:
        sv = _norm_field(f, sheet_values.get(f, ""))
        ev = _norm_field(f, excel_values.get(f, ""))
        if sv != ev:
            diffs[f] = (excel_values.get(f, ""), sheet_values.get(f, ""))
    return diffs


# ---------- conflict selection parsing ----------

def parse_selection(text: str, n: int) -> list[int] | None:
    """'1,3' / '2-4' / 'all' -> sorted row numbers in 1..n; None if invalid."""
    text = text.strip().lower()
    if not text or text == "all":
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


# ---------- batch review and prompt ----------

def show_summary(conflicts: list[tuple[int, str, str, dict, dict]], new_rows: list[dict]) -> None:
    """Print all conflicts and new rows at once."""
    if conflicts:
        print(f"\nDifferences ({len(conflicts)} row(s) differ from Sheet):")
        for idx, (e_row, company, position, diffs, _) in enumerate(conflicts, start=1):
            print(f"  [{idx}] Row {e_row}: {company} - {position}")
            for f, (ev, sv) in diffs.items():
                print(f"      {f:22s}  Excel = {_display(ev):28s}  |  Sheet = {_display(sv)}")

    if new_rows:
        print(f"\nNew rows in Google Sheet ({len(new_rows)} to add to Excel):")
        for idx, s_values in enumerate(new_rows, start=1):
            c = s_values.get("Company", "?")
            p = s_values.get("Position", "?")
            u = s_values.get("URL", "")
            print(f"  [+{idx}] {c} - {p} ({u})")


def batch_review(
    conflicts: list[tuple[int, str, str, dict, dict]],
    new_rows: list[dict],
    input_fn,
    auto_accept: bool
) -> tuple[list[tuple[int, str, str, dict, dict]], list[dict]]:
    """Present all conflicts at once and return (chosen_conflicts, chosen_new_rows)."""
    show_summary(conflicts, new_rows)

    if auto_accept:
        return conflicts, new_rows

    prompt = "\nApply all changes to Excel? [Enter / y = yes (all), e = select conflicts, n = cancel]: "
    while True:
        ans = input_fn(prompt).strip().lower()
        if ans in ("", "y", "yes"):
            return conflicts, new_rows
        if ans in ("n", "no"):
            print("Cancelled. No changes made.")
            return [], []
        if ans == "e":
            if not conflicts:
                print("No conflicts to select from (only new rows). Press Enter to apply new rows or n to cancel.")
                continue
            while True:
                sel_prompt = f"Enter conflict numbers to apply (1-{len(conflicts)}, all; Enter = all, c = cancel): "
                sel_str = input_fn(sel_prompt).strip().lower()
                if sel_str in ("c", "cancel"):
                    print("Cancelled. No changes made.")
                    return [], []
                picked_indices = parse_selection(sel_str, len(conflicts))
                if picked_indices is not None:
                    chosen_conflicts = [conflicts[i - 1] for i in picked_indices]
                    return chosen_conflicts, new_rows
                print(f"Invalid input. Enter numbers between 1 and {len(conflicts)}, e.g. '1, 3-4' or 'all'.")
        print("Please press Enter, y, e, or n.")


# ---------- pull ----------

def pull(config: dict, tracker_path: Path, *, input_fn=input,
         dry_run: bool = False, auto_accept: bool = False, ws=None) -> tuple[int, int]:
    """Read the Sheet, compare with Excel, merge. Returns (updates_count, new_count)."""
    if ws is None:
        ws = sheet_tracker.open_sheet(
            config["sheet_id"], config.get("sheet_tab", "Sheet1"),
            apply._resolve(config.get("google_key", "google-key.json")))

    print("Reading Google Sheet...")
    s_rows = sheet_tracker.read_rows(ws)
    print(f"  {len(s_rows)} rows in the Sheet.")

    print(f"Reading {tracker_path.name}...")
    e_rows = tracker.read_rows(tracker_path)
    print(f"  {len(e_rows)} rows in Excel.")

    e_rows_by_row = {item[0]: item for item in e_rows}
    excel_url_idx = _index_by_url(e_rows)
    excel_pair_idx = _index_by_pair(e_rows)

    conflicts: list[tuple[int, str, str, dict, dict]] = []  # (e_row, company, position, diffs, s_values)
    new_rows: list[dict] = []

    for s_item in s_rows:
        _, s_values, _ = s_item
        match = find_match(s_item, e_rows_by_row, excel_url_idx, excel_pair_idx)
        if match is None:
            new_rows.append(s_values)
            continue
        e_row, e_values = match
        diffs = diff_fields(s_values, e_values)
        if diffs:
            conflicts.append((
                e_row,
                str(s_values.get("Company", "?")),
                str(s_values.get("Position", "?")),
                diffs,
                s_values,
            ))

    if not conflicts and not new_rows:
        print("\nEverything is in sync. Local Excel already matches Google Sheet.")
        return 0, 0

    if dry_run:
        show_summary(conflicts, new_rows)
        print(f"\nDry run: {len(conflicts)} row(s) to update, {len(new_rows)} new row(s) to add.")
        return len(conflicts), len(new_rows)

    chosen_conflicts, chosen_new_rows = batch_review(
        conflicts, new_rows, input_fn, auto_accept)

    if not chosen_conflicts and not chosen_new_rows:
        return 0, 0

    # ---------- write ----------
    tracker.backup(tracker_path)
    wb = load_workbook(tracker_path)
    ws_xl = wb[tracker.SHEET]
    cols = tracker.column_map(next(ws_xl.iter_rows(max_row=1, values_only=True), ()))

    for e_row, _, _, diffs, s_values in chosen_conflicts:
        for field in diffs:
            cell = ws_xl.cell(e_row, cols[field])
            val = s_values.get(field, "")
            if field in tracker.DATE_FIELDS:
                parsed = tracker.parse_date(val)
                cell.value = parsed if parsed else (val or None)
                cell.number_format = tracker.DATE_FORMAT
            elif field == "URL":
                m = sheet_tracker.HYPERLINK_TARGET.match(str(val or ""))
                target = m.group(1).replace('""', '"') if m else val
                cell.value = target or None
                if target:
                    cell.hyperlink = target
            else:
                cell.value = val if val else None

    for s_values in chosen_new_rows:
        r = tracker.next_row(ws_xl, cols["Company"])
        tracker._extend_table(ws_xl, r, cols)
        if r > 2:
            for col in range(1, max(cols.values()) + 1):
                ws_xl.cell(r, col)._style = copy(ws_xl.cell(r - 1, col)._style)
        for field in tracker.FIELDS:
            val = s_values.get(field, "")
            cell = ws_xl.cell(r, cols[field])
            if field in tracker.DATE_FIELDS:
                parsed = tracker.parse_date(val)
                cell.value = parsed if parsed else (val or None)
                cell.number_format = tracker.DATE_FORMAT
            else:
                cell.value = val or None
        url_val = s_values.get("URL", "")
        if url_val:
            m = sheet_tracker.HYPERLINK_TARGET.match(str(url_val))
            target = m.group(1).replace('""', '"') if m else url_val
            ws_xl.cell(r, cols["URL"]).hyperlink = target

    tracker._save(wb, tracker_path)
    wb.close()

    print(f"\nDone: {len(chosen_conflicts)} row(s) updated, {len(chosen_new_rows)} new row(s) added to {tracker_path.name}.")
    return len(chosen_conflicts), len(chosen_new_rows)


# ---------- CLI ----------

def main(argv=None, input_fn=input, ws=None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull changes from the Google Sheet into the local Excel tracker.")
    parser.add_argument("--tracker", type=Path, help="local Excel tracker")
    parser.add_argument("--config", type=Path, help="config.yaml path")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change, don't write")
    parser.add_argument("--yes", action="store_true",
                        help="accept all Sheet values without prompting")
    args = parser.parse_args(argv)

    config = apply.load_config(args.config or apply.DEFAULT_CONFIG)
    if not config.get("sheet_id"):
        print("No sheet_id in config.yaml.  Nothing to pull.")
        return 1
    tracker_path = apply.tracker_path_for(args.tracker, config)
    if not tracker_path.exists():
        print(f"Tracker not found: {tracker_path}")
        return 1

    try:
        pull(config, tracker_path, input_fn=input_fn,
             dry_run=args.dry_run, auto_accept=args.yes, ws=ws)
    except SheetUnavailable as exc:
        print(f"Google Sheet unavailable: {exc}")
        return 1
    except SheetMismatch as exc:
        print(f"Google Sheet layout problem: {exc}")
        return 1
    except tracker.TrackerLocked:
        print(f"{tracker_path.name} is open in Excel.  Close it and try again.")
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
