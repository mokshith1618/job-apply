"""The tracker in Google Sheets: duplicate check and row writing, same rules as tracker.py.

Access is through a Google Cloud service account (google-key.json); the Sheet is shared with
its email as Editor. Every function takes a gspread Worksheet, so tests can pass a fake one.
"""
from __future__ import annotations

import csv
import functools
import re
from datetime import datetime
from pathlib import Path

import tracker
from tracker import TrackerRow

HEADERS = ["Company", "Position", "URL", "Posted date/ Source", "Date", "Outcome", "Stage"]  # A..G, checked before writing
DATE_PATTERN = tracker.DATE_FORMAT  # M/d/yyyy, same as the Excel file
SHEET_GROWTH = 100  # rows added when the sheet has no empty row left
HYPERLINK_TARGET = re.compile(r'^=HYPERLINK\(\s*"((?:[^"]|"")*)"', re.IGNORECASE)


class SheetUnavailable(Exception):
    """The Sheet can't be reached: offline, Google error, bad key, or not shared with the service account."""


class SheetMismatch(Exception):
    """Row 1 isn't the tracker header, so this is probably the wrong sheet or tab. Nothing is written."""


def _network_errors() -> tuple:
    import gspread
    import requests
    from google.auth.exceptions import GoogleAuthError
    return gspread.exceptions.GSpreadException, GoogleAuthError, requests.exceptions.RequestException


def _guard(fn):
    """Turn any Google / network error into SheetUnavailable, so callers only handle one kind."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _network_errors() as exc:
            raise SheetUnavailable(f"{type(exc).__name__}: {exc}") from exc
    return wrapper


@_guard
def open_sheet(sheet_id: str, tab: str, key_file):
    import gspread
    key_file = Path(key_file)
    if not key_file.exists():
        raise SheetUnavailable(f"service account key not found: {key_file}")
    return gspread.service_account(filename=str(key_file)).open_by_key(sheet_id).worksheet(tab)


def _norm_header(value) -> str:
    return "".join(str(value or "").casefold().split())


def check_header(values: list[list]) -> None:
    got = (values[0] if values else [])[: len(HEADERS)]
    if [_norm_header(v) for v in got] != [_norm_header(h) for h in HEADERS]:
        raise SheetMismatch(f"row 1 should start with {HEADERS}, found {got}")


def _pad(row: list, n: int) -> list:
    return list(row[:n]) + [""] * (n - len(row))


# ---------- duplicate check ----------

def _job_rows(values: list[list], formulas: list[list]) -> list[tuple[int, list, list[str]]]:
    """[(row number, A..H display values, urls in C)] like tracker.read_rows; rows with no
    Company and no URL are skipped."""
    rows = []
    for i, raw in enumerate(values[1:], start=2):
        a_to_h = _pad(raw, tracker.REMARKS_COL)
        if not a_to_h[0] and not a_to_h[2]:
            continue
        urls = [a_to_h[2]] if a_to_h[2] else []
        formula = _pad(formulas[i - 1], 1)[0] if i - 1 < len(formulas) else ""
        m = HYPERLINK_TARGET.match(str(formula))
        if m:
            urls.append(m.group(1).replace('""', '"'))
        rows.append((i, a_to_h, urls))
    return rows


@_guard
def read_rows(ws) -> list[tuple[int, list, list[str]]]:
    """Every job row of the Sheet: [(row number, A..H display values, urls in C)]."""
    values = ws.get_all_values()
    check_header(values)
    formulas = ws.get("C:C", value_render_option="FORMULA")  # =HYPERLINK("target", "text") in C
    return _job_rows(values, formulas)


@_guard
def find_duplicates(ws, url: str | None = None, company: str | None = None,
                    position: str | None = None) -> list[tuple[int, list]]:
    """Same matching as tracker.find_duplicates, on the Sheet. -> [(row, A..G display values)]"""
    rows = [(r, values[:tracker.STAGE_COL], urls) for r, values, urls in read_rows(ws)]
    return tracker.match_rows(rows, url, company, position)


# ---------- writing ----------

def next_row(values: list[list]) -> int:
    """First row after the last row that has a Company value."""
    for i in range(len(values) - 1, 0, -1):
        if str(_pad(values[i], 1)[0]).strip():
            return i + 2
    return 2


def backup_values(values: list[list], backup_dir) -> Path:
    """Save the Sheet's values to backups/sheet-YYYYMMDD-HHMMSS.csv before any write."""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"sheet-{stamp}.csv"
    n = 1
    while target.exists():  # two writes in the same second
        target = backup_dir / f"sheet-{stamp}-{n}.csv"
        n += 1
    with open(target, "w", newline="", encoding="utf-8-sig") as f:  # -sig: Excel reads it as UTF-8
        csv.writer(f).writerows(values)
    return target


def _text(value: str) -> str:
    """Keep job-board text as text: a leading = + - @ would otherwise be read as a formula."""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def row_values(row: TrackerRow) -> list[str]:
    """A..F as typed into Sheets (USER_ENTERED). The ISO date is understood in every locale."""
    return [
        _text(row.company),
        _text(row.position),
        f"=HYPERLINK({_quote(row.url)}, {_quote(row.url)})",
        _text(row.posted),
        row.applied_on.isoformat(),
        tracker.OUTCOME,
    ]


def _format_requests(sheet_id: int, r: int) -> list[dict]:
    """Copy format + data validation (Outcome and Stage dropdowns, date check) from row r-1 to row r,
    then give E the M/d/yyyy date format. Rows here are 1-based; the API's are 0-based."""
    def grid(row):
        return {"sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                "startColumnIndex": 0, "endColumnIndex": tracker.LAST_COL}
    requests = []
    if r > 2:
        for paste in ("PASTE_FORMAT", "PASTE_DATA_VALIDATION"):
            requests.append({"copyPaste": {"source": grid(r - 1), "destination": grid(r), "pasteType": paste}})
    requests.append({"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": r - 1, "endRowIndex": r,
                  "startColumnIndex": 4, "endColumnIndex": 5},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": DATE_PATTERN}}},
        "fields": "userEnteredFormat.numberFormat",
    }})
    return requests


@_guard
def append_row(ws, row: TrackerRow, backup_dir) -> int:
    """Check the header, back up, then write `row` after the last Company row. Returns the row number."""
    values = ws.get_all_values()
    check_header(values)
    r = next_row(values)
    backup_values(values, backup_dir)
    if r > ws.row_count:
        ws.add_rows(SHEET_GROWTH)
    ws.update(values=[row_values(row)], range_name=f"A{r}:F{r}", value_input_option="USER_ENTERED")
    ws.spreadsheet.batch_update({"requests": _format_requests(ws.id, r)})
    return r


# ---------- Outcome updates (find.py) ----------

def ensure_choices(ws, col: int, name: str, wanted) -> None:
    """Make the Sheet's dropdown on column `col` (its row-2 list rule) offer every one of `wanted`.
    Only a plain list rule is changed, and only by adding; any other rule gets a note and is left alone."""
    letter = "ABCDEFGHIJ"[col - 1]
    meta = ws.spreadsheet.fetch_sheet_metadata(params={
        "ranges": f"'{ws.title}'!{letter}2", "includeGridData": "true",
        "fields": "sheets(properties.sheetId,data.rowData.values.dataValidation)"})
    try:
        cell = meta["sheets"][0]["data"][0]["rowData"][0]["values"][0]
    except (KeyError, IndexError):
        return
    rule = cell.get("dataValidation")
    if not rule:
        return
    condition = rule.get("condition", {})
    if condition.get("type") != "ONE_OF_LIST":
        print(f"Note: the Sheet's {name} dropdown is a {condition.get('type')} rule; "
              f"check it offers {', '.join(wanted)}.")
        return
    choices = [v.get("userEnteredValue", "") for v in condition.get("values", [])]
    missing = [o for o in wanted if o not in choices]
    if not missing:
        return
    new_rule = {**rule, "condition": {**condition, "values": [{"userEnteredValue": c} for c in choices + missing]}}
    ws.spreadsheet.batch_update({"requests": [{"setDataValidation": {
        "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": ws.row_count,
                  "startColumnIndex": col - 1, "endColumnIndex": col},
        "rule": new_rule,
    }}]})


def ensure_dropdowns(ws) -> None:
    ensure_choices(ws, tracker.OUTCOME_COL, "Outcome", tracker.OUTCOMES)
    ensure_choices(ws, tracker.STAGE_COL, "Stage", tracker.STAGES)


@_guard
def update_outcome(ws, updates: list[tracker.OutcomeUpdate], backup_dir) -> tuple[list, list]:
    """Same as tracker.update_outcome, on the Sheet: check the header, back up, then write Outcome
    (and Stage / Remarks when given) row by row. -> ([(row, update) written], [not found])"""
    values = ws.get_all_values()
    check_header(values)
    rows = _job_rows(values, ws.get("C:C", value_render_option="FORMULA"))
    found = [(tracker.locate(rows, u), u) for u in updates]
    written = [(r, u) for r, u in found if r is not None]
    missing = [u for r, u in found if r is None]
    if not written:
        return written, missing
    backup_values(values, backup_dir)
    current = {r: v for r, v, _ in rows}  # kept up to date, so a second update to a row builds on the first
    for r, u in written:
        stage = current[r][6] = u.stage or current[r][6]
        if u.note.strip():
            remarks = current[r][7] = tracker.format_note(u.noted_on, u.note, current[r][7])
            ws.update(values=[[u.outcome, stage, _text(remarks)]], range_name=f"F{r}:H{r}",
                      value_input_option="USER_ENTERED")
        elif u.stage:
            ws.update(values=[[u.outcome, u.stage]], range_name=f"F{r}:G{r}", value_input_option="USER_ENTERED")
        else:
            ws.update(values=[[u.outcome]], range_name=f"F{r}", value_input_option="USER_ENTERED")
    ensure_dropdowns(ws)
    return written, missing
