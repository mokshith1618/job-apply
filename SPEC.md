# Job Apply Helper: Spec

A personal command-line tool. I paste a job link, it opens the application in a browser,
fills what it can from my profile, stops before submit, and after I submit it adds a row
to my Excel tracker.

## Hard rules

1. **Never submit.** The tool never clicks a submit/apply/send button. I click it myself.
2. **No AI calls at runtime.** Everything is plain code. Network calls only to job-board
   APIs and the Google Sheets API for the tracker. Unknown questions go to me.
3. **Never guess** work authorization, sponsorship, salary, start date, relocation,
   or demographic (EEO) answers. They come from `profile.yaml` or from me.
4. **Never lose tracker data.** Back up the tracker before every write.

## Usage

```
python apply.py [<job-url>] [--source LinkedIn|Tsenta|Other]   # any case; near-misses fixed; other names kept as typed
python apply.py [<job-url>] --check      # print the job facts card and exit
python find.py <text>                  # search the tracker, change Outcome / Stage (milestones 7, 8)
python report.py [--sheet] [--out PATH] [--no-open] [--today YYYY-MM-DD]   # read-only report page (milestone 9)
```

No link on the command line: it asks `Job link: ` and I paste it (no quotes needed for `&` in
PowerShell). Blank asks again; surrounding spaces and quotes are removed; anything not starting
with `http://` or `https://` gets `Paste the full link (starting with https://).` and asks again.
Ctrl+C or end of input there prints `Stopped.`. This is the only question before the card.

## Flow

0. **Job facts card first.** Right after I give the link: detect the system (step 1), read the
   job details and description (step 3, without asking me anything yet), print the job facts
   card (see below), run the duplicate check (step 2) and print its result under the card.
   Then straight on, with no question in between: missing details, the form, and the one
   question at the end (step 6). There is only one "did I apply" question: the last one.

1. **Detect the system** from the URL:
   - Greenhouse: `job-boards.greenhouse.io`, `boards.greenhouse.io`, or a `gh_jid=` parameter
   - Ashby: `jobs.ashbyhq.com`
   - Lever: `jobs.lever.co`
   - Rippling: `ats.rippling.com`
   - Workday: `*.myworkdayjobs.com`
   - iCIMS: `*.icims.com`
   - Oracle Cloud: `*.oraclecloud.com` with `/CandidateExperience/` in the path
   - SmartRecruiters: `jobs.smartrecruiters.com` or `careers.smartrecruiters.com`, path `/{company}/{id}[-slug]`
   - UKG: `recruiting*.ultipro.com` or `*.ukg.net`, path `/{tenant}/JobBoard/{board}/OpportunityDetail?opportunityId=`
   - ADP: `workforcenow.adp.com` with `cid` and `jobId` parameters
   - Amazon: `amazon.jobs`, path `/{lang}/jobs/{id}`
   - Workable: `apply.workable.com`, path `/{account}/j/{shortcode}`
   - SAP SuccessFactors: `*.sapsf.com`, `*.sapsf.eu`, `*.successfactors.com`, `*.successfactors.eu`
     with a `career_job_req_id` parameter
   - anything else: `other`
2. **Duplicate check.** Compare the URL (with tracking parameters such as `utm_*`,
   `source`, `gh_src` and iCIMS display params like `mobile`, `width`, `in_iframe` removed) and company + position against the tracker. This
   runs with the card: matching rows (or "no matching link or job found") print under it.
   If I type the company or position later (the job didn't give them) and that pair matches
   another row, show it too. Never a question: my answer at the end (step 6) is the decision.
3. **Read job details:** company, position, posted date.
   - Greenhouse, Ashby, Lever: their public job board APIs (confirm the exact date field
     for each when building).
   - Rippling: no JSON-LD; the job page's Next.js `__NEXT_DATA__` script has
     `props.pageProps.apiData.jobPost` → `name`, `companyName`, `createdOn` (`/apply` links map
     to the job page). Its `og:site_name` is "Rippling Recruiting", not the employer.
   - iCIMS: the page is a branded wrapper; the job is in an iframe at the same path with
     `?in_iframe=1`, which has `JobPosting` JSON-LD.
   - Oracle Cloud: `GET {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id="{id}",siteNumber={site}`
     → `items[0].Title`, `items[0].ExternalPostedStartDate`. No company in that API; use
     `SeoOrganizationName` from `recruitingCESites?onlyData=true&q=SiteNumber={site}` when set,
     else ask me.
   - Milestone 1e boards (each field confirmed on a live job when its reader is built):
     - SmartRecruiters: `api.smartrecruiters.com/v1/companies/{company}/postings/{id}` →
       `name`, `company.name`, `releasedDate`, `jobAd.sections` (the description, in page order).
     - UKG: the job page itself has `CandidateOpportunityDetail({...})` JSON → `Title`,
       `PostedDate`, `Description`. No company: `companies.yaml` per host + tenant, else ask me.
     - ADP: `workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions/{jobId}?cid={cid}`.
       Company per `cid` in `companies.yaml`, else ask me.
     - Amazon: `amazon.jobs/en/search.json?job_id_icims[]={id}` → `title`, `posted_date`,
       `company_name` (Amazon's unit code like ` - D48` removed), description and qualifications.
     - Workable: `apply.workable.com/api/v2/accounts/{account}/jobs/{shortcode}` (title,
       published day, description, requirements, benefits) and `api/v1/accounts/{account}` (name).
     - SAP SuccessFactors: the job page itself (plain download, confirmed 2026-10-19): the title in
       `<h1>` ("Career Opportunities: {title} ({id})"), the posted time in the hidden input
       `postedOnFastDate` (milliseconds), the description in `div.joqReqDescription`. No company:
       `companies.yaml` per host + `company` parameter, else ask me.
   - Other sites: the page's `JobPosting` JSON-LD (`title`, `hiringOrganization`,
     `datePosted`) if present.
   - Still missing: load the page in Chrome (headless, `browser-profile/` so my logins apply),
     wait up to 10 s for JavaScript, and read `JobPosting` JSON-LD from the page and every
     iframe. Read only: no clicks.
   - Still missing: ask me in the terminal. Company and position guesses from `og:site_name`,
     `og:title`, `<h1>` and `<title>` are offered as defaults (Enter accepts). A JSON-LD company
     that needs tidying ("JPMC Candidate Experience page", Workday's "2100 NVIDIA USA") is also
     only a guess. The posted date is never guessed. At the posted-date question I can type
     `today`, `YYYY-MM-DD`, blank (unknown), or any other text (e.g. `Sameday - Tsenta`), which
     goes to column D exactly as typed. A `YYYY-MM-DD` that isn't a real date asks again.
   - Company still missing (e.g. HPE's Workday leaves it blank everywhere): use the name I gave
     this careers site before, from `companies.yaml`. Otherwise ask me, suggesting the name in
     the link (`hpe.wd5.myworkdayjobs.com` -> `HPE`), and save my answer for the site. Only
     single-company sites are saved (Workday/iCIMS/Oracle host, Greenhouse/Ashby/Lever/Rippling board),
     never job boards like LinkedIn.
4. **Open the form** in a visible browser (Playwright, Chrome channel, persistent profile
   folder `browser-profile/` so logins stay saved).
5. **Fill fields:**
   - Standard fields (name, email, phone, location, LinkedIn, GitHub, website,
     education, current company) from `profile.yaml`.
   - Resume upload from the path in `profile.yaml`.
   - Free-text (text box) questions about my visa, immigration or work authorization
     **status or type** ("What is your current visa status?") get
     `work_authorization.visa_details` from `profile.yaml`. Missing = ask me. Dropdowns
     keep their Yes/No rules; other sponsorship text questions still come to me.
   - Custom questions: match the question label (lowercased, punctuation stripped)
     against `answers.yaml`.
   - Unknown **required** field: highlight it in the page, print the label in the
     terminal, and ask me for the answer. Offer to save it to `answers.yaml`.
   - Unknown optional field: leave blank and list it at the end.
6. **Pause.** Print a summary (filled, skipped, needs attention) and:
   `Review the form and click Submit yourself. Then press Enter = applied, s = skipped, e = edit details.`
   - `e` (optional) asks Company, Position, Posted date and Source again, each showing its
     current value: Enter keeps it, typing replaces it (`today`, `YYYY-MM-DD`, or `-` = unknown
     for the date; the source is read like `--source`). Any other text at the date question
     (e.g. `Sameday-Tsenta`) is written to column D exactly as typed, and Source isn't asked;
     a later `e` shows that text and Enter keeps it. A `YYYY-MM-DD` that isn't a real date
     asks again. The URL can't be edited. The row summary
     is printed again; if company or position changed, matching tracker rows are shown (no
     question). Then the same question again; `e` can be used more than once. The edits are for
     this row only (`companies.yaml` is not changed).
7. **Write the tracker row** only if I pressed Enter.

## Job facts card (milestone 1d)

When I give a link, apply.py first prints the parts of the job description I use to decide
whether to apply. It shows them **exactly as written in the description**: no rewording,
no summarizing, no shortening, no verdicts, no symbols, no scores. I decide. Rules only, no AI.

### Input

- Job description text (field names confirmed 2026-10-19): Greenhouse `content` (escaped
  HTML, unescape and strip tags), Ashby `descriptionPlain`, Lever `descriptionPlain` + `lists`
  (heading + HTML items) + `additionalPlain` (where Lever boards often put the visa/citizen
  lines), Oracle `OrganizationDescriptionStr`, `ExternalDescriptionStr`,
  `ExternalResponsibilitiesStr`, `ExternalQualificationsStr`, `CorporateDescriptionStr`.
  Other sites (iCIMS, Workday, any page): JobPosting JSON-LD `description`. Still no
  description: the text of the page and its frames as Chrome renders it (Rippling too).
- Title and posted date: already read by `ats/` (`first_published`, `publishedAt`, `createdAt`).
- Keyword lists: `matching.yaml` `keywords:`.

### When it is shown

**First thing after I give the link.** Order in apply.py:
1. Detect system, read job details and description.
2. **Print the card** immediately, before any question to me (company name, posted date)
   and before opening the browser.
3. **Duplicate check** (read only, Google Sheet or the Excel file as in Flow step 2): the
   link, and company + position when the job gave both. Rows still waiting in that tracker's
   pending file count too (pending files are written only when I press Enter = applied).
   Matching rows print under the card; otherwise `Tracker: no matching link or job found.`
4. No question here. Then: missing-detail questions, form filling, and the single question
   at the end (Enter = applied, s = skipped, e = edit details). `s` writes nothing.

`--check` prints the card and the duplicate check and exits, for looking at a link without
applying. A missing tracker file is only a note there.

### Output

```
Acme · Software Engineer I · Greenhouse

Sponsorship:
  Acme is unable to sponsor employment visas now or in the future for this role.

Citizenship:
  This position requires U.S. citizenship due to government contract requirements.

Seniority:
  Title: Software Engineer I
  2+ years of professional software development experience
  Bachelor's degree in Computer Science or equivalent

Posted:
  October 19, 2026, 8:12 AM (6 hours ago)

Already in the tracker:
  row 412: Acme | Software Engineer I | Posted October 2, 2026-LinkedIn | 10/03/2026 | Rejected
           https://job-boards.greenhouse.io/acme/jobs/1234567
```

Rules for the text:
- **Verbatim.** Print each matched sentence or bullet exactly as it appears in the
  description, after only these mechanical steps: HTML tags removed, HTML entities
  decoded (`&amp;` to `&`), and runs of spaces/newlines inside the sentence collapsed
  to one space. No other change: same words, punctuation, capitalization, order.
- **Complete.** Never cut a sentence. Show every matching sentence, in the order they
  appear in the description, with no limit.
- **No duplicates within a section;** a sentence matching two sections appears in both.
- One sentence per line, indented under the section name.
- Nothing found: `not mentioned`. Description unreadable: `Description: not available`,
  and the card still shows the title and posted date.
- **Company in the header:** from the job, else the name I gave this careers site in
  `companies.yaml`, else the page-tag guess marked `(from page)`, else `Company unknown`.
  The title: from the job, else the page-tag guess marked `(from page)`, else `unknown`.
  A guess is only shown; it reaches the tracker only if I accept it at the later question.
  The duplicate check under the card uses the same company and title. A careers site's default name ("Candidate
  Experience site", "Careers") is not offered as a company guess either.
- **Posted:** a readable date in my local time zone, then the age in parentheses:
  `October 8, 2026, 9:00 AM (11 days ago)`. Under a day: "N hours ago" ("less than an hour
  ago" under an hour). A date without a time: `October 8, 2026 (11 days ago)`, or `(today)`.
  A value that can't be read as a date is shown as the board gave it. No date: `unknown`.
  (The verbatim rule is for description sentences, not the date.)

### Which sentences each section shows

Split the description into sentences, and also treat each bullet point and line as its
own unit, so a bullet is shown whole. Matching is whole words, exactly as listed
(`sponsor` does not match `sponsorship`, so `matching.yaml` lists every form). It is
case-insensitive, except that all-caps keywords (OPT, CPT, ITAR, H1B, BS, MS) match only
in capitals, so "opt out" is not a sponsorship sentence.

1. **Sponsorship:** sentences containing any of `keywords.sponsorship`
   (sponsor/sponsors/sponsorship/sponsoring, visa, H-1B, H1B, work authorization,
   authorized to work, employment authorization, OPT, CPT, immigration).
2. **Citizenship:** sentences containing any of `keywords.citizenship`
   (citizen/citizens/citizenship, green card, permanent resident, clearance, TS/SCI,
   public trust, ITAR, export control, U.S. person, US person).
   Leave out sentences containing any of `keywords.citizenship_ignore`
   (regardless of, without regard to, equal opportunity, protected veteran), which are
   equal-opportunity boilerplate.
3. **Seniority:**
   - The job title as the board gives it.
   - Sentences with years of experience: "N+ years", "N-M years", "N to M years",
     "at least N years", "minimum (of) N years", "N or more years", "N years".
   - Sentences with a degree requirement: Bachelor, BS, B.S., Master, MS, M.S., PhD,
     degree.
4. **Posted:** see above.

### Out of scope for 1d

Match score, verdicts, job type, location, already-applied cooldown, H-1B and E-Verify
lookups, saving the full JD text.

### Done when

- Tests with at least 10 saved JD fixtures (`tests/fixtures/jd/`) that assert the exact
  printed text, including: several sponsorship wordings, an OPT/STEM OPT mention,
  EEO boilerplate that must not appear under Citizenship, a clearance requirement,
  years and degree sentences, a bullet-list JD (each bullet shown whole), a very long
  sentence (shown in full), HTML entities, a JD with no mentions (`not mentioned`),
  and posted dates (hours ago, days ago, Lever timestamp, unknown).
- A test that each printed sentence appears word for word in the cleaned description.
- Card shown for a real Greenhouse, Ashby and Lever job, before any prompt.
- `ruff check .` and `pytest` pass.

## Tracker format (`Job Application Tracker.xlsx`)

- Sheet `Sheet1`, Excel table `Table1` (currently `A1:K1000`), header on row 1.
- Append at the first row after the last row that has a Company value.

| Col | Header | Write |
|---|---|---|
| A | Company | company name |
| B | Position | job title |
| C | URL | the URL as text **and** as a hyperlink (some old rows hold an `=HYPERLINK("url","text")` formula) |
| D | Posted date/ Source | e.g. `Posted today-Tsenta`, `Posted October 8, 2026-LinkedIn` (match existing style) |
| E | Date | today as a real date, number format `M/d/yyyy` |
| F | Outcome | `Applied` (dropdown: Applied, Rejected, Awaiting reply, In progress) |
| G | Stage | apply.py leaves it empty (blank = no news yet); find.py sets it (dropdown: Online Assessment, Initial Screening, Interview) |
| H | Last Updated | date of the last real status change (see "Milestone 8"), `M/d/yyyy`, same date check as E; apply.py writes today (same as Date); old rows blank |
| I | Remarks | apply.py leaves it empty; find.py appends dated notes (milestone 7) |
| J, K | Experience, Key Skills | leave empty |

- **Columns are found by header name, never by letter** (milestone 8). Row 1 is read and each
  header mapped to its column, ignoring case and spaces, for both Excel and the Sheet.
  Required headers: Company, Position, URL, Posted date/ Source, Date, Outcome, Stage,
  Last Updated, Remarks. Experience and Key Skills are optional. A missing required header in
  the Excel file stops apply.py and find.py at the start, with a message naming it, before
  any write.
- Every Excel write makes sure the Outcome column's list validation offers the four Outcome
  values and the Stage column's the three Stage values (missing ones are added; nothing
  is removed).

- When the table reaches its last row, extend `Table1` and the data validation ranges
  on the Date, Last Updated, Outcome and Stage columns so new rows keep the date checks and
  the Outcome and Stage dropdowns.
- Before each write, copy the tracker to `backups/tracker-YYYYMMDD-HHMMSS.xlsx`.
- If the file is open in Excel (PermissionError on Windows), keep the row in
  `pending_rows.json`, tell me to close Excel, and retry. Nothing is lost.

## Google Sheet tracker

The main tracker is a native Google Sheet with the same columns A..K as the Excel file.
Every row is written to both: the Sheet first, then the local Excel file.

- Config in `config.yaml` (gitignored): `sheet_id`, `sheet_tab`, `google_key`, `local_tracker`.
  No `config.yaml` or no `sheet_id` = Excel only. `--no-sheet` also means Excel only.
- Access through a Google Cloud **service account** (`google-key.json`, gitignored). The Sheet
  is shared with the service account email as Editor.
- Before reading or writing, map row 1's headers to columns (same rules as the Excel file). A
  missing required header is named, and the Sheet is then treated like "can't be reached":
  the run carries on with the Excel file, and rows and updates wait in the pending files.
  Every run that finds the header wrong prints a clear warning naming the missing header.
- Text fields (Company, Position, Posted date/ Source, Outcome, Stage, Remarks) are written
  with `RAW`, so they are stored exactly as given (`SDE 1-2`, `10/20`, `=...` stay text).
  Only Date, Last Updated and the `=HYPERLINK` URL are written `USER_ENTERED`.
- Duplicate check reads the Sheet (display text, plus `=HYPERLINK()` targets in the URL column).
  If the Sheet can't be reached, fall back to the Excel file.
- Write at the first row after the last Company value, each field into its own column by
  header: URL = `=HYPERLINK(url, url)`, Date and Last Updated = the date, entered as if typed
  and shown as `M/d/yyyy`, Outcome = `Applied`. Other columns are not touched. Copy format and data
  validation from the row above so the Outcome and Stage dropdowns carry on.
- Before each write, save the Sheet's values to `backups/sheet-YYYYMMDD-HHMMSS.csv`.
- If the Sheet can't be reached, keep the row in `pending_sheet.json` and write it next run.

## Files

| File | Purpose |
|---|---|
| `apply.py` | entry point |
| `find.py` | search the tracker and change Outcome / Stage / Remarks (milestone 7) |
| `ats/` | one module per system: `greenhouse.py`, `ashby.py`, `lever.py`, `workday.py`, `rippling.py`, `icims.py`, `oracle.py`, `generic.py`, `browser.py` (page reading in Chrome) |
| `job_facts.py` | the job facts card (sentence splitting, keyword matching, posted age) |
| `tracker.py` | duplicate check, search, row writing and Outcome / Stage updates (Excel) |
| `sheet_tracker.py` | the same for the Google Sheet |
| `pending_rows.json`, `pending_sheet.json` | new rows waiting for Excel / the Sheet |
| `pending_updates.json`, `pending_sheet_updates.json` | Outcome / Stage updates waiting for Excel / the Sheet |
| `config.yaml` | Sheet ID, tab, key path, local tracker path |
| `profile.yaml` | my details (filled from resume; sensitive answers set by me) |
| `answers.yaml` | saved answers to custom questions, grows over time |
| `companies.yaml` | company name per careers site, saved the first time I type it |
| `matching.yaml` | keyword lists for the job facts card (and my skills list, not used yet) |
| `report.py` | the read-only report page (milestone 9) |
| `reporting/` | the report's parts: `load.py`, `derive.py`, `metrics.py`, `render.py`, `templates/`, `static/` |
| `report.yaml` | report settings (in git, no personal data) |
| `report.html` | the generated page (gitignored, never published) |
| `tracker_copy.xlsx` | copy of the tracker for manual experiments. Tests build their own fake tracker (`tests/fake_tracker.py`). |
| `tests/` | pytest tests |

## Milestones (build in this order, one per Claude session)

1. **Tracker only:** link in, details read, tracker row written. No form filling.
   Done when: tests pass on `tracker_copy.xlsx`; a new row appears at row 898 with the
   right formats; the file still opens in Excel; duplicate check catches a URL already
   in the tracker.
1b. **Google Sheet tracker:** rows go to the Google Sheet and the Excel file (see above).
2. **Greenhouse filler.** Done when: a real Greenhouse form is filled and paused,
   with nothing submitted. (Done 2026-10-14 on a Figma posting.) Confirmed details:
   - Questions: `GET boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}?questions=true`
     returns `questions`, `location_questions`, `compliance` (EEO) and `education`.
   - The form is `#application-form` at `job-boards.greenhouse.io/{board}/jobs/{id}`.
     Company sites with `?gh_jid=` embed `job-boards.greenhouse.io/embed/job_app?for={board}&token={id}`.
   - Element ids equal the API field names (`first_name`, `resume`, `question_<n>`,
     `gender`, `veteran_status`). Exceptions: location (`candidate-location`), the phone
     country (`country`) and education (`school--0`, `degree--0`).
   - Dropdowns are react-select (`input[role=combobox]` in `.select-shell`, options
     `.select__option`). Location and school are autocompletes.
   - The filler only clicks through a guard that refuses submit buttons, and never presses Enter.
1c. **Job details from any link** (done 2026-10-15; details for the tracker only, no form filling):
   iCIMS (iframe page), Oracle Cloud (recruiting API), Rippling (`__NEXT_DATA__`), the Chrome
   fallback for JavaScript pages, company/position guesses offered as defaults, and
   `companies.yaml` (company name remembered per careers site). See Flow step 3.
1d. **Job facts card:** the decision card printed right after I give a link, before any
   prompt or browser. See "Job facts card" above. (Done 2026-10-19: 12 saved JDs in
   `tests/fixtures/jd/`, checked on real Greenhouse, Ashby and Lever jobs.)
1e. **More job boards** (job details and the card only, no form filling): SmartRecruiters,
   UKG, ADP, Amazon, Workable, SAP SuccessFactors (see Flow steps 1 and 3), and page-tag guesses shown on the
   card, marked. Chosen from the links in my tracker that the earlier readers missed.
3. **Ashby**, then **Lever**, using the same pattern. (Next.)
4. **Workday** (account login per company: pause and let me log in).
5. **Other sites:** the generic module fills only fields it can match with confidence;
   for the rest I use Claude in Chrome by hand.
6. **Email:** parked.
7. **Search and update status** (`find.py`). See "Milestone 7" below.
8. **Tracker layout and status model:** columns by header name, Last Updated, In progress,
   two questions in find.py. See "Milestone 8" below. (Done 2026-10-28; real run checked by me.)
9. **Report page** (`report.py`): a read-only page of the tracker. See "Milestone 9" below.

## Milestone 7: Search by company and update status

A quick way to find every job I applied to at a company and change their Outcome or Stage together,
so I don't have to scroll the tracker. No email access, no AI, no network calls except the
Google Sheet the tracker already uses.

### Usage

```
python find.py <text> [--tracker PATH] [--no-sheet]
```
Example: `python find.py acme`. `<text>` can be several words (`python find.py "s&p global"`;
PowerShell needs the quotes around `&`). `--tracker` and `--no-sheet` work as in apply.py.
Ctrl+C or end of input at any question stops the run (`Stopped.`); anything not yet written
stays in its pending file.

### What it searches

Every tracker row with a Company or URL value where `<text>` appears in:
- **Company** (column A),
- **Position** (column B),
- **URL** (column C): the link text or the hyperlink target, e.g. `acme.wd5.myworkdayjobs.com`.

Matching: case-insensitive substring. For Company and Position, both sides are cleaned the
same way: punctuation becomes a space, spaces collapse, and trailing company suffixes are
dropped (inc, llc, ltd, corp, corporation, co, plc, gmbh, lp, llp, ag, sa), so `Acme Inc` =
`Acme` and `s&p global` finds `S&P Global`. For the URL, the text as typed (lowercased), or
the cleaned text without spaces, must appear in the link.

Data source: the Google Sheet if configured and reachable, otherwise the Excel tracker. Rows
still waiting in a pending rows file are not shown; a note under the table says how many wait.

### What it shows

A table in the terminal (`rich`), grouped by company. Groups are ordered by their newest
date, rows inside a group newest first; a date that can't be read goes last.

```
3 jobs found for "acme"

 #  Row  Date        Company  Position             Outcome         Stage              Remarks             Link
 1  912  10/18/2026  Acme     Software Engineer I  Applied                                                acme.wd5.myworkdayjobs.com
 2  877  10/02/2026  Acme     Cloud Engineer       Awaiting reply  Online Assessment                      job-boards.greenhouse.io
 3  640  08/21/2026  Acme     DevOps Engineer      Rejected                           Same day rejection  job-boards.greenhouse.io
```

- Link shows the domain; the full URL is clickable where the terminal supports links
  (OSC 8 hyperlinks via `rich`).
- Outcome colored: Applied and Awaiting reply (plain), Rejected (dim). Stage colored: Online
  Assessment (yellow), Initial Screening (cyan), Interview (blue). Long text wraps.
- More than 50 matches: show the first 50 and say how many more (narrow the search).
- No matches: `No jobs found for "acme".`

### Changing status

(Milestone 8 replaced the single status menu with two questions, Outcome then Stage, and
the rule that a Stage sets Awaiting reply. See "Milestone 8". The rest of this section still holds.)

After the table:
```
Rows to update (e.g. 1,2 or 1-3 or all; Enter = done):
New status: 1 Applied  2 Rejected  3 Awaiting reply  4 Online Assessment  5 Initial Screening  6 Interview
Note for Remarks (optional):
Update 2 rows to Rejected? [y/N]
```
- Invalid input asks again. The status can be its number or its name (any case).
  Anything but `y` at the confirm writes nothing.
- One menu for both columns. An Outcome pick (1-3) writes **Outcome** and leaves **Stage** as
  it is (Rejected after an interview keeps `Interview`). A Stage pick (4-6) writes **Stage** and
  sets **Outcome** to `Awaiting reply`. The confirm names what I picked (`Update 2 rows to Interview?`).
- If a note is given, appends `MM/DD/YYYY <note>` to **Remarks**
  (separated by ` | `, never overwriting existing text). The note is added to whatever
  Remarks holds when the write happens.
- **Finding the row again.** Sheet and Excel row numbers can differ, and either may have
  changed since the search. Each picked row is carried as company, position, URL and date
  plus the row number it was found at. In each store, before writing: the hinted row is used
  if it still has that URL (or company + position when there's no URL); otherwise the one row
  with that URL, or with that company + position + date. None or several: that row is not
  written and is reported by name.
- Same write path as apply.py: backup first, Google Sheet then Excel. If the Sheet can't be
  reached the update waits in `pending_sheet_updates.json`. If Excel has the file open:
  `Close Excel, then press Enter to retry, s = leave it pending`; `s` keeps it in
  `pending_updates.json`. Pending updates are written on the next find.py update or apply.py
  write, after pending rows (so an update to a row that was itself pending finds it).
- Prints the rows again after the update (read again from the source), then asks again;
  Enter at `Rows to update` quits.
- Missing values are added to the dropdowns: Excel data validation on columns F and G (list
  formula), and the Sheet's validation if it is a list rule (`ONE_OF_LIST`); any other Sheet
  rule is left alone with a note. Values that are no longer choices are never added back.
- An update saved in a pending file before Stage existed (no stage in it, Outcome
  `Online Assessment` or `Interview`) is read as that Stage + `Awaiting reply`.

### Done when

- Tests on the fake tracker: match by company, position and URL; case and punctuation;
  suffixes (Acme Inc = Acme); no match; selection parsing (`1,3`, `2-4`, `all`, invalid);
  Outcome update; Stage update sets Awaiting reply; Outcome update keeps Stage; Remarks
  appended, not overwritten; dropdown values;
  pending file when Excel is locked; Sheet update via the fake worksheet.
- `ruff check .` and `pytest` pass.
- One real run (by me): search a company, update a row, see it in the Sheet and Excel.

## Milestone 8: Tracker layout and status model

The tracker layout changed by hand (Excel and Sheet in sync): **Last Updated** was inserted at H,
so Remarks, Experience and Key Skills moved to I, J and K (see "Tracker format"). The app finds
every column by its header name (see there), so a moved column can't receive the wrong data.

### Status model

Outcome = whose turn it is. Stage = furthest step reached.

| Stage | Outcome | Meaning |
|---|---|---|
| blank | Applied | applied, no news yet |
| a stage | **In progress** | that stage is on me (assessment to do, interview coming) |
| a stage | Awaiting reply | I've done that stage, waiting on them |
| any | Rejected | done; Stage kept to show how far it got |

- Outcomes: Applied, Rejected, Awaiting reply, In progress. `In progress` is added to the
  Outcome dropdowns if missing (Excel and Sheet).
- No rule "a Stage sets Outcome to Awaiting reply" any more.
- Pending files saved by the old version (a stage with no Stage field, or an explicit
  Awaiting reply + stage) are still read the old way, so nothing pending is lost.

### find.py: two questions

After picking rows:
```
Outcome: 1 Applied  2 In progress  3 Awaiting reply  4 Rejected  (Enter = keep)
Stage:   1 Online Assessment  2 Initial Screening  3 Interview  (Enter = keep)
Note for Remarks (optional):
Update 2 rows: In progress · Online Assessment? [y/N]
```
- Number or name, any case; invalid input asks again.
- **Rejected:** the Stage question is not asked; Stage stays as it is.
- **In progress:** a Stage is required if the row has none (the Stage question has no
  `Enter = keep` then, and Enter asks again). With several rows picked, required if any of
  them has no Stage.
- **Applied / Awaiting reply:** Stage question asked; Enter keeps each row's own Stage.
- Enter at both questions and no note = nothing to change, back to the row prompt.
- The confirm line names exactly what will be written: the Outcome, the Stage and
  `note "..."`, joined by ` · `, leaving out what is kept.
- Table: **Last Updated** after Stage. Outcome styles: In progress bold, Rejected dim.
- Everything else from milestone 7 stays (finding rows again, pending files, re-print).

### Last Updated

- `find.py` writes today's date to **Last Updated** on a row only when, on that row:
  - Stage changes to a different value, or
  - Outcome changes to Awaiting reply or Rejected (from something else).

  A note alone, Outcome changing to Applied or In progress, or picking the value the row
  already has does not change Last Updated. (Excel as a real date with `M/d/yyyy`; Sheet as a
  date value.) It is checked against the row as it is when the write happens.
- `apply.py` writes today's date to Last Updated on the new row (same as Date).
- Never written for rows I didn't change. Old rows stay blank.

### Done when

- Tests: header map (order, case, spaces, missing required header stops before writing);
  append and update write to the right columns in the new layout and in a shuffled layout;
  Remarks note goes to I and keeps existing text; Last Updated set on append, and on update
  only for a Stage change or a change to Awaiting reply / Rejected (each case tested);
  Sheet text written RAW and unchanged (`SDE 1-2`, `10/20`, `=`, `+`);
  `In progress` added to dropdowns; Rejected skips the Stage question; In progress requires
  a Stage; Enter keeps; old pending files still apply; Sheet path via the fake worksheet.
- `pytest` and `ruff check .` pass.
- One real run (by me) on my tracker: `find.py` on one company, set In progress + Online
  Assessment with a note, then check Excel and the Sheet: F, G, H (today) and I (note) are right.
- README and SPEC.md tracker format updated to the new layout and model.

## Milestone 9: Report page (`report.py`)

### Purpose

I can read the tracker in Excel, but it's tiring. The report shows the same information in a
calm, predictable page: the most important things first, few numbers, plain sentences,
details only when I open them. It only reads the tracker; it never writes (no backups, no
pending files written or flushed).

### Usage

```
python report.py [--sheet] [--out PATH] [--no-open] [--today YYYY-MM-DD] [--tracker PATH]
```
- Reads the local Excel tracker from `config.yaml` (`local_tracker`) by default, read-only.
  `--tracker` works as in apply.py. `--sheet` reads the Google Sheet instead. (The Sheet in
  config is currently the test copy.)
- Writes one self-contained `report.html` (default: in the project folder) and opens it in
  the default browser unless `--no-open`.
- `--today` is for tests and checking past weeks.
- The tracker can't be read (missing, open and locked, a required header missing): a message
  naming the problem, exit code 2, no page written.
- `report.html` is in `.gitignore`. Never published or uploaded anywhere.

### Settings: `report.yaml` (in git, no personal data)

```yaml
weekly_target: 70          # applications per week
follow_up_days: 14         # Awaiting reply older than this (by Last Updated) = follow up
no_reply_days: 30          # Applied, no Stage, older than this = no reply
many_applications: 5       # this many applications to one company = flagged
min_group: 20              # groups smaller than this show counts only, no rate
weeks_shown: 12
sources: [Jobright, Tsenta, LinkedIn]        # matched in column D, case-insensitive
early_career_words: [new grad, graduate, grad, early career, entry, junior, jr, residency,
                     associate, university, " I", " 1", intern]
title_types:
  Backend: [backend, back-end, back end, api]
  DevOps/Cloud/SRE/Platform: [devops, sre, reliability, platform, infrastructure, cloud]
  AI/ML/Data: [ai, machine learning, ml, data]
  Software (general): [software, developer, sde, swe, engineer]
remark_tags:
  No sponsorship: [sponsor, visa]
  Clearance/citizenship: [clearance, citizen]
  Referral: [referral, referred]
```
The code holds the same values as defaults: no `report.yaml` uses them all, a key left out
uses its default. Tests use the defaults or their own file, never mine.
Title type = first type whose word appears (whole word, case-insensitive), else "Other".
Early career = any of its words in the title (whole word; " I" and " 1" only as the last
word, e.g. "Software Engineer I").

### Derived fields (computed in memory, never written back)

| Field | Rule |
|---|---|
| Source | first of `sources` found in column D (whole word); else "Other" |
| Job system | `ats.detect_system(url)` from the app |
| Title level | Early career / Other |
| Title type | see settings |
| Responded | Stage is not blank |
| Status group | In progress / Awaiting reply / Rejected after response / Rejected / No news (Applied, no Stage). Applied with a Stage (old model) counts as Awaiting reply |
| Age | days since Date |
| Since update | days since Last Updated (blank if unknown) |
| Remark tags | `remark_tags` words found in Remarks, at the start of a word (`sponsor` finds `sponsorship`, `citizen` finds `Citizens`) |
| Company key | the same normalization as `find.py` search (Acme Inc = Acme) |

URL from the hyperlink target, or from an `=HYPERLINK("url", ...)` formula, or the cell text.
Weeks run Monday to Sunday; "last week" is the previous full week.

### Page layout (always in this order, same every time)

Top of the page fits on one screen without scrolling: sections 1-4 (on a desktop window).

**1. Summary: three plain sentences** (the opening of the page, larger text, no visible heading)
Templates, filled from the data; a sentence is left out if it has nothing to say:
- `This week: {n} applications (target {target}, last week {n_last}). {responses_text}.`
  where responses_text = `No new responses` / `{k} new response(s): {Company} ({Stage}), ...`
  (new = Last Updated in this week and Stage set; if Last Updated is blank, not counted).
- `{p} in progress and {a} awaiting reply.` (left out if both 0)
- `Best source so far: {source}, {r} responses from {n} applications.` Only if that
  source has n ≥ min_group and at least 2 responses; otherwise left out.

**2. This week** (card)
A large progress bar `19 of 70`: applications this week (Monday to today) toward
`weekly_target` (full bar at or over the target; the text shows the real number), the change
from last full week as a small badge (`↑ 13 from last week`, up / down / same). Below it, small:
responses this week, rows in progress.

**3. Totals** (one row of 4 stat tiles, 2 x 2 on narrow windows)
Large numbers with short labels: Applied (all rows), Responses (Stage set), Awaiting reply,
Rejected (Outcome Rejected).

**4. Needs your attention** (card)
Each line is a chip colored by type: Your turn = blue, Follow up = amber, Many applications =
grey. Every Your turn and Follow up line is shown; at most 3 Many applications lines, the rest
under `+N more` (expandable). In this order:
1. **Your turn:** every In progress row: `{Company}: {Stage} to do` (+ `since {n} days` if
   Last Updated known), oldest first.
2. **Follow up:** Awaiting reply rows with Last Updated older than `follow_up_days`:
   `{Company}: {Stage}, no reply for {n} days`. Awaiting reply rows with no Last Updated:
   `{Company}: {Stage}, waiting (date unknown)`.
3. **Many applications:** companies with ≥ `many_applications` applications and no response:
   `{Company}: {n} applications, no response`.
Nothing to show: `Nothing needs your attention.`

**5. Weekly** (last `weeks_shown` weeks, ending with the current week)
Bar chart: applications per week (by Date), a dot on each bar for applications from that
week that got a response, a dashed line at `weekly_target`. Week labels `Oct 20`. Exact
numbers on hover (SVG `<title>`) and in a small table under a "Show numbers" toggle.
Bars at or above the target are drawn brighter.

**6. Monthly** (chart, the last 12 months with applications, oldest left)
Small paired bars per month: applications (neutral) and responses (green), labels `Oct`
(`Jan 2026` style when the year changes). Exact numbers on hover (SVG `<title>`) and, under
"Show numbers", the table of every month, newest first: Month · Applications · Responses ·
Rejected · Response rate. Response rate as `5 of 128 (3.9%)`; when applications < `min_group`,
counts only.

**7. Pipeline** (a strip of 4 steps with counts)
Applied → Responses → Initial Screening → Interview. Counts are "reached at least": Initial
Screening = Stage Initial Screening or Interview; Interview = Stage Interview. Online Assessment
counts only toward Responses.

**8. Your responses** (cards, every row with a Stage, newest applied first)
Heading shows the count: `Your responses (12)`. Each card: Company (bold), Position below,
a Stage pill (green) and an Outcome pill (In progress = blue, Awaiting reply = grey, or amber
when Last Updated is older than `follow_up_days`, Rejected = muted red). Source, Job system,
Applied, Last Updated and the link inside a collapsed `<details>` on the card.

**9. Top 10 companies, with outcomes**
By number of applications (ties: most recent application first). One horizontal bar each,
length = applications, segmented: green = rows with a response, muted red = rejected with no
response, the rest neutral. The numbers on hover (SVG `<title>`) and as text at the end of the
bar: `6 · 1 response · 2 rejected` (Rejected counts every Outcome Rejected row).

**10. No reply after {no_reply_days} days** (collapsed by default)
Count line always visible: `412 applications with no reply after 30 days.`
Expanded: count per month, and under each month a collapsed list (Company · Position · Applied).

**11. More details** (collapsed by default)
For Source, Job system, Title level, Title type, Remark tags: a table each with
Group · Applications · Responses · Rate · Rejection notices. Rate only when applications ≥
`min_group`, else `too few to compare`. Column note: "Rejection notices show how often
companies tell you, not how well you did."

**12. Data check** (collapsed; heading shows the count of issues)
Rows with: blank Position, blank URL, no source found in D (D naming `Other`, as apply.py
writes it, counts as a source), URL stored as a formula (Excel only: every app-written Sheet
row is a `=HYPERLINK` formula by design), Stage set but Outcome Applied (old model: should be
In progress or Awaiting reply), Outcome In progress with no Stage. Each issue: count + list
(row number, Company).

Footer: `Generated {date time} from {file name} · {n} rows`.

### Look and feel

- One HTML file, inline CSS, charts as inline SVG. **No JavaScript and no external files,
  fonts or requests.** Collapsible parts with `<details>`.
- Calm: large numbers, short labels, generous spacing.
- System font, max width about 960px, generous spacing, one column on narrow windows.
- Light and dark mode follow the system (`prefers-color-scheme`), colors as CSS variables.
- Color only carries meaning: green = response, blue = in progress, amber = follow up,
  muted red = rejected, grey = no news. Everything else neutral.
- Numbers rounded (1.3%, not 1.29%); dates `Oct 20` in charts, `10/20/2026` in tables.
- Job links in tables and cards are clickable and open in a new tab, shown as the domain only.
- All text from the tracker is HTML-escaped.

### Code structure

The package is `reporting/`, not `report/`: a `report/` folder next to `report.py` would be
imported instead of it.

| File | Job |
|---|---|
| `report.py` | entry point and options |
| `reporting/load.py` | settings; rows read-only by header name (`tracker.read_rows` / `sheet_tracker.read_rows`), handles `=HYPERLINK` |
| `reporting/derive.py` | derived fields, small pure functions |
| `reporting/metrics.py` | summary values, this week, attention list, weekly and monthly series, responses, top companies, no-reply, details, data check |
| `reporting/render.py` | fills the page template: values and chart geometry, no markup; embeds the CSS in a `<style>` block so the page stays one file |
| `reporting/templates/report.html.j2` | the page as a Jinja2 template, autoescape on (every tracker text escaped) |
| `reporting/static/report.css` | all CSS; colors, spacing, font sizes and radii as variables at the top |
| `report.yaml` | settings |

### Done when

- Tests on the fake tracker (new layout) with added rows: Jobright/Tsenta/LinkedIn sources,
  In progress and Awaiting reply rows with and without Last Updated, rejected after a
  stage, one company with 6 applications, a `=HYPERLINK` URL, a blank position. Fixed
  `--today`. Tests check exact values for: every derived field, summary sentences (including
  left-out sentences), this-week numbers and change, attention list order and the 5 cap,
  weekly and monthly series, top 10 order, no-reply counts, `too few to compare`, data check.
- Render test: the HTML has every section heading in order, escapes `<script>` from a
  tracker cell, and contains no `<script src`, `<link`, `@import` or `http` request other than
  job links in tables.
- `report.py` never opens the tracker for writing (test: file modified time unchanged).
- `pytest` and `ruff check .` pass.
- One real run on my tracker; I check the page against the spreadsheet.

### Out of scope

Email, AI, writing to the tracker, charts by job system or title type beyond the tables in
More details, publishing the page anywhere.

## Out of scope

Job searching or scraping job boards, auto-submit, AI calls, filling Experience or
Key Skills, solving CAPTCHAs, creating accounts automatically.
