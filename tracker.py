"""Excel tracker: duplicate check and row writing.

Layout (see SPEC.md): Sheet1, table Table1, header on row 1, columns
A Company | B Position | C URL | D Posted date/ Source | E Date | F Outcome | G-I left empty.
"""
from __future__ import annotations

import json
import os
import shutil
from copy import copy
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.worksheet.cell_range import MultiCellRange

SHEET = "Sheet1"
TABLE = "Table1"
DATE_FORMAT = "M/d/yyyy"
OUTCOME = "Applied"
LAST_COL = 9  # A..I
TABLE_GROWTH = 100  # rows added to Table1 and the E/F validations when the table is full
TRACKING_PARAMS = {"source", "gh_src", "lever-source", "lever-origin"}  # plus every utm_*
JOB_PAGE_SUFFIXES = ("/apply", "/application")  # Lever / Ashby form pages = same job


class TrackerLocked(Exception):
    """The tracker file can't be written, almost always because it is open in Excel."""


@dataclass
class TrackerRow:
    company: str
    position: str
    url: str
    posted: str  # column D text, e.g. "Posted today-Tsenta"
    applied_on: date

    def to_json(self) -> dict:
        d = asdict(self)
        d["applied_on"] = self.applied_on.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict) -> "TrackerRow":
        return cls(**{**d, "applied_on": date.fromisoformat(d["applied_on"])})


# ---------- duplicate check ----------

def normalize_url(url: str) -> str:
    """Comparable form of a job URL: no scheme, www, fragment, trailing slash or tracking params."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    for suffix in JOB_PAGE_SUFFIXES:
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)]
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in TRACKING_PARAMS)
    )
    return f"{host}{path}" + (f"?{urlencode(query)}" if query else "")


def _norm_text(value) -> str:
    return " ".join(str(value).casefold().split()) if value else ""


def match_rows(rows, url: str | None = None, company: str | None = None,
               position: str | None = None) -> list[tuple[int, list]]:
    """Pick duplicates from `rows` = [(row number, A..F values, urls in C)]. -> [(row, A..F values)]

    A row matches if one of its URLs matches `url`, or its company AND position both match.
    """
    want_url = normalize_url(url) if url else None
    want_pair = (_norm_text(company), _norm_text(position)) if company and position else None
    hits = []
    for r, values, urls in rows:
        url_hit = want_url is not None and any(normalize_url(u) == want_url for u in urls)
        pair_hit = want_pair is not None and (_norm_text(values[0]), _norm_text(values[1])) == want_pair
        if url_hit or pair_hit:
            hits.append((r, values))
    return hits


def find_duplicates(path, url: str | None = None, company: str | None = None,
                    position: str | None = None) -> list[tuple[int, list]]:
    """Rows whose URL matches `url`, or whose company AND position both match. -> [(row, A..F values)]"""
    wb = load_workbook(path)  # not read_only: hyperlink targets are needed too
    ws = wb[SHEET]
    rows = []
    for row in ws.iter_rows(min_row=2, max_col=LAST_COL):
        a, c = row[0], row[2]
        if a.value is None and c.value is None:
            continue
        urls = [str(c.value)] if c.value else []
        if c.hyperlink is not None and c.hyperlink.target:
            urls.append(c.hyperlink.target)
        rows.append((a.row, [cell.value for cell in row[:6]], urls))
    wb.close()
    return match_rows(rows, url, company, position)


# ---------- writing ----------

def next_row(ws) -> int:
    """First row after the last row that has a Company value."""
    for r in range(ws.max_row, 1, -1):
        if ws.cell(r, 1).value not in (None, ""):
            return r + 1
    return 2


def format_posted(posted_date: date | None, source: str, today: date) -> str:
    """Column D: 'Posted today-Tsenta' or 'Posted October 8, 2026-LinkedIn'."""
    if posted_date is None:
        return source
    if posted_date == today:
        return f"Posted today-{source}"
    return f"Posted {posted_date:%B} {posted_date.day}, {posted_date.year}-{source}"


def backup(path, backup_dir=None) -> Path:
    """Copy the tracker to backups/tracker-YYYYMMDD-HHMMSS.xlsx before any write."""
    path = Path(path)
    backup_dir = Path(backup_dir) if backup_dir else path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"tracker-{stamp}.xlsx"
    n = 1
    while target.exists():  # two writes in the same second
        target = backup_dir / f"tracker-{stamp}-{n}.xlsx"
        n += 1
    shutil.copy2(path, target)
    return target


def _extend_table(ws, row: int) -> None:
    """Grow Table1 and the E/F data validations so `row` keeps the date check and Outcome dropdown."""
    table = ws.tables[TABLE]
    min_col, min_row, max_col, max_row = range_boundaries(table.ref)
    if row <= max_row:
        return
    new_end = row + TABLE_GROWTH
    table.ref = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_end}"
    if table.autoFilter is not None:
        table.autoFilter.ref = table.ref
    for dv in ws.data_validations.dataValidation:
        ranges = []
        for rng in dv.sqref.ranges:
            if rng.min_col == rng.max_col and rng.min_col in (5, 6) and rng.max_row == max_row:
                letter = get_column_letter(rng.min_col)
                ranges.append(f"{letter}{rng.min_row}:{letter}{new_end}")
            else:
                ranges.append(rng.coord)
        dv.sqref = MultiCellRange(" ".join(ranges))


def _save(wb, path: Path) -> None:
    """Save to a temp file next to the tracker, then swap it in, so a failed save can't corrupt it."""
    tmp = path.with_name(f"~{path.stem}.tmp.xlsx")
    try:
        wb.save(tmp)
        os.replace(tmp, path)
    except PermissionError as exc:
        raise TrackerLocked(str(exc)) from exc
    finally:
        if tmp.exists():
            tmp.unlink()


def append_row(path, row: TrackerRow, backup_dir=None) -> int:
    """Back up, then write `row` after the last Company row. Returns the row number written."""
    path = Path(path)
    try:
        wb = load_workbook(path)
    except PermissionError as exc:
        raise TrackerLocked(str(exc)) from exc
    ws = wb[SHEET]
    r = next_row(ws)
    _extend_table(ws, r)

    if r > 2:  # same look as the row above (hyperlink font in C, date format in E, ...)
        for col in range(1, LAST_COL + 1):
            ws.cell(r, col)._style = copy(ws.cell(r - 1, col)._style)

    ws.cell(r, 1, row.company)
    ws.cell(r, 2, row.position)
    url_cell = ws.cell(r, 3, row.url)
    url_cell.hyperlink = row.url
    ws.cell(r, 4, row.posted)
    date_cell = ws.cell(r, 5, row.applied_on)
    date_cell.number_format = DATE_FORMAT
    ws.cell(r, 6, OUTCOME)
    for col in range(7, LAST_COL + 1):
        ws.cell(r, col).value = None

    backup(path, backup_dir)
    _save(wb, path)
    return r


# ---------- pending rows (tracker open in Excel) ----------

def pending_path_for(path) -> Path:
    return Path(path).parent / "pending_rows.json"


def load_pending(pending_path) -> list[TrackerRow]:
    p = Path(pending_path)
    if not p.exists():
        return []
    return [TrackerRow.from_json(d) for d in json.loads(p.read_text(encoding="utf-8"))]


def _write_pending(pending_path, rows: list[TrackerRow]) -> None:
    p = Path(pending_path)
    if rows:
        p.write_text(json.dumps([r.to_json() for r in rows], indent=2), encoding="utf-8")
    elif p.exists():
        p.unlink()


def save_pending(pending_path, row: TrackerRow) -> None:
    _write_pending(pending_path, load_pending(pending_path) + [row])


def flush_pending(path, pending_path=None, backup_dir=None, append=None) -> list[tuple[int, TrackerRow]]:
    """Write every pending row to the tracker, removing each from the file once it's saved.

    `append(row) -> row number` writes one row; the default is append_row on the Excel file at `path`.
    Raises TrackerLocked (with the unwritten rows still pending) if the tracker is open in Excel;
    any error from `append` likewise leaves the unwritten rows pending.
    """
    pending_path = pending_path or pending_path_for(path)
    append = append or (lambda row: append_row(path, row, backup_dir))
    rows = load_pending(pending_path)
    written = []
    while rows:
        r = append(rows[0])
        written.append((r, rows.pop(0)))
        _write_pending(pending_path, rows)
    return written
