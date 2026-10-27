"""End-to-end apply.py runs on a fake tracker (tests/fake_tracker.py), with scripted terminal input."""
from datetime import date

import pytest
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
    script = Script("")
    assert run(tracker_file, NEW_URL, script, extra=["--source", "LinkedIn"]) == 0
    assert script.prompts == [apply.PAUSE_PROMPT]  # the only question
    assert cell(tracker_file, "A898") == "Acme Robotics"
    assert cell(tracker_file, "D898") == "Posted October 8, 2026-LinkedIn"
    assert cell(tracker_file, "F898") == "Applied"
    assert "Added row 898" in capsys.readouterr().out
    assert not tracker.pending_path_for(tracker_file).exists()


@pytest.mark.parametrize("typed,source", [
    ("Linkedin", "LinkedIn"), ("linkedin", "LinkedIn"), ("LINKEDIN", "LinkedIn"), (" Linked In ", "LinkedIn"),
    ("linked-in", "LinkedIn"), ("tsenta", "Tsenta"), ("other", "Other"), ("", "Other"),
    ("Linkdin", "LinkedIn"), ("Tsneta", "Tsenta"),   # near-misses
    ("Indeed", "Indeed"), ("Hiring Cafe", "Hiring Cafe"), ("Lever", "Lever"), ("Dice", "Dice"),  # kept as typed
])
def test_source_is_forgiving(typed, source):
    assert apply.normalize_source(typed) == source


@pytest.mark.parametrize("typed,column_d", [("linkedin", "Posted October 8, 2026-LinkedIn"),
                                            ("Indeed", "Posted October 8, 2026-Indeed")])
def test_source_as_typed_reaches_the_tracker(tracker_file, typed, column_d):
    assert run(tracker_file, NEW_URL, Script(""), extra=["--source", typed]) == 0
    assert cell(tracker_file, "D898") == column_d


def test_s_skips_without_writing(tracker_file):
    before = tracker_file.read_bytes()
    assert run(tracker_file, NEW_URL, Script("s")) == 0
    assert tracker_file.read_bytes() == before
    assert not (tracker_file.parent / "backups").exists()


def run_no_link(tracker_file, script, extra=()):
    return apply.main(["--tracker", str(tracker_file), *extra], input_fn=script, fetch=fetch_ok, today=TODAY)


def test_no_link_asks_for_it(tracker_file):
    script = Script(NEW_URL, "")
    assert run_no_link(tracker_file, script, extra=["--source", "Tsenta"]) == 0
    assert script.prompts == ["Job link: ", apply.PAUSE_PROMPT]
    assert cell(tracker_file, "C898") == NEW_URL
    assert cell(tracker_file, "D898") == "Posted October 8, 2026-Tsenta"


def test_pasted_link_blank_and_quotes(tracker_file):
    url = NEW_URL + "?gh_jid=1&x=2"
    script = Script("", f"  '{url}'  ", "")
    assert run_no_link(tracker_file, script) == 0
    assert script.prompts == ["Job link: ", "Job link: ", apply.PAUSE_PROMPT]
    assert cell(tracker_file, "C898") == url


def test_pasted_text_that_is_not_a_link_asks_again(tracker_file, capsys):
    script = Script("acme", NEW_URL, "s")
    assert run_no_link(tracker_file, script) == 0
    assert script.prompts[:2] == ["Job link: ", "Job link: "]
    assert "Paste the full link" in capsys.readouterr().out


def test_check_without_link_asks_then_shows_the_card(tracker_file, capsys):
    before = tracker_file.read_bytes()
    script = Script(NEW_URL)
    assert run_no_link(tracker_file, script, extra=["--check"]) == 0
    assert script.prompts == ["Job link: "]
    assert "Acme Robotics" in capsys.readouterr().out
    assert tracker_file.read_bytes() == before


def test_ctrl_c_at_the_link_stops(tracker_file, capsys):
    def interrupt(prompt=""):
        raise KeyboardInterrupt
    assert apply.main(["--tracker", str(tracker_file)], input_fn=interrupt, fetch=fetch_ok, today=TODAY) == 1
    assert "Stopped." in capsys.readouterr().out


def test_e_then_enter_keeps_every_value(tracker_file):
    script = Script("e", "", "", "", "", "")
    assert run(tracker_file, NEW_URL, script, extra=["--source", "LinkedIn"]) == 0
    assert script.prompts[1:5] == [
        "Company [Acme Robotics] (Enter = keep): ",
        "Position [Software Engineer I] (Enter = keep): ",
        "Posted date [2026-10-08] (YYYY-MM-DD, 'today', '-' = unknown, "
        "other text = as typed, Enter = keep): ",
        "Source [LinkedIn] (Enter = keep): ",
    ]
    assert script.prompts[-1] == apply.PAUSE_PROMPT  # back to the same question
    assert [cell(tracker_file, r) for r in ("A898", "B898", "C898", "D898")] == [
        "Acme Robotics", "Software Engineer I", NEW_URL, "Posted October 8, 2026-LinkedIn"]


def test_e_edits_reach_the_tracker(tracker_file, capsys):
    script = Script("e", " Acme ", "Backend Engineer", "2026-10-01", "tsenta", "")
    assert run(tracker_file, NEW_URL, script, extra=["--source", "LinkedIn"]) == 0
    assert [cell(tracker_file, r) for r in ("A898", "B898", "C898", "D898")] == [
        "Acme", "Backend Engineer", NEW_URL, "Posted October 1, 2026-Tsenta"]
    assert "Company:  Acme\n  Position: Backend Engineer\n  Posted:   Posted October 1, 2026-Tsenta" \
        in capsys.readouterr().out  # the summary again, before the question


def test_e_twice_starts_from_the_edited_values(tracker_file):
    script = Script("e", "", "", "today", "", "e", "", "", "-", "Indeed", "")
    assert run(tracker_file, NEW_URL, script) == 0
    assert script.prompts[8] == ("Posted date [2026-10-13] (YYYY-MM-DD, 'today', '-' = unknown, "
                                 "other text = as typed, Enter = keep): ")
    assert cell(tracker_file, "D898") == "Indeed"  # no date: just the source


def test_e_bad_date_asks_again(tracker_file, capsys):
    script = Script("e", "", "", "2026-13-40", "2026-10-09", "", "")
    assert run(tracker_file, NEW_URL, script) == 0
    assert script.prompts[3] == script.prompts[4]
    assert "Use YYYY-MM-DD" in capsys.readouterr().out
    assert cell(tracker_file, "D898") == "Posted October 9, 2026-Other"


def test_e_other_text_is_column_d_as_typed(tracker_file):
    script = Script("e", "", "", " Sameday-Tsenta ", "")  # no Source question
    assert run(tracker_file, NEW_URL, script) == 0
    assert len(script.prompts) == 5
    assert script.prompts[-1] == apply.PAUSE_PROMPT
    assert cell(tracker_file, "D898") == "Sameday-Tsenta"


def test_e_typed_posted_text_is_kept_by_a_later_edit(tracker_file):
    script = Script("e", "", "", "Sameday-Tsenta", "e", "", "", "", "")
    assert run(tracker_file, NEW_URL, script) == 0
    assert script.prompts[7].startswith("Posted date [Sameday-Tsenta] ")
    assert cell(tracker_file, "D898") == "Sameday-Tsenta"


def test_e_date_after_typed_text_asks_source_again(tracker_file):
    script = Script("e", "", "", "Sameday-Tsenta", "e", "", "", "today", "LinkedIn", "")
    assert run(tracker_file, NEW_URL, script) == 0
    assert cell(tracker_file, "D898") == "Posted today-LinkedIn"


def test_e_then_s_writes_nothing(tracker_file):
    before = tracker_file.read_bytes()
    assert run(tracker_file, NEW_URL, Script("e", "Other Co", "", "", "", "s")) == 0
    assert tracker_file.read_bytes() == before


class Recorder(Script):
    """A Script that also keeps what was printed before each prompt."""

    def __init__(self, capsys, *answers):
        super().__init__(*answers)
        self.capsys, self.printed = capsys, []

    def __call__(self, prompt=""):
        self.printed.append(self.capsys.readouterr().out)
        return super().__call__(prompt)


def test_e_company_position_matching_a_row_is_shown_not_asked(dup_tracker, capsys):
    tracker_file = dup_tracker
    before = tracker_file.read_bytes()
    script = Recorder(capsys, "e", KNOWN_COMPANY, KNOWN_POSITION, "", "", "s")
    assert run(tracker_file, NEW_URL, script) == 0
    assert script.prompts[-1] == apply.PAUSE_PROMPT and len(script.prompts) == 6  # no extra question
    assert f"row {KNOWN_ROW}: {KNOWN_COMPANY}" in script.printed[-1]
    assert tracker_file.read_bytes() == before


def test_duplicate_url_is_shown_with_the_card(dup_tracker, capsys):
    tracker_file = dup_tracker
    before = tracker_file.read_bytes()

    script = Recorder(capsys, "s")  # the card shows the old row; "s" at the one question
    assert run(tracker_file, DUP_URL + "?utm_source=Tsenta", script) == 0
    assert script.prompts == [apply.PAUSE_PROMPT]
    out = script.printed[0]
    assert f"row {KNOWN_ROW}: {KNOWN_COMPANY}" in out and "None" not in out  # empty cells stay empty
    assert out.index("Posted:") < out.index("Already in the tracker:")  # right under the card
    assert tracker_file.read_bytes() == before


def test_duplicate_url_is_not_a_question(dup_tracker):
    tracker_file = dup_tracker
    script = Script("")
    assert run(tracker_file, DUP_URL, script) == 0
    assert script.prompts == [apply.PAUSE_PROMPT]  # no "Continue anyway?": Enter = applied decides
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


def test_typed_company_position_matching_a_row_is_shown_not_asked(dup_tracker, capsys):
    tracker_file = dup_tracker
    before = tracker_file.read_bytes()
    script = Recorder(capsys, KNOWN_COMPANY, KNOWN_POSITION, "s")
    assert run(tracker_file, "https://example.com/new-link", script,
               fetch=lambda u: JobDetails(posted_date=date(2026, 6, 20))) == 0
    assert script.prompts == ["Company: ", "Position: ", apply.PAUSE_PROMPT]
    assert "Tracker: no matching link or job found." in script.printed[0]
    assert f"row {KNOWN_ROW}" in script.printed[2]  # shown before the one question
    assert tracker_file.read_bytes() == before


def test_pending_row_counts_as_already_in_the_tracker(tracker_file, capsys):
    tracker.save_pending(tracker.pending_path_for(tracker_file),
                         tracker.TrackerRow("Acme Robotics", "Software Engineer I", NEW_URL, "Other", TODAY))
    script = Recorder(capsys, "s")
    assert run(tracker_file, NEW_URL, script) == 0
    assert "pending_rows.json: Acme Robotics" in script.printed[0]
    assert len(tracker.load_pending(tracker.pending_path_for(tracker_file))) == 1  # skip: not flushed


ORACLE_URL = "https://hcgn.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/49903"


def no_company(url):
    return JobDetails(None, KNOWN_POSITION, date(2026, 10, 19))


def test_card_says_company_unknown(tracker_file, capsys):
    script = Recorder(capsys, "Citizens", "s")  # the company is asked after the card
    assert run(tracker_file, ORACLE_URL, script, fetch=no_company) == 0
    assert f"\nCompany unknown · {KNOWN_POSITION} · Oracle Cloud\n" in script.printed[0]


def test_card_uses_the_company_i_gave_for_the_site(dup_tracker, tmp_path, capsys):
    (tmp_path / "companies.yaml").write_text(f"hcgn.fa.us2.oraclecloud.com: {KNOWN_COMPANY}\n", encoding="utf-8")
    script = Recorder(capsys, "s")
    assert run(dup_tracker, ORACLE_URL, script, fetch=no_company) == 0
    out = script.printed[0]
    assert f"\n{KNOWN_COMPANY} · {KNOWN_POSITION} · Oracle Cloud\n" in out
    assert f"row {KNOWN_ROW}: {KNOWN_COMPANY}" in out  # same company + position, found at the card


def test_companies_yaml_beats_a_page_guess(tracker_file, tmp_path, capsys):
    (tmp_path / "companies.yaml").write_text("hcgn.fa.us2.oraclecloud.com: Citizens\n", encoding="utf-8")
    script = Recorder(capsys, "", "s")  # posted date unknown, then the one question
    guessed = JobDetails(position="Dev", company_guess="Citizens Careers Page")
    assert run(tracker_file, ORACLE_URL, script, fetch=lambda u: guessed) == 0
    assert "\nCitizens · Dev · Oracle Cloud\n" in script.printed[0]


def test_page_guesses_are_shown_and_checked_for_duplicates(dup_tracker, capsys):
    before = dup_tracker.read_bytes()
    guessed = JobDetails(company_guess=KNOWN_COMPANY, position_guess=KNOWN_POSITION)
    script = Recorder(capsys, "", "", "", "s")  # company, position, posted date, then the one question
    assert run(dup_tracker, "https://example.com/careers/42", script, fetch=lambda u: guessed) == 0
    out = script.printed[0]
    assert f"\n{KNOWN_COMPANY} (from page) · {KNOWN_POSITION} (from page) · Other site\n" in out
    assert f"row {KNOWN_ROW}: {KNOWN_COMPANY}" in out
    assert dup_tracker.read_bytes() == before


def test_accepted_guesses_matching_a_row_are_not_shown_twice(dup_tracker, capsys):
    guessed = JobDetails(posted_date=date(2026, 10, 1), company_guess=KNOWN_COMPANY, position_guess=KNOWN_POSITION)
    script = Script("", "", "")  # accept both guesses, then applied
    assert run(dup_tracker, "https://example.com/careers/42", script, fetch=lambda u: guessed) == 0
    assert capsys.readouterr().out.count(f"row {KNOWN_ROW}:") == 1  # shown once, with the card
    assert cell(dup_tracker, "A898") == KNOWN_COMPANY


def test_missing_tracker_stops_before_any_question(tmp_path, capsys):
    script = Script()
    assert run(tmp_path / "no-tracker.xlsx", NEW_URL, script) == 2
    assert script.prompts == []
    assert "Tracker not found" in capsys.readouterr().out


def test_missing_details_are_asked(tracker_file):
    script = Script("Beta Corp", "Backend Engineer", "today", "")
    assert run(tracker_file, "https://example.com/job/9", script, fetch=lambda u: JobDetails(),
               extra=["--source", "Tsenta"]) == 0
    assert script.prompts[:3] == ["Company: ", "Position: ",
                                  "Posted date (YYYY-MM-DD, 'today', other text = as typed, "
                                  "or blank if unknown): "]
    assert cell(tracker_file, "A898") == "Beta Corp"
    assert cell(tracker_file, "D898") == "Posted today-Tsenta"


def no_date(url):
    return JobDetails("Acme Robotics", "Software Engineer I")


def test_missing_date_text_is_column_d_as_typed(tracker_file):
    script = Script(" Sameday  - Tsenta ", "")
    assert run(tracker_file, NEW_URL, script, fetch=no_date, extra=["--source", "Tsenta"]) == 0
    assert len(script.prompts) == 2  # no Source question
    assert cell(tracker_file, "D898") == "Sameday - Tsenta"


def test_missing_date_text_is_kept_by_e(tracker_file):
    script = Script("Sameday - Tsenta", "e", "", "", "", "")
    assert run(tracker_file, NEW_URL, script, fetch=no_date) == 0
    assert script.prompts[4].startswith("Posted date [Sameday - Tsenta] ")
    assert cell(tracker_file, "D898") == "Sameday - Tsenta"


def test_missing_date_not_a_real_date_asks_again(tracker_file, capsys):
    script = Script("2026-13-40", "", "")
    assert run(tracker_file, NEW_URL, script, fetch=no_date, extra=["--source", "LinkedIn"]) == 0
    assert script.prompts[0] == script.prompts[1]
    assert "Use YYYY-MM-DD" in capsys.readouterr().out
    assert cell(tracker_file, "D898") == "LinkedIn"  # blank = unknown: just the source


def test_guesses_are_offered_not_used_silently(tracker_file):
    guessed = JobDetails(posted_date=date(2026, 10, 8), company_guess="Beta Corp", position_guess="Dev")
    script = Script("", "Backend Engineer", "")  # Enter accepts the company guess; typing replaces the title
    assert run(tracker_file, "https://example.com/job/9", script, fetch=lambda u: guessed) == 0
    assert script.prompts[0:2] == ["Company [Beta Corp] (Enter = use this): ", "Position [Dev] (Enter = use this): "]
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



def test_company_typed_once_is_remembered_for_the_site(tracker_file, tmp_path, capsys):
    url = "https://umbrella.wd5.myworkdayjobs.com/en-US/UmbrellaCareers/job/Remote/Dev_JR1"
    no_company = lambda u: JobDetails(None, "Cloud Developer II", date(2026, 10, 8))  # noqa: E731
    first = Script("Umbrella Corporation", "s")
    assert run(tracker_file, url, first, fetch=no_company) == 0
    assert first.prompts[0] == "Company [Umbrella] (Enter = use this): "  # suggested from the link
    assert "Saved: umbrella.wd5.myworkdayjobs.com = Umbrella Corporation" in capsys.readouterr().out

    second = Script("")  # only the one question: the company isn't asked again
    assert run(tracker_file, url.replace("Dev_JR1", "Ops_JR2"), second, fetch=no_company) == 0
    assert second.prompts == [apply.PAUSE_PROMPT]
    assert cell(tracker_file, "A898") == "Umbrella Corporation"


def test_company_from_job_data_is_not_overridden_or_saved(tracker_file, tmp_path):
    url = "https://umbrella.wd5.myworkdayjobs.com/en-US/UmbrellaCareers/job/Remote/Dev_JR1"
    assert run(tracker_file, url, Script("")) == 0  # fetch_ok has a company
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
    assert prompt == apply.PAUSE_PROMPT  # nothing is asked between the card and the end
    assert ("Acme Robotics · Software Engineer I · Greenhouse\n\n"
            "Sponsorship:\n  We do not sponsor visas.\n\n"
            "Citizenship:\n  not mentioned\n\n"
            "Seniority:\n  Title: Software Engineer I\n  3+ years of Python.\n\n"
            "Posted:\n  October ") in out and " days ago)" in out  # date shown in my time zone
    assert out.index("Posted:") < out.index("Tracker: no matching link or job found.") < out.index("  URL:")


def test_skip_at_the_end_writes_nothing(tracker_file):
    before = tracker_file.read_bytes()
    script = Script("s")
    assert run(tracker_file, NEW_URL, script, fetch=lambda u: CARD_JOB) == 0
    assert script.prompts == [apply.PAUSE_PROMPT]
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
