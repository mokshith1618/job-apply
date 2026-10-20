# Job Apply Helper

A personal command-line tool for logging job applications. You paste a job link. The tool
first prints a job facts card (what the description says about sponsorship, citizenship and
seniority, word for word), then reads the company, position and posted date, checks whether
you've already applied, and waits while you submit the application yourself. Then it adds a row to your tracker, in a
Google Sheet and a local Excel file.

```
python apply.py https://job-boards.greenhouse.io/acme/jobs/1234567 --source LinkedIn
```

```
System: greenhouse
Reading job details...

Acme · Software Engineer · Greenhouse

Sponsorship:
  Acme is unable to sponsor employment visas now or in the future for this role.

Citizenship:
  not mentioned

Seniority:
  Title: Software Engineer
  2+ years of professional software development experience

Posted:
  October 13, 2026, 8:12 AM (6 hours ago)

Tracker: no matching link or job found.

Apply to this job? [Enter = yes, s = skip]

  Company:  Acme
  Position: Software Engineer
  Posted:   Posted October 13, 2026-LinkedIn
  URL:      https://job-boards.greenhouse.io/acme/jobs/1234567

Review the form and click Submit yourself. Then press Enter = applied, s = skipped.
Added row 900 to the Google Sheet.
Added row 899 to Job Application Tracker.xlsx.
```

## Ground rules

- **It never submits anything.** The tool never clicks a submit, apply or send button. You do.
- **No AI calls.** It's plain code. The only network calls go to public job-board APIs and
  the Google Sheets API.
- **No guessing on sensitive answers:** work authorization, sponsorship, salary, start date,
  relocation and EEO questions always come from you.
- **No lost tracker data.** It backs up the tracker before every write. If Excel has the file
  open or the Sheet can't be reached, the row waits in a pending file and is written on the
  next run.

## What it does

1. **Detects the job system** from the URL: Greenhouse, Ashby, Lever, Workday, iCIMS, Oracle
   Cloud, Rippling, SmartRecruiters, UKG, ADP, Amazon, Workable, or other.
2. **Checks for duplicates** by URL (ignoring tracking parameters like `utm_*` and `gh_src`)
   and by company + position, right under the job facts card, before it asks whether to
   apply. Rows still waiting in a pending file count too. If you type the company or position
   yourself later and they match a row, it shows the row and asks before continuing.
3. **Reads job details** from each board's own public data (job APIs, or the job JSON in the
   page), else from a page's `JobPosting` JSON-LD, else from the page as Chrome shows it.
   Anything it can't find, it asks you in the terminal.
4. **Fills the form** (Greenhouse only, for now) in a visible Chrome window. See
   [Form filling](#form-filling).
5. **Waits for you** to submit. Press Enter for applied or `s` for skipped.
6. **Writes the row** with Company, Position, URL (as a link), "Posted date/ Source",
   today's date and `Applied`. The Sheet gets it first, then the Excel file.

## Setup (Windows, Python 3.11+)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Tracker format

Both trackers use the same columns, with the header in row 1:

| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| Company | Position | URL | Posted date/ Source | Date | Outcome | Remarks | Experience | Key Skills |

The Excel file (`Job Application Tracker.xlsx`) keeps the data in sheet `Sheet1` as an
Excel table named `Table1`. See [SPEC.md](SPEC.md) for the full format.

### Google Sheet (optional)

Without this step the tool writes to the Excel file only.

1. In [Google Cloud Console](https://console.cloud.google.com), create a project and
   enable the **Google Sheets API**.
2. Create a **service account**, add a **JSON key**, and save it as `google-key.json` in
   this folder.
3. Share your Sheet with the service account's email (`…@….iam.gserviceaccount.com`) as
   **Editor**.
4. Create `config.yaml` in this folder:

   ```yaml
   sheet_id: '<the ID between /d/ and /edit in the Sheet URL>'
   sheet_tab: 'Sheet1'
   google_key: 'google-key.json'
   local_tracker: 'Job Application Tracker.xlsx'
   ```

Before writing, the tool checks that row 1 of the Sheet has the tracker headers, so it
won't write into the wrong sheet.

## Usage

```
python apply.py <job-url> [--source LinkedIn|Tsenta|Other] [--tracker PATH] [--no-sheet] [--no-fill]
python apply.py <job-url> --check
```

| Option | Meaning |
|---|---|
| `--source` | where you found the job; goes into column D and answers "How did you hear about us?" |
| `--tracker` | a different local Excel file |
| `--no-sheet` | skip the Google Sheet for this run |
| `--no-fill` | don't open or fill the form |
| `--check` | print the job facts card and stop (nothing asked, nothing written) |
| `--matching` | a different keyword file (default `matching.yaml`) |
| `--profile`, `--answers` | different `profile.yaml` / `answers.yaml` files |
| `--config` | a different config file (default `config.yaml`) |

## Job facts card

Printed right after you give the link, before any question or browser. It shows the
description's own sentences, never reworded or shortened: everything about sponsorship,
everything about citizenship or clearance (equal-opportunity boilerplate left out), and the
years-of-experience and degree sentences, plus how long ago the job was posted. The
keywords are in `matching.yaml`. They match whole words, so list every form you want
(`sponsor`, `sponsorship`, ...). ALL-CAPS keywords such as `OPT` match only in capitals.
A company or title read from the job is shown as is. If the job doesn't give one, the card
shows the page's own tag marked `(from page)` (only a guess), else `Company unknown`.
Under the card it says whether the link or the same company + position is already in the
tracker (the Google Sheet, or the Excel file if the Sheet can't be reached). Then
`Apply to this job? [Enter = yes, s = skip]`: skip ends the run and writes nothing.
`--check` prints the card and the tracker result, then exits.

## Form filling

For a Greenhouse link (including company sites with `?gh_jid=`), the tool reads the
form's questions from the public job board API and opens the form in Chrome. Chrome
uses its own profile in `browser-profile/`, so logins stay saved. Then:

- **Your details:** name, email, phone, location, resume, links, current job and EEO
  answers come from `profile.yaml`.
- **Visa status in a text box** ("What is your current visa status?") is filled with
  `work_authorization.visa_details` from `profile.yaml`.
- **Custom questions:** matched by their label (lowercased, punctuation removed) against
  `answers.yaml`. A few common questions have built-in rules that point at your profile:
  work authorization, sponsorship (a "now or in the future" question uses your *future*
  answer), relocation, start date and salary. These rules only answer dropdowns, so a
  free-text question that merely mentions relocation isn't filled with "Yes".
- **Dropdowns only take an exact option.** If your profile says `Not a Veteran` and the
  options are `I am not a protected veteran` / `I don't wish to answer`, nothing is
  picked. The summary tells you, and you choose it yourself.
- **Unknown required field:** it's outlined in red in the page, and the terminal shows
  the question (with numbered options for a dropdown). Type the answer, or press Enter to
  fill it in the browser yourself. After an answer you're asked
  `Save to answers.yaml? [Y/n]`, so next time it's filled automatically.
- **Unknown optional field:** left blank and listed in the summary.

Then it prints a summary (filled, left blank, needs your attention) and waits. **It never
clicks Submit and never presses Enter in the form.** You review and submit; the browser
closes after you answer the prompt. If anything goes wrong while filling (Chrome missing,
page changed), it says so and you fill the form by hand. The tracker step still works.

## Files

| Path | Purpose |
|---|---|
| `apply.py` | entry point |
| `job_facts.py` | the job facts card |
| `matching.yaml` | keyword lists for the card |
| `tracker.py` | Excel tracker: duplicate check, row writing, backups, pending rows |
| `sheet_tracker.py` | the same for the Google Sheet |
| `ats/` | one module per job system: reads company, position and posted date; `greenhouse.py` also fills the form |
| `ats/form.py` | shared filling rules: profile and `answers.yaml` lookup, option matching |
| `tests/` | pytest tests |
| `SPEC.md` | the full spec and the milestone plan |

## Private files

These stay on your machine and are listed in `.gitignore`:

| File | Holds |
|---|---|
| `google-key.json` | the service account key: anyone with it can edit your Sheet |
| `config.yaml` | your Sheet ID and tracker path |
| `*.xlsx`, `backups/`, `pending_*.json` | your tracker data |
| `profile.yaml`, `answers.yaml` | your personal details and saved form answers (for the form filler) |
| `*.pdf` | your resume |

## Tests

```
pytest
```

The tests run on a temporary copy of `tracker_copy.xlsx` and never touch the real tracker.
The Google Sheet tests use a fake worksheet and make no network calls. `tracker_copy.xlsx`
is personal data, so it isn't in this repo. To run the tests, put a copy of your own
tracker in that format at the repo root. A few tests expect the next empty row to be 898,
so you may need to adjust `EXPECTED_ROW` in `tests/test_tracker.py`. The real-Excel test
is skipped if Excel or pywin32 isn't installed.

## Status

| Milestone | Status |
|---|---|
| 1. Tracker: link in, details read, row written | done |
| 1b. Google Sheet tracker | done |
| 2. Greenhouse form filler (fills, pauses, never submits) | done |
| 3. Ashby, then Lever | planned |
| 4. Workday | planned |
| 5. Other sites | planned |
