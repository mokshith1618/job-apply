"""Saved job postings for the job facts card tests (tests/fixtures/jd/).

Real postings are the board API responses trimmed to the fields the readers use, saved 2026-10-19.
Files named synthetic-* are made up to cover cases the real ones don't.
"""
import json
from pathlib import Path

JD_DIR = Path(__file__).parent / "fixtures" / "jd"


def load_fixture(name: str):
    return json.loads((JD_DIR / name).read_text(encoding="utf-8"))
