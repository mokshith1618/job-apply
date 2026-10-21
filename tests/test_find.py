"""Milestone 7: find.py search and Outcome update, on the fake tracker and a fake worksheet."""
from datetime import datetime

from openpyxl import load_workbook

import sheet_tracker
import tracker
from fake_sheet import HEADER, FakeWorksheet

ACME_URL = "https://acme.wd5.myworkdayjobs.com/External/job/Austin/Cloud-Engineer_R123"
SP_URL = "https://job-boards.greenhouse.io/spglobal/jobs/555"
LEVER_URL = "https://jobs.lever.co/zenith/abc-123"


def row(r, company, position, url="", outcome="Applied", remarks="", date="10/1/2026", target=None):
    values = [company, position, url, "Posted today-Other", date, outcome, remarks]
    urls = [u for u in (url, target) if u]
    return (r, values, urls)


SAMPLE = [
    row(2, "Acme Inc.", "Cloud Engineer", ACME_URL),
    row(3, "S&P Global", "Software Engineer", SP_URL),
    row(4, "Zenith Labs", "Acme Integrations Developer", "click here", target=LEVER_URL),
    row(5, "Other Co", "Data Engineer", "https://example.com/jobs/5"),
]


def found(text, rows=SAMPLE):
    return [r for r, _, _ in tracker.search_rows(rows, text)]


# ---------- search ----------

def test_search_key_cleans_case_punctuation_and_suffixes():
    assert tracker.search_key("  ACME, Inc. ") == "acme"
    assert tracker.search_key("S&P Global") == "s p global"
    assert tracker.search_key("Foo Bar LLC") == "foo bar"
    assert tracker.search_key("Co") == "co"  # a name that is only a suffix stays
    assert tracker.search_key("Costco Wholesale Corp") == "costco wholesale"


def test_match_by_company_ignoring_case_and_suffix():
    assert found("acme") == [2, 4]  # row 4: "Acme" in the position
    assert found("ACME INC") == [2, 4]
    assert found("acme, inc.") == [2, 4]


def test_match_by_position():
    assert found("data engineer") == [5]
    assert found("integrations") == [4]


def test_match_with_punctuation():
    assert found("s&p global") == [3]
    assert found("S & P") == [3]


def test_match_by_url_text_and_hyperlink_target():
    assert found("myworkdayjobs") == [2]
    assert found("acme.wd5") == [2]
    assert found("jobs.lever.co/zenith") == [4]  # only in the hyperlink target
    assert found("spglobal") == [3]


def test_no_match():
    assert found("globex") == []
    assert found("   ") == []


def test_excel_read_rows_has_remarks_and_hyperlink_targets(tracker_file):
    wb = load_workbook(tracker_file)
    ws = wb["Sheet1"]
    ws.cell(10, 1, "Acme Inc.")
    ws.cell(10, 3, "click here").hyperlink = ACME_URL
    ws.cell(10, 7, "Recruiter call")
    for col in (1, 3):  # row 11: no Company, no URL (ws.cell(r, c, None) would leave the value)
        ws.cell(11, col).value = None
    ws.cell(11, 3).hyperlink = None
    wb.save(tracker_file)

    rows = tracker.read_rows(tracker_file)
    by_row = {r: (values, urls) for r, values, urls in rows}
    values, urls = by_row[10]
    assert values[0] == "Acme Inc." and values[6] == "Recruiter call" and len(values) == 7
    assert urls == ["click here", ACME_URL]
    assert isinstance(values[4], datetime)
    assert 11 not in by_row  # no Company and no URL: not a job row
    assert [r for r, _, _ in tracker.search_rows(rows, "acme")] == [10]


def test_sheet_read_rows_has_remarks_and_hyperlink_targets():
    ws = FakeWorksheet([
        HEADER,
        ["Acme Inc.", "Cloud Engineer", "click here", "Posted today-Other", "10/1/2026", "Applied", "OA sent"],
        ["", "", "", "", "", "", "a remark with no company"],
        ["S&P Global", "Software Engineer", SP_URL, "Posted today-Other", "9/1/2026", "Rejected"],
    ], formulas={2: f'=HYPERLINK("{ACME_URL}", "click here")'})
    rows = sheet_tracker.read_rows(ws)
    assert [r for r, _, _ in rows] == [2, 4]
    assert rows[0][1][6] == "OA sent" and rows[0][2] == ["click here", ACME_URL]
    assert rows[1][1][6] == ""  # short rows are padded to A..G
    assert [r for r, _, _ in tracker.search_rows(rows, "myworkdayjobs")] == [2]
