"""Shared form logic: label keys, profile values, answer matching. Made-up data only; no browser."""
import pytest
import yaml

from ats import form
from ats.form import Field, Profile

PROFILE_YAML = """\
personal:
  first_name: Alex
  last_name: Doe
  preferred_name: Al
  email: alex@example.com
  phone: "+1 555-010-0000"
  city: Springfield
  state: Oregon
  country: United States
  zip: 97477
links:
  linkedin: https://linkedin.com/in/example
  github: https://github.com/example
  website: TODO
resume_path: resume.pdf
education:
  - school: Example State University
    degree: Master of Science
current_job:
  company: Initech
  title: Software Engineer
work_authorization:
  authorized_to_work_in_us: Yes
  requires_sponsorship_now: No
  requires_sponsorship_future: Yes
preferences:
  willing_to_relocate: TODO
  earliest_start_date: Immediately
eeo:
  gender: Male
  veteran_status: Not a Veteran
"""

ANSWERS_YAML = """\
# Saved answers to custom application questions.
# Key = the question text, lowercased with punctuation removed.
"are you at least 18 years of age": "Yes"
"have you worked here before": No
"""


@pytest.fixture
def profile(tmp_path) -> Profile:
    (tmp_path / "profile.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4 made up")
    return Profile.load(tmp_path / "profile.yaml")


@pytest.fixture
def answers_file(tmp_path):
    path = tmp_path / "answers.yaml"
    path.write_text(ANSWERS_YAML, encoding="utf-8")
    return path


def resolve(profile, label, kind=form.TEXT, options=(), fid="question_1", answers=None, source="LinkedIn"):
    return form.resolve(Field(fid, label, kind, True, list(options)), profile, answers or {}, source)


def test_normalize_label():
    assert form.normalize_label("Are you at least 18 years of age?*") == "are you at least 18 years of age"
    assert form.normalize_label("  LinkedIn   Profile ") == "linkedin profile"


def test_profile_values_come_back_as_text(profile):
    assert profile.get("work_authorization.authorized_to_work_in_us") == "Yes"  # YAML read it as True
    assert profile.get("work_authorization.requires_sponsorship_now") == "No"
    assert profile.get("personal.zip") == "97477"
    assert profile.get("education.0.school") == "Example State University"
    assert profile.get("links.website") is None  # TODO = missing
    assert profile.get("nope.nothing") is None
    assert profile.location() == "Springfield, Oregon"
    assert profile.resume().name == "resume.pdf"


def test_load_answers_normalizes(answers_file):
    assert form.load_answers(answers_file) == {"are you at least 18 years of age": "Yes",
                                               "have you worked here before": "No"}


def test_standard_ids_and_links(profile):
    assert resolve(profile, "First Name", fid="first_name").value == "Alex"
    assert resolve(profile, "Email", fid="email").source == "profile:personal.email"
    assert resolve(profile, "LinkedIn Profile").value == "https://linkedin.com/in/example"
    assert resolve(profile, "GitHub URL").value == "https://github.com/example"
    assert resolve(profile, "Website") is None  # TODO in the profile
    assert resolve(profile, "Preferred First Name").value == "Al"
    assert resolve(profile, "Who is your current or previous employer?").value == "Initech"
    assert resolve(profile, "What is your current or previous job title?").value == "Software Engineer"
    assert resolve(profile, "Location (City)", fid="candidate-location").value == "Springfield, Oregon"
    resume = form.resolve(Field("resume", "Resume/CV", form.FILE, True), profile, {}, None)
    assert resume.value.endswith("resume.pdf")


def test_source_answers_how_did_you_hear(profile):
    assert resolve(profile, "How did you hear about us?").value == "LinkedIn"
    assert resolve(profile, "How did you hear about us?", form.SELECT, ["LinkedIn", "Other"]).value == "LinkedIn"
    assert resolve(profile, "How did you connect with us?", form.SELECT, ["Career fair", "Other"]) is None


YES_NO = ["Yes", "No"]


def test_sensitive_rules_on_dropdowns(profile):
    auth = resolve(profile, "Are you legally authorized to work in the United States?", form.SELECT, YES_NO)
    assert (auth.value, auth.source) == ("Yes", "profile:work_authorization.authorized_to_work_in_us")
    assert resolve(profile, "Do you require visa sponsorship?", form.SELECT, YES_NO).value == "No"
    future = resolve(profile, "Will you now or in the future require employment visa sponsorship?",
                     form.SELECT, YES_NO)
    assert (future.value, future.source) == ("Yes", "profile:work_authorization.requires_sponsorship_future")


def test_worked_here_before_and_graduation(tmp_path):
    (tmp_path / "p.yaml").write_text(PROFILE_YAML + "history:\n  worked_at_company_before: No\n", encoding="utf-8")
    p = Profile.load(tmp_path / "p.yaml")
    (tmp_path / "p.yaml").write_text(PROFILE_YAML.replace("    degree: Master of Science\n",
                                     "    degree: Master of Science\n    graduation_date: May 11, 2026\n"),
                                     encoding="utf-8")
    grad = Profile.load(tmp_path / "p.yaml")
    worked = "Have you ever worked for Figma before, as an employee or a contractor/consultant?"
    assert resolve(p, worked, form.SELECT, YES_NO).value == "No"
    assert resolve(p, "Have you ever been employed by Stripe or a Stripe affiliate?", form.SELECT, YES_NO).value == "No"
    assert resolve(p, "Have you ever interviewed at Acme before?", form.SELECT, YES_NO) is None
    assert resolve(profile=grad, label="What is your graduation date?").value == "May 11, 2026"
    # A graduation dropdown still needs an exact option, so it is asked.
    assert resolve(grad, "Expected graduation date?", form.SELECT, ["Spring 2027", "I am not currently enrolled"]) is None


def test_never_guesses(profile):
    # Profile says TODO for relocation: unknown, so I get asked.
    assert resolve(profile, "Are you open to relocation for this role?", form.SELECT, YES_NO) is None
    # A text question that mentions relocation or sponsorship is not a Yes/No question.
    assert resolve(profile, "What address will you work from? If you would need to relocate, say where") is None
    assert resolve(profile, "Explain your sponsorship needs", form.TEXTAREA) is None
    # Dropdown answers must be an exact option; no fuzzy matching.
    assert resolve(profile, "Veteran Status", form.SELECT, ["I don't wish to answer", "I am not a protected veteran"],
                   fid="veteran_status") is None
    assert resolve(profile, "Gender", form.SELECT, ["Decline To Self Identify", "Female", "Male"],
                   fid="gender").value == "Male"
    assert resolve(profile, "Race", form.SELECT, ["Asian", "White"], fid="race") is None  # not in profile
    assert resolve(profile, "Why do you want to join us?", form.TEXTAREA) is None


def test_unmatched_reports_the_value_that_did_not_fit(profile):
    vet = Field("veteran_status", "Veteran Status", form.SELECT, False, ["I am not a protected veteran"])
    assert form.unmatched(vet, profile, {}, None) == ("Not a Veteran", "profile:eeo.veteran_status")
    gender = Field("gender", "Gender", form.SELECT, False, ["Female", "Male"])
    assert form.unmatched(gender, profile, {}, None) is None  # it fit
    essay = Field("q", "Why us?", form.TEXTAREA, True)
    assert form.unmatched(essay, profile, {}, None) is None  # nothing to report


def test_saved_answer_wins_and_must_fit(profile, answers_file):
    answers = form.load_answers(answers_file)
    assert resolve(profile, "Are you at least 18 years of age?", form.SELECT, YES_NO, answers=answers).value == "Yes"
    saved = {"veteran status": "I am not a protected veteran"}
    vet = resolve(profile, "Veteran Status", form.SELECT, ["I am not a protected veteran"],
                  fid="veteran_status", answers=saved)
    assert (vet.value, vet.source) == ("I am not a protected veteran", "answers.yaml")
    multi = form.resolve(Field("q", "Countries", form.MULTISELECT, True, ["US", "Canada", "Mexico"]),
                         profile, {"countries": ["us", "Canada"]}, None)
    assert multi.value == ["US", "Canada"]


def test_save_answer_appends_and_keeps_comments(answers_file):
    form.save_answer(answers_file, "Are you Hispanic/Latino?", "No")
    form.save_answer(answers_file, 'Quote "this": please', "It's fine: yes")
    text = answers_file.read_text(encoding="utf-8")
    assert text.startswith(ANSWERS_YAML)  # comments and old entries untouched
    loaded = form.load_answers(answers_file)
    assert loaded["are you hispaniclatino"] == "No"
    assert loaded["quote this please"] == "It's fine: yes"
    assert yaml.safe_load(text)["are you at least 18 years of age"] == "Yes"


def test_report_summary():
    report = form.FillReport(filled=[("Email", "profile:personal.email")], attention=[("Why us?", "fill it in")],
                             skipped=["Pronouns"])
    text = report.summary()
    assert "+ Email" in text and "! Why us?: fill it in" in text and "- Pronouns" in text
