"""Milestone 7: find.py search and Outcome update, on the fake tracker and a fake worksheet."""
from datetime import date, datetime

from openpyxl import load_workbook
from rich.console import Console

import find
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


# ---------- selection, status, note, table (find.py) ----------

def test_parse_selection():
    assert find.parse_selection("1,3", 5) == [1, 3]
    assert find.parse_selection("2-4", 5) == [2, 3, 4]
    assert find.parse_selection(" 3 , 1-2, 3 ", 5) == [1, 2, 3]
    assert find.parse_selection("all", 3) == [1, 2, 3]
    assert find.parse_selection("ALL", 2) == [1, 2]
    for bad in ("0", "6", "4-2", "1-9", "x", "1,,2", "1-", "-2", "1.5", "all,1"):
        assert find.parse_selection(bad, 5) is None, bad


def test_parse_status_by_number_or_name():
    assert find.parse_status("2") == "Rejected"
    assert find.parse_status("4") == "Interview"
    assert find.parse_status(" online assessment ") == "Online Assessment"
    assert find.parse_status("INTERVIEW") == "Interview"
    for bad in ("", "0", "5", "offer", "rej"):
        assert find.parse_status(bad) is None, bad


def test_format_note_appends_with_date():
    day = date(2026, 10, 21)
    assert find.format_note(day, "Phone screen", "") == "10/21/2026 Phone screen"
    assert find.format_note(day, "Phone screen", None) == "10/21/2026 Phone screen"
    assert find.format_note(day, " Phone screen ", "Same day rejection") == \
        "Same day rejection | 10/21/2026 Phone screen"
    assert find.format_note(day, "  ", "kept") == "kept"


def test_rows_grouped_by_company_newest_first():
    rows = [
        row(10, "Acme", "Old role", date="8/21/2026"),
        row(11, "Beta", "Newest overall", date="10/20/2026"),
        row(12, "Acme Inc.", "New role", date=datetime(2026, 10, 18)),
        row(13, "acme", "Middle role", date="10/2/2026"),
        row(14, "Acme", "No date", date=""),
        row(15, "Gamma", "Only undated", date="n/a"),
    ]
    assert [r for r, _, _ in find.order_rows(rows)] == [11, 12, 13, 10, 14, 15]


def show(hits, text="acme"):
    console = Console(record=True, width=200, color_system=None)
    shown = find.show_table(console, hits, text)
    return shown, console.export_text()


def test_table_shows_rows_and_domain():
    hits = [
        row(640, "Acme", "DevOps Engineer", SP_URL, outcome="Rejected", remarks="Same day rejection",
            date="8/21/2026"),
        row(912, "Acme", "Software Engineer I", ACME_URL, date=datetime(2026, 10, 18)),
    ]
    shown, out = show(hits)
    assert [r for r, _, _ in shown] == [912, 640]
    lines = out.splitlines()
    assert lines[0] == '2 jobs found for "acme"'
    first = next(line for line in lines if "912" in line).split()
    assert first == ["1", "912", "10/18/2026", "Acme", "Software", "Engineer", "I", "Applied",
                     "acme.wd5.myworkdayjobs.com"]
    second = next(line for line in lines if "640" in line)
    assert "Same day rejection" in second and "job-boards.greenhouse.io" in second
    assert second.split()[:3] == ["2", "640", "08/21/2026"]


def test_table_link_text_without_url_and_one_job_wording():
    shown, out = show([row(4, "Zenith Labs", "Developer", "click here")], "zenith")
    assert out.splitlines()[0] == '1 job found for "zenith"'
    assert "click here" in out


def test_table_capped_at_50():
    hits = [row(r, "Acme", f"Role {r}") for r in range(2, 57)]
    shown, out = show(hits)
    assert len(shown) == 50
    assert "5 more not shown; narrow the search." in out


def test_no_matches_message():
    shown, out = show([], "acme")
    assert shown == [] and out.strip() == 'No jobs found for "acme".'
