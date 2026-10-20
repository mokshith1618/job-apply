"""Job facts card (milestone 1d): saved job descriptions in, exact card text out. No network."""
from datetime import datetime, timedelta, timezone

import pytest
from jd import JD_DIR, load_fixture

import job_facts
from ats import ashby, generic, greenhouse, lever, smartrecruiters, ukg
from ats.common import JobDetails

# The lists in matching.yaml when these cards were written; tests don't read my real file.
KEYWORDS = job_facts.Keywords(
    sponsorship=["sponsor", "sponsors", "sponsorship", "sponsoring", "visa", "H-1B", "H1B", "work authorization",
                 "authorized to work", "employment authorization", "OPT", "CPT", "immigration"],
    citizenship=["citizen", "citizens", "citizenship", "green card", "permanent resident", "clearance", "TS/SCI",
                 "public trust", "ITAR", "export control", "U.S. person", "US person"],
    citizenship_ignore=["regardless of", "without regard to", "equal opportunity", "protected veteran"],
)
NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone(timedelta(hours=-4)))


def details_for(name: str) -> tuple[JobDetails, str]:
    """Run a saved posting through its board's reader, as apply.py would."""
    if name.startswith("ukg-"):
        return ukg.parse_page((JD_DIR / name).read_text(encoding="utf-8")), "ukg"
    if name.endswith(".html"):
        return generic.parse_page((JD_DIR / name).read_text(encoding="utf-8")), "other"
    data = load_fixture(name)
    if name.startswith("ashby-"):
        return ashby.parse_api(data, data["jobs"][0]["id"]), "ashby"
    if name.startswith("lever-"):
        return lever.parse_api(data), "lever"
    if name.startswith("sr-"):
        return smartrecruiters.parse_api(data), "smartrecruiters"
    return greenhouse.parse_api(data), "greenhouse"


FIXTURES = sorted(p.name for p in JD_DIR.iterdir() if p.suffix in (".json", ".html"))


def test_enough_fixtures():
    assert len(FIXTURES) >= 10
    for name in FIXTURES:
        assert (JD_DIR / name).with_suffix(".card.txt").exists(), name


@pytest.mark.parametrize("name", FIXTURES)
def test_card_matches_the_hand_written_card(name):
    details, system = details_for(name)
    expected = (JD_DIR / name).with_suffix(".card.txt").read_text(encoding="utf-8")
    assert job_facts.card(details, system, KEYWORDS, NOW) + "\n" == expected


@pytest.mark.parametrize("name", FIXTURES)
def test_every_printed_sentence_is_word_for_word_from_the_description(name):
    details, system = details_for(name)
    cleaned = " ".join(details.description.split())
    section = None
    for line in job_facts.card(details, system, KEYWORDS, NOW).split("\n"):
        if line.endswith(":") and not line.startswith(" "):
            section = line
        if not line.startswith("  ") or line.strip() == "not mentioned" or section == "Posted:":
            continue
        text = line[2:]
        if text.startswith("Title: "):
            continue
        assert text in cleaned


def units(text):
    return list(job_facts.units(text))


def test_units_split_sentences_but_not_abbreviations():
    assert units("Must be a U.S. Person. We do sponsor visas! However, not always. Why? Because.") == [
        "Must be a U.S. Person.", "We do sponsor visas!", "However, not always.", "Why?", "Because."]
    assert units("A B.S. or Ph.D. in CS (e.g., Math). Done in 2026. Next line\n- bullet one\n- bullet two") == [
        "A B.S. or Ph.D. in CS (e.g., Math).", "Done in 2026.", "Next line", "- bullet one", "- bullet two"]
    assert units('He said "Stop." Then left.') == ['He said "Stop."', "Then left."]


def find(text):
    return job_facts.find_facts(text, KEYWORDS)


def test_keywords_are_whole_words_and_all_caps_ones_match_only_capitals():
    assert find("You can opt out of emails. LS-Opt is a tool.").sponsorship == []
    assert find("Open to F-1 OPT holders.").sponsorship == ["Open to F-1 OPT holders."]
    assert find("We offer sponsorships for events.").sponsorship == []  # not listed in KEYWORDS
    assert find("Sponsorship is available.").sponsorship == ["Sponsorship is available."]
    assert find("Work Authorization required.").sponsorship == ["Work Authorization required."]
    assert find("Must hold an active clearance.").citizenship == ["Must hold an active clearance."]


def test_citizenship_leaves_out_equal_opportunity_text():
    text = ("We hire without regard to citizenship. Must be a US citizen. "
            "Equal Opportunity employer: citizenship is not considered.")
    assert find(text).citizenship == ["Must be a US citizen."]


def test_sentence_in_two_sections_and_no_repeats():
    text = "Must be a U.S. citizen; no visa sponsorship.\nNo visa sponsorship.\nNo visa sponsorship."
    facts = find(text)
    assert facts.sponsorship == ["Must be a U.S. citizen; no visa sponsorship.", "No visa sponsorship."]
    assert facts.citizenship == ["Must be a U.S. citizen; no visa sponsorship."]


@pytest.mark.parametrize("sentence", [
    "2+ years of Go.", "3-5 years of Go.", "3–5 years of Go.", "3 to 5 years of Go.", "At least 4 years of Go.",
    "Minimum of 6 years of Go.", "Minimum 6 years of Go.", "5 or more years of Go.", "7 years of Go.",
    "1 year of Go.", "Bachelor's in CS.", "BS in CS.", "B.S. in CS.", "Master’s in CS.", "MS in CS.",
    "M.S. in CS.", "PhD in CS.", "Ph.D. in CS.", "A degree in CS.", "Degrees welcome.",
])
def test_seniority_sentences(sentence):
    assert find(sentence).seniority == [sentence]


@pytest.mark.parametrize("sentence", [
    "We were founded years ago.", "Ships in 2 weeks.", "ms latency matters.", "Five years of Go.",
])
def test_not_seniority(sentence):
    assert find(sentence).seniority == []


@pytest.mark.parametrize("raw,shown", [
    ("2026-10-19T08:00:00-04:00", "October 19, 2026, 8:00 AM (6 hours ago)"),
    ("2026-10-19T13:30:00-04:00", "October 19, 2026, 1:30 PM (less than an hour ago)"),
    ("2026-10-19T13:00:00-04:00", "October 19, 2026, 1:00 PM (1 hour ago)"),
    ("2026-10-19T00:05:00-04:00", "October 19, 2026, 12:05 AM (13 hours ago)"),
    ("2026-10-19T12:00:00-04:00", "October 19, 2026, 12:00 PM (2 hours ago)"),
    ("2026-10-18T14:30:00-04:00", "October 18, 2026, 2:30 PM (23 hours ago)"),
    ("2026-10-18T14:00:00-04:00", "October 18, 2026, 2:00 PM (1 day ago)"),
    ("2026-10-19T12:00:00Z", "October 19, 2026, 8:00 AM (6 hours ago)"),  # shown in my time zone
    ("2026-10-02T03:00:00.120+00:00", "October 1, 2026, 11:00 PM (17 days ago)"),
    ("2026-10-19T10:00:00", "October 19, 2026, 10:00 AM (4 hours ago)"),  # no zone: my time zone
    ("2026-10-17", "October 17, 2026 (2 days ago)"),
    ("2026-10-18", "October 18, 2026 (1 day ago)"),
    ("2026-10-19", "October 19, 2026 (today)"),
    ("2026-10-20T08:00:00-04:00", "October 20, 2026, 8:00 AM (less than an hour ago)"),  # clock skew
    ("Posted 3 Days Ago", "Posted 3 Days Ago"),  # shown as written, no age
    (None, "unknown"),
])
def test_posted_line(raw, shown):
    assert job_facts.posted_line(raw, NOW) == shown


def test_lever_timestamp_is_shown_as_a_readable_date():
    d = lever.parse_api({"text": "Dev", "createdAt": 1791308667290})
    assert job_facts.posted_line(d.posted_raw, NOW) == "October 6, 2026, 1:44 PM (13 days ago)"


def test_description_not_available():
    d = JobDetails(company="Acme", position="Dev")
    assert job_facts.card(d, "greenhouse", KEYWORDS, NOW) == (
        "Acme · Dev · Greenhouse\n\n"
        "Description: not available\n\n"
        "Seniority:\n  Title: Dev\n\n"
        "Posted:\n  unknown")


def test_missing_company_and_title_are_marked_unknown_not_guessed():
    d = JobDetails(company_guess="Hooli Jobs", position_guess="Dev", description="Nothing here.")
    text = job_facts.card(d, "workday", KEYWORDS, NOW)
    assert text.split("\n")[0] == "Company unknown · Workday"
    assert "  Title: unknown" in text and "Hooli" not in text


def test_load_keywords(tmp_path):
    path = tmp_path / "matching.yaml"
    path.write_text("keywords:\n  sponsorship: [sponsor, OPT]\n  citizenship: [citizen]\n"
                    "  citizenship_ignore: [regardless of]\nskills:\n  Python: []\n", encoding="utf-8")
    assert job_facts.load_keywords(path) == job_facts.Keywords(["sponsor", "OPT"], ["citizen"], ["regardless of"])
    with pytest.raises(SystemExit, match="matching.yaml"):
        job_facts.load_keywords(tmp_path / "missing" / "matching.yaml")
