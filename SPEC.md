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
python find.py <text>                  # search the tracker, change Outcome (milestone 7)
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
     only a guess. The posted date is never guessed.
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

- Sheet `Sheet1`, Excel table `Table1` (currently `A1:I1000`), header on row 1.
- Append at the first row after the last row that has a Company value (currently row 898).

| Col | Header | Write |
|---|---|---|
| A | Company | company name |
| B | Position | job title |
| C | URL | the URL as text **and** as a hyperlink |
| D | Posted date/ Source | e.g. `Posted today-Tsenta`, `Posted October 8, 2026-LinkedIn` (match existing style) |
| E | Date | today as a real date, number format `M/d/yyyy` |
| F | Outcome | `Applied` (must be one of the dropdown values: Applied, Rejected, Online Assessment, Interview) |
| G | Remarks | apply.py leaves it empty; find.py appends dated notes (milestone 7) |
| H, I | Experience, Key Skills | leave empty |

- Every Excel write makes sure the column F list validation offers all four Outcome values
  (Interview is added if missing).

- When the table reaches its last row, extend `Table1` and the data validation ranges
  on columns E and F so new rows keep the date check and the Outcome dropdown.
- Before each write, copy the tracker to `backups/tracker-YYYYMMDD-HHMMSS.xlsx`.
- If the file is open in Excel (PermissionError on Windows), keep the row in
  `pending_rows.json`, tell me to close Excel, and retry. Nothing is lost.

## Google Sheet tracker

The main tracker is a native Google Sheet with the same columns A..I as the Excel file.
Every row is written to both: the Sheet first, then the local Excel file.

- Config in `config.yaml` (gitignored): `sheet_id`, `sheet_tab`, `google_key`, `local_tracker`.
  No `config.yaml` or no `sheet_id` = Excel only. `--no-sheet` also means Excel only.
- Access through a Google Cloud **service account** (`google-key.json`, gitignored). The Sheet
  is shared with the service account email as Editor.
- Before writing, check that row 1 holds the A..I headers; if not, write nothing.
- Duplicate check reads the Sheet (display text, plus `=HYPERLINK()` targets in column C).
  If the Sheet can't be reached, fall back to the Excel file.
- Write at the first row after the last Company value. C = `=HYPERLINK(url, url)`,
  E = the date as `M/d/yyyy`, entered as if typed, F = `Applied`. Copy format and data
  validation from the row above so the Outcome dropdown carries on.
- Before each write, save the Sheet's values to `backups/sheet-YYYYMMDD-HHMMSS.csv`.
- If the Sheet can't be reached, keep the row in `pending_sheet.json` and write it next run.

## Files

| File | Purpose |
|---|---|
| `apply.py` | entry point |
| `find.py` | search the tracker and change Outcome / Remarks (milestone 7) |
| `ats/` | one module per system: `greenhouse.py`, `ashby.py`, `lever.py`, `workday.py`, `rippling.py`, `icims.py`, `oracle.py`, `generic.py`, `browser.py` (page reading in Chrome) |
| `job_facts.py` | the job facts card (sentence splitting, keyword matching, posted age) |
| `tracker.py` | duplicate check, search, row writing and Outcome updates (Excel) |
| `sheet_tracker.py` | the same for the Google Sheet |
| `pending_rows.json`, `pending_sheet.json` | new rows waiting for Excel / the Sheet |
| `pending_updates.json`, `pending_sheet_updates.json` | Outcome updates waiting for Excel / the Sheet |
| `config.yaml` | Sheet ID, tab, key path, local tracker path |
| `profile.yaml` | my details (filled from resume; sensitive answers set by me) |
| `answers.yaml` | saved answers to custom questions, grows over time |
| `companies.yaml` | company name per careers site, saved the first time I type it |
| `matching.yaml` | keyword lists for the job facts card (and my skills list, not used yet) |
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

## Milestone 7: Search by company and update status

A quick way to find every job I applied to at a company and change their Outcome together,
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

 #  Row  Date        Company  Position                    Outcome    Remarks             Link
 1  912  10/18/2026  Acme     Software Engineer I         Applied                         acme.wd5.myworkdayjobs.com
 2  877  10/02/2026  Acme     Cloud Engineer              Applied                         job-boards.greenhouse.io
 3  640  08/21/2026  Acme     DevOps Engineer             Rejected   Same day rejection   job-boards.greenhouse.io
```

- Link shows the domain; the full URL is clickable where the terminal supports links
  (OSC 8 hyperlinks via `rich`).
- Outcome colored: Applied (plain), Online Assessment (yellow), Interview (blue),
  Rejected (dim). Long text wraps.
- More than 50 matches: show the first 50 and say how many more (narrow the search).
- No matches: `No jobs found for "acme".`

### Changing status

After the table:
```
Rows to update (e.g. 1,2 or 1-3 or all; Enter = done):
New status: 1 Applied  2 Rejected  3 Online Assessment  4 Interview
Note for Remarks (optional):
Update 2 rows to Rejected? [y/N]
```
- Invalid input asks again. The status can be its number or its name (any case).
  Anything but `y` at the confirm writes nothing.
- Writes **Outcome**; if a note is given, appends `MM/DD/YYYY <note>` to **Remarks**
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
- **Interview** is added to the Outcome dropdown: Excel data validation on column F (list
  formula), and the Sheet's validation if it is a list rule (`ONE_OF_LIST`); any other Sheet
  rule is left alone with a note.

### Done when

- Tests on the fake tracker: match by company, position and URL; case and punctuation;
  suffixes (Acme Inc = Acme); no match; selection parsing (`1,3`, `2-4`, `all`, invalid);
  Outcome update; Remarks appended, not overwritten; Interview accepted by the dropdown;
  pending file when Excel is locked; Sheet update via the fake worksheet.
- `ruff check .` and `pytest` pass.
- One real run (by me): search a company, update a row, see it in the Sheet and Excel.

## Out of scope

Job searching or scraping job boards, auto-submit, AI calls, filling Experience or
Key Skills, solving CAPTCHAs, creating accounts automatically.
