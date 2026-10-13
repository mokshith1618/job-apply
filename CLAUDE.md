# Job Apply Helper

Read SPEC.md before planning any change. Build one milestone per session.

## Rules
- IMPORTANT: the app must never click a submit/apply/send button. It stops and waits for me.
- No AI or API calls inside the app. Unknown form fields: ask me in the terminal, then save to answers.yaml.
- Never guess work authorization, sponsorship, salary, start date, relocation or EEO answers.
- Tests and experiments use tracker_copy.xlsx only. Never write to "Job Application Tracker.xlsx" unless I run apply.py myself.
- Do not edit profile.yaml or answers.yaml values without asking me.

## Stack
- Windows, Python 3.11+, virtual env in .venv
- Playwright (Chrome channel, persistent profile in browser-profile/), openpyxl, PyYAML, pytest

## Workflow
- Run `pytest` after every change and show me the result.
- When building a form filler, open a real job form with the browser tools to read its fields first.
