"""The report as one self-contained HTML page (SPEC "Page layout" and "Look and feel").

Inline CSS and inline SVG only: no scripts, no external files, fonts or requests. Collapsible parts
are <details>. Every text that comes from the tracker goes through esc(); job links are only made
from http(s) URLs and open in a new tab, shown as the domain.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from urllib.parse import urlsplit

from reporting import metrics
from reporting.derive import AWAITING, IN_PROGRESS, NO_NEWS, REJECTED, REJECTED_AFTER, Facts
from reporting.load import Settings

GROUP_CLASS = {IN_PROGRESS: "progress", AWAITING: "response", REJECTED_AFTER: "rejected", REJECTED: "rejected",
               NO_NEWS: "none"}

CSS = """
:root { color-scheme: light dark;
  --bg: #fbfbfa; --card: #ffffff; --text: #24292f; --muted: #6a737d; --line: #e4e4e2;
  --bar: #c9ced6; --green: #2f855a; --blue: #2b6cb0; --red: #b35c5c; --grey: #8a9099; }
@media (prefers-color-scheme: dark) { :root {
  --bg: #16181b; --card: #1e2125; --text: #e3e5e8; --muted: #9aa1aa; --line: #2e3238;
  --bar: #4a515b; --green: #68b78b; --blue: #7aa7dd; --red: #d08b8b; --grey: #8d949e; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); line-height: 1.5;
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.4rem; margin: 0 0 12px; }
h2 { font-size: 1.1rem; margin: 0 0 10px; display: inline; }
section { margin: 28px 0; }
section > h2 { display: block; }
.summary p { margin: 4px 0; font-size: 1.05rem; }
.cards { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; }
.card section, .cards section { margin: 0; }
.stat { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; }
.stat b { font-weight: 600; }
ul.plain { list-style: none; padding: 0; margin: 0; }
ul.plain li { padding: 3px 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.92rem; margin: 8px 0; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.table-wrap { overflow-x: auto; }
summary { cursor: pointer; padding: 2px 0; }
details details { margin-left: 16px; }
.note, footer, .muted-text { color: var(--muted); font-size: 0.88rem; }
.response { color: var(--green); } .progress { color: var(--blue); }
.rejected { color: var(--red); } .none { color: var(--grey); }
tr.green td:first-child { box-shadow: inset 3px 0 var(--green); }
tr.muted td { color: var(--muted); }
a { color: inherit; }
svg { width: 100%; height: auto; display: block; }
svg text { fill: var(--muted); font-size: 11px; }
svg .bar { fill: var(--bar); } svg .dot { fill: var(--green); }
svg .target { stroke: var(--muted); stroke-dasharray: 4 4; }
@media (max-width: 640px) { .cards { grid-template-columns: 1fr; } }
"""


def esc(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def day(value: date | None) -> str:
    return f"{value:%m/%d/%Y}" if value else ""


def short_day(value: date) -> str:
    return f"{value:%b} {value.day}"


def link(url: str) -> str:
    """The job link as its domain, opening in a new tab; nothing for a value that isn't an http(s) link."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    return (f'<a href="{esc(url.strip())}" target="_blank" rel="noopener noreferrer">'
            f'{esc(parts.hostname.removeprefix("www."))}</a>')


def table(headers: list[str], rows: list[list[str]], numeric=(), row_classes=None) -> str:
    """`rows` are already-escaped cell HTML. Columns named in `numeric` are right-aligned."""
    def cls(h):
        return ' class="num"' if h in numeric else ""
    head = "".join(f"<th{cls(h)}>{esc(h)}</th>" for h in headers)
    body = []
    for i, row in enumerate(rows):
        rc = row_classes[i] if row_classes and row_classes[i] else ""
        cells = "".join(f"<td{cls(h)}>{c}</td>" for h, c in zip(headers, row))
        body.append(f'<tr class="{rc}">{cells}</tr>' if rc else f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def status(f: Facts, text: str) -> str:
    return f'<span class="{GROUP_CLASS.get(f.group, "")}">{esc(text)}</span>'


# ---------- sections ----------

def summary_section(sentences: list[str]) -> str:
    return '<section class="summary"><h2>Summary</h2>' + "".join(f"<p>{esc(s)}</p>" for s in sentences) + "</section>"


def week_card(week: metrics.ThisWeek) -> str:
    stats = [("Applications", f"{week.applications} · {metrics.change_text(week.applications, week.last_week)}"),
             ("Responses this week", str(len(week.new_responses))),
             ("In progress", str(week.in_progress)), ("Awaiting reply", str(week.awaiting))]
    rows = "".join(f'<div class="stat"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in stats)
    return f'<section class="card"><h2>This week</h2>{rows}</section>'


def attention_card(lines: list[str]) -> str:
    if not lines:
        body = "<p>Nothing needs your attention.</p>"
    else:
        shown, more = metrics.cap(lines)
        body = '<ul class="plain">' + "".join(f"<li>{esc(line)}</li>" for line in shown) + "</ul>"
        if more:
            body += (f"<details><summary>+{len(more)} more</summary><ul class=\"plain\">"
                     + "".join(f"<li>{esc(line)}</li>" for line in more) + "</ul></details>")
    return f'<section class="card"><h2>Needs your attention</h2>{body}</section>'


def chart(weeks: list[metrics.Week], target: int) -> str:
    """Bars = applications per week, a dot = how many of them got a response, dashed line = target."""
    width, height, left, right, top, bottom = 920, 220, 34, 70, 12, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    top_value = max([w.applications for w in weeks] + [target, 1])

    def y(value):
        return top + plot_h - plot_h * value / top_value
    slot = plot_w / max(len(weeks), 1)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Applications per week">']
    for i, w in enumerate(weeks):
        x = left + i * slot + slot * 0.2
        bar_w = slot * 0.6
        tip = (f"Week of {short_day(w.start)}: {metrics.plural(w.applications, 'application')}, "
               f"{metrics.plural(w.responses, 'response')}")
        parts.append(f'<g><title>{esc(tip)}</title><rect class="bar" x="{x:.1f}" y="{y(w.applications):.1f}" '
                     f'width="{bar_w:.1f}" height="{y(0) - y(w.applications):.1f}" rx="2"></rect>')
        if w.responses:
            parts.append(f'<circle class="dot" cx="{x + bar_w / 2:.1f}" cy="{y(w.responses):.1f}" r="4"></circle>')
        parts.append("</g>")
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{height - 8}" text-anchor="middle">{short_day(w.start)}</text>')
    parts.append(f'<line class="target" x1="{left}" x2="{left + plot_w}" y1="{y(target):.1f}" y2="{y(target):.1f}">'
                 "</line>")
    parts.append(f'<text x="{left + plot_w + 6}" y="{y(target) + 4:.1f}">target {target}</text>')
    parts.append(f'<text x="{left - 6}" y="{y(0):.1f}" text-anchor="end">0</text>')
    parts.append(f'<text x="{left - 6}" y="{y(top_value) + 8:.1f}" text-anchor="end">{top_value}</text>')
    parts.append("</svg>")
    return "".join(parts)


def weekly_section(weeks: list[metrics.Week], target: int) -> str:
    numbers = table(["Week of", "Applications", "Responses"],
                    [[short_day(w.start), str(w.applications), str(w.responses)] for w in reversed(weeks)],
                    numeric=("Applications", "Responses"))
    return (f"<section><h2>Weekly</h2>{chart(weeks, target)}"
            '<p class="note">Bars: applications per week. Dots: those that got a response. Dashed line: '
            f"weekly target.</p><details><summary>Show numbers</summary>{numbers}</details></section>")


def monthly_section(months: list[metrics.Month]) -> str:
    rows = [[f"{m.start:%B %Y}", str(m.applications), str(m.responses), str(m.rejected), esc(m.rate)]
            for m in months]
    body = table(["Month", "Applications", "Responses", "Rejected", "Response rate"], rows,
                 numeric=("Applications", "Responses", "Rejected")) if rows else "<p>No applications yet.</p>"
    return f"<section><h2>Monthly</h2>{body}</section>"


def responses_section(rows: list[Facts]) -> str:
    cells = [[esc(f.job.company), esc(f.job.position), esc(f.source), esc(f.system), day(f.job.applied),
              esc(f.job.stage), status(f, f.job.outcome), day(f.job.last_updated), link(f.job.url)] for f in rows]
    body = table(["Company", "Position", "Source", "Job system", "Applied", "Stage", "Outcome", "Last Updated",
                  "Link"], cells) if cells else "<p>No responses yet.</p>"
    return f"<section><h2>Your responses ({len(rows)})</h2>{body}</section>"


def top_section(companies: list[metrics.CompanyRow]) -> str:
    rows = [[esc(c.name), str(c.applications), str(c.responses), str(c.open), str(c.rejected), day(c.last_applied)]
            for c in companies]
    body = table(["Company", "Applications", "Responses", "In progress/Awaiting", "Rejected", "Last applied"], rows,
                 numeric=("Applications", "Responses", "In progress/Awaiting", "Rejected"),
                 row_classes=[c.mark for c in companies]) if rows else "<p>No applications yet.</p>"
    return f"<section><h2>Top 10 companies, with outcomes</h2>{body}</section>"


def no_reply_section(total: int, months, days: int) -> str:
    inner = "".join(
        f"<details><summary>{start:%B %Y} · {len(fs)}</summary>"
        + table(["Company", "Position", "Applied", "Link"],
                [[esc(f.job.company), esc(f.job.position), day(f.job.applied), link(f.job.url)] for f in fs])
        + "</details>" for start, fs in months)
    more = f"<details><summary>By month</summary>{inner}</details>" if months else ""
    return (f"<section><h2>No reply after {days} days</h2>"
            f"<p>{esc(metrics.plural(total, 'application'))} with no reply after {days} days.</p>{more}</section>")


def details_section(tables) -> str:
    parts = []
    for title, groups in tables:
        rows = [[esc(g.name), str(g.applications), str(g.responses), esc(g.rate), str(g.rejections)] for g in groups]
        parts.append(f"<h3>{esc(title)}</h3>" + (table(["Group", "Applications", "Responses", "Rate",
                                                         "Rejection notices"], rows,
                                                        numeric=("Applications", "Responses", "Rejection notices"))
                                                  if rows else '<p class="muted-text">None.</p>'))
    note = ('<p class="note">Rejection notices show how often companies tell you, not how well you did.</p>')
    return f"<section><details><summary><h2>More details</h2></summary>{note}{''.join(parts)}</details></section>"


def data_check_section(issues) -> str:
    count = sum(len(fs) for _, fs in issues)
    if not issues:
        body = "<p>No issues found.</p>"
    else:
        body = "".join(f"<h3>{esc(name)} ({len(fs)})</h3>"
                       + table(["Row", "Company"], [[str(f.job.row), esc(f.job.company)] for f in fs],
                               numeric=("Row",)) for name, fs in issues)
    return f"<section><details><summary><h2>Data check ({count})</h2></summary>{body}</details></section>"


def page(rows: list[Facts], settings: Settings, today: date, *, excel: bool, source_name: str,
         generated: datetime) -> str:
    total, months = metrics.no_reply(rows, settings, today)
    stamp = f"{generated:%m/%d/%Y} {generated.hour % 12 or 12}:{generated:%M %p}"
    body = "".join([
        summary_section(metrics.summary(rows, settings, today)),
        '<div class="cards">', week_card(metrics.this_week(rows, today)),
        attention_card(metrics.attention(rows, settings, today)), "</div>",
        weekly_section(metrics.weekly(rows, settings, today), settings.weekly_target),
        monthly_section(metrics.monthly(rows, settings)),
        responses_section(metrics.responses(rows)),
        top_section(metrics.top_companies(rows, settings)),
        no_reply_section(total, months, settings.no_reply_days),
        details_section(metrics.details(rows, settings)),
        data_check_section(metrics.data_check(rows, settings, excel)),
    ])
    footer = f"<footer>Generated {esc(stamp)} from {esc(source_name)} · {metrics.plural(len(rows), 'row')}</footer>"
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>Job search report</title><style>{CSS}</style></head>"
            f"<body><main><h1>Job search report · {today:%B} {today.day}, {today.year}</h1>{body}{footer}</main>"
            "</body></html>")
