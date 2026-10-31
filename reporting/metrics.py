"""What the report page says (SPEC "Page layout"), each a pure function of the rows' Facts, the
settings and today. Rows with no readable Date are left out of anything counted by date."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from reporting import derive
from reporting.derive import AWAITING, IN_PROGRESS, NO_NEWS, REJECTED, Facts
from reporting.load import Settings

TODAY_SHOWN = 8  # today's applications listed before "+N more"
ATTENTION_SHOWN = 5  # lines in "Needs your attention" before "+N more"
MANY_SHOWN = 3  # "many applications" lines shown on the page before "+N more"
TOP_COMPANIES = 10


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def week_start(day: date) -> date:
    """The Monday of `day`'s week."""
    return day - timedelta(days=day.weekday())


def month_start(day: date) -> date:
    return day.replace(day=1)


def percent(r: int, n: int) -> str:
    """'3.9%', '5%', '0%': one decimal, none when it is .0."""
    return f"{round(100 * r / n, 1):g}%"


def rate_text(r: int, n: int, min_group: int) -> str:
    """'5 of 128 (3.9%)'; counts only when n is under `min_group`."""
    return f"{r} of {n} ({percent(r, n)})" if n >= min_group else f"{r} of {n}"


def change_text(n: int, last: int, period: str = "last week") -> str:
    if n > last:
        return f"↑ {n - last} from {period}"
    if n < last:
        return f"↓ {last - n} from {period}"
    return f"same as {period}"


def _applied_between(rows, first: date, last: date) -> list[Facts]:
    return [f for f in rows if f.job.applied and first <= f.job.applied <= last]


# ---------- 1-3. highlights, today and this week ----------

@dataclass
class Today:
    applications: list[Facts]  # Date = today, most recently added (highest row) first
    yesterday: int  # applications with Date = yesterday
    updates: list[Facts]  # Last Updated = today with a Stage or Outcome, new applications left out; highest row first


def _new_today(f: Facts, today: date) -> bool:
    """Applied today and nothing has happened yet: already in today's applications, not an update."""
    return f.job.applied == today and f.job.outcome == "Applied" and not f.job.stage


def today_facts(rows: list[Facts], today: date) -> Today:
    def newest_first(fs):
        return sorted(fs, key=lambda f: -f.job.row)
    return Today(applications=newest_first(f for f in rows if f.job.applied == today),
                 yesterday=sum(f.job.applied == today - timedelta(days=1) for f in rows),
                 updates=newest_first(f for f in rows if f.job.last_updated == today
                                      and (f.job.stage or f.job.outcome) and not _new_today(f, today)))


@dataclass
class ThisWeek:
    applications: int  # Monday to today
    last_week: int  # the previous full week
    new_responses: list[Facts]  # Stage set and Last Updated this week, oldest update first
    in_progress: int
    awaiting: int


def this_week(rows: list[Facts], today: date) -> ThisWeek:
    monday = week_start(today)
    new = sorted((f for f in rows if f.responded and f.job.last_updated and monday <= f.job.last_updated <= today),
                 key=lambda f: (f.job.last_updated, f.job.row))
    return ThisWeek(applications=len(_applied_between(rows, monday, today)),
                    last_week=len(_applied_between(rows, monday - timedelta(days=7), monday - timedelta(days=1))),
                    new_responses=new,
                    in_progress=sum(f.group == IN_PROGRESS for f in rows),
                    awaiting=sum(f.group == AWAITING for f in rows))


def best_source(rows: list[Facts], settings: Settings) -> tuple[str, int, int] | None:
    """(source, responses, applications) with the best response rate among sources with at least
    `min_group` applications and 2 responses; ties go to more responses. None if no source qualifies."""
    best = None
    for name in settings.sources:
        group = [f for f in rows if f.source == name]
        n, r = len(group), sum(f.responded for f in group)
        if n >= settings.min_group and r >= 2 and (best is None or (r / n, r) > (best[1] / best[2], best[1])):
            best = (name, r, n)
    return best


REJECTED_TODAY, RESPONSE, NEUTRAL = "rejected", "response", "neutral"  # highlight chip kinds


def highlights(rows: list[Facts], settings: Settings, today: date) -> list[tuple[str, str]]:
    """Up to 3 chips that only say what the cards don't: rejections set today, new responses this week
    (or that there are none), the best source. [(kind, text)]; a chip with nothing to say is left out."""
    chips = []
    rejected = sum(f.job.outcome == REJECTED and f.job.last_updated == today for f in rows)
    if rejected:
        chips.append((REJECTED_TODAY, f"{plural(rejected, 'rejection')} today"))
    new = len(this_week(rows, today).new_responses)
    chips.append((RESPONSE, f"{plural(new, 'new response')} this week") if new
                 else (NEUTRAL, "No new responses this week"))
    best = best_source(rows, settings)
    if best:
        name, r, n = best
        chips.append((NEUTRAL, f"Best source: {name} · {r} of {n}"))
    return chips


# ---------- 3. needs your attention ----------

def _companies(rows: list[Facts]) -> dict[str, list[Facts]]:
    """Rows by company key (Acme Inc = Acme), blank companies left out."""
    groups: dict[str, list[Facts]] = {}
    for f in rows:
        if f.company_key:
            groups.setdefault(f.company_key, []).append(f)
    return groups


def _newest(group: list[Facts]) -> Facts:
    return max(group, key=lambda f: (f.job.applied or date.min, f.job.row))


TURN, FOLLOW_UP, MANY = "turn", "follow", "many"  # attention line kinds


def attention(rows: list[Facts], settings: Settings, today: date) -> list[str]:
    """Your turn (In progress, oldest first), follow up (Awaiting reply too long, or since when unknown),
    then companies with many applications and no response. All of them; `cap` splits off the rest."""
    return [text for _, text in attention_items(rows, settings, today)]


def attention_items(rows: list[Facts], settings: Settings, today: date) -> list[tuple[str, str]]:
    """`attention` with each line's kind: [(TURN | FOLLOW_UP | MANY, text)], same order."""
    items = []
    yours = sorted((f for f in rows if f.group == IN_PROGRESS),
                   key=lambda f: (f.job.last_updated is None, f.job.last_updated or date.min, f.job.row))
    for f in yours:
        since = f" since {plural(f.since_update, 'day')}" if f.since_update is not None else ""
        items.append((TURN, f"{f.job.company}: {f.job.stage or 'next step'} to do{since}"))
    waiting = [f for f in rows if f.group == AWAITING]
    late = sorted((f for f in waiting if f.since_update is not None and f.since_update > settings.follow_up_days),
                  key=lambda f: (-f.since_update, f.job.row))
    items += [(FOLLOW_UP, f"{f.job.company}: {f.job.stage}, no reply for {plural(f.since_update, 'day')}")
              for f in late]
    items += [(FOLLOW_UP, f"{f.job.company}: {f.job.stage}, waiting (date unknown)")
              for f in waiting if f.since_update is None]
    many = [(len(g), _newest(g).job.company) for g in _companies(rows).values()
            if len(g) >= settings.many_applications and not any(f.responded for f in g)]
    items += [(MANY, f"{name}: {n} applications, no response") for n, name in sorted(many, key=lambda m: (-m[0], m[1]))]
    return items


def cap(lines: list[str], shown: int = ATTENTION_SHOWN) -> tuple[list[str], list[str]]:
    return lines[:shown], lines[shown:]


# ---------- totals and pipeline ----------

@dataclass
class Totals:
    applied: int  # every row
    responses: int  # Stage set
    awaiting: int  # status group Awaiting reply
    rejected: int  # Outcome Rejected


def totals(rows: list[Facts]) -> Totals:
    return Totals(len(rows), sum(f.responded for f in rows), sum(f.group == AWAITING for f in rows),
                  sum(f.job.outcome == REJECTED for f in rows))


SCREENING, INTERVIEW = "Initial Screening", "Interview"


def pipeline(rows: list[Facts]) -> list[tuple[str, int]]:
    """Applied -> Responses -> Initial Screening -> Interview, each "reached at least" (the tracker keeps only
    the current Stage, and Interview comes after Initial Screening)."""
    return [("Applied", len(rows)), ("Responses", sum(f.responded for f in rows)),
            (SCREENING, sum(f.job.stage in (SCREENING, INTERVIEW) for f in rows)),
            (INTERVIEW, sum(f.job.stage == INTERVIEW for f in rows))]


# ---------- 4-5. weekly and monthly ----------

@dataclass
class Week:
    start: date  # Monday
    applications: int
    responses: int  # applications from that week that got a response


def weekly(rows: list[Facts], settings: Settings, today: date) -> list[Week]:
    """The last `weeks_shown` weeks, oldest first, ending with this (partial) week."""
    this_monday = week_start(today)
    weeks = []
    for i in range(settings.weeks_shown - 1, -1, -1):
        start = this_monday - timedelta(weeks=i)
        applied = _applied_between(rows, start, start + timedelta(days=6))
        weeks.append(Week(start, len(applied), sum(f.responded for f in applied)))
    return weeks


@dataclass
class Month:
    start: date  # the 1st
    applications: int
    responses: int
    rejected: int
    rate: str  # rate_text


def monthly(rows: list[Facts], settings: Settings) -> list[Month]:
    """Every month with applications, newest first."""
    groups: dict[date, list[Facts]] = {}
    for f in rows:
        if f.job.applied:
            groups.setdefault(month_start(f.job.applied), []).append(f)
    months = []
    for start in sorted(groups, reverse=True):
        g = groups[start]
        r = sum(f.responded for f in g)
        months.append(Month(start, len(g), r, sum(f.job.outcome == REJECTED for f in g),
                            rate_text(r, len(g), settings.min_group)))
    return months


# ---------- 6-8. responses, top companies, no reply ----------

def _newest_first(rows: list[Facts]) -> list[Facts]:
    """By Date, newest first; rows with no readable Date last."""
    return sorted(rows, key=lambda f: (f.job.applied is None, -(f.job.applied or date.min).toordinal(), f.job.row))


def responses(rows: list[Facts]) -> list[Facts]:
    return _newest_first([f for f in rows if f.responded])


@dataclass
class CompanyRow:
    name: str  # as written on its newest row
    applications: int
    responses: int
    open: int  # In progress or Awaiting reply
    rejected: int
    last_applied: date | None
    mark: str  # "green" = any response, "muted" = many applications and none, else ""
    rejected_silent: int = field(default=0, compare=False)  # Rejected with no response (bar segments)


def top_companies(rows: list[Facts], settings: Settings) -> list[CompanyRow]:
    """Most applications first; ties: most recent application first."""
    table = []
    for g in _companies(rows).values():
        r = sum(f.responded for f in g)
        newest = _newest(g)
        mark = "green" if r else "muted" if len(g) >= settings.many_applications else ""
        table.append(CompanyRow(newest.job.company, len(g), r, sum(f.group in (IN_PROGRESS, AWAITING) for f in g),
                                sum(f.job.outcome == REJECTED for f in g), newest.job.applied, mark,
                                sum(f.group == REJECTED for f in g)))
    table.sort(key=lambda c: (-c.applications, -(c.last_applied or date.min).toordinal(), c.name))
    return table[:TOP_COMPANIES]


def no_reply(rows: list[Facts], settings: Settings, today: date) -> tuple[int, list[tuple[date, list[Facts]]]]:
    """Applied with no Stage for more than `no_reply_days`. -> (count, [(month, rows newest first)] newest first)"""
    quiet = [f for f in rows if f.group == NO_NEWS and f.age is not None and f.age > settings.no_reply_days]
    months: dict[date, list[Facts]] = {}
    for f in _newest_first(quiet):
        months.setdefault(month_start(f.job.applied), []).append(f)
    return len(quiet), list(months.items())


# ---------- 9. more details ----------

@dataclass
class GroupRow:
    name: str
    applications: int
    responses: int
    rate: str  # '3.9%' or 'too few to compare'
    rejections: int  # rows with Outcome Rejected


DETAILS = (("Source", lambda f: [f.source]), ("Job system", lambda f: [f.system]),
           ("Title level", lambda f: [f.level]), ("Title type", lambda f: [f.kind]),
           ("Remark tags", lambda f: f.tags))


def details(rows: list[Facts], settings: Settings) -> list[tuple[str, list[GroupRow]]]:
    """One table per grouping, groups with most applications first."""
    tables = []
    for title, groups_of in DETAILS:
        groups: dict[str, list[Facts]] = {}
        for f in rows:
            for name in groups_of(f):
                groups.setdefault(name, []).append(f)
        table = []
        for name, g in groups.items():
            r = sum(f.responded for f in g)
            rate = percent(r, len(g)) if len(g) >= settings.min_group else "too few to compare"
            table.append(GroupRow(name, len(g), r, rate, sum(f.job.outcome == REJECTED for f in g)))
        table.sort(key=lambda row: (-row.applications, row.name))
        tables.append((title, table))
    return tables


# ---------- 10. data check ----------

def data_check(rows: list[Facts], settings: Settings, excel: bool) -> list[tuple[str, list[Facts]]]:
    """[(issue, rows)] for every issue that has rows. URL formulas only count in the Excel file."""
    checks = [
        ("Blank Position", lambda f: not f.job.position),
        ("Blank URL", lambda f: not f.job.url),
        ("No source found in Posted date/ Source",
         lambda f: not derive.source_named(f.job.posted, settings.sources)),
        ("URL stored as a formula", lambda f: excel and f.job.url_is_formula),
        ("Stage set but Outcome Applied", lambda f: bool(f.job.stage) and f.job.outcome == "Applied"),
        ("In progress with no Stage", lambda f: f.job.outcome == IN_PROGRESS and not f.job.stage),
    ]
    issues = [(name, [f for f in rows if test(f)]) for name, test in checks]
    return [(name, found) for name, found in issues if found]
