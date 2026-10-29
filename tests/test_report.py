"""Milestone 9: report.py, a read-only page of the tracker, on the fake tracker and a fake worksheet."""
import hashlib
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

from fake_sheet import HEADER, FakeWorksheet
from fake_tracker import SHUFFLED, make_tracker
from reporting import load
from reporting.load import Job, Settings

TODAY = date(2026, 10, 28)  # a Wednesday: this week is Oct 26-28, last week Oct 19-25


def _fingerprint(path):
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def plant(path, rows):
    """Write {header: value} rows over the fake tracker, starting at row 2 (by header name)."""
    wb = load_workbook(path)
    ws = wb["Sheet1"]
    col = {c.value: c.column for c in ws[1]}
    for r, values in enumerate(rows, start=2):
        for header, value in values.items():
            cell = ws.cell(r, col[header])
            cell.value = value  # ws.cell(r, c, None) would leave the old value
            if header == "URL":  # a plain link is text + hyperlink like real rows; a formula or blank has none
                cell.hyperlink = value if value and not str(value).startswith("=") else None
            if isinstance(value, datetime):
                cell.number_format = "M/d/yyyy"
    wb.save(path)


# ---------- load ----------

def test_excel_rows_by_header_name(tracker_file):
    plant(tracker_file, [{"Company": "Acme", "Position": "Backend Engineer", "URL": "https://jobs.lever.co/acme/1",
                          "Posted date/ Source": "Posted today-Jobright", "Date": datetime(2026, 10, 27),
                          "Outcome": "In progress", "Stage": "Interview", "Last Updated": datetime(2026, 10, 27),
                          "Remarks": "referred by Sam"}])
    jobs = load.excel_rows(tracker_file)
    assert len(jobs) == 896
    assert jobs[0] == Job(row=2, company="Acme", position="Backend Engineer", url="https://jobs.lever.co/acme/1",
                          posted="Posted today-Jobright", applied=date(2026, 10, 27), outcome="In progress",
                          stage="Interview", last_updated=date(2026, 10, 27), remarks="referred by Sam",
                          url_is_formula=False)
    assert jobs[1].company == "Company 3" and jobs[1].last_updated is None and jobs[1].stage == ""


def test_excel_rows_in_a_shuffled_layout(tmp_path):
    path = make_tracker(tmp_path / "shuffled.xlsx", headers=SHUFFLED)
    plant(path, [{"Company": "Acme", "Position": "SRE", "Outcome": "Rejected", "Stage": "Online Assessment",
                  "Remarks": "no visa"}])
    job = load.excel_rows(path)[0]
    assert (job.company, job.position, job.outcome, job.stage, job.remarks) == (
        "Acme", "SRE", "Rejected", "Online Assessment", "no visa")
    assert job.url == "https://example.com/jobs/2"


def test_hyperlink_formula_gives_the_target(tracker_file):
    plant(tracker_file, [{"URL": '=HYPERLINK("https://jobs.ashbyhq.com/acme/9", "click here")'},
                         {"URL": None, "Company": "No Link Co"}])
    first, second = load.excel_rows(tracker_file)[:2]
    assert first.url == "https://jobs.ashbyhq.com/acme/9" and first.url_is_formula
    assert second.url == "" and not second.url_is_formula


def test_hyperlink_target_wins_over_link_text(tracker_file):
    wb = load_workbook(tracker_file)
    ws = wb["Sheet1"]
    ws.cell(2, 3, "click here").hyperlink = "https://jobs.lever.co/acme/2"
    wb.save(tracker_file)
    assert load.excel_rows(tracker_file)[0].url == "https://jobs.lever.co/acme/2"


def test_reading_never_changes_the_tracker(tracker_file):
    before = _fingerprint(tracker_file)
    load.excel_rows(tracker_file)
    assert _fingerprint(tracker_file) == before


def test_sheet_rows_use_the_formula_target():
    ws = FakeWorksheet([
        HEADER,
        ["Acme", "Data Engineer", "click here", "Posted today-Tsenta", "10/27/2026", "Awaiting reply", "Interview",
         "10/27/2026", "", "", ""],
        ["Zenith", "SWE", "https://jobs.lever.co/zenith/1", "LinkedIn", "10/1/2026", "Applied", "", "", "", "", ""],
    ], formulas={2: '=HYPERLINK("https://jobs.lever.co/acme/3", "click here")'})
    acme, zenith = load.sheet_rows(ws)
    assert acme.url == "https://jobs.lever.co/acme/3" and not acme.url_is_formula  # formulas: Excel check only
    assert acme.applied == date(2026, 10, 27) and acme.last_updated == date(2026, 10, 27)
    assert zenith.url == "https://jobs.lever.co/zenith/1" and zenith.last_updated is None
    assert ws.updates == []


def test_settings_defaults_when_no_file(tmp_path):
    s = load.load_settings(tmp_path / "missing.yaml")
    assert s == Settings()
    assert (s.weekly_target, s.follow_up_days, s.no_reply_days, s.many_applications, s.min_group,
            s.weeks_shown) == (25, 14, 30, 5, 20, 12)
    assert s.sources == ["Jobright", "Tsenta", "LinkedIn"]
    assert list(s.title_types) == ["Backend", "DevOps/Cloud/SRE/Platform", "AI/ML/Data", "Software (general)"]
    assert list(s.remark_tags) == ["No sponsorship", "Clearance/citizenship", "Referral"]


def test_settings_file_overrides_only_its_keys(tmp_path):
    path = tmp_path / "report.yaml"
    path.write_text("weekly_target: 10\nsources: [Handshake]\n", encoding="utf-8")
    s = load.load_settings(path)
    assert s.weekly_target == 10 and s.sources == ["Handshake"] and s.follow_up_days == 14


def test_settings_unknown_key_is_named(tmp_path):
    path = tmp_path / "report.yaml"
    path.write_text("weekly_targe: 10\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="weekly_targe"):
        load.load_settings(path)


def test_repo_report_yaml_matches_the_defaults():
    from pathlib import Path
    assert load.load_settings(Path(__file__).resolve().parent.parent / "report.yaml") == Settings()
