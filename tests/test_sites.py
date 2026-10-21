"""Company names remembered per careers site (companies.yaml), with made-up links."""
import pytest

from ats import sites

WD = "https://umbrella.wd5.myworkdayjobs.com/en-US/UmbrellaCareers/job/Remote/Dev_JR1"


@pytest.mark.parametrize("url,system,key", [
    (WD, "workday", "umbrella.wd5.myworkdayjobs.com"),
    ("https://careers-hooli.icims.com/jobs/1/dev/job?mobile=false", "icims", "careers-hooli.icims.com"),
    ("https://abcd.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/1", "oracle",
     "abcd.fa.us2.oraclecloud.com"),
    ("https://job-boards.greenhouse.io/Acme/jobs/1", "greenhouse", "job-boards.greenhouse.io/acme"),
    ("https://boards.greenhouse.io/embed/job_app?for=acme&token=1", "greenhouse", "boards.greenhouse.io/acme"),
    ("https://jobs.lever.co/initech/aaaa/apply", "lever", "jobs.lever.co/initech"),
    ("https://ats.rippling.com/Hooli/jobs/aaaa", "rippling", "ats.rippling.com/hooli"),
    ("https://jobs.smartrecruiters.com/Winsupply1/3743990016228326", "smartrecruiters",
     "jobs.smartrecruiters.com/winsupply1"),
    ("https://recruiting2.ultipro.com/DES1004DFCU/JobBoard/117d/OpportunityDetail?opportunityId=1", "ukg",
     "recruiting2.ultipro.com/des1004dfcu"),  # many employers share this host; the tenant is the employer
    ("https://eventus.rec.pro.ukg.net/eve1500evew/JobBoard/4771/OpportunityDetail?opportunityId=1", "ukg",
     "eventus.rec.pro.ukg.net/eve1500evew"),
    ("https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=A67E&jobId=5", "adp",
     "workforcenow.adp.com/a67e"),  # cid is the employer
    ("https://apply.workable.com/CodeHunter/j/D1A0B33C26", "workable", "apply.workable.com/codehunter"),
    ("https://career55.sapsf.eu/career?career_job_req_id=158104&company=HCLPRD", "successfactors",
     "career55.sapsf.eu/hclprd"),  # one host serves many employers; company= is the employer
    ("https://www.linkedin.com/jobs/view/123", "other", None),  # job boards list many companies
    ("https://boards.greenhouse.io/embed/job_app?token=1", "greenhouse", None),
])
def test_site_key(url, system, key):
    assert sites.site_key(url, system) == key


@pytest.mark.parametrize("url,system,name", [
    ("https://hpe.wd5.myworkdayjobs.com/en-US/jobsathpe/job/X_1", "workday", "HPE"),
    (WD, "workday", "Umbrella"),
    ("https://careers-hooli.icims.com/jobs/1/job", "icims", "Hooli"),
    ("https://abcd.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/1", "oracle", None),
    ("https://acme.example/jobs/1", "other", None),
])
def test_name_from_link(url, system, name):
    assert sites.name_from_link(url, system) == name


def test_remember_and_load(tmp_path):
    path = tmp_path / "companies.yaml"
    assert sites.load(path) == {}
    sites.remember(path, "hpe.wd5.myworkdayjobs.com", "Hewlett Packard Enterprise")
    sites.remember(path, "careers-hooli.icims.com", "Hooli")
    assert sites.load(path) == {"hpe.wd5.myworkdayjobs.com": "Hewlett Packard Enterprise",
                                "careers-hooli.icims.com": "Hooli"}
    assert path.read_text(encoding="utf-8").startswith("# Company name per careers site")
