"""End-to-end apply.py runs on a temp copy of tracker_copy.xlsx, with scripted terminal input."""
from datetime import date

from openpyxl import load_workbook

import apply
from conftest import KNOWN_COMPANY, KNOWN_POSITION, KNOWN_ROW, KNOWN_URL
import tracker
from ats.common import JobDetails

TODAY = date(2026, 10, 13)
NEW_URL = "https://job-boards.greenhouse.io/acme/jobs/1234567"
DUP_URL = KNOWN_URL


class Script:
    """Feeds answers to input() and records the prompts."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        assert self.answers, f"unexpected prompt: {prompt!r}"
        return self.answers.pop(0)


def fetch_ok(url):
    return JobDetails("Acme Robotics", "Software Engineer I", date(2026, 10, 8))


def run(tracker_file, url, script, fetch=fetch_ok, extra=()):
    return apply.main([url, "--tracker", str(tracker_file), *extra], input_fn=script, fetch=fetch, today=TODAY)


def cell(path, ref):
    return load_workbook(path)["Sheet1"][ref].value


def test_enter_writes_row(tracker_file, capsys):
    script = Script("")
    assert run(tracker_file, NEW_URL, script, extra=["--source", "LinkedIn"]) == 0
    assert script.prompts == [apply.PAUSE_PROMPT]
    assert cell(tracker_file, "A898") == "Acme Robotics"
    assert cell(tracker_file, "D898") == "Posted October 8, 2026-LinkedIn"
    assert cell(tracker_file, "F898") == "Applied"
    assert "Added row 898" in capsys.readouterr().out
    assert not tracker.pending_path_for(tracker_file).exists()


def test_s_skips_without_writing(tracker_file):
    before = tracker_file.read_bytes()
    assert run(tracker_file, NEW_URL, Script("s")) == 0
    assert tracker_file.read_bytes() == before
    assert not (tracker_file.parent / "backups").exists()


def test_duplicate_url_shows_old_row_and_stops(dup_tracker, capsys):
    tracker_file = dup_tracker
    before = tracker_file.read_bytes()

    def must_not_fetch(url):
        raise AssertionError("should stop before fetching")

    assert run(tracker_file, DUP_URL + "?utm_source=Tsenta", Script("n"), fetch=must_not_fetch) == 1
    out = capsys.readouterr().out
    assert f"row {KNOWN_ROW}" in out and KNOWN_COMPANY in out
    assert tracker_file.read_bytes() == before


def test_duplicate_url_continue_anyway(dup_tracker):
    tracker_file = dup_tracker
    script = Script("y", "")
    assert run(tracker_file, DUP_URL, script) == 0
    assert cell(tracker_file, "C898") == DUP_URL


def test_duplicate_company_position_asks(dup_tracker):
    tracker_file = dup_tracker
    def fetch_dup(url):
        return JobDetails(KNOWN_COMPANY, KNOWN_POSITION, date(2026, 6, 20))

    before = tracker_file.read_bytes()
    script = Script("n")
    assert run(tracker_file, "https://example.com/new-link", script, fetch=fetch_dup) == 1
    assert tracker_file.read_bytes() == before


def test_missing_details_are_asked(tracker_file):
    script = Script("Beta Corp", "Backend Engineer", "today", "")
    assert run(tracker_file, "https://example.com/job/9", script, fetch=lambda u: JobDetails(),
               extra=["--source", "Tsenta"]) == 0
    assert script.prompts[:3] == ["Company: ", "Position: ",
                                  "Posted date (YYYY-MM-DD, 'today', or blank if unknown): "]
    assert cell(tracker_file, "A898") == "Beta Corp"
    assert cell(tracker_file, "D898") == "Posted today-Tsenta"


def test_excel_open_keeps_row_pending_until_closed(tracker_file, monkeypatch):
    real_replace = tracker.os.replace
    attempts = {"n": 0}

    def replace_locked_once(src, dst):
        attempts["n"] += 1
        if attempts["n"] == 1:
            assert tracker.load_pending(tracker.pending_path_for(tracker_file))  # row is safe on disk
            raise PermissionError(13, "file in use")
        return real_replace(src, dst)

    monkeypatch.setattr(tracker.os, "replace", replace_locked_once)
    script = Script("", "")  # Enter = applied, then Enter = retry after closing Excel
    assert run(tracker_file, NEW_URL, script) == 0
    assert "Close Excel" in script.prompts[1]
    assert cell(tracker_file, "A898") == "Acme Robotics"
    assert not tracker.pending_path_for(tracker_file).exists()


def test_leftover_pending_rows_are_written_first(tracker_file):
    tracker.save_pending(tracker.pending_path_for(tracker_file),
                         tracker.TrackerRow("Old Co", "Old Job", "https://old.example/1", "Other", TODAY))
    assert run(tracker_file, NEW_URL, Script("")) == 0
    assert cell(tracker_file, "A898") == "Old Co"
    assert cell(tracker_file, "A899") == "Acme Robotics"

