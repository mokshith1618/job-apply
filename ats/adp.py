"""ADP Workforce Now: public career-center API.

Job links: https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={cid}&jobId={id}
GET https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions/{jobId}
    ?cid={cid}&lang=en_US&locale=en_US
The link's jobId is the job's ExternalJobID. Fields used (confirmed 2026-10-19 on a live job):
requisitionTitle, postDate, requisitionDescription (HTML). A closed job comes back without them.
No company name in the API; the name I type is remembered per cid in companies.yaml.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from .common import JobDetails, clean, get_json, html_text, parse_date

HOST = "workforcenow.adp.com"
API = ("https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions/"
       "{job_id}?cid={cid}&lang=en_US&locale=en_US")


def parse_url(url: str) -> tuple[str | None, str | None]:
    """-> (cid, job id)."""
    parts = urlsplit(url.strip())
    if (parts.hostname or "").lower() != HOST:
        return (None, None)
    query = parse_qs(parts.query)
    cid, job_id = query.get("cid", [None])[0], query.get("jobId", [None])[0]
    return (cid, job_id) if cid and job_id else (None, None)


def parse_api(data) -> JobDetails:
    if not isinstance(data, dict):
        return JobDetails()
    return JobDetails(position=clean(data.get("requisitionTitle")),
                      posted_date=parse_date(data.get("postDate")),
                      description=html_text(data.get("requisitionDescription")),
                      posted_raw=clean(data.get("postDate")))


def fetch_details(url: str) -> JobDetails:
    cid, job_id = parse_url(url)
    if not (cid and job_id):
        return JobDetails()
    return parse_api(get_json(API.format(cid=cid, job_id=job_id)))
