"""ATS detection and parsers, using payload shapes confirmed against the live APIs (no network here)."""
from datetime import date, datetime

import pytest

import ats
from ats import ashby, generic, greenhouse, lever
from ats.common import JobDetails


@pytest.mark.parametrize("url,system", [
    ("https://job-boards.greenhouse.io/acme/jobs/1000001", "greenhouse"),
    ("https://boards.greenhouse.io/acme/jobs/1000001?gh_src=abc", "greenhouse"),
    ("https://acme.com/jobs/search?gh_jid=1000001", "greenhouse"),
    ("https://jobs.ashbyhq.com/globex/11111111-2222-4333-8444-555555555555", "ashby"),
    ("https://jobs.lever.co/initech/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/apply", "lever"),
    ("https://umbrella.wd5.myworkdayjobs.com/en-US/UmbrellaCareers/job/X_JR1", "workday"),
    ("https://careers-hooli.icims.com/jobs/1234/job", "other"),
    ("https://myworkdayjobs.com.evil.example/job", "other"),
])
def test_detect_system(url, system):
    assert ats.detect_system(url) == system


def test_greenhouse_url_and_api():
    assert greenhouse.parse_url("https://job-boards.greenhouse.io/acme/jobs/1000001") == ("acme", "1000001")
    assert greenhouse.parse_url("https://boards.greenhouse.io/embed/job_app?for=acme&token=99") == ("acme", "99")
    assert greenhouse.parse_url("https://acme.com/jobs/search?gh_jid=1000001") == (None, "1000001")
    d = greenhouse.parse_api({"title": "Abuse Investigator", "company_name": "Acme",
                              "first_published": "2026-09-09T10:50:29-04:00",
                              "updated_at": "2026-10-07T19:02:27-04:00"})
    assert d == JobDetails("Acme", "Abuse Investigator", date(2026, 9, 9))


def test_lever_url_and_api():
    url = "https://jobs.lever.co/initech/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/apply"
    assert lever.parse_url(url) == ("initech", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    d = lever.parse_api({"text": "Administrative Business Partner", "createdAt": 1786469891368})
    assert d.position == "Administrative Business Partner"
    assert d.posted_date == datetime.fromtimestamp(1786469891368 / 1000).date()
    assert d.company is None  # comes from JSON-LD


def test_ashby_api_picks_job_by_id():
    data = {"apiVersion": "1", "jobs": [
        {"id": "other", "title": "Nope", "publishedAt": "2026-01-01T00:00:00.000+00:00"},
        {"id": "11111111-2222-4333-8444-555555555555", "title": " Security Engineer, Cloud",
         "publishedAt": "2026-04-07T17:12:35.753+00:00"},
    ]}
    d = ashby.parse_api(data, "11111111-2222-4333-8444-555555555555")
    assert d == JobDetails(None, "Security Engineer, Cloud", date(2026, 4, 7))
    assert ashby.parse_api(data, "missing") == JobDetails()


JSONLD_PAGE = """<html><head><title>x</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Wrong"}</script>
<script type="application/ld+json">
{"@context":"https://schema.org/","@type":"JobPosting","title":" Security Engineer, Cloud",
 "datePosted":"2026-04-07","hiringOrganization":{"@type":"Organization","name":"Globex"}}
</script></head></html>"""


def test_generic_jsonld():
    assert generic.parse_jsonld(JSONLD_PAGE) == JobDetails("Globex", "Security Engineer, Cloud", date(2026, 4, 7))


def test_generic_jsonld_graph_and_missing():
    page = ('<script type="application/ld+json">{"@graph":[{"@type":"WebPage"},'
            '{"@type":"JobPosting","title":"Dev","hiringOrganization":"Acme"}]}</script>')
    assert generic.parse_jsonld(page) == JobDetails("Acme", "Dev", None)
    assert generic.parse_jsonld("<html>no data</html>") == JobDetails()


def test_fetch_falls_back_to_jsonld_and_survives_errors(monkeypatch):
    def api_fails(url):
        raise OSError("network down")

    monkeypatch.setitem(ats.FETCHERS, "greenhouse", api_fails)
    monkeypatch.setattr(generic, "get_text", lambda url: JSONLD_PAGE)
    d = ats.fetch_details("https://acme.com/jobs/search?gh_jid=1")
    assert d == JobDetails("Globex", "Security Engineer, Cloud", date(2026, 4, 7))


def test_lever_keeps_api_result_when_page_fails(monkeypatch):
    monkeypatch.setattr(lever, "get_json", lambda url: {"text": "Dev", "createdAt": 1786469891368})

    def page_fails(url):
        raise OSError("timeout")

    monkeypatch.setattr(lever, "fetch_jsonld", page_fails)
    d = lever.fetch_details("https://jobs.lever.co/initech/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    assert d.position == "Dev" and d.company is None
