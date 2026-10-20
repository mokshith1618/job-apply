"""ATS detection and parsers, using payload shapes confirmed against the live APIs (no network here)."""
import json
from datetime import date, datetime

import pytest
from jd import load_fixture

import ats
from ats import adp, ashby, generic, greenhouse, icims, lever, oracle, rippling, smartrecruiters, ukg
from ats.common import JobDetails, html_text


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
    ("https://jobs.smartrecruiters.com/Winsupply1/3743990016228326", "smartrecruiters"),
    ("https://careers.smartrecruiters.com/Winsupply1/3743990016228326-software-developer", "smartrecruiters"),
    ("https://jobs.smartrecruiters.com.evil.example/Winsupply1/1", "other"),
    ("https://recruiting2.ultipro.com/DES1004DFCU/JobBoard/117d2a3d/OpportunityDetail?opportunityId=db7b", "ukg"),
    ("https://eventus.rec.pro.ukg.net/eve1500evew/JobBoard/477175d5/OpportunityDetail?opportunityId=4327", "ukg"),
    ("https://recruiting2.ultipro.com/DES1004DFCU/JobBoard/117d2a3d/", "other"),  # the board, not a job
    ("https://ultipro.com.evil.example/T/JobBoard/B/OpportunityDetail?opportunityId=1", "other"),
    ("https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=a67e&jobId=568057", "adp"),
    ("https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=a67e", "other"),  # job list
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
 "datePosted":"2026-04-07","hiringOrganization":{"@type":"Organization","name":"Globex"},
 "description":"&lt;p&gt;We sponsor visas.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;3+ years of Go&lt;/li&gt;&lt;/ul&gt;"}
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


@pytest.mark.parametrize("site_name", ["Candidate Experience site", "Careers", "Jobs page"])
def test_a_careers_site_default_name_is_not_a_company_guess(site_name):
    page = f'<meta property="og:site_name" content="{site_name}"><h1>Software Engineer I</h1>'
    assert generic.parse_hints(page).company_guess is None  # Oracle's default site name, e.g.


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


# --- Job description text and the posted date as the board wrote it (milestone 1d) ---

def test_html_text_blocks_entities_and_scripts():
    markup = ("<div><p>Tom &amp; Jerry&nbsp; <b>bold</b>\n text</p><ul><li>One</li><li>Two<br>Three</li></ul>"
              "<script>var x = 1;</script><style>p {}</style></div>")
    assert html_text(markup) == "Tom & Jerry bold text\nOne\nTwo\nThree"


def test_html_text_escaped_html_and_plain_text():
    assert html_text("&lt;p&gt;A &amp;amp; B&lt;/p&gt;&lt;p&gt;C&lt;/p&gt;") == "A & B\nC"
    assert html_text("Line one\n\n  - bullet  two \r\nR&amp;D") == "Line one\n- bullet two\nR&D"
    assert html_text(None) is None
    assert html_text(" <p> </p> ") is None


def lines(details):
    return details.description.split("\n")


def test_greenhouse_description_and_raw_date():
    d = greenhouse.parse_api(load_fixture("gh-anthropic.json"))
    assert d.posted_raw == "2026-04-14T06:00:34-04:00"
    assert ("Visa sponsorship: We do sponsor visas! However, we aren't able to successfully sponsor visas for "
            "every role and every candidate. But if we make you an offer, we will make every reasonable effort "
            "to get you a visa, and we retain an immigration lawyer to help with this.") in lines(d)
    assert "<" not in d.description and "&nbsp;" not in d.description


def test_ashby_description_and_raw_date():
    data = load_fixture("ashby-harvey.json")
    d = ashby.parse_api(data, data["jobs"][0]["id"])
    assert d.posted_raw == "2025-08-07T10:47:38.950+00:00"
    assert ("- Work eligibility: Must have valid Canadian work rights; Harvey does not currently offer visa "
            "sponsorship for this role") in lines(d)


def test_lever_description_has_lists_and_additional_text():
    d = lever.parse_api(load_fixture("lever-zoox.json"))
    assert d.posted_raw == "2026-10-06T17:44:27+00:00"  # createdAt in ms, shown as an ISO date-time (UTC)
    assert lines(d)[-7:] == [
        "Qualifications",
        "Masters degree in mechanical engineering, or related field",
        "Experienced with FMVSS, USNCAP, IIHS, ECE, EU legal and consumer safety protocols",
        "Extensive experience in virtual development in occupant safety CAE using LS-dyna",
        "Extensive experience in SW tools, BetaCAE, Oasys, LS-Dyna, FE dummies, LS-Opt",
        "Strong analytical and communication skills",
        "Experience with basic Python coding",
    ]
    palantir = lever.parse_api(load_fixture("lever-palantir.json"))
    assert palantir.posted_raw == "2026-08-11T17:38:11+00:00"
    assert ("Palantir is particularly interested in applicants who have a current right to work in Singapore, "
            "and we encourage Singapore citizens to apply.") in lines(palantir)  # from additionalPlain


def test_jsonld_description_and_raw_date():
    d = generic.parse_jsonld(JSONLD_PAGE)
    assert (d.description, d.posted_raw) == ("We sponsor visas.\n3+ years of Go", "2026-04-07")


def test_oracle_description_from_all_text_fields():
    job = {"items": [{**ORACLE_JOB["items"][0],
                      "OrganizationDescriptionStr": "Initech R&amp;D",
                      "ExternalDescriptionStr": "<p>Build things.</p><ul><li>3+ years</li></ul>",
                      "ExternalResponsibilitiesStr": None,
                      "ExternalQualificationsStr": "",
                      "CorporateDescriptionStr": "<p>We do not sponsor visas.</p>"}]}
    d = oracle.parse_api(job)
    assert d.description == "Initech R&D\nBuild things.\n3+ years\nWe do not sponsor visas."
    assert d.posted_raw == "2026-10-15T20:43:44+00:00"


def test_merge_keeps_description_and_raw_date():
    a = JobDetails(position="Dev")
    b = JobDetails(company="Acme", description="Text", posted_raw="2026-10-01")
    m = a.merge(b)
    assert (m.description, m.posted_raw) == ("Text", "2026-10-01")


def test_chrome_reads_page_text_when_no_description(monkeypatch):
    page = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Dev","datePosted":"2026-10-01",'
            '"hiringOrganization":{"name":"Hooli"}}</script>')
    monkeypatch.setattr(generic, "get_text", lambda url: page)
    rendered = page + "<main><h1>Dev</h1><p>We cannot sponsor visas.</p><script>x=1</script></main>"
    d = ats.fetch_details("https://jobs.hooli.example/1", render=lambda url, ready: [rendered])
    assert d.description == "Dev\nWe cannot sponsor visas."


# ---------- SmartRecruiters (milestone 1e) ----------

SR_URL = "https://jobs.smartrecruiters.com/Winsupply1/3743990016228326?trid=abc"


def test_smartrecruiters_url():
    assert smartrecruiters.parse_url(SR_URL) == ("Winsupply1", "3743990016228326")
    assert smartrecruiters.parse_url("https://careers.smartrecruiters.com/Winsupply1/3743990016228326-software-dev") == (
        "Winsupply1", "3743990016228326")
    assert smartrecruiters.parse_url("https://careers.smartrecruiters.com/Winsupply1") == (None, None)


def test_smartrecruiters_api(monkeypatch):
    calls = []

    def fake_json(url):
        calls.append(url)
        return {"name": "Software Developer", "releasedDate": "2026-10-19T15:46:05.691Z",
                "company": {"name": "Winsupply", "identifier": "Winsupply1"},
                "jobAd": {"sections": {
                    "companyDescription": {"title": "Company Description", "text": "<p>We sell &amp; ship.</p>"},
                    "jobDescription": {"title": "Job Description", "text": "<ul><li>Write Java.</li></ul>"},
                    "qualifications": {"title": "Qualifications", "text": ""}}}}

    monkeypatch.setattr(smartrecruiters, "get_json", fake_json)
    d = smartrecruiters.fetch_details(SR_URL)
    assert calls == ["https://api.smartrecruiters.com/v1/companies/Winsupply1/postings/3743990016228326"]
    assert d == JobDetails("Winsupply", "Software Developer", date(2026, 10, 19))
    assert d.posted_raw == "2026-10-19T15:46:05.691Z"
    assert d.description == "Company Description\nWe sell & ship.\nJob Description\nWrite Java."
    assert smartrecruiters.fetch_details("https://careers.smartrecruiters.com/Winsupply1") == JobDetails()


# ---------- UKG / UltiPro (milestone 1e) ----------

UKG_URL = ("https://recruiting2.ultipro.com/DES1004DFCU/JobBoard/117d2a3d-f3b9-413c-9fb0-4bb23de1c403/"
           "OpportunityDetail?opportunityId=db7b9339-25b3-4b67-a59f-f69ef00f6ae8&utm_source=linkedin&source=LinkedIn")
UKG_PAGE = """<html><script>
  $(function () {
    var opportunity = new US.Opportunity.CandidateOpportunityDetail({"Id":"db7b","Title":"Web Developer II",
      "PostedDate":"2026-09-15T15:40:32.649Z","Description":"<p>Build <b>apps</b> &amp; sites.</p>",
      "EqualOpportunityEmployerDescription":"Equal Opportunity Employer<br>Know your rights. (See notice)"});
  });
</script></html>"""


def test_ukg_page(monkeypatch):
    calls = []
    monkeypatch.setattr(ukg, "get_text", lambda url: calls.append(url) or UKG_PAGE)
    d = ukg.fetch_details(UKG_URL)
    assert calls == ["https://recruiting2.ultipro.com/DES1004DFCU/JobBoard/117d2a3d-f3b9-413c-9fb0-4bb23de1c403/"
                     "OpportunityDetail?opportunityId=db7b9339-25b3-4b67-a59f-f69ef00f6ae8"]
    assert d == JobDetails(None, "Web Developer II", date(2026, 9, 15))  # UKG has no company field
    assert d.posted_raw == "2026-09-15T15:40:32.649Z"
    assert d.description == "Build apps & sites.\nEqual Opportunity Employer\nKnow your rights. (See notice)"
    assert ukg.parse_page("<html>no job here</html>") == JobDetails()
    assert ukg.fetch_details("https://recruiting2.ultipro.com/DES1004DFCU/JobBoard/117d2a3d/") == JobDetails()


# ---------- ADP Workforce Now (milestone 1e) ----------

ADP_URL = ("https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
           "?cid=a67e64fb-ad7f-4857-9e34-38ede4751278&jobId=568057&lang=en_US&source=LinkedIn")


def test_adp_api(monkeypatch):
    calls = []

    def fake_json(url):
        calls.append(url)
        return {"itemID": "9201293595925_1", "requisitionTitle": "Product Development Specialist",
                "postDate": "2026-09-21T10:16:00.000-04:00",
                "requisitionDescription": "<p>Note: start in May.</p><ul><li>Bachelor&#39;s degree</li></ul>"}

    monkeypatch.setattr(adp, "get_json", fake_json)
    d = adp.fetch_details(ADP_URL)
    assert calls == ["https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/"
                     "job-requisitions/568057?cid=a67e64fb-ad7f-4857-9e34-38ede4751278&lang=en_US&locale=en_US"]
    assert d == JobDetails(None, "Product Development Specialist", date(2026, 9, 21))  # no company in ADP's API
    assert d.posted_raw == "2026-09-21T10:16:00.000-04:00"
    assert d.description == "Note: start in May.\nBachelor's degree"
    assert adp.parse_api({}) == JobDetails()  # a closed job comes back empty
