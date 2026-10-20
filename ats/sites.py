"""Company names I've typed, remembered per careers site in companies.yaml.

Some sites never publish the company (HPE's Workday has "hiringOrganization": {"name": ""}),
so the first time I type it, it is saved under the site and filled in from then on.

Only sites that belong to one company are remembered: a Workday/iCIMS/Oracle host, or a
Greenhouse/Ashby/Lever/Rippling board. A job board like linkedin.com is never a key.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

SHARED_HOSTS = {"job-boards.greenhouse.io", "boards.greenhouse.io", "jobs.ashbyhq.com", "jobs.lever.co",
                "ats.rippling.com", "jobs.smartrecruiters.com", "careers.smartrecruiters.com"}
REMEMBERED_SYSTEMS = {"greenhouse", "ashby", "lever", "rippling", "workday", "icims", "oracle",
                      "smartrecruiters", "ukg", "adp"}


def site_key(url: str, system: str) -> str | None:
    """'https://hpe.wd5.myworkdayjobs.com/en-US/...' -> 'hpe.wd5.myworkdayjobs.com';
    'https://job-boards.greenhouse.io/figma/jobs/1' -> 'job-boards.greenhouse.io/figma'."""
    if system not in REMEMBERED_SYSTEMS:
        return None
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not host:
        return None
    if host in SHARED_HOSTS:
        board = parse_qs(parts.query).get("for", [None])[0]  # greenhouse embed: ?for={board}
        segments = [s for s in parts.path.split("/") if s]
        if not board and segments and segments[0] != "embed":
            board = segments[0]
        return f"{host}/{board.lower()}" if board else None
    if system == "adp":  # one host for every ADP employer; the cid is the employer
        cid = parse_qs(parts.query).get("cid", [None])[0]
        return f"{host}/{cid.lower()}" if cid else None
    if system == "ukg":  # one host serves many employers; the first path part is the employer
        segments = [s for s in parts.path.split("/") if s]
        return f"{host}/{segments[0].lower()}" if segments else None
    return host


def name_from_link(url: str, system: str) -> str | None:
    """A first-time suggestion from the link: 'hpe.wd5.myworkdayjobs.com' -> 'HPE',
    'careers-hyland.icims.com' -> 'Hyland'. Oracle hosts are tenant codes, so none there."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    if system == "workday" and host.endswith(".myworkdayjobs.com"):
        name = host.split(".")[0]
    elif system == "icims" and host.endswith(".icims.com"):
        name = host.split(".")[0].removeprefix("careers-").removeprefix("jobs-")
    else:
        return None
    if not name.isalpha():
        return None
    return name.upper() if len(name) <= 4 else name.capitalize()


def load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k).lower(): str(v) for k, v in data.items() if v} if isinstance(data, dict) else {}


def remember(path: Path, key: str, company: str) -> None:
    names = load(path)
    names[key] = company
    text = "# Company name per careers site; filled in by apply.py. Edit freely.\n"
    text += yaml.safe_dump(dict(sorted(names.items())), allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
