import hashlib
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TRACKER_COPY = ROOT / "tracker_copy.xlsx"
REAL_TRACKER = ROOT / "Job Application Tracker.xlsx"


def _digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="session", autouse=True)
def originals_untouched():
    """Tests work on a temp copy of tracker_copy.xlsx; neither original may change."""
    before = (_digest(TRACKER_COPY), _digest(REAL_TRACKER))
    yield
    assert (_digest(TRACKER_COPY), _digest(REAL_TRACKER)) == before


@pytest.fixture
def tracker_file(tmp_path) -> Path:
    """A fresh temp copy of tracker_copy.xlsx (never the real tracker)."""
    assert TRACKER_COPY.exists(), "tracker_copy.xlsx is missing"
    dest = tmp_path / "tracker_copy.xlsx"
    shutil.copy2(TRACKER_COPY, dest)
    return dest


@pytest.fixture(autouse=True)
def no_real_google_sheet(tmp_path, monkeypatch):
    """Tests never read the real config.yaml or open the real Google Sheet; they pass a FakeWorksheet."""
    import apply
    import sheet_tracker

    monkeypatch.setattr(apply, "DEFAULT_CONFIG", tmp_path / "no-config.yaml")

    def refuse(*args, **kwargs):
        raise AssertionError("tests must not open the real Google Sheet")

    monkeypatch.setattr(sheet_tracker, "open_sheet", refuse)


# A made-up job planted at row 199 of the temp copy, so duplicate tests never name a real application.
KNOWN_ROW = 199
KNOWN_COMPANY = "Example Labs, Inc."
KNOWN_POSITION = "Software Engineer - Python"
KNOWN_URL = "https://jobs.ashbyhq.com/examplelabs/00000000-0000-4000-8000-000000000199"


@pytest.fixture
def dup_tracker(tracker_file) -> Path:
    """tracker_file with the KNOWN_* job in row 199 (C as text and hyperlink, like real rows)."""
    from openpyxl import load_workbook

    wb = load_workbook(tracker_file)
    ws = wb["Sheet1"]
    ws.cell(KNOWN_ROW, 1, KNOWN_COMPANY)
    ws.cell(KNOWN_ROW, 2, KNOWN_POSITION)
    ws.cell(KNOWN_ROW, 3, KNOWN_URL).hyperlink = KNOWN_URL
    wb.save(tracker_file)
    return tracker_file
