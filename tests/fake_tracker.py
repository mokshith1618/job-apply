"""A made-up tracker with the same layout as "Job Application Tracker.xlsx" (see SPEC.md).

Tests build it in a temp folder, so they need no private file and never see real applications.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

HEADERS = ["Company", "Position", "URL", "Posted date/ Source", "Date", "Outcome", "Stage",
           "Remarks", "Experience", "Key Skills"]
LAST_ROW = 897  # last row with a Company value, so the next row is 898 like the real file
TABLE_END = 1000
LINK_FONT = Font(color="FF0563C1", underline="single")
OUTCOMES = '"Applied,Rejected,Awaiting reply"'
STAGES = '"Online Assessment,Interview,Initial Screening"'  # the real file's order
DATE_CHECK = 'OR(NOT(ISERROR(DATEVALUE(E2))), AND(ISNUMBER(E2), LEFT(CELL("format", E2))="D"))'


def make_tracker(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(HEADERS)
    first_day = datetime(2025, 6, 1)
    for r in range(2, LAST_ROW + 1):
        url = f"https://example.com/jobs/{r}"
        ws.append([f"Company {r}", f"Role {r}", url, "Posted today-Other",
                   first_day + timedelta(days=r % 400), "Applied"])
        ws.cell(r, 3).hyperlink = url
        ws.cell(r, 3).font = LINK_FONT
        ws.cell(r, 5).number_format = "M/d/yyyy"
    ws.freeze_panes = "A2"

    table = Table(displayName="Table1", ref=f"A1:J{TABLE_END}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(table)

    outcome = DataValidation(type="list", formula1=OUTCOMES, allow_blank=True)
    outcome.add(f"F2:F{TABLE_END}")
    stage = DataValidation(type="list", formula1=STAGES, allow_blank=True)
    stage.add(f"G2:G{TABLE_END}")
    date_check = DataValidation(type="custom", formula1=DATE_CHECK, allow_blank=True)
    date_check.add(f"E2:E{TABLE_END}")
    ws.add_data_validation(outcome)
    ws.add_data_validation(stage)
    ws.add_data_validation(date_check)

    wb.save(path)
    return path
