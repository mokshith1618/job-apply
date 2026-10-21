"""Greenhouse: public Job Board API, and the form filler.

GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}
Fields used (confirmed 2026-10-13): title, company_name, first_published;
content (the description, escaped HTML; confirmed 2026-10-19).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import TimeoutError as PWTimeout

from . import form
from .common import JobDetails, clean, get_json, html_text, parse_date

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"


def parse_url(url: str) -> tuple[str | None, str | None]:
    """Return (board, job_id). Board is None for custom career sites using ?gh_jid=."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    m = re.match(r"^/([^/]+)/jobs/(\d+)", parts.path)
    if m and m.group(1) != "embed":
        return m.group(1), m.group(2)
    if "for" in query and "token" in query:  # /embed/job_app?for=board&token=id
        return query["for"][0], query["token"][0]
    if "gh_jid" in query:
        return None, query["gh_jid"][0]
    return None, None


def parse_api(data: dict) -> JobDetails:
    return JobDetails(
        company=clean(data.get("company_name")),
        position=clean(data.get("title")),
        posted_date=parse_date(data.get("first_published")),
        description=html_text(data.get("content")),
        posted_raw=clean(data.get("first_published")),
    )


def fetch_details(url: str) -> JobDetails:
    board, job_id = parse_url(url)
    if not (board and job_id):
        return JobDetails()  # caller falls back to the page's JSON-LD, then asks me
    return parse_api(get_json(API.format(board=board, job_id=job_id)))


# ---------------------------------------------------------------------------
# Form filler (Milestone 2). Field ids on the page equal the API field names
# (confirmed 2026-10-14 on job-boards.greenhouse.io): first_name, phone, resume,
# question_<n>, gender, veteran_status, school--0 ... Dropdowns are react-select:
# input[role=combobox] inside .select-shell, options are .select__option.
# NEVER submits: every click goes through _click, and nothing ever presses Enter.
# ---------------------------------------------------------------------------

FORM_URL = "https://job-boards.greenhouse.io/{board}/jobs/{job_id}"
KINDS = {
    "input_text": form.TEXT,
    "textarea": form.TEXTAREA,
    "input_file": form.FILE,
    "multi_value_single_select": form.SELECT,
    "multi_value_multi_select": form.MULTISELECT,
}
SKIP_IDS = {"resume_text", "cover_letter", "cover_letter_text", "latitude", "longitude"}
ID_ALIASES = {"location": "candidate-location"}  # API name -> element id
PREFIX_IDS = {"candidate-location", "school--0", "country"}  # autocompletes: option may add ", United States"
OPTION = ".select__option, [role=option]"
SUBMIT_WORDS = re.compile(r"\b(submit|apply|send)\b", re.I)


def _pretty(label: str) -> str:
    """'VeteranStatus' -> 'Veteran Status'. Labels with spaces ('LinkedIn Profile') stay as they are."""
    label = " ".join(str(label).split())
    return label if " " in label else re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label)


def fields_from_api(data: dict) -> list[form.Field]:
    """Questions, location, EEO and education from the ?questions=true payload, in page order."""
    groups = list(data.get("questions") or []) + list(data.get("location_questions") or [])
    for block in data.get("compliance") or []:
        groups += block.get("questions") or []
    fields, seen = [], set()
    for q in groups:
        for f in q.get("fields") or []:
            name = str(f.get("name") or "").removesuffix("[]")
            kind = KINDS.get(f.get("type"))
            if not kind or not name or name in SKIP_IDS:
                continue
            fid = ID_ALIASES.get(name, name)
            if fid in seen:
                continue
            if fid == "race" and "hispanic_ethnicity" not in seen:
                # The API lists only "race"; the page asks Hispanic/Latino first and shows race after it.
                seen.add("hispanic_ethnicity")
                fields.append(form.Field("hispanic_ethnicity", "Are you Hispanic/Latino?", form.SELECT,
                                         bool(q.get("required"))))
            seen.add(fid)
            if fid in PREFIX_IDS:  # the API says input_text, but the page shows an autocomplete dropdown
                kind = form.SELECT
            options = [str(v["label"]) for v in f.get("values") or [] if v.get("label")]
            fields.append(form.Field(fid, _pretty(q.get("label", fid)), kind, bool(q.get("required")), options))
    edu = data.get("education")
    if edu in ("education_required", "education_optional"):
        req = edu == "education_required"
        fields += [form.Field("school--0", "School", form.SELECT, req),
                   form.Field("degree--0", "Degree", form.SELECT, req),
                   form.Field("discipline--0", "Discipline", form.SELECT, req)]
    return fields


def plan_fill(fields, profile, answers, source) -> list[tuple[form.Field, form.Answer | None]]:
    return [(f, form.resolve(f, profile, answers, source)) for f in fields]


class SubmitRefused(RuntimeError):
    pass


def _click(locator) -> None:
    """The only way the filler clicks. Refuses anything that could submit the application."""
    info = locator.evaluate("""e => ({tag: e.tagName.toLowerCase(), type: String(e.type || '').toLowerCase(),
        role: e.getAttribute('role') || '', text: (e.innerText || e.value || '').trim()})""")
    clickable = info["tag"] in ("button", "a", "input") or info["role"] == "button"
    if (info["tag"] in ("button", "input") and info["type"] == "submit") or \
            (clickable and SUBMIT_WORDS.search(info["text"])):
        raise SubmitRefused(f"refused to click {info['tag']} {info['text']!r}")
    locator.click()


def _by_id(page, fid: str):
    return page.locator(f'#application-form [id="{fid}"]')


def _scope(page, el):
    """The dropdown's own container, so options from another open menu are never picked."""
    shell = el.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' select-shell ')][1]")
    return shell if shell.count() else page


def _read_options(page, el, typed: str = "", timeout: int = 3000) -> list[str]:
    """Open the dropdown (optionally typing to filter) and return the visible option texts."""
    _click(el)
    if typed:
        el.press_sequentially(typed, delay=15)
    opts = _scope(page, el).locator(OPTION)
    try:
        opts.first.wait_for(state="visible", timeout=timeout)
    except PWTimeout:
        return []
    if typed:
        page.wait_for_timeout(400)  # async lists (school, location) refine after the first results
    return [" ".join(t.split()) for t in opts.all_inner_texts()]


def _close_menu(el) -> None:
    el.press("Escape")  # Escape only; never Enter


def _choose(page, el, value: str, prefix: bool) -> str | None:
    """Pick the option equal to value (or starting with it, for autocompletes). No match = nothing picked."""
    texts = _read_options(page, el, value, timeout=6000 if prefix else 3000)
    pick = form.match_option(value, texts)
    if not pick and prefix:
        want = form.normalize_label(value)
        pick = next((t for t in texts if form.normalize_label(t).startswith(want)), None)
    if not pick:
        _close_menu(el)
        el.fill("")
        return None
    _click(_scope(page, el).locator(OPTION).nth(texts.index(pick)))
    return pick


def _apply(page, el, field: form.Field, value) -> bool:
    if field.kind == form.FILE:
        el.set_input_files(value)
        return True
    if field.kind in (form.TEXT, form.TEXTAREA):
        el.fill(value)
        return True
    ok = True
    for v in (value if isinstance(value, list) else [value]):
        ok = _choose(page, el, v, prefix=field.id in PREFIX_IDS) is not None and ok
    return ok


def _highlight(el) -> None:
    el.evaluate("""e => { const t = e.closest('.select__control') || e;
        t.style.outline = '3px solid red'; t.scrollIntoView({block: 'center'}); }""")


def _dom_label(page, field: form.Field) -> str:
    if field.kind == form.FILE:
        return field.label  # the page's label[for=resume] is the "Attach" button
    lab = page.locator(f'#application-form label[for="{field.id}"]')
    text = " ".join(lab.first.inner_text().split()).rstrip("*").strip() if lab.count() else ""
    return text or field.label


def _ask(field: form.Field, label: str, options: list[str], input_fn, note: str = ""):
    """Ask me in the terminal. Returns text, an option (a list for multi-select), or None = I'll do it in the browser."""
    print(f"\n  Required: {label}")
    if note:
        print(f"  ({note})")
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    multi = field.kind == form.MULTISELECT
    hint = "numbers, comma-separated" if multi else "number" if options else "answer"
    while True:
        raw = input_fn(f"  Your {hint} (blank = I'll fill it in the browser): ").strip()
        if not raw:
            return None
        if not options:
            return raw
        picks = []
        for part in (raw.split(",") if multi else [raw]):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= len(options):
                picks.append(options[int(part) - 1])
            elif opt := form.match_option(part, options):
                picks.append(opt)
            else:
                picks = []
                break
        if picks:
            return picks if multi else picks[0]
        print("  Pick from the numbered options.")


LEFTOVER_JS = r"""known => [...document.querySelectorAll(
      '#application-form [aria-required="true"][id], #application-form [required][id]')]
    .filter(e => !known.includes(e.id) && e.type !== 'hidden' && e.type !== 'search')
    .filter(e => e.getAttribute('role') === 'combobox'
        ? !e.closest('.select-shell')?.querySelector('.select__single-value, .select__multi-value')
        : (e.type === 'file' ? !e.files.length : !e.value))
    .map(e => { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]');
                return ((l && l.innerText) || e.id).replace(/\*\s*$/, '').trim(); })"""


def fill_form(page, fields, profile, answers: dict, answers_path, source, input_fn) -> form.FillReport:
    """Fill the open Greenhouse form. Leaves Submit to me."""
    report = form.FillReport()
    country_el = _by_id(page, "country")
    if country_el.count() and (country := profile.get("personal.country")):
        if _choose(page, country_el.first, country, prefix=True):
            report.filled.append(("Country (phone)", "profile:personal.country"))

    for field, answer in plan_fill(fields, profile, answers, source):
        el = _by_id(page, field.id)
        if not el.count():
            if field.required:
                report.attention.append((field.label, "not found on the page"))
            continue
        el = el.first
        label = _dom_label(page, field)
        if answer is not None and _apply(page, el, field, answer.value):
            report.filled.append((label, answer.source))
            continue
        miss = form.unmatched(field, profile, answers, source)
        note = f"{miss[1]} says {miss[0]!r}, which is not one of the options" if miss else ""
        if answer is not None:
            note = f"{answer.source} says {answer.value!r}, which the page didn't accept"
        if not field.required:
            if note:
                report.attention.append((label, note + "; pick it in the browser"))
            else:
                report.skipped.append(label)
            continue
        if field.kind == form.FILE:
            _highlight(el)
            report.attention.append((label, "attach the file yourself (resume_path missing?)"))
            continue
        options = field.options
        if field.kind in (form.SELECT, form.MULTISELECT) and not options:
            options = _read_options(page, el)
            _close_menu(el)
        _highlight(el)
        value = _ask(field, label, options, input_fn, note)
        if value is None:
            report.attention.append((label, "fill it in the browser"))
        elif _apply(page, el, field, value):
            report.filled.append((label, "me"))
            if input_fn("  Save to answers.yaml? [Y/n] ").strip().lower() != "n":
                form.save_answer(answers_path, label, value)
                answers[form.normalize_label(label)] = value
        else:
            report.attention.append((label, f"could not select {value!r}"))

    known = {f.id for f in fields} | {"country"}
    for label in page.evaluate(LEFTOVER_JS, sorted(known)):
        report.attention.append((label, "required, not in the job API; fill it in the browser"))
    return report


def resolve_board(page, url: str) -> tuple[str, str]:
    """(board, job_id). A company page with ?gh_jid= embeds the form in an iframe that names the board."""
    board, job_id = parse_url(url)
    if board and job_id:
        return board, job_id
    page.goto(url)
    frame = page.locator('iframe[src*="greenhouse.io/embed/job_app"]').first
    frame.wait_for(state="attached", timeout=20000)
    board, job_id = parse_url(frame.get_attribute("src") or "")
    if not (board and job_id):
        raise RuntimeError("could not find the Greenhouse form on that page")
    return board, job_id


class Session:
    """The open browser; apply.py closes it after I answer the pause prompt."""

    def __init__(self, report, context, playwright):
        self.report, self._context, self._pw = report, context, playwright

    def close(self) -> None:
        for step in (self._context.close if self._context else None, self._pw.stop):
            try:
                if step:
                    step()
            except Exception:  # noqa: BLE001 - I may have closed the window already
                pass


def open_and_fill(url: str, *, profile_path, answers_path, source, input_fn, user_data_dir) -> Session:
    """Open the form in visible Chrome (persistent profile), fill it, and leave it open for me."""
    from playwright.sync_api import sync_playwright

    profile = form.Profile.load(profile_path)
    answers = form.load_answers(answers_path)
    pw = sync_playwright().start()
    session = Session(None, None, pw)
    try:
        session._context = pw.chromium.launch_persistent_context(
            str(user_data_dir), channel="chrome", headless=False, no_viewport=True)
        page = session._context.pages[0] if session._context.pages else session._context.new_page()
        board, job_id = resolve_board(page, url)
        fields = fields_from_api(get_json(API.format(board=board, job_id=job_id) + "?questions=true"))
        page.goto(FORM_URL.format(board=board, job_id=job_id))
        page.locator("#application-form").wait_for(timeout=30000)
        print("Filling the form...")
        session.report = fill_form(page, fields, profile, answers, answers_path, source, input_fn)
        return session
    except BaseException:
        session.close()
        raise
