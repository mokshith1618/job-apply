"""End-to-end apply.py runs on a fake tracker (tests/fake_tracker.py), with scripted terminal input."""
from datetime import date

from openpyxl import load_workbook

import apply
import tracker
from ats.common import JobDetails
from conftest import KNOWN_COMPANY, KNOWN_POSITION, KNOWN_ROW, KNOWN_URL

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
    script = Script("", "")
    assert run(tracker_file, NEW_URL, script, extra=["--source", "LinkedIn"]) == 0
    assert script.prompts == [apply.APPLY_PROMPT, apply.PAUSE_PROMPT]
    assert cell(tracker_file, "A898") == "Acme Robotics"
    assert cell(tracker_file, "D898") == "Posted October 8, 2026-LinkedIn"
    assert cell(tracker_file, "F898") == "Applied"
    assert "Added row 898" in capsys.readouterr().out
    assert not tracker.pending_path_for(tracker_file).exists()


def test_s_skips_without_writing(tracker_file):
    before = tracker_file.read_bytes()
    assert run(tracker_file, NEW_URL, Script("", "s")) == 0
    assert tracker_file.read_bytes() == before
    assert not (tracker_file.parent / "backups").exists()


class Recorder(Script):
    """A Script that also keeps what was printed before each prompt."""

    def __init__(self, capsys, *answers):
        super().__init__(*answers)
        self.capsys, self.printed = capsys, []

    def __call__(self, prompt=""):
        self.printed.append(self.capsys.readouterr().out)
        return super().__call__(prompt)


def test_duplicate_url_is_shown_with_the_card(dup_tracker, capsys):
    tracker_file = dup_tracker
    before = tracker_file.read_bytes()

    script = Recorder(capsys, "s")  # the card shows the old row; "s" at the Apply prompt
    assert run(tracker_file, DUP_URL + "?utm_source=Tsenta", script) == 0
    assert script.prompts == [apply.APPLY_PROMPT]
    out = script.printed[0]
    assert f"row {KNOWN_ROW}: {KNOWN_COMPANY}" in out
    assert out.index("Posted:") < out.index("Already in the tracker:")  # right under the card
    assert tracker_file.read_bytes() == before


def test_duplicate_url_apply_anyway_is_not_asked_twice(dup_tracker):
    tracker_file = dup_tracker
    script = Script("", "")
    assert run(tracker_file, DUP_URL, script) == 0
    assert script.prompts == [apply.APPLY_PROMPT, apply.PAUSE_PROMPT]  # no "Continue anyway?"
    assert cell(tracker_file, "C898") == DUP_URL


def test_duplicate_company_position_from_the_job_is_shown_with_the_card(dup_tracker, capsys):
    tracker_file = dup_tracker
    def fetch_dup(url):
        return JobDetails(KNOWN_COMPANY, KNOWN_POSITION, date(2026, 6, 20))

    before = tracker_file.read_bytes()
    script = Recorder(capsys, "s")
    assert run(tracker_file, "https://example.com/new-link", script, fetch=fetch_dup) == 0
    assert f"row {KNOWN_ROW}" in script.printed[0]
    assert tracker_file.read_bytes() == before


def test_typed_company_position_matching_a_row_still_asks(dup_tracker, capsys):
    tracker_file = dup_tracker
    before = tracker_file.read_bytes()
    script = Recorder(capsys, "", KNOWN_COMPANY, KNOWN_POSITION, "n")
    assert run(tracker_file, "https://example.com/new-link", script,
               fetch=lambda u: JobDetails(posted_date=date(2026, 6, 20))) == 1
    assert script.prompts == [apply.APPLY_PROMPT, "Company: ", "Position: ", "Continue anyway? [y/N] "]
    assert "Tracker: no matching link or job found." in script.printed[0]
    assert f"row {KNOWN_ROW}" in script.printed[3]
    assert tracker_file.read_bytes() == before


def test_pending_row_counts_as_already_in_the_tracker(tracker_file, capsys):
    tracker.save_pending(tracker.pending_path_for(tracker_file),
                         tracker.TrackerRow("Acme Robotics", "Software Engineer I", NEW_URL, "Other", TODAY))
    script = Recorder(capsys, "s")
    assert run(tracker_file, NEW_URL, script) == 0
    assert "pending_rows.json: Acme Robotics" in script.printed[0]
    assert len(tracker.load_pending(tracker.pending_path_for(tracker_file))) == 1  # skip: not flushed


def test_missing_tracker_stops_before_the_apply_prompt(tmp_path, capsys):
    script = Script()
    assert run(tmp_path / "no-tracker.xlsx", NEW_URL, script) == 2
    assert script.prompts == []
    assert "Tracker not found" in capsys.readouterr().out


def test_missing_details_are_asked(tracker_file):
    script = Script("", "Beta Corp", "Backend Engineer", "today", "")
    assert run(tracker_file, "https://example.com/job/9", script, fetch=lambda u: JobDetails(),
               extra=["--source", "Tsenta"]) == 0
    assert script.prompts[:4] == [apply.APPLY_PROMPT, "Company: ", "Position: ",
                                  "Posted date (YYYY-MM-DD, 'today', or blank if unknown): "]
    assert cell(tracker_file, "A898") == "Beta Corp"
    assert cell(tracker_file, "D898") == "Posted today-Tsenta"


def test_guesses_are_offered_not_used_silently(tracker_file):
    guessed = JobDetails(posted_date=date(2026, 10, 8), company_guess="Beta Corp", position_guess="Dev")
    script = Script("", "", "Backend Engineer", "")  # Enter accepts the company guess; typing replaces the title
    assert run(tracker_file, "https://example.com/job/9", script, fetch=lambda u: guessed) == 0
    assert script.prompts[1:3] == ["Company [Beta Corp] (Enter = use this): ", "Position [Dev] (Enter = use this): "]
    assert cell(tracker_file, "A898") == "Beta Corp"
    assert cell(tracker_file, "B898") == "Backend Engineer"


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
    script = Script("", "", "")  # Enter at the card, Enter = applied, then Enter = retry after closing Excel
    assert run(tracker_file, NEW_URL, script) == 0
    assert "Close Excel" in script.prompts[2]
    assert cell(tracker_file, "A898") == "Acme Robotics"
    assert not tracker.pending_path_for(tracker_file).exists()


def test_leftover_pending_rows_are_written_first(tracker_file):
    tracker.save_pending(tracker.pending_path_for(tracker_file),
                         tracker.TrackerRow("Old Co", "Old Job", "https://old.example/1", "Other", TODAY))
    assert run(tracker_file, NEW_URL, Script("", "")) == 0
    assert cell(tracker_file, "A898") == "Old Co"
    assert cell(tracker_file, "A899") == "Acme Robotics"



def test_company_typed_once_is_remembered_for_the_site(tracker_file, tmp_path, capsys):
    url = "https://umbrella.wd5.myworkdayjobs.com/en-US/UmbrellaCareers/job/Remote/Dev_JR1"
    no_company = lambda u: JobDetails(None, "Cloud Developer II", date(2026, 10, 8))  # noqa: E731
    first = Script("", "Umbrella Corporation", "s")
    assert run(tracker_file, url, first, fetch=no_company) == 0
    assert first.prompts[1] == "Company [Umbrella] (Enter = use this): "  # suggested from the link
    assert "Saved: umbrella.wd5.myworkdayjobs.com = Umbrella Corporation" in capsys.readouterr().out

    second = Script("", "")  # only the card and pause prompts: the company isn't asked again
    assert run(tracker_file, url.replace("Dev_JR1", "Ops_JR2"), second, fetch=no_company) == 0
    assert second.prompts == [apply.APPLY_PROMPT, apply.PAUSE_PROMPT]
    assert cell(tracker_file, "A898") == "Umbrella Corporation"


def test_company_from_job_data_is_not_overridden_or_saved(tracker_file, tmp_path):
    url = "https://umbrella.wd5.myworkdayjobs.com/en-US/UmbrellaCareers/job/Remote/Dev_JR1"
    assert run(tracker_file, url, Script("", "")) == 0  # fetch_ok has a company
    assert not (tmp_path / "companies.yaml").exists()


# --- Job facts card (milestone 1d) ---

CARD_JOB = JobDetails("Acme Robotics", "Software Engineer I", date(2026, 10, 8),
                      description="We do not sponsor visas.\n3+ years of Python.",
                      posted_raw="2026-10-08T09:00:00-04:00")


def test_card_is_printed_before_any_prompt(tracker_file, capsys):
    asked = []

    def input_fn(prompt):
        asked.append((prompt, capsys.readouterr().out))  # what was printed before this prompt
        return "s"

    assert apply.main([NEW_URL, "--tracker", str(tracker_file)], input_fn=input_fn,
                      fetch=lambda u: CARD_JOB, today=TODAY) == 0
    [(prompt, out)] = asked
    assert prompt == apply.APPLY_PROMPT
    assert ("Acme Robotics · Software Engineer I · Greenhouse\n\n"
            "Sponsorship:\n  We do not sponsor visas.\n\n"
            "Citizenship:\n  not mentioned\n\n"
            "Seniority:\n  Title: Software Engineer I\n  3+ years of Python.\n\n"
            "Posted:\n  October ") in out and " days ago)" in out  # date shown in my time zone
    assert out.rstrip().endswith("Tracker: no matching link or job found.")


def test_skip_at_the_card_ends_the_run(tracker_file):
    before = tracker_file.read_bytes()
    script = Script("s")
    assert run(tracker_file, NEW_URL, script, fetch=lambda u: CARD_JOB) == 0
    assert script.prompts == [apply.APPLY_PROMPT]  # nothing else asked, no form opened
    assert tracker_file.read_bytes() == before
    assert not tracker.pending_path_for(tracker_file).exists()


def test_check_prints_the_card_and_exits(tmp_path, capsys):
    script = Script()  # any prompt fails the test
    missing = tmp_path / "no-tracker.xlsx"  # --check doesn't need the tracker
    assert apply.main([NEW_URL, "--check", "--tracker", str(missing)], input_fn=script,
                      fetch=lambda u: CARD_JOB, today=TODAY) == 0
    assert script.prompts == []
    out = capsys.readouterr().out
    assert "Sponsorship:\n  We do not sponsor visas." in out
    assert "Tracker not found" in out  # only a note with --check
    assert not missing.exists()


def test_check_shows_the_duplicate_and_writes_nothing(dup_tracker, capsys):
    before = dup_tracker.read_bytes()
    tracker.save_pending(tracker.pending_path_for(dup_tracker),
                         tracker.TrackerRow("Old Co", "Old Job", "https://old.example/1", "Other", TODAY))
    script = Script()
    assert run(dup_tracker, DUP_URL, script, extra=["--check"]) == 0
    assert script.prompts == []
    assert f"row {KNOWN_ROW}: {KNOWN_COMPANY}" in capsys.readouterr().out
    assert dup_tracker.read_bytes() == before
    assert tracker.load_pending(tracker.pending_path_for(dup_tracker))  # --check never flushes


def test_card_without_a_description(tracker_file, capsys):
    assert run(tracker_file, NEW_URL, Script("s")) == 0  # fetch_ok has no description
    assert "Description: not available" in capsys.readouterr().out
