"""Google Sheet tracker against a fake worksheet (no network), plus apply.py runs that write to both."""
import csv
from datetime import date

import pytest
import requests
from openpyxl import load_workbook

import apply
import sheet_tracker
import tracker
from ats.common import JobDetails
from conftest import KNOWN_ROW, KNOWN_URL
from fake_sheet import HEADER, FakeWorksheet
from sheet_tracker import SheetMismatch, SheetUnavailable

TODAY = date(2026, 10, 13)
NEW_URL = "https://job-boards.greenhouse.io/acme/jobs/1234567"
LINKED_URL = "https://jobs.lever.co/linked/abc-123"


def sample_sheet(**kwargs):
    return FakeWorksheet([
        HEADER,
        ["Example Labs", "Software Engineer - Python", "https://jobs.ashbyhq.com/examplelabs/1234abcd",
         "Posted today-Tsenta", "6/20/2026", "Applied"],
        ["Linked Co", "Backend Engineer", "click here", "Posted today-LinkedIn", "7/1/2026", "Rejected"],
        ["", "", "", "", "", "", "a remark with no company"],
    ], formulas={3: f'=HYPERLINK("{LINKED_URL}", "click here")'}, **kwargs)


def new_row(**overrides):
    fields = dict(company="Acme Robotics", position="Software Engineer I", url=NEW_URL,
                  posted="Posted October 8, 2026-LinkedIn", applied_on=TODAY)
    return tracker.TrackerRow(**{**fields, **overrides})


# ---------- sheet_tracker ----------

def test_row_goes_after_last_company_with_typed_values(tmp_path):
    ws = sample_sheet()
    assert sheet_tracker.append_row(ws, new_row(), tmp_path / "backups") == 4
    assert ws.updates == [("A4:F4", [[
        "Acme Robotics", "Software Engineer I",
        f'=HYPERLINK("{NEW_URL}", "{NEW_URL}")',
        "Posted October 8, 2026-LinkedIn", "2026-10-13", "Applied",
    ]])]


def test_format_and_dropdown_copied_from_row_above_and_date_format_set(tmp_path):
    ws = sample_sheet()
    sheet_tracker.append_row(ws, new_row(), tmp_path)
    copies = [q["copyPaste"] for q in ws.spreadsheet.requests if "copyPaste" in q]
    assert [c["pasteType"] for c in copies] == ["PASTE_FORMAT", "PASTE_DATA_VALIDATION"]
    for c in copies:
        assert (c["source"]["sheetId"], c["source"]["startRowIndex"], c["destination"]["startRowIndex"]) == (7, 2, 3)
        assert c["destination"]["endColumnIndex"] == 9
    cell = ws.spreadsheet.requests[-1]["repeatCell"]
    assert cell["range"]["startRowIndex"] == 3 and cell["range"]["startColumnIndex"] == 4
    assert cell["cell"]["userEnteredFormat"]["numberFormat"] == {"type": "DATE", "pattern": "M/d/yyyy"}


def test_quotes_escaped_and_formula_text_kept_as_text():
    values = sheet_tracker.row_values(new_row(company="=IMPORTXML(1)", position="+Lead",
                                              url='https://x.com/a"b'))
    assert values[0] == "'=IMPORTXML(1)" and values[1] == "'+Lead"
    assert values[2] == '=HYPERLINK("https://x.com/a""b", "https://x.com/a""b")'


def test_wrong_header_writes_nothing(tmp_path):
    ws = FakeWorksheet([["Name", "Email"], ["x", "y"]])
    with pytest.raises(SheetMismatch):
        sheet_tracker.append_row(ws, new_row(), tmp_path / "backups")
    assert ws.updates == [] and ws.spreadsheet.requests == []
    assert not (tmp_path / "backups").exists()


def test_header_match_ignores_case_and_spaces():
    sheet_tracker.check_header([["company", "Position ", "URL", "Posted date /Source", "Date", "Outcome"]])


def test_backup_csv_holds_values_before_the_write(tmp_path):
    ws = sample_sheet()
    sheet_tracker.append_row(ws, new_row(), tmp_path / "backups")
    (backup,) = (tmp_path / "backups").glob("sheet-*.csv")
    with open(backup, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == HEADER and len(rows) == 4 and rows[1][0] == "Example Labs"


def test_full_sheet_gets_more_rows(tmp_path):
    ws = sample_sheet(row_count=3)
    assert sheet_tracker.append_row(ws, new_row(), tmp_path) == 4
    assert ws.added_rows == sheet_tracker.SHEET_GROWTH


def test_second_row_goes_below_first(tmp_path):
    ws = sample_sheet()
    sheet_tracker.append_row(ws, new_row(), tmp_path)
    assert sheet_tracker.append_row(ws, new_row(url=NEW_URL + "9"), tmp_path) == 5


def test_duplicates_by_url_hyperlink_target_and_company_position():
    ws = sample_sheet()
    hits = sheet_tracker.find_duplicates(ws, url="https://www.jobs.ashbyhq.com/examplelabs/1234abcd/?utm_source=x")
    assert [r for r, _ in hits] == [2]
    assert hits[0][1][0] == "Example Labs" and len(hits[0][1]) == 6
    assert [r for r, _ in sheet_tracker.find_duplicates(ws, url=LINKED_URL + "/apply")] == [3]
    assert [r for r, _ in sheet_tracker.find_duplicates(ws, company="linked co", position="BACKEND  engineer")] == [3]
    assert sheet_tracker.find_duplicates(ws, url=NEW_URL, company="Acme", position="SWE") == []


def test_network_errors_become_sheet_unavailable(tmp_path):
    ws = sample_sheet(fail=requests.exceptions.ConnectionError("offline"))
    with pytest.raises(SheetUnavailable, match="offline"):
        sheet_tracker.append_row(ws, new_row(), tmp_path)
    with pytest.raises(SheetUnavailable):
        sheet_tracker.find_duplicates(ws, url=NEW_URL)


def test_missing_key_file_is_sheet_unavailable(tmp_path, monkeypatch):
    monkeypatch.undo()  # the autouse guard replaces open_sheet; test the real one
    with pytest.raises(SheetUnavailable, match="key not found"):
        sheet_tracker.open_sheet("id", "Sheet1", tmp_path / "missing.json")


# ---------- apply.py writes to both ----------

class Script:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        assert self.answers, f"unexpected prompt: {prompt!r}"
        return self.answers.pop(0)


def fetch_ok(url):
    return JobDetails("Acme Robotics", "Software Engineer I", date(2026, 10, 8))


def run(tracker_file, ws, script, url=NEW_URL, extra=()):
    return apply.main([url, "--tracker", str(tracker_file), *extra], input_fn=script, fetch=fetch_ok,
                      today=TODAY, sheet_ws=ws)


def excel(path, ref):
    return load_workbook(path)["Sheet1"][ref].value


def test_row_goes_to_sheet_and_excel(tracker_file, capsys):
    ws = sample_sheet()
    assert run(tracker_file, ws, Script("")) == 0
    assert ws.values[3][0] == "Acme Robotics"
    assert excel(tracker_file, "A898") == "Acme Robotics"
    out = capsys.readouterr().out
    assert "Added row 4 to the Google Sheet" in out and "Added row 898" in out
    assert list((tracker_file.parent / "backups").glob("sheet-*.csv"))


def test_duplicate_found_in_sheet_is_shown_with_the_card(tracker_file, capsys):
    ws = sample_sheet()
    before = tracker_file.read_bytes()
    script = Script("s")
    assert run(tracker_file, ws, script, url=LINKED_URL) == 0
    assert script.prompts == [apply.PAUSE_PROMPT]
    assert "row 3: Linked Co" in capsys.readouterr().out
    assert ws.updates == [] and tracker_file.read_bytes() == before


def test_skip_writes_nowhere(tracker_file):
    ws = sample_sheet()
    before = tracker_file.read_bytes()
    assert run(tracker_file, ws, Script("s")) == 0
    assert ws.updates == [] and tracker_file.read_bytes() == before


def test_sheet_down_at_write_keeps_row_pending_then_flushes(tracker_file, capsys):
    ws = sample_sheet()
    real_update = ws.update

    def offline(*args, **kwargs):
        raise requests.exceptions.ConnectionError("offline")

    ws.update = offline
    assert run(tracker_file, ws, Script("")) == 0
    pending = tracker_file.parent / "pending_sheet.json"
    assert [r.company for r in tracker.load_pending(pending)] == ["Acme Robotics"]
    assert excel(tracker_file, "A898") == "Acme Robotics"  # Excel still written
    assert "pending_sheet.json" in capsys.readouterr().out

    ws.update = real_update  # back online
    assert run(tracker_file, ws, Script("s"), url=NEW_URL + "9") == 0
    assert "pending_sheet.json: Acme Robotics" in capsys.readouterr().out  # same company + position, still waiting
    assert ws.values[3][0] == "" and pending.exists()  # skipped: nothing flushed

    script = Script("")  # applied: the waiting row is written first, then this one
    assert run(tracker_file, ws, script, url=NEW_URL + "9") == 0
    assert script.prompts == [apply.PAUSE_PROMPT]
    assert ws.values[3][0] == "Acme Robotics" and ws.values[4][2] == NEW_URL + "9" and not pending.exists()
    assert "Wrote pending row 4 to the Google Sheet" in capsys.readouterr().out


def test_wrong_sheet_keeps_row_pending(tracker_file):
    ws = FakeWorksheet([["Name", "Email"]])
    assert run(tracker_file, ws, Script("")) == 0
    assert ws.updates == []
    assert tracker.load_pending(tracker_file.parent / "pending_sheet.json")
    assert excel(tracker_file, "A898") == "Acme Robotics"


def test_no_sheet_flag_is_excel_only(tracker_file):
    ws = sample_sheet()
    assert run(tracker_file, ws, Script(""), extra=["--no-sheet"]) == 0
    assert ws.updates == [] and len(ws.values) == 4
    assert excel(tracker_file, "A898") == "Acme Robotics"
    assert not (tracker_file.parent / "pending_sheet.json").exists()


def test_config_sheet_unreachable_falls_back_to_excel(dup_tracker, tmp_path, monkeypatch, capsys):
    tracker_file = dup_tracker
    config = tmp_path / "config.yaml"
    config.write_text(f"sheet_id: abc\nlocal_tracker: '{tracker_file}'\n", encoding="utf-8")

    def unreachable(sheet_id, tab, key_file):
        assert (sheet_id, tab, key_file.name) == ("abc", "Sheet1", "google-key.json")
        raise SheetUnavailable("offline")

    monkeypatch.setattr(sheet_tracker, "open_sheet", unreachable)
    dup_url = KNOWN_URL
    assert apply.main([dup_url, "--config", str(config)], input_fn=Script("s"),
                      fetch=fetch_ok, today=TODAY) == 0  # duplicate found in the Excel file
    out = capsys.readouterr().out
    assert "Google Sheet unavailable: offline" in out and f"row {KNOWN_ROW}" in out

    assert apply.main([NEW_URL, "--config", str(config)], input_fn=Script(""), fetch=fetch_ok, today=TODAY) == 0
    assert excel(tracker_file, "A898") == "Acme Robotics"
    assert tracker.load_pending(tracker_file.parent / "pending_sheet.json")


def test_no_config_is_excel_only(tracker_file):
    assert apply.main([NEW_URL, "--tracker", str(tracker_file)], input_fn=Script(""),
                      fetch=fetch_ok, today=TODAY) == 0
    assert excel(tracker_file, "A898") == "Acme Robotics"
    assert not (tracker_file.parent / "pending_sheet.json").exists()
