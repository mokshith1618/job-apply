# Job Apply Helper

A personal command-line tool for logging job applications. You paste a job link. The tool
reads the company, position and posted date, checks whether you've already applied, and
waits while you submit the application yourself. Then it adds a row to your tracker, in a
Google Sheet and a local Excel file.

```
python apply.py https://job-boards.greenhouse.io/acme/jobs/1234567 --source LinkedIn
```

```
System: greenhouse
Reading job details...

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

1. **Detects the job system** from the URL: Greenhouse, Ashby, Lever, Workday, or other.
2. **Checks for duplicates** by URL (ignoring tracking parameters like `utm_*` and `gh_src`)
   and by company + position. If it finds a match, it shows the old row and asks before
   continuing.
3. **Reads job details** from the public Greenhouse, Ashby and Lever APIs, or from a page's
   `JobPosting` JSON-LD. Anything it can't find, it asks you in the terminal.
4. **Waits for you** to submit. Press Enter for applied or `s` for skipped.
5. **Writes the row** with Company, Position, URL (as a link), "Posted date/ Source",
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
python apply.py <job-url> [--source LinkedIn|Tsenta|Other] [--tracker PATH] [--no-sheet]
```

| Option | Meaning |
|---|---|
| `--source` | where you found the job; goes into column D |
| `--tracker` | a different local Excel file |
| `--no-sheet` | skip the Google Sheet for this run |
| `--config` | a different config file (default `config.yaml`) |

## Files

| Path | Purpose |
|---|---|
| `apply.py` | entry point |
| `tracker.py` | Excel tracker: duplicate check, row writing, backups, pending rows |
| `sheet_tracker.py` | the same for the Google Sheet |
| `ats/` | one module per job system: reads company, position and posted date |
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
| 2. Greenhouse form filler (fills, pauses, never submits) | planned |
| 3. Ashby, then Lever | planned |
| 4. Workday | planned |
| 5. Other sites | planned |
