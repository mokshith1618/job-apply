"""Oracle Cloud (Oracle Recruiting Cloud, "Candidate Experience"): public REST API.

Job links: https://{host}/hcmUI/CandidateExperience/{lang}/sites/{site}/job/{id}
GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
    ?expand=all&onlyData=true&finder=ById;Id="{id}",siteNumber={site}
Fields used (confirmed 2026-10-15): items[0].Title, items[0].ExternalPostedStartDate;
the description from the DESCRIPTION_FIELDS below (HTML, confirmed 2026-10-19).
The job API has no company name. The site API (recruitingCESites) has SeoOrganizationName,
which is often null; then I'm asked in the terminal.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .common import JobDetails, clean, get_json, html_text, parse_date

DETAILS_API = ("{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
               '?expand=all&onlyData=true&finder=ById;Id="{job_id}",siteNumber={site}')
SITE_API = "{base}/hcmRestApi/resources/latest/recruitingCESites?onlyData=true&q=SiteNumber={site}"


def parse_url(url: str) -> tuple[str | None, str | None, str | None]:
    """-> (https://host, site number, job id)."""
    parts = urlsplit(url.strip())
    m = re.search(r"/sites/([^/]+)/(?:job|requisitions/preview)/(\d+)", parts.path)
    if not (parts.hostname and m):
        return (None, None, None)
    return (f"https://{parts.netloc}", m.group(1), m.group(2))


def _first_item(data) -> dict:
    items = data.get("items") if isinstance(data, dict) else None
    return items[0] if items and isinstance(items[0], dict) else {}


# HTML fields that make up the description on the job page, in page order.
DESCRIPTION_FIELDS = ("OrganizationDescriptionStr", "ExternalDescriptionStr", "ExternalResponsibilitiesStr",
                      "ExternalQualificationsStr", "CorporateDescriptionStr")


def parse_api(data) -> JobDetails:
    item = _first_item(data)
    text = "\n".join(t for t in (html_text(item.get(f)) for f in DESCRIPTION_FIELDS) if t)
    return JobDetails(position=clean(item.get("Title")),
                      posted_date=parse_date(item.get("ExternalPostedStartDate")),
                      description=text or None,
                      posted_raw=clean(item.get("ExternalPostedStartDate")))


def parse_site(data) -> str | None:
    return clean(_first_item(data).get("SeoOrganizationName"))


def fetch_details(url: str) -> JobDetails:
    base, site, job_id = parse_url(url)
    if not (base and site and job_id):
        return JobDetails()
    details = parse_api(get_json(DETAILS_API.format(base=base, job_id=job_id, site=site)))
    try:  # company name, when the site sets one
        details.company = parse_site(get_json(SITE_API.format(base=base, site=site)))
    except Exception as exc:  # noqa: BLE001 - keep the API result, ask for the rest
        print(f"  Could not read Oracle site info: {exc}")
    return details
