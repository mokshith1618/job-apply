# Job Apply Helper: Spec

A personal command-line tool. I paste a job link, it opens the application in a browser,
fills what it can from my profile, stops before submit, and after I submit it adds a row
to my Excel tracker.

## Hard rules

1. **Never submit.** The tool never clicks a submit/apply/send button. I click it myself.
2. **No AI or API calls at runtime.** Everything is plain code. Unknown questions go to me.
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
   - Workday: `*.myworkdayjobs.com`
   - anything else: `other`
2. **Duplicate check.** Compare the URL (with tracking parameters such as `utm_*`,
   `source`, `gh_src` removed) and company + position against the tracker. If it
   matches, show the old row and ask whether to continue.
3. **Read job details:** company, position, posted date.
   - Greenhouse, Ashby, Lever: their public job board APIs (confirm the exact date field
     for each when building).
   - Other sites: the page's `JobPosting` JSON-LD (`title`, `hiringOrganization`,
     `datePosted`) if present.
   - If still missing: ask me in the terminal.
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

## Files

| File | Purpose |
|---|---|
| `apply.py` | entry point |
| `ats/` | one module per system: `greenhouse.py`, `ashby.py`, `lever.py`, `workday.py`, `generic.py` |
| `tracker.py` | duplicate check and row writing |
| `profile.yaml` | my details (filled from resume; sensitive answers set by me) |
| `answers.yaml` | saved answers to custom questions, grows over time |
| `tracker_copy.xlsx` | test copy. Tests use only this file. |
| `tests/` | pytest tests |

## Milestones (build in this order, one per Claude session)

1. **Tracker only:** link in, details read, tracker row written. No form filling.
   Done when: tests pass on `tracker_copy.xlsx`; a new row appears at row 898 with the
   right formats; the file still opens in Excel; duplicate check catches a URL already
   in the tracker.
2. **Greenhouse filler.** Done when: a real Greenhouse form is filled and paused,
   with nothing submitted.
3. **Ashby**, then **Lever**, using the same pattern.
4. **Workday** (account login per company: pause and let me log in).
5. **Other sites:** the generic module fills only fields it can match with confidence;
   for the rest I use Claude in Chrome by hand.

## Out of scope

Job searching or scraping job boards, auto-submit, AI calls, filling Experience or
Key Skills, solving CAPTCHAs, creating accounts automatically.
