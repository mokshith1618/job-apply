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
python apply.py <job-url> [--source LinkedIn|Tsenta|Other]
```

## Flow

1. **Detect the system** from the URL:
   - Greenhouse: `job-boards.greenhouse.io`, `boards.greenhouse.io`, or a `gh_jid=` parameter
   - Ashby: `jobs.ashbyhq.com`
   - Lever: `jobs.lever.co`
   - Rippling: `ats.rippling.com`
   - Workday: `*.myworkdayjobs.com`
   - iCIMS: `*.icims.com`
   - Oracle Cloud: `*.oraclecloud.com` with `/CandidateExperience/` in the path
   - anything else: `other`
2. **Duplicate check.** Compare the URL (with tracking parameters such as `utm_*`,
   `source`, `gh_src` and iCIMS display params like `mobile`, `width`, `in_iframe` removed) and company + position against the tracker. If it
   matches, show the old row and ask whether to continue.
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
   - Custom questions: match the question label (lowercased, punctuation stripped)
     against `answers.yaml`.
   - Unknown **required** field: highlight it in the page, print the label in the
     terminal, and ask me for the answer. Offer to save it to `answers.yaml`.
   - Unknown optional field: leave blank and list it at the end.
6. **Pause.** Print a summary (filled, skipped, needs attention) and:
   `Review the form and click Submit yourself. Then press Enter = applied, s = skipped.`
7. **Write the tracker row** only if I pressed Enter.

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
| F | Outcome | `Applied` (must be one of the dropdown values: Applied, Rejected, Online Assessment) |
| G, H, I | Remarks, Experience, Key Skills | leave empty |

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
| `ats/` | one module per system: `greenhouse.py`, `ashby.py`, `lever.py`, `workday.py`, `rippling.py`, `icims.py`, `oracle.py`, `generic.py`, `browser.py` (page reading in Chrome) |
| `tracker.py` | duplicate check and row writing (Excel) |
| `sheet_tracker.py` | the same for the Google Sheet |
| `config.yaml` | Sheet ID, tab, key path, local tracker path |
| `profile.yaml` | my details (filled from resume; sensitive answers set by me) |
| `answers.yaml` | saved answers to custom questions, grows over time |
| `companies.yaml` | company name per careers site, saved the first time I type it |
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
3. **Ashby**, then **Lever**, using the same pattern. (Next.)
4. **Workday** (account login per company: pause and let me log in).
5. **Other sites:** the generic module fills only fields it can match with confidence;
   for the rest I use Claude in Chrome by hand.

## Out of scope

Job searching or scraping job boards, auto-submit, AI calls, filling Experience or
Key Skills, solving CAPTCHAs, creating accounts automatically.
