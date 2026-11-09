"""Milestone 9: report.py, a read-only page of the tracker, on the fake tracker and a fake worksheet."""
import hashlib
import json
import re
import shutil
import subprocess
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

import tracker
from conftest import ROOT
from fake_sheet import HEADER, FakeWorksheet
from fake_tracker import SHUFFLED, make_tracker
from reporting import derive, load, metrics, render
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
            s.weeks_shown) == (70, 14, 30, 5, 20, 12)
    assert s.daily_target == 10  # 70 / 7, rounded up
    assert s.sources == ["Jobright", "Tsenta", "LinkedIn"]
    assert list(s.title_types) == ["Backend", "DevOps/Cloud/SRE/Platform", "AI/ML/Data", "Software (general)"]
    assert list(s.remark_tags) == ["No sponsorship", "Clearance/citizenship", "Referral"]


def test_settings_file_overrides_only_its_keys(tmp_path):
    path = tmp_path / "report.yaml"
    path.write_text("weekly_target: 10\nsources: [Handshake]\n", encoding="utf-8")
    s = load.load_settings(path)
    assert s.weekly_target == 10 and s.sources == ["Handshake"] and s.follow_up_days == 14


def test_daily_target_default_follows_the_weekly_target(tmp_path):
    path = tmp_path / "report.yaml"
    path.write_text("weekly_target: 15\n", encoding="utf-8")
    assert load.load_settings(path).daily_target == 3  # 15 / 7 = 2.1, rounded up
    path.write_text("weekly_target: 15\ndaily_target: 4\n", encoding="utf-8")
    assert load.load_settings(path).daily_target == 4
    assert Settings(weekly_target=14).daily_target == 2


def test_settings_unknown_key_is_named(tmp_path):
    path = tmp_path / "report.yaml"
    path.write_text("weekly_targe: 10\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="weekly_targe"):
        load.load_settings(path)


def test_repo_report_yaml_matches_the_defaults():
    from pathlib import Path
    assert load.load_settings(Path(__file__).resolve().parent.parent / "report.yaml") == Settings()


# ---------- derive ----------

def job(row=2, company="Acme", position="Software Engineer", url="https://jobs.lever.co/acme/1",
        posted="Posted today-Jobright", applied=date(2026, 10, 1), outcome="Applied", stage="",
        last_updated=None, remarks="", url_is_formula=False) -> Job:
    return Job(row, company, position, url, posted, applied, outcome, stage, last_updated, remarks, url_is_formula)


S = Settings()


@pytest.mark.parametrize("posted, source", [
    ("Posted today-Jobright", "Jobright"),
    ("Sameday- Tsenta", "Tsenta"),
    ("Posted October 8, 2026-linkedin", "LinkedIn"),
    ("Posted 2 days ago-Jobright via LinkedIn", "Jobright"),  # first of `sources`, not first in the text
    ("Posted today-Other", "Other"),
    ("Posted today", "Other"),
    ("", "Other"),
    ("Posted today-LinkedInish", "Other"),  # whole word only
])
def test_source(posted, source):
    assert derive.source(posted, S.sources) == source


@pytest.mark.parametrize("posted, named", [
    ("Posted today-Tsenta", True), ("Posted today-Other", True), ("Posted today", False), ("", False),
])
def test_source_named(posted, named):
    assert derive.source_named(posted, S.sources) is named


@pytest.mark.parametrize("url, system", [
    ("https://job-boards.greenhouse.io/acme/jobs/1", "Greenhouse"),
    ("https://jobs.ashbyhq.com/acme/1", "Ashby"),
    ("https://acme.wd5.myworkdayjobs.com/External/job/X_R1", "Workday"),
    ("https://careers-acme.icims.com/jobs/1/job", "iCIMS"),
    ("https://example.com/jobs/1", "Other"),
    ("", "Unknown"),
])
def test_job_system(url, system):
    assert derive.job_system(url) == system


@pytest.mark.parametrize("title, level", [
    ("Software Engineer I", "Early career"),
    ("Software Engineer 1", "Early career"),
    ("New Grad Software Engineer", "Early career"),
    ("Software Engineer, Early Career", "Early career"),
    ("Jr. Developer", "Early career"),
    ("Software Engineering Intern", "Early career"),
    ("Software Engineer II", "Other"),
    ("I/O Engineer", "Other"),  # " I" only as the last word
    ("Senior Software Engineer", "Other"),
    ("Internal Tools Engineer", "Other"),  # whole word: "intern" is not "internal"
    ("", "Other"),
])
def test_title_level(title, level):
    assert derive.title_level(title, S.early_career_words) == level


@pytest.mark.parametrize("title, kind", [
    ("Backend Software Engineer", "Backend"),  # Backend comes before Software (general)
    ("Software Engineer, API Platform", "Backend"),
    ("Site Reliability Engineer", "DevOps/Cloud/SRE/Platform"),
    ("Cloud Engineer I", "DevOps/Cloud/SRE/Platform"),
    ("AI Engineer", "AI/ML/Data"),
    ("Data Engineer", "AI/ML/Data"),
    ("SDE 1", "Software (general)"),
    ("Product Manager", "Other"),
    ("Email Marketing", "Other"),  # "ai" and "ml" as whole words only
])
def test_title_type(title, kind):
    assert derive.title_type(title, S.title_types) == kind


@pytest.mark.parametrize("outcome, stage, group", [
    ("In progress", "Online Assessment", "In progress"),
    ("Awaiting reply", "Interview", "Awaiting reply"),
    ("Rejected", "Initial Screening", "Rejected after response"),
    ("Rejected", "", "Rejected"),
    ("Applied", "", "No news"),
    ("", "", "No news"),
    ("Applied", "Interview", "Awaiting reply"),  # the old model: a Stage meant waiting on them
])
def test_status_group(outcome, stage, group):
    assert derive.status_group(outcome, stage) == group


def test_remark_tags():
    assert derive.remark_tags("10/02/2026 no visa sponsorship | referred by Sam", S.remark_tags) == [
        "No sponsorship", "Referral"]
    assert derive.remark_tags("US Citizens only", S.remark_tags) == ["Clearance/citizenship"]
    assert derive.remark_tags("", S.remark_tags) == []


def test_facts_of_a_row():
    j = job(company="Acme, Inc.", position="Backend Engineer I", posted="Posted today-Tsenta",
            applied=date(2026, 10, 8), outcome="Awaiting reply", stage="Interview",
            last_updated=date(2026, 10, 14), remarks="referral from Sam")
    f = derive.facts(j, S, TODAY)
    assert f.job is j
    assert (f.source, f.system, f.level, f.kind, f.responded, f.group) == (
        "Tsenta", "Lever", "Early career", "Backend", True, "Awaiting reply")
    assert (f.age, f.since_update, f.tags, f.company_key) == (20, 14, ["Referral"], "acme")


def test_facts_with_unknown_dates():
    f = derive.facts(job(applied=None, last_updated=None), S, TODAY)
    assert f.age is None and f.since_update is None and not f.responded and f.group == "No news"


# ---------- metrics ----------

def F(**kw) -> derive.Facts:
    return derive.facts(job(**kw), S, TODAY)


def d(month, day, year=2026):
    return date(year, month, day)


def test_change_text():
    assert metrics.change_text(19, 6) == "↑ 13 from last week"
    assert metrics.change_text(2, 5) == "↓ 3 from last week"
    assert metrics.change_text(4, 4) == "same as last week"


@pytest.mark.parametrize("r, n, text", [
    (5, 128, "5 of 128 (3.9%)"), (1, 20, "1 of 20 (5%)"), (0, 25, "0 of 25 (0%)"), (3, 12, "3 of 12"),
])
def test_rate_text(r, n, text):
    assert metrics.rate_text(r, n, 20) == text


WEEK_ROWS = [
    F(company="A", applied=d(10, 26)), F(company="B", applied=d(10, 28)), F(company="C", applied=d(10, 28)),
    F(company="D", applied=d(10, 19)), F(company="E", applied=d(10, 25)),  # last week
    F(company="F", applied=d(10, 18)), F(company="G", applied=None),
    F(company="Delta", applied=d(10, 1), outcome="Awaiting reply", stage="Interview", last_updated=d(10, 27)),
    F(company="Zeta", applied=d(10, 2), outcome="In progress", stage="Online Assessment", last_updated=d(10, 25)),
    F(company="Eta", applied=d(9, 2), outcome="Awaiting reply", stage="Initial Screening"),  # no Last Updated
]


def test_this_week():
    week = metrics.this_week(WEEK_ROWS, TODAY)
    assert (week.applications, week.last_week, week.in_progress, week.awaiting) == (3, 2, 1, 2)
    assert [f.job.company for f in week.new_responses] == ["Delta"]


def test_highlights_new_responses_this_week():
    assert metrics.highlights(WEEK_ROWS, S, TODAY) == [("response", "1 new response this week")]  # Delta
    two = [F(company="Acme", stage="Interview", outcome="In progress", last_updated=d(10, 26)),
           F(company="Zen", stage="Online Assessment", outcome="Awaiting reply", last_updated=d(10, 28)),
           F(company="Old", stage="Interview", outcome="Awaiting reply", last_updated=d(10, 25))]  # last week
    assert metrics.highlights(two, S, TODAY) == [("response", "2 new responses this week")]


def test_highlights_empty_tracker():
    assert metrics.highlights([], S, TODAY) == [("neutral", "No new responses this week")]
    assert metrics.highlights([F(applied=d(10, 28))], S, TODAY) == [("neutral", "No new responses this week")]


def test_highlights_rejections_today():
    rows = [F(outcome="Rejected", last_updated=d(10, 28)),
            F(outcome="Rejected", last_updated=d(10, 27)),  # yesterday: left out
            F(outcome="Rejected")]  # no Last Updated: left out
    assert metrics.highlights(rows, S, TODAY) == [("rejected", "1 rejection today"),
                                                  ("neutral", "No new responses this week")]
    rows.append(F(outcome="Rejected", stage="Interview", last_updated=d(10, 28)))  # also a new response
    assert metrics.highlights(rows, S, TODAY) == [("rejected", "2 rejections today"),
                                                  ("response", "1 new response this week")]


def _source_rows(source, n, responded, applied=d(1, 5)):
    return [F(company=f"{source} {i}", posted=f"Posted today-{source}", applied=applied,
              outcome="Rejected", stage="Interview" if i < responded else "") for i in range(n)]


def test_highlights_best_source():
    rows = _source_rows("Tsenta", 20, 2) + _source_rows("Jobright", 25, 2) + _source_rows("LinkedIn", 5, 3)
    assert metrics.highlights(rows, S, TODAY) == [
        ("neutral", "No new responses this week"),
        ("neutral", "Best source: Tsenta · 2 of 20"),  # 10% beats 8%; LinkedIn too few
    ]


def test_highlights_no_best_source():
    assert len(metrics.highlights(_source_rows("Tsenta", 30, 1), S, TODAY)) == 1  # only 1 response
    assert len(metrics.highlights(_source_rows("Tsenta", 19, 5), S, TODAY)) == 1  # under min_group


def test_today_count_and_order():
    rows = [F(row=5, company="Old", applied=d(10, 28)), F(row=9, company="New", applied=d(10, 28)),
            F(row=7, company="Mid", applied=d(10, 28)), F(row=8, company="Yesterday", applied=d(10, 27)),
            F(row=10, company="Tomorrow", applied=d(10, 29)), F(row=11, company="NoDate", applied=None)]
    t = metrics.today_facts(rows, TODAY)
    assert [f.job.company for f in t.applications] == ["New", "Mid", "Old"]  # most recently added first
    assert t.yesterday == 1
    assert metrics.today_facts(rows, d(10, 29)).applications[0].job.company == "Tomorrow"  # follows --today


@pytest.mark.parametrize("today_n, yesterday_n, text", [
    (4, 1, "↑ 3 from yesterday"), (1, 3, "↓ 2 from yesterday"), (2, 2, "same as yesterday"),
    (0, 0, "same as yesterday"), (0, 2, "↓ 2 from yesterday"), (3, 0, "↑ 3 from yesterday"),
])
def test_today_against_yesterday(today_n, yesterday_n, text):
    rows = [F(applied=d(10, 28))] * today_n + [F(applied=d(10, 27))] * yesterday_n
    t = metrics.today_facts(rows, TODAY)
    assert (len(t.applications), t.yesterday) == (today_n, yesterday_n)
    assert metrics.change_text(len(t.applications), t.yesterday, "yesterday") == text


def test_updates_today():
    rows = [F(row=2, company="NewApp", applied=d(10, 28), outcome="Applied", last_updated=d(10, 28)),  # new: out
            F(row=3, company="FastNo", applied=d(10, 28), outcome="Rejected", last_updated=d(10, 28)),
            F(row=4, company="Rej", outcome="Rejected", last_updated=d(10, 28)),
            F(row=5, company="Prog", outcome="In progress", stage="Interview", last_updated=d(10, 28)),
            F(row=6, company="Wait", outcome="Awaiting reply", last_updated=d(10, 28)),
            F(row=7, company="StageOnly", outcome="Applied", stage="Online Assessment", last_updated=d(10, 28)),
            F(row=8, company="Old", outcome="Rejected", last_updated=d(10, 27)),  # yesterday: out
            F(row=9, company="Blank", outcome="", last_updated=d(10, 28))]  # nothing set: out
    updates = metrics.today_facts(rows, TODAY).updates
    assert [f.job.company for f in updates] == ["StageOnly", "Wait", "Prog", "Rej", "FastNo"]  # highest row first
    assert metrics.today_facts(rows[:1] + rows[6:], TODAY).updates == []


ATTENTION_ROWS = [
    F(company="Beta", outcome="In progress", stage="Online Assessment", last_updated=d(10, 25)),
    F(company="Gamma", outcome="In progress", stage="Interview", last_updated=d(10, 18)),
    F(company="Nu", outcome="In progress", stage="Interview"),
    F(company="Omicron", outcome="Awaiting reply", stage="Initial Screening", last_updated=d(10, 10)),
    F(company="Delta", outcome="Awaiting reply", stage="Interview", last_updated=d(10, 1)),
    F(company="Zeta", outcome="Awaiting reply", stage="Online Assessment", last_updated=d(10, 20)),  # 8 days: fine
    F(company="Epsilon", outcome="Awaiting reply", stage="Initial Screening"),
    *[F(company="Acme Inc" if i < 3 else "Acme", applied=d(9, 1 + i)) for i in range(5)],
    *[F(company="Pi", applied=d(9, 1 + i)) for i in range(4)],
    F(company="Pi", outcome="Rejected", stage="Online Assessment"),  # one response: not flagged
    *[F(company="Rho", applied=d(9, 1 + i)) for i in range(4)],  # only 4
]


def test_attention_order():
    assert metrics.attention(ATTENTION_ROWS, S, TODAY) == [
        "Gamma: Interview to do since 10 days",
        "Beta: Online Assessment to do since 3 days",
        "Nu: Interview to do",
        "Delta: Interview, no reply for 27 days",
        "Omicron: Initial Screening, no reply for 18 days",
        "Epsilon: Initial Screening, waiting (date unknown)",
        "Acme: 5 applications, no response",
    ]


def test_attention_cap():
    lines = metrics.attention(ATTENTION_ROWS, S, TODAY)
    shown, more = metrics.cap(lines)
    assert shown == lines[:5] and more == lines[5:]
    assert metrics.cap(["a"]) == (["a"], [])
    assert metrics.attention([F()], S, TODAY) == []


def test_weekly_series():
    rows = [F(applied=d(10, 26), stage="Interview", outcome="Awaiting reply"), F(applied=d(10, 28)),
            F(applied=d(10, 19)), F(applied=d(8, 10)), F(applied=d(8, 9)), F(applied=None)]
    weeks = metrics.weekly(rows, S, TODAY)
    assert len(weeks) == 12
    assert weeks[0] == metrics.Week(d(8, 10), 1, 0)
    assert weeks[-2] == metrics.Week(d(10, 19), 1, 0)
    assert weeks[-1] == metrics.Week(d(10, 26), 2, 1)
    assert sum(w.applications for w in weeks) == 4


def test_monthly_table():
    rows = ([F(applied=d(9, 1 + i)) for i in range(17)]
            + [F(applied=d(9, 20), outcome="Rejected", stage="Interview"),
               F(applied=d(9, 21), outcome="Rejected"), F(applied=d(9, 22), outcome="Rejected")]
            + [F(applied=d(10, 2)), F(applied=d(10, 3), outcome="In progress", stage="Interview")]
            + [F(applied=d(7, 4)), F(applied=None)])
    assert metrics.monthly(rows, S) == [
        metrics.Month(d(10, 1), 2, 1, 0, "1 of 2"),
        metrics.Month(d(9, 1), 20, 1, 3, "1 of 20 (5%)"),
        metrics.Month(d(7, 1), 1, 0, 0, "0 of 1"),
    ]


def test_responses_newest_first():
    rows = [F(company="Old", applied=d(8, 1), stage="Interview", outcome="Rejected"),
            F(company="None", applied=None, stage="Interview", outcome="Awaiting reply"),
            F(company="New", applied=d(10, 1), stage="Online Assessment", outcome="In progress"),
            F(company="No stage", applied=d(10, 20))]
    assert [f.job.company for f in metrics.responses(rows)] == ["New", "Old", "None"]


def test_top_companies():
    rows = ([F(company="Acme Inc" if i % 2 else "Acme", applied=d(10, 16 + i)) for i in range(6)]  # last Oct 21
            + [F(company="Beta", applied=d(10, 18)), F(company="Beta", applied=d(10, 19)),
               F(company="Beta", applied=d(10, 20), outcome="In progress", stage="Online Assessment")]
            + [F(company="Gamma", applied=d(10, 20)), F(company="Gamma", applied=d(10, 21), outcome="Rejected"),
               F(company="Gamma", applied=d(10, 22), outcome="Rejected", stage="Interview")]
            + [F(company=f"S{i}", applied=d(10, i)) for i in range(1, 10)]
            + [F(company="", applied=d(10, 27))])
    top = metrics.top_companies(rows, S)
    assert [c.name for c in top] == ["Acme Inc", "Gamma", "Beta", "S9", "S8", "S7", "S6", "S5", "S4", "S3"]
    assert top[0] == metrics.CompanyRow("Acme Inc", 6, 0, 0, 0, d(10, 21), "muted")  # name of the newest row
    assert top[1] == metrics.CompanyRow("Gamma", 3, 1, 0, 2, d(10, 22), "green")
    assert top[2] == metrics.CompanyRow("Beta", 3, 1, 1, 0, d(10, 20), "green")
    assert top[3] == metrics.CompanyRow("S9", 1, 0, 0, 0, d(10, 9), "")


def test_no_reply():
    rows = [F(company="A", applied=d(9, 27)), F(company="B", applied=d(9, 28)),  # 31 days / exactly 30
            F(company="C", applied=d(8, 5)), F(company="D", applied=d(8, 20)),
            F(company="E", applied=d(8, 1), outcome="Rejected"),
            F(company="F", applied=d(7, 1), outcome="Awaiting reply", stage="Interview"),
            F(company="G", applied=d(7, 1), stage="Interview"), F(company="H", applied=None)]
    total, months = metrics.no_reply(rows, S, TODAY)
    assert total == 3
    assert [(m, [f.job.company for f in fs]) for m, fs in months] == [(d(9, 1), ["A"]), (d(8, 1), ["D", "C"])]


def test_details_tables():
    rows = ([F(posted="Posted today-Jobright", outcome="Rejected", stage="Interview" if i < 2 else "")
             for i in range(3)]
            + [F(posted="Posted today-Jobright") for _ in range(17)]
            + [F(posted="Posted today-Tsenta", remarks="no visa"), F(posted="Posted today-Tsenta")])
    tables = dict(metrics.details(rows, S))
    assert list(tables) == ["Source", "Job system", "Title level", "Title type", "Remark tags"]
    assert tables["Source"] == [metrics.GroupRow("Jobright", 20, 2, "10%", 3),
                                metrics.GroupRow("Tsenta", 2, 0, "too few to compare", 0)]
    assert tables["Remark tags"] == [metrics.GroupRow("No sponsorship", 1, 0, "too few to compare", 0)]
    assert tables["Job system"] == [metrics.GroupRow("Lever", 22, 2, "9.1%", 3)]


def test_data_check():
    rows = [F(row=2, company="Ok"),
            F(row=3, company="NoPos", position=""),
            F(row=4, company="NoUrl", url=""),
            F(row=5, company="NoSrc", posted="Posted today"),
            F(row=6, company="Formula", url_is_formula=True),
            F(row=7, company="Old", outcome="Applied", stage="Interview"),
            F(row=8, company="Stuck", outcome="In progress"),
            F(row=9, company="Other", posted="Posted today-Other")]
    issues = metrics.data_check(rows, S, excel=True)
    assert [(name, [(f.job.row, f.job.company) for f in fs]) for name, fs in issues] == [
        ("Blank Position", [(3, "NoPos")]),
        ("Blank URL", [(4, "NoUrl")]),
        ("No source found in Posted date/ Source", [(5, "NoSrc")]),
        ("URL stored as a formula", [(6, "Formula")]),
        ("Stage set but Outcome Applied", [(7, "Old")]),
        ("In progress with no Stage", [(8, "Stuck")]),
    ]
    assert "URL stored as a formula" not in dict(metrics.data_check(rows, S, excel=False))
    assert metrics.data_check([F()], S, excel=True) == []


def test_attention_items_kinds():
    items = metrics.attention_items(ATTENTION_ROWS, S, TODAY)
    assert [kind for kind, _ in items] == ["turn"] * 3 + ["follow"] * 3 + ["many"]
    assert [text for _, text in items] == metrics.attention(ATTENTION_ROWS, S, TODAY)


def test_totals():
    rows = [F(), F(), F(outcome="Rejected"),
            F(outcome="Awaiting reply", stage="Initial Screening"), F(outcome="Applied", stage="Interview"),
            F(outcome="In progress", stage="Online Assessment"), F(outcome="Rejected", stage="Interview")]
    assert metrics.totals(rows) == metrics.Totals(applied=7, responses=4, awaiting=2, rejected=2)


# Rows for every band of "Where your applications went" (TODAY = Oct 28, no_reply_days = 30).
FLOW_ROWS = [
    F(outcome="In progress", stage="Online Assessment"), F(outcome="In progress", stage="Online Assessment"),
    F(outcome="Awaiting reply", stage="Online Assessment"),
    F(outcome="Rejected", stage="Initial Screening"),
    F(outcome="Applied", stage="Interview"),  # old model: Stage set, Outcome Applied = awaiting reply
    F(outcome="In progress", stage="Interview"),
    F(outcome="Rejected"), F(outcome="Rejected"), F(outcome="Rejected"),  # rejected, no response
    F(applied=d(10, 20)), F(applied=d(10, 20)),  # 8 days
    F(applied=d(9, 28)),  # exactly 30 days: not over, like the "No reply" section
    F(applied=None),  # no readable Date: not counted as old
    F(outcome="", applied=d(10, 1)),  # blank Outcome, no Stage: no reply yet
    F(applied=d(9, 27)),  # 31 days
    F(outcome="Awaiting reply", applied=d(8, 1)),  # no Stage: no reply yet, 88 days
]


def columns(part):
    return [[(nd.key, nd.name, nd.count, nd.cls) for nd in col] for col in part.columns]


def bands(part):
    return [(b.source, b.target, b.count) for b in part.bands]


def test_flow_counts():
    f = metrics.flow(FLOW_ROWS, S)
    assert columns(f.left) == [
        [("all", "Applications", 16, "total")],
        [("responded", "Responded", 6, "responded"), ("rejected", "Rejected, no response", 3, "rejected"),
         ("quiet", "No reply yet", 7, "noreply")],
        [("new", "Under 30 days", 5, "new"), ("old", "30+ days", 2, "old")]]
    assert bands(f.left) == [("all", "responded", 6), ("all", "rejected", 3), ("all", "quiet", 7),
                             ("quiet", "new", 5), ("quiet", "old", 2)]
    assert f.responses == 6
    assert columns(f.right) == [
        [("responded", "Responded", 6, "responded")],
        [("stage:Online Assessment", "Online Assessment", 3, "responded"),
         ("stage:Initial Screening", "Initial Screening", 1, "responded"),
         ("stage:Interview", "Interview", 2, "responded")],
        [("outcome:In progress", "In progress", 3, "progress"),
         ("outcome:Awaiting reply", "Awaiting reply", 2, "awaiting"),
         ("outcome:Rejected after response", "Rejected", 1, "rejected")]]
    assert bands(f.right) == [
        ("responded", "stage:Online Assessment", 3), ("responded", "stage:Initial Screening", 1),
        ("responded", "stage:Interview", 2),
        ("stage:Online Assessment", "outcome:In progress", 2), ("stage:Online Assessment", "outcome:Awaiting reply", 1),
        ("stage:Initial Screening", "outcome:Rejected after response", 1),
        ("stage:Interview", "outcome:In progress", 1), ("stage:Interview", "outcome:Awaiting reply", 1)]


def test_flow_leaves_out_empty_nodes_and_bands():
    f = metrics.flow([F(applied=d(10, 20)), F(outcome="Awaiting reply", stage="Interview")], S)
    assert columns(f.left) == [[("all", "Applications", 2, "total")],
                               [("responded", "Responded", 1, "responded"), ("quiet", "No reply yet", 1, "noreply")],
                               [("new", "Under 30 days", 1, "new")]]
    assert bands(f.left) == [("all", "responded", 1), ("all", "quiet", 1), ("quiet", "new", 1)]
    assert columns(f.right)[1:] == [[("stage:Interview", "Interview", 1, "responded")],
                                    [("outcome:Awaiting reply", "Awaiting reply", 1, "awaiting")]]
    assert bands(f.right) == [("responded", "stage:Interview", 1), ("stage:Interview", "outcome:Awaiting reply", 1)]


def test_flow_split_follows_no_reply_days():
    rows = [F(applied=d(10, 20)), F(applied=d(10, 17)), F(applied=d(10, 1))]  # 8, 11, 27 days
    f = metrics.flow(rows, Settings(no_reply_days=10))
    assert columns(f.left)[2] == [("new", "Under 10 days", 1, "new"), ("old", "10+ days", 2, "old")]
    assert metrics.no_reply(rows, Settings(no_reply_days=10), TODAY)[0] == 2  # the same rule


def test_flow_other_stage_after_the_known_ones():
    f = metrics.flow([F(stage="Phone call", outcome="In progress"), F(stage="Interview", outcome="In progress")], S)
    assert [nd.name for nd in f.right.columns[1]] == ["Interview", "Phone call"]


def test_flow_no_responses_and_no_rows():
    f = metrics.flow([F(), F(outcome="Rejected")], S)
    assert f.right is None and f.responses == 0
    assert [nd.key for nd in f.left.columns[1]] == ["rejected", "quiet"]
    assert metrics.flow([], S) is None


def test_top_companies_rejected_with_no_response():
    rows = [F(company="Gamma", outcome="Rejected"), F(company="Gamma", outcome="Rejected", stage="Interview"),
            F(company="Gamma", outcome="Rejected"), F(company="Gamma")]
    gamma = metrics.top_companies(rows, S)[0]
    assert (gamma.applications, gamma.responses, gamma.rejected, gamma.rejected_silent) == (4, 1, 3, 2)


# ---------- render ----------

SECTIONS = ["search", "highlights", "today", "this-week", "totals", "attention", "weekly", "flow", "monthly", "responses", "top",
            "no-reply", "details", "data-check"]
HEADINGS = ["Search", "Highlights", "Today", "This week", "Totals", "Needs your attention", "Weekly",
            "Where your applications went", "Monthly", "Your responses (", "Top 10 companies, with outcomes", "No reply after 30 days", "More details",
            "Data check ("]
GENERATED = datetime(2026, 10, 28, 9, 5)


def page(rows, excel=True):
    return render.page(rows, S, TODAY, excel=excel, source_name="tracker.xlsx", generated=GENERATED)


def section(html, name):
    return re.search(rf'<section id="{name}".*?</section>', html, re.S).group(0)


SEARCH_SCRIPTS = re.compile(r'<script type="application/json" id="search-data">.*?</script>\s*<script>.*?</script>', re.S)


def without_search_scripts(html):
    """The page minus the search box's two script blocks (checked on their own in the search tests)."""
    assert len(SEARCH_SCRIPTS.findall(html)) == 1
    return SEARCH_SCRIPTS.sub("", html)


def test_sections_in_order():
    html = page(ATTENTION_ROWS + WEEK_ROWS)
    assert re.findall(r'<section id="([^"]+)"', html) == SECTIONS
    headings = re.findall(r"<h2[^>]*>(.*?)</h2>", html)
    assert len(headings) == len(HEADINGS)
    for heading, start in zip(headings, HEADINGS):
        assert heading.startswith(start), (heading, start)
    assert "Your responses (11)" in headings[9]


def test_sections_present_with_no_rows():
    html = page([])
    assert re.findall(r'<section id="([^"]+)"', html) == SECTIONS
    assert "No applications yet." in section(html, "monthly") and "No responses yet." in section(html, "responses")
    assert "No applications yet." in section(html, "flow") and "<svg" not in section(html, "flow")


def test_tracker_text_is_escaped():
    bad = "<script>alert(1)</script>"
    html = page([F(company=bad, position="A & B", stage="Interview", outcome="In progress", remarks="<b>x</b>",
                   posted=f"Posted today-{bad}")] * 5)
    assert "<script" not in without_search_scripts(html)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in section(html, "responses")  # card
    assert "<title>&lt;script&gt;alert(1)&lt;/script&gt;: 5 applications" in section(html, "top")  # SVG title
    assert "&lt;script&gt;alert(1)&lt;/script&gt;: Interview to do" in section(html, "attention")  # chip
    assert "A &amp; B" in html


def test_no_external_requests():
    html = without_search_scripts(page(ATTENTION_ROWS + WEEK_ROWS + [F(company="Bad", url="javascript:alert(1)",
                                                                       stage="Interview")]))
    for banned in ("<script", "<link", "@import", "url(", "javascript:", "<iframe", "<img", "src="):
        assert banned not in html.lower(), banned
    links = re.findall(r'<a href="([^"]*)"[^>]*>', html)
    assert links and all(u.startswith("https://") for u in links)
    assert all('target="_blank"' in a and 'rel="noopener noreferrer"' in a for a in re.findall(r"<a [^>]*>", html))
    without_links = re.sub(r'<a href="[^"]*"', "", html)
    assert "http" not in without_links


def test_css_is_embedded_with_tokens_and_dark_mode():
    css = re.search(r"<style>(.*)</style>", page([]), re.S).group(1)
    assert css.index(":root {") < css.index("body {")
    assert all(f"--{token}:" in css for token in ("green", "blue", "amber", "red", "grey", "radius", "space-4",
                                                    "text-base"))
    assert "@media (prefers-color-scheme: dark)" in css


def test_job_link_shows_the_domain():
    html = page([F(url="https://www.jobs.lever.co/acme/1", stage="Interview", outcome="Awaiting reply")])
    assert re.search(r'<a href="https://www.jobs.lever.co/acme/1"[^>]*>jobs.lever.co</a>', section(html, "responses"))


def test_this_week_progress_and_badge():
    html = page(WEEK_ROWS)
    week = section(html, "this-week")
    assert '<span class="big">3</span><span class="of">of 70</span>' in week
    assert '<span class="badge up">↑ 1 from last week</span>' in week
    assert 'style="width: 4%"' in week
    assert "1 new response · 1 in progress" in week
    over = section(page([F(applied=d(10, 27))] * 75), "this-week")
    assert 'style="width: 100%"' in over and '<span class="big">75</span>' in over
    assert '<span class="badge down">↓ 2 from last week</span>' in page([F(applied=d(10, 20))] * 2)
    assert '<span class="badge same">same as last week</span>' in page([])


def today_items(html):
    return re.findall(r'<li><span class="today-company">([^<]*)</span> <span class="today-sep">·</span> '
                      r'<span class="today-position">([^<]*)</span></li>', html)


def test_today_card():
    rows = [F(row=r, company=f"C{r}", position=f"Role {r}", applied=d(10, 28)) for r in range(2, 12)]  # 10 today
    rows += [F(applied=d(10, 27))] * 3
    card = section(page(rows), "today")
    assert '<span class="big">10</span><span class="of">of 10</span>' in card
    assert '<span class="badge up">↑ 7 from yesterday</span>' in card and 'style="width: 100%"' in card
    shown, more = card.split('<details class="more">')
    assert today_items(shown) == [(f"C{r}", f"Role {r}") for r in range(11, 3, -1)]  # 8, newest first
    assert "<summary>+2 more</summary>" in more and today_items(more) == [("C3", "Role 3"), ("C2", "Role 2")]
    assert "Updates today" not in card and "today-pills" not in card  # new applications are not updates


def test_today_card_empty_and_updates():
    card = section(page([F(applied=d(10, 27)), F(company="<b>Zen</b>", stage="Interview", outcome="In progress",
                                                  last_updated=d(10, 28))]), "today")
    assert '<span class="big">0</span>' in card and '<span class="badge down">↓ 1 from yesterday</span>' in card
    assert "No applications yet today." in card and "more</summary>" not in card
    assert re.search(r'<h3 class="mini">Updates today \(1\)</h3>', card)
    assert update_items(card) == [("&lt;b&gt;Zen&lt;/b&gt;", "Software Engineer", "progress", "In progress",
                                   "Interview")]
    few = section(page([F(row=3, company="A & B", applied=d(10, 28))]), "today")
    assert today_items(few) == [("A &amp; B", "Software Engineer")] and "<details" not in few


def update_items(html):
    return re.findall(r'<li><span class="today-company">([^<]*)</span> <span class="today-sep">·</span> '
                      r'<span class="today-position">([^<]*)</span><span class="today-pills">'
                      r'<span class="pill (\w+)">([^<]*)</span>(?:<span class="pill stage">([^<]*)</span>)?</span></li>',
                      html)


def test_today_updates_pills_and_cap():
    outcomes = ["Rejected", "In progress", "Awaiting reply", "Applied"]
    rows = [F(row=r, company=f"U{r}", position=f"Role {r}", outcome=outcomes[r % 4],
              stage="Interview" if r % 2 else "", last_updated=d(10, 28)) for r in range(2, 12)]  # 10 updates
    card = section(page(rows), "today")
    updates = card.split('<div class="updates">')[1]
    assert '<h3 class="mini">Updates today (10)</h3>' in updates
    shown, more = updates.split('<details class="more">')
    assert [(c, cls, o, st) for c, _, cls, o, st in update_items(shown)] == [
        ("U11", "waiting", "Applied", "Interview"), ("U10", "followup", "Awaiting reply", ""),
        ("U9", "progress", "In progress", "Interview"), ("U8", "rejected", "Rejected", ""),
        ("U7", "waiting", "Applied", "Interview"), ("U6", "followup", "Awaiting reply", ""),
        ("U5", "progress", "In progress", "Interview"), ("U4", "rejected", "Rejected", "")]
    assert "<summary>+2 more</summary>" in more and [u[0] for u in update_items(more)] == ["U3", "U2"]
    assert '<span class="pill stage"></span>' not in card  # no empty Stage pill


def test_highlight_chips():
    rows = WEEK_ROWS + [F(outcome="Rejected", last_updated=d(10, 28))] + _source_rows("Tsenta", 20, 2)
    hl = section(page(rows), "highlights")
    assert re.findall(r'<li class="highlight (\w+)">([^<]+)</li>', hl) == [
        ("rejected", "1 rejection today"), ("response", "1 new response this week"),
        ("neutral", "Best source: Tsenta · 2 of 20")]
    assert re.findall(r'<li class="highlight (\w+)">', section(page([]), "highlights")) == ["neutral"]
    html = page(WEEK_ROWS)
    assert "Today: " not in html and "This week: " not in html and "awaiting reply." not in html  # no sentences


def test_stat_tiles():
    tiles = section(page(WEEK_ROWS + [F(outcome="Rejected")]), "totals")
    found = re.findall(r'<div class="tile ?([a-z]*)"><span class="tile-value">(\d+)</span>'
                       r'<span class="tile-label">([^<]+)</span>', tiles)
    assert found == [("", "11", "Applied"), ("response", "3", "Responses"), ("waiting", "2", "Awaiting reply"),
                     ("rejected", "1", "Rejected")]


def chips(html):
    return re.findall(r'<li class="chip (\w+)"><span class="chip-kind">([^<]+)</span> <span class="chip-text">'
                      r'([^<]+)</span>', html)


def test_attention_chips_by_type():
    att = section(page(ATTENTION_ROWS), "attention")
    assert chips(att) == [
        ("turn", "Your turn", "Gamma: Interview to do since 10 days"),
        ("turn", "Your turn", "Beta: Online Assessment to do since 3 days"),
        ("turn", "Your turn", "Nu: Interview to do"),
        ("follow", "Follow up", "Delta: Interview, no reply for 27 days"),
        ("follow", "Follow up", "Omicron: Initial Screening, no reply for 18 days"),
        ("follow", "Follow up", "Epsilon: Initial Screening, waiting (date unknown)"),
        ("many", "Many applications", "Acme: 5 applications, no response"),
    ]
    assert "more</summary>" not in att
    assert "Nothing needs your attention." in page([F()])


def test_attention_many_applications_capped_at_3():
    rows = [F(company=f"Many{i}", applied=d(9, 1 + j)) for i in range(5) for j in range(5)]
    rows.append(F(company="Beta", outcome="In progress", stage="Interview"))
    shown, more = section(page(rows), "attention").split('<details class="more">')
    assert [c[0] for c in chips(shown)] == ["turn", "many", "many", "many"]
    assert "<summary>+2 more</summary>" in more and [c[0] for c in chips(more)] == ["many", "many"]


def charts(html):
    """{"wide": svg, "narrow": svg}: each chart is drawn twice, CSS shows one by window width."""
    return {m.group(1): m.group(0) for m in re.finditer(r'<svg class="chart (\w+)".*?</svg>', html, re.S)}


def test_weekly_chart():
    weekly = section(page(WEEK_ROWS + [F(applied=d(10, 20))] * 70), "weekly")
    svg = charts(weekly)
    assert list(svg) == ["wide", "narrow"]
    for chart in svg.values():
        assert chart.count('<rect class="bar') == 12
        assert chart.count('<rect class="bar hit"') == 1  # last week: 72 of 70
        assert "<title>Week of Oct 26: 3 applications, 0 responses</title>" in chart
        assert 'class="target"' in chart and ">Oct 26<" in chart
    assert ">Oct 19<" in svg["wide"] and ">Oct 19<" not in svg["narrow"]  # every other week labelled on phones
    assert "Show numbers" in weekly


def test_monthly_chart():
    rows = ([F(applied=d(9, 1 + i)) for i in range(17)] + [F(applied=d(9, 20), outcome="Rejected", stage="Interview")]
            + [F(applied=d(10, 2)), F(applied=d(10, 3), outcome="In progress", stage="Interview")]
            + [F(applied=date(2025, m, 3)) for m in (1, 11, 12)] + [F(applied=d(m, 3)) for m in range(1, 9)])
    monthly = section(page(rows), "monthly")
    chart_part, numbers = monthly.split("Show numbers")
    assert "<table" not in chart_part and "<table" in numbers
    svg = charts(chart_part)
    assert list(svg) == ["wide", "narrow"]
    for chart in svg.values():
        assert chart.count('<rect class="bar"') == 12 and chart.count('<rect class="resp"') == 12  # last 12 months
        assert "<title>October 2026: 2 applications</title>" in chart
        assert "<title>September 2026: 1 response (1 of 18)</title>" in chart
    assert "<td>January 2025</td>" in numbers  # every month in the numbers table
    wide = svg["wide"]
    assert ">Nov 2025<" in wide and ">Jan 2026<" in wide and ">Feb<" in wide  # a year on the first and each Jan


def sankeys(html):
    """{"wide": svg, "narrow": svg} of the flow section."""
    return {m.group(1): m.group(0)
            for m in re.finditer(r'<svg class="chart sankey (\w+)".*?</svg>', section(html, "flow"), re.S)}


def labels(svg):
    """Each node's label, its lines joined with a space."""
    return [" ".join(re.findall(r"<tspan[^>]*>([^<]*)</tspan>", t))
            for t in re.findall(r'<text class="sk-label">(.*?)</text>', svg)]


def test_flow_section():
    html = page(FLOW_ROWS)
    flow = section(html, "flow")
    svg = sankeys(html)
    assert list(svg) == ["wide", "narrow"]
    for shape, chart in svg.items():
        assert labels(chart) == [
            "Applications · 16", "Responded · 6", "Rejected, no response · 3", "No reply yet · 7",
            "Under 30 days · 5", "30+ days · 2",
            "Responded · 6", "Online Assessment · 3", "Initial Screening · 1", "Interview · 2",
            "In progress · 3", "Awaiting reply · 2", "Rejected · 1"], shape
        assert chart.count('<path class="sk-band') == 5 + 8  # every band with rows, nothing else
        assert chart.count('<rect class="sk-node') == 6 + 7
        assert "<title>Applications -&gt; Responded: 6</title>" in chart
        assert "<title>No reply yet -&gt; Under 30 days: 5</title>" in chart
        assert "<title>Online Assessment -&gt; Awaiting reply: 1</title>" in chart
        assert '<path class="sk-bracket"' in chart and ">zoomed in: 6 responses</text>" in chart
        for cls in ("sk-total", "sk-responded", "sk-rejected", "sk-noreply", "sk-new", "sk-old", "sk-progress",
                    "sk-awaiting"):
            assert f'class="sk-node {cls}"' in chart, cls
    assert "Stage shows the furthest step each application reached. The right side is zoomed in." in flow
    assert "No responses yet." not in flow
    assert html.index('id="weekly"') < html.index('id="flow"') < html.index('id="monthly"')
    assert 'class="pipeline"' not in html and "step-value" not in html  # the strip is gone


def test_flow_section_without_responses():
    html = page([F(), F(outcome="Rejected")])
    flow = section(html, "flow")
    for chart in sankeys(html).values():
        assert labels(chart) == ["Applications · 2", "Rejected, no response · 1", "No reply yet · 1",
                                 "Under 30 days · 1"]  # F() applied Oct 1: 27 days
        assert "sk-bracket" not in chart and "zoomed in" not in chart
    assert "No responses yet." in flow and "zoomed in" not in flow and "The right side" not in flow


def test_flow_labels_wrap_on_phones():
    narrow = sankeys(page(FLOW_ROWS))["narrow"]
    assert "<tspan" in narrow and ">Rejected, no</tspan>" in narrow and ">response · 3</tspan>" in narrow


def test_flow_tracker_text_is_escaped():
    html = page([F(stage="<script>alert(1)</script>", outcome="In progress"), F()])
    assert "<script" not in without_search_scripts(html)
    chart = sankeys(html)["wide"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt; · 1" in chart
    assert "<title>Responded -&gt; &lt;script&gt;alert(1)&lt;/script&gt;: 1</title>" in chart


def test_flow_no_external_requests():
    flow = section(page(FLOW_ROWS), "flow")
    for banned in ("<script", "<link", "@import", "url(", "javascript:", "<img", "src=", "href", "http"):
        assert banned not in flow.lower(), banned


def part(cols, bands_):
    return metrics.FlowPart([[metrics.FlowNode(k, k, c, "total") for k, c in col] for col in cols],
                            [metrics.FlowBand(a, b, c) for a, b, c in bands_])


def test_flow_bands_and_nodes_at_least_3px():
    tiny = part([[("all", 10_000)], [("big", 9_999), ("one", 1)]], [("all", "big", 9_999), ("all", "one", 1)])
    for wrap in (None, 18):
        p_ = render.sankey_part(tiny, 0, 40, 220, wrap)
        assert min(b["w"] for b in p_["bands"]) == render.SK_MIN
        assert all(float(nd["h"]) >= render.SK_MIN for nd in p_["nodes"])
        one = next(b for b in p_["bands"] if b["tip"] == "all -> one: 1")
        assert one["w"] == 3


def test_band_width_proportional_within_its_part():
    p_ = render.sankey_part(part([[("all", 30)], [("a", 20), ("b", 10)]], [("all", "a", 20), ("all", "b", 10)]),
                            0, 40, 220, None)
    a, b = (next(x["w"] for x in p_["bands"] if x["tip"].startswith(f"all -> {k}")) for k in "ab")
    assert a == pytest.approx(2 * b)


LONG = "Very Long Stage Name For A Small Company Process"


@pytest.mark.parametrize("shape", [render.WIDE, render.NARROW])
def test_flow_labels_never_overlap(shape):
    rows = FLOW_ROWS + [F(stage=f"{LONG} {i}", outcome=o) for i in range(3)
                        for o in ("In progress", "Rejected", "Awaiting reply")]
    rows += [F(applied=d(10, 27))] * 400  # one big band next to small ones
    chart = render.sankey(metrics.flow(rows, S), shape)
    boxes, rects = [], []
    for p_ in chart["parts"]:
        for nd in p_["nodes"]:
            boxes.append(nd["box"])
            x, y, h = float(nd["x"]), float(nd["y"]), float(nd["h"])
            rects.append(render.Box(x, y, x + nd["w"], y + h))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not a.overlaps(b), (a, b)
        for r in rects:
            assert not a.overlaps(r), (a, r)  # a label never covers a node
    if chart["bracket"]:
        note = render.Box(float(chart["bracket"]["x"]), float(chart["bracket"]["y"]) - render.SK_FONT,
                          float(chart["bracket"]["x"]) + len(chart["bracket"]["text"]) * render.SK_CHAR,
                          float(chart["bracket"]["y"]) + 3)
        assert not any(note.overlaps(b) for b in boxes + rects)
    assert all(b.x0 >= 0 and b.x1 <= chart["width"] and b.y0 >= 0 and b.y1 <= chart["height"] for b in boxes)


def test_response_cards_and_pills():
    rows = [F(company="Prog", applied=d(10, 5), outcome="In progress", stage="Interview"),
            F(company="Wait", applied=d(10, 4), outcome="Awaiting reply", stage="Interview", last_updated=d(10, 20)),
            F(company="Late", applied=d(10, 3), outcome="Awaiting reply", stage="Initial Screening",
              last_updated=d(10, 1)),
            F(company="Rej", applied=d(10, 2), outcome="Rejected", stage="Online Assessment"),
            F(company="None", applied=d(10, 1))]
    cards = section(page(rows), "responses")
    assert "<table" not in cards
    found = re.findall(r'<h3>([^<]+)</h3>.*?<span class="pill stage">([^<]+)</span><span class="pill (\w+)">([^<]+)<',
                       cards, re.S)
    assert found == [("Prog", "Interview", "progress", "In progress"),
                     ("Wait", "Interview", "waiting", "Awaiting reply"),
                     ("Late", "Initial Screening", "followup", "Awaiting reply"),
                     ("Rej", "Online Assessment", "rejected", "Rejected")]
    assert cards.count("<details><summary>Details</summary>") == 4
    assert "<dt>Source</dt><dd>Jobright</dd><dt>Job system</dt><dd>Lever</dd><dt>Applied</dt><dd>10/05/2026</dd>" in cards
    assert "<dt>Last Updated</dt><dd>10/20/2026</dd>" in cards and "<dt>Link</dt>" in cards


def test_remark_lines():
    assert render.remark_lines("a | 10/27/2026 b |  | c ") == ["a", "10/27/2026 b", "c"]
    assert render.remark_lines("") == [] and render.remark_lines(" | ") == []


def test_response_card_remarks_closed_and_one_line_per_note():
    rows = [F(company="Noted", applied=d(10, 5), outcome="In progress", stage="Interview",
              remarks="referred by Sam | 10/27/2026 OA sent"),
            F(company="Blank", applied=d(10, 4), outcome="Awaiting reply", stage="Interview")]
    cards = re.findall(r'<article class="response-card">.*?</article>', section(page(rows), "responses"), re.S)
    noted, blank = cards
    details = re.search(r"<details>.*</details>", noted, re.S).group(0)  # inside the closed Details
    assert "<details open" not in noted
    assert ('<dt>Remarks</dt><dd><span class="remark">referred by Sam</span>'
            '<span class="remark">10/27/2026 OA sent</span></dd>') in details
    assert "<dt>Remarks</dt>" not in blank


def test_top_companies_bars():
    rows = ([F(company="Gamma", applied=d(10, 20)), F(company="Gamma", applied=d(10, 21), outcome="Rejected"),
             F(company="Gamma", applied=d(10, 22), outcome="Rejected", stage="Interview")]
            + [F(company="Acme", applied=d(9, 1 + i)) for i in range(6)])
    top = section(page(rows), "top")
    assert re.findall(r'<li class="company ?(\w*)">\s*<span class="company-name">([^<]+)</span>', top) == [
        ("muted", "Acme"), ("green", "Gamma")]
    assert '<span class="company-text">3 · 1 response · 2 rejected</span>' in top
    assert '<span class="company-text">6 · 0 responses · 0 rejected</span>' in top
    assert ("<title>Gamma: 3 applications, 1 response, 0 in progress or awaiting, 2 rejected, "
            "last applied 10/22/2026</title>") in top
    gamma = top.split('<span class="company-name">Gamma</span>')[1]
    widths = re.findall(r'<rect class="seg-(\w+)" x="[\d.]+" y="0" width="([\d.]+)"', gamma)
    assert widths == [("response", "16.7"), ("rejected", "16.7"), ("rest", "16.7")]  # 1 + 1 + 1 of 6


def test_collapsed_sections_kept():
    html = page([F(company="Old", applied=d(8, 1))])
    assert "1 application with no reply after 30 days." in section(html, "no-reply")
    assert "<summary><h2>More details</h2></summary>" in section(html, "details")
    assert "<summary><h2>Data check (0)</h2></summary>" in section(html, "data-check")


def test_footer_and_empty_tracker():
    html = page([])
    assert "Generated 10/28/2026 9:05 AM from tracker.xlsx · 0 rows" in html
    assert "Data check (0)" in html


# ---------- report.py ----------

def dt(month, day):
    return datetime(2026, month, day)


PLANTED = [
    {"Company": "Beta", "Position": "Backend Engineer I", "Posted date/ Source": "Posted today-Jobright",
     "Date": dt(10, 20), "Outcome": "In progress", "Stage": "Online Assessment", "Last Updated": dt(10, 27)},
    {"Company": "Gamma", "Position": "Data Engineer", "Posted date/ Source": "Sameday- Tsenta",
     "Date": dt(10, 26), "Outcome": "In progress", "Stage": "Interview"},
    {"Company": "Delta", "Position": "SRE", "Posted date/ Source": "Posted October 1, 2026-LinkedIn",
     "Date": dt(9, 1), "Outcome": "Awaiting reply", "Stage": "Interview", "Last Updated": dt(10, 1)},
    {"Company": "Epsilon", "Position": "Cloud Engineer", "Posted date/ Source": "Posted today-Jobright",
     "Date": dt(9, 2), "Outcome": "Awaiting reply", "Stage": "Initial Screening"},
    {"Company": "Eta", "Position": "Software Engineer", "Posted date/ Source": "Posted today-Tsenta",
     "Date": dt(8, 3), "Outcome": "Rejected", "Stage": "Interview", "Last Updated": dt(9, 10),
     "Remarks": "09/10/2026 no sponsorship"},
    *[{"Company": "Acme" if day == 27 else "Acme Inc", "Position": f"Engineer {day}",
       "Posted date/ Source": "Posted today-LinkedIn", "Date": dt(10, day), "Outcome": "Applied"}
      for day in (1, 5, 8, 12, 15, 27)],
    {"Company": "Kappa", "Position": "Platform Engineer", "URL": '=HYPERLINK("https://jobs.lever.co/kappa/1", "apply")',
     "Posted date/ Source": "Posted today-Jobright", "Date": dt(10, 2), "Outcome": "Applied"},
    {"Company": "Iota", "Position": None, "Posted date/ Source": "Posted today-Jobright", "Date": dt(10, 3),
     "Outcome": "Applied"},
]


@pytest.fixture
def report_env(tmp_path, monkeypatch):
    """report.py with the default settings, its page in tmp_path and the browser recorded, not opened."""
    import report

    opened = []
    monkeypatch.setattr(report, "DEFAULT_SETTINGS", tmp_path / "no-report.yaml")
    monkeypatch.setattr(report, "DEFAULT_OUT", tmp_path / "report.html")
    monkeypatch.setattr(report.webbrowser, "open", opened.append)
    return report, tmp_path / "report.html", opened


def test_report_end_to_end(tracker_file, report_env):
    report, out, opened = report_env
    plant(tracker_file, PLANTED)
    before = _fingerprint(tracker_file)
    assert report.main(["--tracker", str(tracker_file), "--no-open", "--today", "2026-10-28"]) == 0
    assert _fingerprint(tracker_file) == before  # never written
    assert opened == []
    html = out.read_text(encoding="utf-8")
    for text in [
        '<span class="big">0</span><span class="of">of 10</span>',
        "No applications yet today.",
        '<span class="big">2</span><span class="of">of 70</span>',
        '<li class="highlight response">1 new response this week</li>',
        "Beta: Online Assessment to do since 1 day",
        "Gamma: Interview to do",
        "Delta: Interview, no reply for 27 days",
        "Epsilon: Initial Screening, waiting (date unknown)",
        "Acme: 6 applications, no response",
        "Your responses (5)",
        "URL stored as a formula (1)",
        "Blank Position (1)",
        "Data check (2)",
        "from tracker.xlsx · 896 rows",
        "Applications · 896",
        "Responded · 5",
        "zoomed in: 5 responses",
    ]:
        assert text in html, text
    assert "+1 more" not in html and "<script" not in without_search_scripts(html) and "Updates today" not in html
    assert '<a href="https://example.com/jobs/4" target="_blank" rel="noopener noreferrer">example.com</a>' in html


def test_report_opens_the_page(tracker_file, report_env):
    report, out, opened = report_env
    assert report.main(["--tracker", str(tracker_file), "--today", "2026-10-28"]) == 0
    assert opened == [out.resolve().as_uri()]


def test_report_from_the_sheet(report_env):
    report, out, _ = report_env
    ws = FakeWorksheet([
        HEADER,
        ["Acme", "SWE", "apply", "Posted today-Tsenta", "10/27/2026", "Awaiting reply", "Interview", "10/27/2026",
         "", "", ""],
        ["Zen", "SDE", "https://jobs.lever.co/zen/1", "LinkedIn", "10/1/2026", "Applied", "", "", "", "", ""],
    ], formulas={2: '=HYPERLINK("https://jobs.ashbyhq.com/acme/1", "apply")'})
    assert report.main(["--sheet", "--no-open", "--today", "2026-10-28"], sheet_ws=ws) == 0
    html = out.read_text(encoding="utf-8")
    assert "from the Google Sheet · 2 rows" in html
    assert '<li class="highlight response">1 new response this week</li>' in html
    assert '<a href="https://jobs.ashbyhq.com/acme/1"' in html
    assert "URL stored as a formula" not in html
    assert ws.updates == []


def test_report_sheet_not_configured(report_env, capsys):
    report, out, _ = report_env
    assert report.main(["--sheet", "--no-open"]) == 2
    assert "sheet_id" in capsys.readouterr().out and not out.exists()


def test_report_missing_tracker(tmp_path, report_env, capsys):
    report, out, _ = report_env
    assert report.main(["--tracker", str(tmp_path / "nope.xlsx"), "--no-open"]) == 2
    assert "Tracker not found" in capsys.readouterr().out and not out.exists()


def test_report_missing_header(tracker_file, report_env, capsys):
    report, out, _ = report_env
    wb = load_workbook(tracker_file)
    wb["Sheet1"]["G1"] = "Stg"
    wb.save(tracker_file)
    assert report.main(["--tracker", str(tracker_file), "--no-open"]) == 2
    assert "Stage" in capsys.readouterr().out and not out.exists()


def test_report_out_must_be_html(tracker_file, report_env, capsys):
    report, _, _ = report_env
    before = _fingerprint(tracker_file)
    assert report.main(["--tracker", str(tracker_file), "--out", str(tracker_file), "--no-open"]) == 2
    assert ".html" in capsys.readouterr().out
    assert _fingerprint(tracker_file) == before



# ---------- 0. search ----------

SEARCH_FIELDS = {"company", "company_key", "position", "position_key", "applied", "outcome", "outcome_cls", "stage",
                 "domain", "href", "remarks"}


def search_block(html):
    return re.search(r'<script type="application/json" id="search-data">(.*?)</script>', html, re.S).group(1)


def search_json(html):
    return json.loads(search_block(html))


def test_search_data_rows_and_fields():
    rows = [F(row=2, company="Acme, Inc.", position="Data Engineer", applied=d(10, 1), stage="Interview",
              outcome="In progress"),
            F(row=3, company="Globex", position="SRE", applied=None, url="javascript:alert(1)"),
            F(row=4, company="ACME", position="Backend Engineer", applied=d(10, 20), outcome="Rejected",
              remarks="referred by Sam | 10/22/2026 rejected by email"),
            F(row=5, company="Initech LLC", position="S&P Analyst", applied=d(10, 20), outcome="",
              url="https://www.boards.greenhouse.io/initech/jobs/5")]
    data = search_json(page(rows))
    assert data["suffixes"] == sorted(tracker.COMPANY_SUFFIXES)
    assert all(set(r) == SEARCH_FIELDS for r in data["rows"])
    # newest applied first; same day: highest row (the last added) first; no Date last
    assert [r["company"] for r in data["rows"]] == ["Initech LLC", "ACME", "Acme, Inc.", "Globex"]
    initech, acme_upper, acme, globex = data["rows"]
    assert initech == {"company": "Initech LLC", "company_key": "initech", "position": "S&P Analyst",
                       "position_key": "s p analyst", "applied": "10/20/2026", "outcome": "Applied",
                       "outcome_cls": "waiting", "stage": "", "domain": "boards.greenhouse.io",
                       "href": "https://www.boards.greenhouse.io/initech/jobs/5", "remarks": []}
    assert acme["company_key"] == acme_upper["company_key"] == "acme"
    assert (acme["outcome"], acme["outcome_cls"], acme["stage"]) == ("In progress", "progress", "Interview")
    assert acme_upper["outcome_cls"] == "rejected"
    assert acme_upper["remarks"] == ["referred by Sam", "10/22/2026 rejected by email"]
    assert (globex["applied"], globex["domain"], globex["href"]) == ("", "", "")


def test_search_data_is_escaped():
    bad, pos = "</script><b>x", "A & B <i> "
    html = page([F(company=bad, position=pos, stage="Interview", outcome="In progress", remarks=f"ok | {bad}")])
    block = search_block(html)
    assert not re.search(r"[<>&  ]", block)
    assert "</script><b>" not in html and "<b>x" not in html and "<i>" not in html
    assert html.count("</script>") == 2  # the data block and the search script, nothing from the tracker
    row = json.loads(block)["rows"][0]
    assert (row["company"], row["position"], row["remarks"]) == (bad, pos, ["ok", bad])
    assert '<span class="remark">&lt;/script&gt;&lt;b&gt;x</span>' in section(html, "responses")


def test_search_box_hidden_until_the_script_runs():
    html = page([F()])
    assert '<section id="search" hidden>' in html
    assert html.index('id="search-data"') > html.index("</main>")  # after the page, so the page renders first


def test_search_script_is_local():
    html = page([F()])
    script = re.search(r'</script>\s*<script>(.*?)</script>', html, re.S).group(1)
    assert script.strip() == (ROOT / "reporting" / "static" / "search.js").read_text(encoding="utf-8").strip()
    for banned in ("fetch", "XMLHttpRequest", "import", "src", "innerHTML", "outerHTML", "insertAdjacentHTML",
                   "eval", "Function(", "document.write", "</script", "<!--", "localStorage"):
        assert banned not in script, banned
    assert not re.search(r"<script[^>]*\ssrc=", html)


NORMALIZE_CASES = ["Acme, Inc.", "S&P Global", "Inc", "Nestlé S.A.", "  Foo--Bar  LLC ", "ÉCOLE", "Straße",
                   "data_eng", "Acme Corp.", "co", "Ünïcode Co. Ltd", "Σίσυφος", "AT&T", "", "  ", "3M Co",
                   "Data Engineer II (Remote)", "C++ / C# developer"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_search_normalization_matches_find():
    script = ROOT / "reporting" / "static" / "search.js"
    code = ("const {normalize} = require(process.argv[1]); const cases = JSON.parse(process.argv[2]);"
            "const suffixes = JSON.parse(process.argv[3]);"
            "process.stdout.write(JSON.stringify(cases.map(c => normalize(c, suffixes))));")
    out = subprocess.run(["node", "-e", code, str(script), json.dumps(NORMALIZE_CASES),
                          json.dumps(sorted(tracker.COMPANY_SUFFIXES))],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    assert json.loads(out) == [tracker.search_key(c) for c in NORMALIZE_CASES]
