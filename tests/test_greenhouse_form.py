"""Greenhouse filler: API -> fields, the driver on a local copy of the form, and apply.py wiring.

The driver test runs headless Chrome on tests/fixtures/greenhouse_form.html (no network) and
checks that nothing was submitted. Made-up profile data only.
"""
from datetime import date
from pathlib import Path

import pytest
from test_apply import Script

import apply
from ats import form, greenhouse
from ats.common import JobDetails

FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse_form.html"

YES_NO = [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]


def q(label, name, ftype="input_text", required=False, values=()):
    return {"label": label, "required": required,
            "fields": [{"name": name, "type": ftype, "values": list(values)}]}


# Same shape as boards-api.greenhouse.io ...?questions=true (confirmed 2026-10-14), made-up content.
PAYLOAD = {
    "title": "Software Engineer",
    "company_name": "Acme",
    "questions": [
        q("First Name", "first_name", required=True),
        q("Last Name", "last_name", required=True),
        q("Email", "email", required=True),
        q("Phone", "phone", required=True),
        {"label": "Resume/CV", "required": True, "fields": [
            {"name": "resume", "type": "input_file", "values": []},
            {"name": "resume_text", "type": "textarea", "values": []}]},
        {"label": "Cover Letter", "required": False, "fields": [
            {"name": "cover_letter", "type": "input_file", "values": []}]},
        q("LinkedIn Profile", "question_101"),
        q("Are you legally authorized to work in the United States?", "question_102",
          "multi_value_single_select", True, YES_NO),
        q("Will you now or in the future require visa sponsorship?", "question_103",
          "multi_value_single_select", True, YES_NO),
        q("Why do you want to join Acme?", "question_104", "textarea", True),
        q("How did you connect with us?", "question_105", "multi_value_single_select", True,
          [{"label": "Career fair", "value": 1}, {"label": "Apply through a partner", "value": 2},
           {"label": "Other", "value": 3}]),
        q("Pronouns", "question_106", "multi_value_single_select", False,
          [{"label": "she/her", "value": 1}, {"label": "he/him", "value": 2}, {"label": "they/them", "value": 3}]),
    ],
    "location_questions": [
        q("Longitude", "longitude", "input_hidden", True),
        q("Latitude", "latitude", "input_hidden", True),
        q("Location", "location", "input_text", True),
    ],
    "compliance": [{"type": "eeoc", "questions": [
        q("Gender", "gender", "multi_value_single_select", False,
          [{"label": "Decline To Self Identify", "value": 3}, {"label": "Female", "value": 1},
           {"label": "Male", "value": 2}]),
        q("VeteranStatus", "veteran_status", "multi_value_single_select", False,
          [{"label": "I don't wish to answer", "value": 3}, {"label": "I am not a protected veteran", "value": 1}]),
    ]}],
}

PROFILE_YAML = """\
personal:
  first_name: Alex
  last_name: Doe
  email: alex@example.com
  phone: "+1 555-010-0000"
  city: Springfield
  state: Oregon
  country: United States
links:
  linkedin: https://linkedin.com/in/example
resume_path: resume.pdf
work_authorization:
  authorized_to_work_in_us: Yes
  requires_sponsorship_now: No
  requires_sponsorship_future: Yes
eeo:
  gender: Male
  veteran_status: Not a Veteran
"""


@pytest.fixture
def profile_files(tmp_path):
    (tmp_path / "profile.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4 made up")
    (tmp_path / "answers.yaml").write_text("# saved answers\n", encoding="utf-8")
    return tmp_path / "profile.yaml", tmp_path / "answers.yaml"


def test_fields_from_api():
    fields = {f.id: f for f in greenhouse.fields_from_api(PAYLOAD)}
    assert list(fields)[:5] == ["first_name", "last_name", "email", "phone", "resume"]
    assert not {"resume_text", "cover_letter", "latitude", "longitude", "location"} & set(fields)
    assert fields["resume"].kind == form.FILE and fields["resume"].required
    assert fields["question_102"].options == ["Yes", "No"] and fields["question_102"].kind == form.SELECT
    assert fields["question_104"].kind == form.TEXTAREA
    assert fields["question_101"].required is False
    assert fields["candidate-location"].kind == form.SELECT  # an autocomplete on the page
    assert fields["veteran_status"].label == "Veteran Status"
    assert fields["question_101"].label == "LinkedIn Profile"
    edu = greenhouse.fields_from_api({"questions": [], "education": "education_required"})
    assert [(f.id, f.required) for f in edu] == [("school--0", True), ("degree--0", True), ("discipline--0", True)]
    eeo = greenhouse.fields_from_api({"compliance": [{"questions": [
        q("Race", "race", "multi_value_single_select", False, [{"label": "Asian", "value": 1}]),
        q("Gender", "gender", "multi_value_single_select")]}]})
    assert [f.id for f in eeo] == ["hispanic_ethnicity", "race", "gender"]
    assert form.resolve(eeo[0], form.Profile({}, Path(".")), {"are you hispaniclatino": "No"}, None).value == "No"
    multi = greenhouse.fields_from_api({"questions": [q("Countries", "question_9[]", "multi_value_multi_select")]})
    assert (multi[0].id, multi[0].kind) == ("question_9", form.MULTISELECT)


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    pw = sync_api.sync_playwright().start()
    try:
        b = pw.chromium.launch(channel="chrome", headless=True)
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"Chrome not available for Playwright: {exc}")
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def page(browser):
    p = browser.new_page()
    p.goto(FIXTURE.as_uri())
    yield p
    p.close()


def single_value(page, fid):
    return page.evaluate("""id => document.getElementById(id).closest('.select-shell')
        .querySelector('.select__single-value')?.textContent || null""", fid)


def test_fill_form_fills_asks_and_never_submits(page, profile_files, capsys):
    profile_path, answers_path = profile_files
    profile = form.Profile.load(profile_path)
    answers = form.load_answers(answers_path)
    script = Script("",      # Why do you want to join Acme? -> I'll write it in the browser
                    "2",     # How did you connect with us? -> "Apply through a partner"
                    "y")     # save it to answers.yaml
    report = greenhouse.fill_form(page, greenhouse.fields_from_api(PAYLOAD), profile, answers,
                                  answers_path, "LinkedIn", script)

    assert page.evaluate("window.submitted") is False
    assert page.input_value("#first_name") == "Alex"
    assert page.input_value("#email") == "alex@example.com"
    assert page.input_value("#phone") == "+1 555-010-0000"
    assert page.input_value("#question_101") == "https://linkedin.com/in/example"
    assert page.evaluate("document.getElementById('resume').files[0].name") == "resume.pdf"
    assert single_value(page, "country") == "United States +1"
    assert single_value(page, "candidate-location") == "Springfield, Oregon, United States"
    assert single_value(page, "question_102") == "Yes"
    assert single_value(page, "question_103") == "Yes"  # "now or in the future" -> future
    assert single_value(page, "question_105") == "Apply through a partner"
    assert single_value(page, "gender") == "Male"
    assert single_value(page, "veteran_status") is None  # "Not a Veteran" is not an option: not guessed
    assert single_value(page, "question_106") is None   # optional and unknown: left blank

    # The essay was left for me, highlighted in the page.
    assert page.input_value("#question_104") == ""
    assert "red" in page.evaluate("document.getElementById('question_104').style.outline")

    assert form.load_answers(answers_path) == {"how did you connect with us": "Apply through a partner"}
    assert any(p.startswith("  Your number") for p in script.prompts)
    assert "Pronouns" in report.skipped
    assert ("Resume/CV", "profile:resume_path") in report.filled
    attention = dict(report.attention)
    assert set(attention) == {"Why do you want to join Acme?", "Veteran Status", "Start date year"}
    assert "required, not in the job API" in attention["Start date year"]
    assert "profile:eeo.veteran_status says 'Not a Veteran'" in attention["Veteran Status"]
    out = capsys.readouterr().out
    assert "1. Career fair" in out and "Required: Why do you want to join Acme?" in out


def test_click_refuses_submit(page):
    with pytest.raises(greenhouse.SubmitRefused):
        greenhouse._click(page.locator("button[type=submit]"))
    assert page.evaluate("window.submitted") is False
    greenhouse._click(page.locator("button", has_text="Locate me"))  # an ordinary button is fine


def test_filler_source_never_presses_enter_or_submits():
    src = Path(greenhouse.__file__).read_text(encoding="utf-8")
    assert '"Enter"' not in src and "'Enter'" not in src
    assert ".submit(" not in src and "dispatch_event" not in src
    assert src.count(".click(") == 1  # only inside _click


# ---- apply.py wiring (fake filler, no browser) ----

class FakeSession:
    def __init__(self):
        self.report = form.FillReport(filled=[("Email", "profile:personal.email")])
        self.closed = False

    def close(self):
        self.closed = True


def fetch_ok(url):
    return JobDetails("Acme Robotics", "Software Engineer I", date(2026, 10, 8))


def run(tracker_file, profile_path, script, fill, extra=()):
    return apply.main(["https://job-boards.greenhouse.io/acme/jobs/1234567", "--tracker", str(tracker_file),
                       "--profile", str(profile_path), *extra],
                      input_fn=script, fetch=fetch_ok, today=date(2026, 10, 14), fill=fill)


def test_apply_fills_then_pauses_then_closes(tracker_file, profile_files, capsys):
    profile_path, answers_path = profile_files
    calls, session = [], FakeSession()

    def fill(url, **kw):
        calls.append((url, kw))
        return session

    before = tracker_file.read_bytes()
    script = Script("", "s")
    assert run(tracker_file, profile_path, script, fill, ["--source", "LinkedIn"]) == 0
    assert script.prompts == [apply.APPLY_PROMPT, apply.PAUSE_PROMPT]
    assert calls[0][1]["source"] == "LinkedIn" and calls[0][1]["profile_path"] == profile_path
    assert session.closed
    out = capsys.readouterr().out
    assert "+ Email" in out
    assert tracker_file.read_bytes() == before


def test_apply_no_fill_and_filler_failure(tracker_file, profile_files, capsys):
    profile_path, _ = profile_files

    def must_not_run(url, **kw):
        raise AssertionError("--no-fill should skip the filler")

    assert run(tracker_file, profile_path, Script("", "s"), must_not_run, ["--no-fill"]) == 0

    def broken(url, **kw):
        raise RuntimeError("Chrome not found")

    script = Script("", "s")
    assert run(tracker_file, profile_path, script, broken) == 0
    assert script.prompts == [apply.APPLY_PROMPT, apply.PAUSE_PROMPT]  # still pauses so I can apply by hand
    assert "Could not fill the form (RuntimeError: Chrome not found)" in capsys.readouterr().out
