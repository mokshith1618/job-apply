"""Milestone 7: find.py search and Outcome update, on the fake tracker and a fake worksheet."""
from datetime import date, datetime

import pytest
import requests
from openpyxl import load_workbook
from rich.console import Console

import find
import sheet_tracker
import tracker
from conftest import KNOWN_COMPANY, KNOWN_POSITION, KNOWN_ROW, KNOWN_URL
from fake_sheet import HEADER, FakeWorksheet
from sheet_tracker import SheetMismatch, SheetUnavailable

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
    assert tracker.format_note(day, "Phone screen", "") == "10/21/2026 Phone screen"
    assert tracker.format_note(day, "Phone screen", None) == "10/21/2026 Phone screen"
    assert tracker.format_note(day, " Phone screen ", "Same day rejection") == \
        "Same day rejection | 10/21/2026 Phone screen"
    assert tracker.format_note(day, "  ", "kept") == "kept"


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


# ---------- Excel update ----------

NOTE_DAY = date(2026, 10, 21)


def update(row_hint=KNOWN_ROW, outcome="Rejected", note="", urls=(KNOWN_URL,), company=KNOWN_COMPANY,
           position=KNOWN_POSITION, applied=""):
    return tracker.OutcomeUpdate(company=company, position=position, urls=list(urls), applied=applied,
                                 row=row_hint, outcome=outcome, note=note, noted_on=NOTE_DAY)


def cells(path, *refs):
    ws = load_workbook(path)["Sheet1"]
    return [ws[ref].value for ref in refs]


def test_outcome_written_and_remark_appended_not_overwritten(dup_tracker):
    wb = load_workbook(dup_tracker)
    wb["Sheet1"].cell(KNOWN_ROW, 7, "Recruiter call")
    wb.save(dup_tracker)
    written, missing = tracker.update_outcome(dup_tracker, [update(note="Phone screen")],
                                              dup_tracker.parent / "backups")
    assert [r for r, _ in written] == [KNOWN_ROW] and missing == []
    assert cells(dup_tracker, f"F{KNOWN_ROW}", f"G{KNOWN_ROW}") == \
        ["Rejected", "Recruiter call | 10/21/2026 Phone screen"]
    assert len(list((dup_tracker.parent / "backups").glob("tracker-*.xlsx"))) == 1


def test_no_note_leaves_remarks_alone(dup_tracker):
    tracker.update_outcome(dup_tracker, [update(outcome="Online Assessment")], dup_tracker.parent / "b")
    assert cells(dup_tracker, f"F{KNOWN_ROW}", f"G{KNOWN_ROW}") == ["Online Assessment", None]


def outcome_list(path):
    ws = load_workbook(path)["Sheet1"]
    (dv,) = [dv for dv in ws.data_validations.dataValidation if dv.type == "list"]
    return dv.formula1, str(dv.sqref)


def test_interview_added_to_the_dropdown(dup_tracker):
    assert outcome_list(dup_tracker)[0] == '"Applied,Rejected,Online Assessment"'
    tracker.update_outcome(dup_tracker, [update(outcome="Interview")], dup_tracker.parent / "b")
    assert outcome_list(dup_tracker) == ('"Applied,Rejected,Online Assessment,Interview"', "F2:F1000")
    assert cells(dup_tracker, f"F{KNOWN_ROW}") == ["Interview"]


def test_interview_added_when_apply_writes_a_row(tracker_file):
    tracker.append_row(tracker_file, tracker.TrackerRow("Acme", "SWE", "https://x.com/1", "Posted today-Other",
                                                        NOTE_DAY), tracker_file.parent / "b")
    assert outcome_list(tracker_file)[0] == '"Applied,Rejected,Online Assessment,Interview"'


def test_row_found_again_when_the_hint_is_stale(dup_tracker):
    written, missing = tracker.update_outcome(dup_tracker, [update(row_hint=300)], dup_tracker.parent / "b")
    assert [r for r, _ in written] == [KNOWN_ROW] and missing == []
    assert cells(dup_tracker, "F300", f"F{KNOWN_ROW}") == ["Applied", "Rejected"]


def test_row_without_url_found_by_company_position_and_date(tracker_file):
    wb = load_workbook(tracker_file)
    ws = wb["Sheet1"]
    for r, day in ((50, datetime(2026, 9, 1)), (60, datetime(2026, 10, 1))):
        ws.cell(r, 1, "Zenith")
        ws.cell(r, 2, "Developer")
        ws.cell(r, 3).value = None
        ws.cell(r, 3).hyperlink = None
        ws.cell(r, 5, day)
    wb.save(tracker_file)
    u = update(row_hint=2, urls=(), company="Zenith", position="Developer", applied="2026-10-01")
    written, missing = tracker.update_outcome(tracker_file, [u], tracker_file.parent / "b")
    assert [r for r, _ in written] == [60]
    assert cells(tracker_file, "F50", "F60") == ["Applied", "Rejected"]


def test_ambiguous_or_missing_row_not_written(dup_tracker):
    wb = load_workbook(dup_tracker)
    ws = wb["Sheet1"]
    ws.cell(KNOWN_ROW + 1, 1, KNOWN_COMPANY)
    ws.cell(KNOWN_ROW + 1, 2, KNOWN_POSITION)
    ws.cell(KNOWN_ROW + 1, 3, KNOWN_URL).hyperlink = KNOWN_URL
    ws.cell(KNOWN_ROW + 1, 5, ws.cell(KNOWN_ROW, 5).value)
    wb.save(dup_tracker)
    before = dup_tracker.read_bytes()
    gone = update(urls=("https://jobs.lever.co/nobody/1",), company="Nobody", position="None")
    twins = update(row_hint=5)  # two rows with this job and no way to tell them apart
    written, missing = tracker.update_outcome(dup_tracker, [gone, twins], dup_tracker.parent / "backups")
    assert written == [] and missing == [gone, twins]
    assert dup_tracker.read_bytes() == before and not (dup_tracker.parent / "backups").exists()


def test_locked_excel_keeps_update_pending_until_next_flush(dup_tracker, monkeypatch):
    pending = tracker.pending_updates_path_for(dup_tracker)
    tracker.save_pending_updates(pending, [update(note="Phone screen")])

    def locked(wb, path):
        raise tracker.TrackerLocked("open in Excel")

    real_save = tracker._save
    monkeypatch.setattr(tracker, "_save", locked)
    with pytest.raises(tracker.TrackerLocked):
        tracker.flush_pending_updates(dup_tracker, backup_dir=dup_tracker.parent / "b")
    assert tracker.load_pending_updates(pending) == [update(note="Phone screen")]
    assert cells(dup_tracker, f"F{KNOWN_ROW}") == ["Applied"]

    monkeypatch.setattr(tracker, "_save", real_save)
    written, missing = tracker.flush_pending_updates(dup_tracker, backup_dir=dup_tracker.parent / "b")
    assert [r for r, _ in written] == [KNOWN_ROW] and not pending.exists()
    assert cells(dup_tracker, f"F{KNOWN_ROW}", f"G{KNOWN_ROW}") == ["Rejected", "10/21/2026 Phone screen"]


# ---------- Sheet update ----------

LIST_RULE = {"condition": {"type": "ONE_OF_LIST", "values": [
    {"userEnteredValue": "Applied"}, {"userEnteredValue": "Rejected"}, {"userEnteredValue": "Online Assessment"}]},
    "strict": True, "showCustomUi": True}


def sheet(**kwargs):
    return FakeWorksheet([
        HEADER,
        ["Acme Inc.", "Cloud Engineer", "click here", "Posted today-Other", "10/1/2026", "Applied", "OA sent"],
        ["S&P Global", "Software Engineer", SP_URL, "Posted today-Other", "9/1/2026", "Applied"],
    ], formulas={2: f'=HYPERLINK("{ACME_URL}", "click here")'}, **kwargs)


def sheet_update(ws, r, **kwargs):
    (found_row,) = [x for x in sheet_tracker.read_rows(ws) if x[0] == r]
    return tracker.OutcomeUpdate.for_row(*found_row, outcome=kwargs.get("outcome", "Rejected"),
                                         note=kwargs.get("note", ""), noted_on=NOTE_DAY)


def test_sheet_outcome_and_remark_written(tmp_path):
    ws = sheet()
    updates = [sheet_update(ws, 2, note="=Phone screen"), sheet_update(ws, 3, outcome="Interview")]
    written, missing = sheet_tracker.update_outcome(ws, updates, tmp_path / "backups")
    assert [r for r, _ in written] == [2, 3] and missing == []
    assert ws.updates == [("F2:G2", [["Rejected", "OA sent | 10/21/2026 =Phone screen"]]),
                          ("F3", [["Interview"]])]
    assert len(list((tmp_path / "backups").glob("sheet-*.csv"))) == 1


def test_sheet_remark_that_looks_like_a_formula_is_kept_as_text(tmp_path):
    ws = sheet()
    ws.values[1][6] = ""
    sheet_tracker.update_outcome(ws, [sheet_update(ws, 2, note="+1 recruiter")], tmp_path)
    assert ws.updates == [("F2:G2", [["Rejected", "10/21/2026 +1 recruiter"]])]
    assert sheet_tracker._text("=x") == "'=x"


def test_sheet_row_found_again_after_a_shift(tmp_path):
    ws = sheet()
    u = sheet_update(ws, 3)
    ws.values.insert(1, ["New Co", "New role", "https://x.com/9", "", "10/20/2026", "Applied"])
    written, _ = sheet_tracker.update_outcome(ws, [u], tmp_path)
    assert [r for r, _ in written] == [4] and ws.values[3][5] == "Rejected"


def test_sheet_dropdown_gets_interview(tmp_path):
    ws = sheet(validation=LIST_RULE)
    sheet_tracker.update_outcome(ws, [sheet_update(ws, 2)], tmp_path)
    (params,) = ws.spreadsheet.metadata_params
    assert params["ranges"] == "'Sheet1'!F2"
    (req,) = [q["setDataValidation"] for q in ws.spreadsheet.requests]
    assert req["range"] == {"sheetId": 7, "startRowIndex": 1, "endRowIndex": 1000,
                            "startColumnIndex": 5, "endColumnIndex": 6}
    assert [v["userEnteredValue"] for v in req["rule"]["condition"]["values"]] == list(tracker.OUTCOMES)
    assert req["rule"]["strict"] is True and req["rule"]["showCustomUi"] is True


def test_sheet_dropdown_left_alone_when_complete_missing_or_not_a_list(tmp_path, capsys):
    complete = {**LIST_RULE, "condition": {"type": "ONE_OF_LIST", "values": [
        {"userEnteredValue": o} for o in tracker.OUTCOMES]}}
    by_range = {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Lists!A1:A3"}]}}
    for rule in (complete, None, by_range):
        ws = sheet(validation=rule)
        sheet_tracker.update_outcome(ws, [sheet_update(ws, 2)], tmp_path)
        assert ws.spreadsheet.requests == []
    assert "add Interview to it by hand" in capsys.readouterr().out


def test_sheet_missing_row_and_wrong_header_write_nothing(tmp_path):
    ws = sheet()
    gone = update(urls=("https://jobs.lever.co/nobody/1",), company="Nobody", position="None")
    assert sheet_tracker.update_outcome(ws, [gone], tmp_path / "b") == ([], [gone])
    assert ws.updates == [] and not (tmp_path / "b").exists()
    ws = FakeWorksheet([["Name", "Email"], ["x", "y"]])
    with pytest.raises(SheetMismatch):
        sheet_tracker.update_outcome(ws, [gone], tmp_path / "b")
    assert ws.updates == []


def test_sheet_offline_is_sheet_unavailable(tmp_path):
    ws = sheet()
    u = sheet_update(ws, 2)
    ws.fail = requests.exceptions.ConnectionError("offline")
    with pytest.raises(SheetUnavailable):
        sheet_tracker.update_outcome(ws, [u], tmp_path)
