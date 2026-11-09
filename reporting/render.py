"""The report as one self-contained HTML page (SPEC "Page layout" and "Look and feel").

render.py works out what the page shows (values and chart geometry); templates/report.html.j2 draws
it, with autoescape on so every text from the tracker is escaped, and static/report.css styles it.
The CSS is embedded in a <style> block; the only script is the search box's (static/search.js,
inline), with its rows as escaped JSON. No external files, fonts or requests. Job links are only
made from http(s) URLs and open in a new tab, shown as the domain.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

import tracker
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


# ---------- 2-5. today, this week, totals, attention ----------

def progress(count: int, target: int, last: int, period: str, label: str) -> dict:
    """The big number toward a target, its bar (full at or over the target) and the change badge."""
    return {"count": count, "target": target, "label": label,
            "percent": min(100, round(100 * count / target)) if target > 0 else 100,
            "change": metrics.change_text(count, last, period),
            "direction": "up" if count > last else "down" if count < last else "same"}


UPDATE_CLASS = {REJECTED: "rejected", IN_PROGRESS: "progress", AWAITING: "followup"}  # else grey


def today_card(t: metrics.Today, target: int) -> dict:
    lines = [{"company": f.job.company, "position": f.job.position} for f in t.applications]
    shown, more = metrics.cap(lines, metrics.TODAY_SHOWN)
    updates = [{"company": f.job.company, "position": f.job.position, "stage": f.job.stage,
                "outcome": f.job.outcome, "outcome_cls": UPDATE_CLASS.get(f.job.outcome, "waiting")}
               for f in t.updates]
    updates_shown, updates_more = metrics.cap(updates, metrics.TODAY_SHOWN)
    return {"progress": progress(len(t.applications), target, t.yesterday, "yesterday",
                                 "Applications today toward the daily target"),
            "shown": shown, "more": more,
            "updates_count": len(updates), "updates_shown": updates_shown, "updates_more": updates_more}


def this_week(week: metrics.ThisWeek, target: int) -> dict:
    return {"progress": progress(week.applications, target, week.last_week, "last week",
                                 "Applications this week toward the weekly target"),
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


# ---------- 6. where your applications went (Sankey) ----------

SK_FONT = 12  # label font size (--text-chart), in SVG units
SK_CHAR = 0.6 * SK_FONT  # estimated width of one character; generous, so labels never collide
SK_LINE = 15  # label line height
SK_NODE_W = 10
SK_GAP = 10  # between nodes in a column
SK_MIN = 3  # thinnest band or node, in px
SK_PAD = 6  # node to its label
SK_RUN = 24  # band left visible after the widest label of a column
SK_FIRST_RUN = 48  # the first column's label sits above its node, so its bands need less room
SK_TOP = 40  # room above the nodes: the first column's label (and the bracket's note)
SK_WRAP = {WIDE: None, NARROW: 18}  # characters per label line; None = one line
SK_HEIGHT = {WIDE: 220, NARROW: 200}  # height the counts of a part are scaled to


@dataclass
class Box:
    """A label's estimated area, for the overlap checks."""
    x0: float
    y0: float
    x1: float
    y1: float

    def overlaps(self, other: "Box") -> bool:
        return self.x0 < other.x1 and other.x0 < self.x1 and self.y0 < other.y1 and other.y0 < self.y1


def label_lines(name: str, count: int, wrap: int | None) -> list[str]:
    """'Name · count', wrapped at spaces to `wrap` characters; the count stays with its dot."""
    words = name.split() + [f"· {count}"]
    if wrap is None:
        return [" ".join(words)]
    lines = [words[0]]
    for w in words[1:]:
        if len(lines[-1]) + 1 + len(w) <= wrap:
            lines[-1] += " " + w
        else:
            lines.append(w)
    return lines


def text_width(lines: list[str]) -> float:
    return max(len(line) for line in lines) * SK_CHAR


def sankey_part(part: metrics.FlowPart, x0: float, top: float, height: float, wrap: int | None) -> dict:
    """Lay out one part: nodes, bands as filled ribbons, labels right of each node (the first
    column's above it). Counts are scaled to `height` within this part; bands and nodes are at
    least SK_MIN px; a node is moved down when its label would touch the one above."""
    total = sum(nd.count for nd in part.columns[0])
    most = max(len(col) for col in part.columns)
    px = (height - (most - 1) * SK_GAP) / total
    widths = {id(b): max(b.count * px, SK_MIN) for b in part.bands}
    out = {nd.key: [b for b in part.bands if b.source == nd.key] for col in part.columns for nd in col}
    into = {nd.key: [b for b in part.bands if b.target == nd.key] for col in part.columns for nd in col}
    order = {nd.key: (i, j) for i, col in enumerate(part.columns) for j, nd in enumerate(col)}
    lines = {nd.key: label_lines(nd.name, nd.count, None if i == 0 else wrap)
             for i, col in enumerate(part.columns) for nd in col}

    xs = [x0]
    for i, col in enumerate(part.columns[:-1]):
        run = SK_FIRST_RUN if i == 0 else SK_PAD + max(text_width(lines[nd.key]) for nd in col) + SK_RUN
        xs.append(xs[-1] + SK_NODE_W + run)

    placed, start_y, end_y, boxes = {}, {}, {}, []
    for i, col in enumerate(part.columns):
        node_bottom, label_bottom = None, top - 4
        for nd in col:
            h = max(nd.count * px, SK_MIN, sum(widths[id(b)] for b in out[nd.key]),
                    sum(widths[id(b)] for b in into[nd.key]))
            lh = len(lines[nd.key]) * SK_LINE
            ideal = min((start_y[id(b)] for b in into[nd.key]), default=top)
            y = max(ideal, top if node_bottom is None else node_bottom + SK_GAP)
            if i > 0:
                y = max(y, label_bottom + lh / 2 - h / 2)
            node_bottom = y + h
            placed[nd.key] = {"x": xs[i], "y": y, "h": h, "node": nd}
            if i == 0:  # above the node
                lx, ly0 = xs[i], top - 10 - SK_FONT
            else:
                lx, ly0 = xs[i] + SK_NODE_W + SK_PAD, y + h / 2 - lh / 2
                label_bottom = ly0 + lh + 4
            box = Box(lx, ly0, lx + text_width(lines[nd.key]), ly0 + len(lines[nd.key]) * SK_LINE)
            placed[nd.key].update(lx=lx, ly0=ly0, box=box)
            boxes.append((i, box))
            # where this node's bands leave it, in the order of their targets
            offset = y
            for b in sorted(out[nd.key], key=lambda b: order[b.target]):
                start_y[id(b)] = offset
                offset += widths[id(b)]
        for nd in col:  # where bands arrive, in the order of their sources
            offset = placed[nd.key]["y"]
            for b in sorted(into[nd.key], key=lambda b: order[b.source]):
                end_y[id(b)] = offset
                offset += widths[id(b)]

    names = {k: v["node"].name for k, v in placed.items()}
    bands = []
    for b in part.bands:
        sx, tx = placed[b.source]["x"] + SK_NODE_W, placed[b.target]["x"]
        sy, ty, w = start_y[id(b)], end_y[id(b)], widths[id(b)]
        mid = (sx + tx) / 2
        d = (f"M{n(sx)},{n(sy)} C{n(mid)},{n(sy)} {n(mid)},{n(ty)} {n(tx)},{n(ty)} "
             f"L{n(tx)},{n(ty + w)} C{n(mid)},{n(ty + w)} {n(mid)},{n(sy + w)} {n(sx)},{n(sy + w)} Z")
        bands.append({"d": d, "cls": placed[b.target]["node"].cls, "w": w,
                      "tip": f"{names[b.source]} -> {names[b.target]}: {b.count}"})
    nodes = []
    for key, v in placed.items():
        node = v["node"]
        nodes.append({"x": n(v["x"]), "y": n(v["y"]), "w": SK_NODE_W, "h": n(v["h"]), "cls": node.cls,
                      "tip": f"{node.name}: {node.count}", "lx": n(v["lx"]),
                      "lines": [{"text": t, "y": n(v["ly0"] + k * SK_LINE + SK_FONT)}
                                for k, t in enumerate(lines[key])],
                      "box": v["box"], "column": order[key][0]})
    right = max([b.x1 for _, b in boxes] + [v["x"] + SK_NODE_W for v in placed.values()])
    bottom = max([b.y1 for _, b in boxes] + [v["y"] + v["h"] for v in placed.values()])
    return {"nodes": nodes, "bands": bands, "right": right, "bottom": bottom}


def sankey(f: metrics.Flow, shape: str = WIDE) -> dict:
    """The left part, then the zoomed-in Responded part: beside it on desktop with a dashed bracket
    between them, below it on phones with a dashed bracket above it."""
    wrap, height = SK_WRAP[shape], SK_HEIGHT[shape]
    parts = [sankey_part(f.left, 0, SK_TOP, height, wrap)]
    bracket = None
    if f.right is not None:
        note = f"zoomed in: {metrics.plural(f.responses, 'response')}"
        if shape == WIDE:
            xb = parts[0]["right"] + 28
            right = sankey_part(f.right, xb + 16, SK_TOP, height, wrap)
            y0, y1 = SK_TOP - 4, right["bottom"]
            bracket = {"d": f"M{n(xb + 8)},{n(y0)} L{n(xb)},{n(y0)} L{n(xb)},{n(y1)} L{n(xb + 8)},{n(y1)}",
                       "x": n(xb), "y": n(SK_TOP - 30), "text": note}
        else:
            yb = parts[0]["bottom"] + 34
            right = sankey_part(f.right, 0, yb + SK_TOP - 6, height, wrap)
            x1 = max(parts[0]["right"], right["right"])
            bracket = {"d": f"M0,{n(yb + 8)} L0,{n(yb)} L{n(x1)},{n(yb)} L{n(x1)},{n(yb + 8)}",
                       "x": "0", "y": n(yb - 8), "text": note}
        parts.append(right)
    width = max(p["right"] for p in parts) + 4
    return {"shape": shape, "parts": parts, "bracket": bracket, "width": round(width),
            "height": round(max(p["bottom"] for p in parts) + 8)}


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


# ---------- 0. search ----------

# < > & and the two JS line separators (U+2028, U+2029) as JSON escapes, e.g. "<" -> "\u003c"
JSON_ESCAPES = {c: "\\u%04x" % ord(c) for c in "<>&" + chr(0x2028) + chr(0x2029)}


def script_json(value) -> str:
    """JSON safe inside a <script> block: no tracker text can close it or start a comment."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    for char, escaped in JSON_ESCAPES.items():
        text = text.replace(char, escaped)
    return text


def search_data(rows: list[Facts], settings: Settings) -> str:
    """The rows the search box needs, newest applied first (same day: highest row, the last added;
    no Date last). Keys come from tracker.search_key (find.py's normalization); the suffix list is
    for the script, which normalizes only the typed text."""
    def row(f: Facts) -> dict:
        lk = link(f.job.url)
        return {"company": f.job.company, "company_key": f.company_key, "position": f.job.position,
                "position_key": tracker.search_key(f.job.position), "applied": day(f.job.applied),
                "outcome": f.job.outcome or "Applied", "outcome_cls": outcome_class(f, settings),
                "stage": f.job.stage, "domain": lk.domain if lk else "", "href": lk.href if lk else ""}
    newest = sorted(rows, key=lambda f: (f.job.applied is None, -(f.job.applied or date.min).toordinal(), -f.job.row))
    return script_json({"suffixes": sorted(tracker.COMPANY_SUFFIXES), "rows": [row(f) for f in newest]})


def page(rows: list[Facts], settings: Settings, today: date, *, excel: bool, source_name: str,
         generated: datetime) -> str:
    weeks = metrics.weekly(rows, settings, today)
    shown, more = attention(metrics.attention_items(rows, settings, today))
    total, quiet_months = metrics.no_reply(rows, settings, today)
    issues = metrics.data_check(rows, settings, excel)
    responses = metrics.responses(rows)
    months = metrics.monthly(rows, settings)
    flow = metrics.flow(rows, settings)
    stamp = f"{generated:%m/%d/%Y} {generated.hour % 12 or 12}:{generated:%M %p}"
    return ENV.get_template("report.html.j2").render(
        css=Markup((HERE / "static" / "report.css").read_text(encoding="utf-8")),
        title_date=f"{today:%B} {today.day}, {today.year}",
        highlights=metrics.highlights(rows, settings, today),
        day=today_card(metrics.today_facts(rows, today), settings.daily_target),
        week=this_week(metrics.this_week(rows, today), settings.weekly_target),
        tiles=tiles(metrics.totals(rows)),
        attention_shown=shown, attention_more=more,
        weekly=[weekly_chart(weeks, settings.weekly_target, shape) for shape in (WIDE, NARROW)],
        weekly_numbers=weekly_numbers(weeks),
        flow=[sankey(flow, shape) for shape in (WIDE, NARROW)] if flow else None,
        flow_responses=flow.responses if flow else 0,
        monthly=[monthly_chart(months, shape) for shape in (WIDE, NARROW)] if months else None,
        monthly_numbers=monthly_table(months),
        responses=response_cards(responses, settings),
        top=company_bars(metrics.top_companies(rows, settings)),
        no_reply_days=settings.no_reply_days, no_reply_total=metrics.plural(total, "application"),
        no_reply_months=no_reply_months(quiet_months),
        details=details_tables(metrics.details(rows, settings)),
        issue_count=sum(len(fs) for _, fs in issues), issues=data_check_tables(issues),
        stamp=stamp, source_name=source_name, row_count=metrics.plural(len(rows), "row"),
        search_json=Markup(search_data(rows, settings)),
        search_js=Markup((HERE / "static" / "search.js").read_text(encoding="utf-8")))
