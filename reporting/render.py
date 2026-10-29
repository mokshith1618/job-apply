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
from reporting.derive import AWAITING, IN_PROGRESS, REJECTED, REJECTED_AFTER, Facts
from reporting.load import Settings

HERE = Path(__file__).resolve().parent
MONTHS_SHOWN = 12  # months in the monthly chart; the "Show numbers" table has them all
# Each chart is drawn twice, shown by window width: wide for desktop, a taller narrow one for phones.
WIDE, NARROW = "wide", "narrow"
KIND_LABEL = {metrics.TURN: "Your turn", metrics.FOLLOW_UP: "Follow up", metrics.MANY: "Many applications"}


@dataclass
class Link:
    href: str
    domain: str


@dataclass
class Table:
    headers: list[str]
    rows: list[list]  # cells: text, Link or None
    numeric: tuple = ()


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=True, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True)
    env.tests["link"] = lambda v: isinstance(v, Link)
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


def n(value: float) -> str:
    """An SVG coordinate."""
    return f"{value:.1f}"


# ---------- 2-4. this week, totals, attention ----------

def this_week(week: metrics.ThisWeek, target: int) -> dict:
    direction = "up" if week.applications > week.last_week else "down" if week.applications < week.last_week \
        else "same"
    return {"applications": week.applications, "target": target,
            "percent": min(100, round(100 * week.applications / target)) if target > 0 else 100,
            "change": metrics.change_text(week.applications, week.last_week), "direction": direction,
            "responses": metrics.plural(len(week.new_responses), "new response"),
            "in_progress": week.in_progress}


def tiles(t: metrics.Totals) -> list[dict]:
    return [{"label": "Applied", "value": t.applied, "cls": ""},
            {"label": "Responses", "value": t.responses, "cls": "response"},
            {"label": "Awaiting reply", "value": t.awaiting, "cls": "waiting"},
            {"label": "Rejected", "value": t.rejected, "cls": "rejected"}]


def attention(items: list[tuple[str, str]]) -> tuple[list[dict], list[dict]]:
    """(shown, under "+N more"): every Your turn and Follow up line, at most MANY_SHOWN Many applications."""
    def chip(kind, text):
        return {"kind": kind, "label": KIND_LABEL[kind], "text": text}
    many_shown, many_more = metrics.cap([text for kind, text in items if kind == metrics.MANY], metrics.MANY_SHOWN)
    shown = [chip(kind, text) for kind, text in items if kind != metrics.MANY]
    return shown + [chip(metrics.MANY, t) for t in many_shown], [chip(metrics.MANY, t) for t in many_more]


# ---------- 5-6. charts ----------

def weekly_chart(weeks: list[metrics.Week], target: int, shape: str = WIDE) -> dict:
    """Bars = applications per week (brighter at or above the target), a dot = how many of them got a
    response, dashed line = target. The narrow shape labels every other week."""
    width, height, left, right, top, bottom = (920, 220, 34, 70, 12, 26) if shape == WIDE else (400, 230, 30, 62, 12, 26)
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
            "hit": target > 0 and w.applications >= target,
            "x": n(x), "y": n(y(w.applications)), "w": n(bar_w), "h": n(y(0) - y(w.applications)),
            "cx": n(x + bar_w / 2), "dot_y": n(y(w.responses)) if w.responses else None,
            "label": short_day(w.start), "alt": shape == NARROW and (len(weeks) - 1 - i) % 2 == 1})
    return {"shape": shape, "width": width, "height": height, "bars": bars, "left": left, "right": left + plot_w,
            "target": target, "target_y": n(y(target)), "target_label_y": n(y(target) + 4),
            "zero_y": n(y(0)), "top_value": top_value, "top_y": n(y(top_value) + 8), "label_y": height - 8}


def monthly_chart(months: list[metrics.Month], shape: str = WIDE) -> dict:
    """Paired bars per month, oldest left: applications (neutral) and responses (green). The narrow shape
    labels every other month."""
    shown = list(reversed(months[:MONTHS_SHOWN]))
    width, height, left, right, top, bottom = (920, 180, 34, 12, 12, 26) if shape == WIDE else (400, 200, 30, 6, 12, 26)
    plot_w, plot_h = width - left - right, height - top - bottom
    top_value = max([m.applications for m in shown] + [1])

    def y(value):
        return top + plot_h - plot_h * value / top_value
    slot = plot_w / max(len(shown), 1)
    bar_w = min(slot * 0.3, 40)
    groups = []
    for i, m in enumerate(shown):
        mid = left + i * slot + slot / 2
        new_year = i == 0 or m.start.month == 1
        groups.append({
            "apps": {"x": n(mid - bar_w - 1), "y": n(y(m.applications)), "h": n(y(0) - y(m.applications)),
                     "tip": f"{m.start:%B %Y}: {metrics.plural(m.applications, 'application')}"},
            "resp": {"x": n(mid + 1), "y": n(y(m.responses)), "h": n(y(0) - y(m.responses)),
                     "tip": f"{m.start:%B %Y}: {metrics.plural(m.responses, 'response')} ({m.rate})"},
            "cx": n(mid), "label": f"{m.start:%b %Y}" if new_year else f"{m.start:%b}",
            "alt": shape == NARROW and (len(shown) - 1 - i) % 2 == 1})
    return {"shape": shape, "width": width, "height": height, "groups": groups, "bar_w": n(bar_w), "left": left,
            "zero_y": n(y(0)), "top_value": top_value, "top_y": n(y(top_value) + 8), "label_y": height - 8}


def weekly_numbers(weeks: list[metrics.Week]) -> Table:
    return Table(["Week of", "Applications", "Responses"],
                 [[short_day(w.start), str(w.applications), str(w.responses)] for w in reversed(weeks)],
                 numeric=("Applications", "Responses"))


def monthly_table(months: list[metrics.Month]) -> Table:
    return Table(["Month", "Applications", "Responses", "Rejected", "Response rate"],
                 [[f"{m.start:%B %Y}", str(m.applications), str(m.responses), str(m.rejected), m.rate]
                  for m in months],
                 numeric=("Applications", "Responses", "Rejected"))


# ---------- 8-9. responses and top companies ----------

def outcome_class(f: Facts, settings: Settings) -> str:
    if f.group == IN_PROGRESS:
        return "progress"
    if f.group in (REJECTED, REJECTED_AFTER):
        return "rejected"
    if f.group == AWAITING and f.since_update is not None and f.since_update > settings.follow_up_days:
        return "followup"
    return "waiting"


def response_cards(rows: list[Facts], settings: Settings) -> list[dict]:
    return [{"company": f.job.company, "position": f.job.position, "stage": f.job.stage,
             "outcome": f.job.outcome or "Applied", "outcome_cls": outcome_class(f, settings),
             "facts": [("Source", f.source), ("Job system", f.system), ("Applied", day(f.job.applied)),
                       ("Last Updated", day(f.job.last_updated) or "unknown")],
             "link": link(f.job.url)} for f in rows]


def company_bars(companies: list[metrics.CompanyRow]) -> list[dict]:
    """Bar length = applications (the longest is the first company); green = rows with a response,
    red = rejected with no response, the rest neutral. Widths in percent of the longest bar."""
    longest = max([c.applications for c in companies] + [1])
    bars = []
    for c in companies:
        green, red = c.responses, c.rejected_silent
        rest = max(c.applications - green - red, 0)
        unit = 100 / longest
        bars.append({
            "name": c.name, "mark": c.mark,
            "green": n(green * unit), "red": n(red * unit), "rest": n(rest * unit),
            "red_x": n(green * unit), "rest_x": n((green + red) * unit),
            "text": f"{c.applications} · {metrics.plural(c.responses, 'response')} · {c.rejected} rejected",
            "tip": (f"{c.name}: {metrics.plural(c.applications, 'application')}, "
                    f"{metrics.plural(c.responses, 'response')}, {c.open} in progress or awaiting, "
                    f"{c.rejected} rejected, last applied {day(c.last_applied) or 'unknown'}")})
    return bars


# ---------- 10-12. collapsed sections ----------

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
    weeks = metrics.weekly(rows, settings, today)
    shown, more = attention(metrics.attention_items(rows, settings, today))
    total, quiet_months = metrics.no_reply(rows, settings, today)
    issues = metrics.data_check(rows, settings, excel)
    responses = metrics.responses(rows)
    months = metrics.monthly(rows, settings)
    stamp = f"{generated:%m/%d/%Y} {generated.hour % 12 or 12}:{generated:%M %p}"
    return ENV.get_template("report.html.j2").render(
        css=Markup((HERE / "static" / "report.css").read_text(encoding="utf-8")),
        title_date=f"{today:%B} {today.day}, {today.year}",
        summary=metrics.summary(rows, settings, today),
        week=this_week(metrics.this_week(rows, today), settings.weekly_target),
        tiles=tiles(metrics.totals(rows)),
        attention_shown=shown, attention_more=more,
        weekly=[weekly_chart(weeks, settings.weekly_target, shape) for shape in (WIDE, NARROW)],
        weekly_numbers=weekly_numbers(weeks),
        monthly=[monthly_chart(months, shape) for shape in (WIDE, NARROW)] if months else None,
        monthly_numbers=monthly_table(months),
        pipeline=metrics.pipeline(rows),
        responses=response_cards(responses, settings),
        top=company_bars(metrics.top_companies(rows, settings)),
        no_reply_days=settings.no_reply_days, no_reply_total=metrics.plural(total, "application"),
        no_reply_months=no_reply_months(quiet_months),
        details=details_tables(metrics.details(rows, settings)),
        issue_count=sum(len(fs) for _, fs in issues), issues=data_check_tables(issues),
        stamp=stamp, source_name=source_name, row_count=metrics.plural(len(rows), "row"))
