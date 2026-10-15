"""ATS detection and parsers, using payload shapes confirmed against the live APIs (no network here)."""
from datetime import date, datetime

import pytest

import ats
import json

from ats import ashby, generic, greenhouse, icims, lever, oracle, rippling
from ats.common import JobDetails


@pytest.mark.parametrize("url,system", [
    ("https://job-boards.greenhouse.io/acme/jobs/1000001", "greenhouse"),
    ("https://boards.greenhouse.io/acme/jobs/1000001?gh_src=abc", "greenhouse"),
    ("https://acme.com/jobs/search?gh_jid=1000001", "greenhouse"),
    ("https://jobs.ashbyhq.com/globex/11111111-2222-4333-8444-555555555555", "ashby"),
    ("https://jobs.lever.co/initech/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/apply", "lever"),
    ("https://umbrella.wd5.myworkdayjobs.com/en-US/UmbrellaCareers/job/X_JR1", "workday"),
    ("https://careers-hooli.icims.com/jobs/1234/job", "icims"),
    ("https://ats.rippling.com/hooli/jobs/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "rippling"),
    ("https://abcd.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/123", "oracle"),
    ("https://abcd.fa.oraclecloud.com.evil.example/hcmUI/CandidateExperience/en/sites/CX_1/job/1", "other"),
    ("https://www.oraclecloud.com/careers", "other"),
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


ICIMS_URL = ("https://careers-hooli.icims.com/jobs/1234/cloud-support-analyst/job?mobile=false&width=1380"
             "&height=500&bga=true&needsRedirect=false&jan1offset=-420&jun1offset=-420")
ICIMS_IFRAME = """<html><script type="application/ld+json">{"@type":"JobPosting","title":"Cloud Support Analyst",
 "datePosted":"2026-10-14T04:00:00.000Z","hiringOrganization":{"@type":"Organization","name":"Hooli"}}</script></html>"""


def test_icims_reads_the_iframe_page(monkeypatch):
    assert icims.iframe_url(ICIMS_URL) ==         "https://careers-hooli.icims.com/jobs/1234/cloud-support-analyst/job?in_iframe=1"
    fetched = []
    monkeypatch.setattr(icims, "get_text", lambda url: fetched.append(url) or ICIMS_IFRAME)
    d = ats.fetch_details(ICIMS_URL)
    assert d == JobDetails("Hooli", "Cloud Support Analyst", date(2026, 10, 14))
    assert fetched[0].endswith("?in_iframe=1")


ORACLE_URL = "https://abcd.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/123456?utm_source=x"
ORACLE_JOB = {"items": [{"Id": "123456", "Title": " Cloud Engineer ",
                         "ExternalPostedStartDate": "2026-10-15T20:43:44+00:00"}]}


def test_oracle_url_and_api():
    assert oracle.parse_url(ORACLE_URL) == ("https://abcd.fa.us2.oraclecloud.com", "CX_1", "123456")
    assert oracle.parse_url("https://abcd.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/"
                            "requisitions/preview/77") == ("https://abcd.fa.oraclecloud.com", "CX", "77")
    assert oracle.parse_url("https://abcd.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX") ==         (None, None, None)
    assert oracle.parse_api(ORACLE_JOB) == JobDetails(None, "Cloud Engineer", date(2026, 10, 15))
    assert oracle.parse_api({"items": []}) == JobDetails()
    assert oracle.parse_site({"items": [{"SiteName": "X Candidate Experience page",
                                         "SeoOrganizationName": None}]}) is None


def test_oracle_fetch_with_company(monkeypatch):
    calls = []

    def fake_json(url):
        calls.append(url)
        if "recruitingCESites" in url:
            return {"items": [{"SeoOrganizationName": "Initech"}]}
        return ORACLE_JOB

    monkeypatch.setattr(oracle, "get_json", fake_json)
    d = oracle.fetch_details(ORACLE_URL)
    assert d == JobDetails("Initech", "Cloud Engineer", date(2026, 10, 15))
    assert 'finder=ById;Id="123456",siteNumber=CX_1' in calls[0]
    assert calls[0].startswith("https://abcd.fa.us2.oraclecloud.com/hcmRestApi/")


def test_oracle_keeps_job_when_site_call_fails(monkeypatch):
    def fake_json(url):
        if "recruitingCESites" in url:
            raise OSError("timeout")
        return ORACLE_JOB

    monkeypatch.setattr(oracle, "get_json", fake_json)
    assert oracle.fetch_details(ORACLE_URL) == JobDetails(None, "Cloud Engineer", date(2026, 10, 15))


# ---------- any site: guesses from page tags, and the Chrome fallback ----------

def test_hints_from_share_tags_title_and_h1():
    page = ('<html><head><meta property="og:site_name" content="Careers at Hooli">'
            '<meta property="og:title" content="Data Analyst | Hooli"><title>Hooli Careers</title></head>'
            '<body><h1>Data Analyst – Platform</h1></body></html>')
    d = generic.parse_page(page)
    assert d == JobDetails()  # guesses never count as read details
    assert (d.company_guess, d.position_guess) == ("Hooli", "Data Analyst – Platform")
    title_only = generic.parse_hints("<title>Site Reliability Engineer - Hooli Careers</title>")
    assert (title_only.company_guess, title_only.position_guess) == (None, "Site Reliability Engineer")
    assert generic.parse_hints("<title>Jobs | Hooli Careers</title><h1>Careers</h1>").position_guess is None


@pytest.mark.parametrize("org,company,guess", [
    ("Hooli", "Hooli", None),
    ("JPMC Candidate Experience page", None, "JPMC"),  # Oracle site name
    ("2100 NVIDIA USA", None, "NVIDIA USA"),  # Workday legal-entity code
])
def test_jsonld_company_that_needs_tidying_is_only_a_guess(org, company, guess):
    page = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Dev",'
            f'"hiringOrganization":{{"name":"{org}"}}}}</script>')
    d = generic.parse_jsonld(page)
    assert (d.company, d.company_guess, d.position) == (company, guess, "Dev")


APP_SHELL = '<html><head><title>Loading...</title><meta property="og:site_name" content="Hooli Jobs"></head></html>'
RENDERED_FRAME = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Cloud Engineer",'
                  '"datePosted":"2026-10-01","hiringOrganization":{"name":"Hooli"}}</script>')


def test_chrome_fallback_reads_rendered_frames(monkeypatch):
    monkeypatch.setattr(generic, "get_text", lambda url: APP_SHELL)
    seen = {}

    def render(url, ready):
        seen["url"] = url
        pages = ["<html><title>Cloud Engineer | Hooli</title></html>", RENDERED_FRAME]
        seen["ready"] = ready(pages)
        return pages

    d = ats.fetch_details("https://jobs.hooli.example/apply/42", render=render)
    assert d == JobDetails("Hooli", "Cloud Engineer", date(2026, 10, 1))
    assert seen == {"url": "https://jobs.hooli.example/apply/42", "ready": True}


def test_chrome_fallback_skipped_when_complete_and_survives_errors(monkeypatch):
    monkeypatch.setattr(generic, "get_text", lambda url: JSONLD_PAGE)

    def must_not_render(url, ready):
        raise AssertionError("details were already complete")

    assert ats.fetch_details("https://globex.example/job/1", render=must_not_render).complete()

    monkeypatch.setattr(generic, "get_text", lambda url: APP_SHELL)

    def chrome_missing(url, ready):
        raise RuntimeError("Chrome not installed")

    d = ats.fetch_details("https://globex.example/job/1", render=chrome_missing)
    assert d == JobDetails() and d.company_guess == "Hooli"


RIPPLING_URL = "https://ats.rippling.com/hooli/jobs/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/apply"
RIPPLING_DATA = {"props": {"pageProps": {"apiData": {
    "jobBoard": {"slug": "hooli", "companyName": "Hooli "},
    "jobPost": {"name": "Network Engineer ", "companyName": "Hooli ",
                "createdOn": "2026-10-15T07:54:57.425000-07:00"}}}}}
RIPPLING_PAGE = ('<meta property="og:site_name" content="Rippling Recruiting"/>'
                 f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(RIPPLING_DATA)}</script>')


def test_rippling_reads_next_data(monkeypatch):
    assert rippling.parse_url(RIPPLING_URL) == ("hooli", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    fetched = []
    monkeypatch.setattr(rippling, "get_text", lambda url: fetched.append(url) or RIPPLING_PAGE)
    assert ats.fetch_details(RIPPLING_URL) == JobDetails("Hooli", "Network Engineer", date(2026, 10, 15))
    assert fetched == ["https://ats.rippling.com/hooli/jobs/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"]
    assert rippling.parse_page("<html>no data</html>") == JobDetails()
    assert rippling.parse_page('<script id="__NEXT_DATA__">{"props": {}}</script>') == JobDetails()
