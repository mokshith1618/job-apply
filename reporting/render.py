"""The report as one self-contained HTML page (SPEC "Page layout" and "Look and feel").

render.py works out what the page shows (values and chart geometry); templates/report.html.j2 draws
it, with autoescape on so every text from the tracker is escaped, and static/report.css styles it.
The CSS is embedded in a <style> block: no scripts, no external files, fonts or requests. Job links
are only made from http(s) URLs and open in a new tab, shown as the domain.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from reporting import metrics
from reporting.derive import AWAITING, IN_PROGRESS, NO_NEWS, REJECTED, REJECTED_AFTER, Facts
from reporting.load import Settings

HERE = Path(__file__).resolve().parent
GROUP_CLASS = {IN_PROGRESS: "progress", AWAITING: "response", REJECTED_AFTER: "rejected", REJECTED: "rejected",
               NO_NEWS: "none"}


@dataclass
class Link:
    href: str
    domain: str


@dataclass
class Status:
    text: str
    cls: str


@dataclass
class Table:
    headers: list[str]
    rows: list[list]  # cells: text, Link, Status or None
    numeric: tuple = ()
    row_classes: list[str] | None = None


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=True, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=False)
    env.tests["link"] = lambda v: isinstance(v, Link)
    env.tests["status"] = lambda v: isinstance(v, Status)
    env.globals["zip"] = zip
    return env


ENV = _env()


def day(value: date | None) -> str:
    return f"{value:%m/%d/%Y}" if value else ""


def short_day(value: date) -> str:
    return f"{value:%b} {value.day}"


def link(url: str) -> Link | None:
    """The job link as its domain; None for a value that isn't an http(s) link."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return Link(url.strip(), parts.hostname.removeprefix("www."))


def status(f: Facts, text: str) -> Status:
    return Status(text, GROUP_CLASS.get(f.group, ""))


def chart(weeks: list[metrics.Week], target: int) -> dict:
    """Bars = applications per week, a dot = how many of them got a response, dashed line = target."""
    width, height, left, right, top, bottom = 920, 220, 34, 70, 12, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    top_value = max([w.applications for w in weeks] + [target, 1])

    def y(value):
        return top + plot_h - plot_h * value / top_value
    slot = plot_w / max(len(weeks), 1)
    bars = []
    for i, w in enumerate(weeks):
        x = left + i * slot + slot * 0.2
        bar_w = slot * 0.6
        bars.append({
            "tip": (f"Week of {short_day(w.start)}: {metrics.plural(w.applications, 'application')}, "
                    f"{metrics.plural(w.responses, 'response')}"),
            "x": f"{x:.1f}", "y": f"{y(w.applications):.1f}", "w": f"{bar_w:.1f}",
            "h": f"{y(0) - y(w.applications):.1f}", "cx": f"{x + bar_w / 2:.1f}",
            "dot_y": f"{y(w.responses):.1f}" if w.responses else None, "label": short_day(w.start)})
    return {"width": width, "height": height, "bars": bars, "left": left, "right": left + plot_w,
            "target": target, "target_y": f"{y(target):.1f}", "target_label_y": f"{y(target) + 4:.1f}",
            "zero_y": f"{y(0):.1f}", "top_value": top_value, "top_y": f"{y(top_value) + 8:.1f}",
            "label_y": height - 8}


def weekly_numbers(weeks: list[metrics.Week]) -> Table:
    return Table(["Week of", "Applications", "Responses"],
                 [[short_day(w.start), str(w.applications), str(w.responses)] for w in reversed(weeks)],
                 numeric=("Applications", "Responses"))


def monthly_table(months: list[metrics.Month]) -> Table:
    return Table(["Month", "Applications", "Responses", "Rejected", "Response rate"],
                 [[f"{m.start:%B %Y}", str(m.applications), str(m.responses), str(m.rejected), m.rate]
                  for m in months],
                 numeric=("Applications", "Responses", "Rejected"))


def responses_table(rows: list[Facts]) -> Table:
    return Table(["Company", "Position", "Source", "Job system", "Applied", "Stage", "Outcome", "Last Updated",
                  "Link"],
                 [[f.job.company, f.job.position, f.source, f.system, day(f.job.applied), f.job.stage,
                   status(f, f.job.outcome), day(f.job.last_updated), link(f.job.url)] for f in rows])


def top_table(companies: list[metrics.CompanyRow]) -> Table:
    return Table(["Company", "Applications", "Responses", "In progress/Awaiting", "Rejected", "Last applied"],
                 [[c.name, str(c.applications), str(c.responses), str(c.open), str(c.rejected), day(c.last_applied)]
                  for c in companies],
                 numeric=("Applications", "Responses", "In progress/Awaiting", "Rejected"),
                 row_classes=[c.mark for c in companies])


def no_reply_months(months) -> list[dict]:
    return [{"name": f"{start:%B %Y}", "count": len(fs),
             "table": Table(["Company", "Position", "Applied", "Link"],
                            [[f.job.company, f.job.position, day(f.job.applied), link(f.job.url)] for f in fs])}
            for start, fs in months]


def details_tables(tables) -> list[dict]:
    return [{"title": title,
             "table": Table(["Group", "Applications", "Responses", "Rate", "Rejection notices"],
                            [[g.name, str(g.applications), str(g.responses), g.rate, str(g.rejections)]
                             for g in groups],
                            numeric=("Applications", "Responses", "Rejection notices"))}
            for title, groups in tables]


def data_check_tables(issues) -> list[dict]:
    return [{"name": name, "count": len(fs),
             "table": Table(["Row", "Company"], [[str(f.job.row), f.job.company] for f in fs], numeric=("Row",))}
            for name, fs in issues]


def page(rows: list[Facts], settings: Settings, today: date, *, excel: bool, source_name: str,
         generated: datetime) -> str:
    week = metrics.this_week(rows, today)
    weeks = metrics.weekly(rows, settings, today)
    lines = metrics.attention(rows, settings, today)
    shown, more = metrics.cap(lines)
    total, quiet_months = metrics.no_reply(rows, settings, today)
    issues = metrics.data_check(rows, settings, excel)
    responses = metrics.responses(rows)
    companies = metrics.top_companies(rows, settings)
    months = metrics.monthly(rows, settings)
    stamp = f"{generated:%m/%d/%Y} {generated.hour % 12 or 12}:{generated:%M %p}"
    return ENV.get_template("report.html.j2").render(
        css=Markup((HERE / "static" / "report.css").read_text(encoding="utf-8")),
        title_date=f"{today:%B} {today.day}, {today.year}",
        summary=metrics.summary(rows, settings, today),
        week_stats=[("Applications", f"{week.applications} · {metrics.change_text(week.applications, week.last_week)}"),
                    ("Responses this week", str(len(week.new_responses))),
                    ("In progress", str(week.in_progress)), ("Awaiting reply", str(week.awaiting))],
        attention_shown=shown, attention_more=more,
        chart=chart(weeks, settings.weekly_target), weekly_numbers=weekly_numbers(weeks),
        monthly=monthly_table(months) if months else None,
        responses_count=len(responses), responses=responses_table(responses) if responses else None,
        top=top_table(companies) if companies else None,
        no_reply_days=settings.no_reply_days, no_reply_total=metrics.plural(total, "application"),
        no_reply_months=no_reply_months(quiet_months),
        details=details_tables(metrics.details(rows, settings)),
        issue_count=sum(len(fs) for _, fs in issues), issues=data_check_tables(issues),
        stamp=stamp, source_name=source_name, row_count=metrics.plural(len(rows), "row"))
