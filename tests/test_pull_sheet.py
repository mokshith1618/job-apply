"""Pull-sheet tests: Sheet → Excel merge against a fake worksheet (no network)."""
from datetime import date, datetime

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

import pull_sheet
import tracker
from fake_sheet import HEADER, FakeWorksheet

TODAY = date(2026, 10, 20)

SHEET_URL_1 = "https://jobs.ashbyhq.com/examplelabs/1234abcd"
SHEET_URL_2 = "https://jobs.lever.co/linked/abc-123"
NEW_URL = "https://job-boards.greenhouse.io/newcorp/jobs/9999999"


# ---------- helpers ----------

def _make_excel(tmp_path, rows=None):
    """Build a small tracker with specific rows instead of the 897-row fake."""
    path = tmp_path / "tracker.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(list(HEADER))
    if rows:
        for row in rows:
            ws.append(row)
    table = Table(displayName="Table1", ref="A1:K1000")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(table)
    dv = DataValidation(type="list", formula1='"Applied,Rejected,Awaiting reply,In progress"', allow_blank=True)
    dv.add("F2:F1000")
    ws.add_data_validation(dv)
    wb.save(path)
    return path


def _excel_values(path, row_num):
    """Read a row from the Excel file and return {field: value}."""
    wb = load_workbook(path)
    ws = wb["Sheet1"]
    cols = tracker.column_map(next(ws.iter_rows(max_row=1, values_only=True), ()))
    values = {f: ws.cell(row_num, cols[f]).value for f in tracker.FIELDS}
    wb.close()
    return values


def _excel_row_count(path):
    """Count non-empty Company rows in the Excel file."""
    rows = tracker.read_rows(path)
    return len(rows)


def _sheet_with(rows, formulas=None):
    return FakeWorksheet([HEADER] + rows, formulas=formulas)


def _config():
    return {"sheet_id": "test-id", "sheet_tab": "Sheet1", "google_key": "google-key.json"}


def _input_sequence(answers):
    """Return an input_fn that yields answers in order."""
    it = iter(answers)
    return lambda prompt: next(it)


# ---------- tests ----------

class TestNoChanges:
    """Sheet and Excel have the same data → 'Nothing to do'."""

    def test_in_sync(self, tmp_path):
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(
            _config(), path, input_fn=input, dry_run=False, auto_accept=True, ws=ws)
        assert updated == 0
        assert new == 0


class TestSheetEdits:
    """Sheet has edits on existing rows → updates written to Excel."""

    def test_outcome_changed_auto_accept(self, tmp_path):
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Rejected",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(
            _config(), path, auto_accept=True, ws=ws)
        assert updated == 1
        assert new == 0
        vals = _excel_values(path, 2)
        assert vals["Outcome"] == "Rejected"

    def test_multiple_fields_changed(self, tmp_path):
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "In progress",
             "Interview", "", "10/20/2026 Had interview", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(
            _config(), path, auto_accept=True, ws=ws)
        assert updated == 1
        vals = _excel_values(path, 2)
        assert vals["Outcome"] == "In progress"
        assert vals["Stage"] == "Interview"
        assert vals["Remarks"] == "10/20/2026 Had interview"


class TestNewRows:
    """Rows in the Sheet but not in Excel → appended."""

    def test_new_row_appended(self, tmp_path):
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
            ["New Corp", "Designer", NEW_URL, "Posted today", "7/1/2026", "Applied",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(
            _config(), path, auto_accept=True, ws=ws)
        assert updated == 0
        assert new == 1
        assert _excel_row_count(path) == 2
        vals = _excel_values(path, 3)
        assert vals["Company"] == "New Corp"
        assert vals["Position"] == "Designer"

    def test_new_row_url_hyperlink(self, tmp_path):
        """The new row's URL is set as a hyperlink in Excel."""
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
            ["New Corp", "Designer", NEW_URL, "Posted today", "7/1/2026", "Applied",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        pull_sheet.pull(_config(), path, auto_accept=True, ws=ws)
        wb = load_workbook(path)
        ws_xl = wb["Sheet1"]
        cols = tracker.column_map(next(ws_xl.iter_rows(max_row=1, values_only=True), ()))
        link = ws_xl.cell(3, cols["URL"]).hyperlink
        assert link is not None
        assert link.target == NEW_URL
        wb.close()


class TestConflictResolution:
    """Batch prompt and conflict resolution."""

    def test_reject_all(self, tmp_path):
        """User types 'n' → Excel values kept."""
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Rejected",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(
            _config(), path, input_fn=_input_sequence(["n"]), ws=ws)
        assert updated == 0
        vals = _excel_values(path, 2)
        assert vals["Outcome"] == "Applied"

    def test_accept_all_with_enter(self, tmp_path):
        """User presses Enter (empty string) → Sheet values written."""
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Rejected",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(
            _config(), path, input_fn=_input_sequence([""]), ws=ws)
        assert updated == 1
        vals = _excel_values(path, 2)
        assert vals["Outcome"] == "Rejected"

    def test_accept_all_with_y(self, tmp_path):
        """User types 'y' → Sheet values written."""
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Rejected",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(
            _config(), path, input_fn=_input_sequence(["y"]), ws=ws)
        assert updated == 1
        vals = _excel_values(path, 2)
        assert vals["Outcome"] == "Rejected"

    def test_select_specific_conflicts_with_e(self, tmp_path):
        """User types 'e', then selects conflict 1, skipping conflict 2."""
        excel_rows = [
            ["Company A", "Dev A", "https://example.com/a", "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
            ["Company B", "Dev B", "https://example.com/b", "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Company A", "Dev A", "https://example.com/a", "Posted today", "6/20/2026", "Rejected",
             "", "", "", "", ""],
            ["Company B", "Dev B", "https://example.com/b", "Posted today", "6/20/2026", "In progress",
             "Interview", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        # Type 'e' to select, then '1' to only apply conflict 1
        updated, new = pull_sheet.pull(
            _config(), path,
            input_fn=_input_sequence(["e", "1"]), ws=ws)
        assert updated == 1
        assert _excel_values(path, 2)["Outcome"] == "Rejected"    # conflict 1 updated
        assert _excel_values(path, 3)["Outcome"] == "Applied"     # conflict 2 kept


class TestDryRun:
    """--dry-run shows changes without writing."""

    def test_dry_run_no_write(self, tmp_path):
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Rejected",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(
            _config(), path, dry_run=True, auto_accept=True, ws=ws)
        assert updated == 1
        # Excel should NOT be changed
        vals = _excel_values(path, 2)
        assert vals["Outcome"] == "Applied"


class TestDateHandling:
    """Date normalization across fields avoids false conflicts."""

    def test_posted_date_datetime_vs_string_not_diff(self, tmp_path):
        """Excel has datetime(2026, 4, 22), Sheet has '4/22/2026' -> no difference."""
        from datetime import datetime
        excel_rows = [
            ["Cargill", "Platform Engineer", SHEET_URL_1, datetime(2026, 4, 22), "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Cargill", "Platform Engineer", SHEET_URL_1, "4/22/2026", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(_config(), path, auto_accept=True, ws=ws)
        assert updated == 0

    def test_last_updated_as_date(self, tmp_path):
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "10/20/2026", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        pull_sheet.pull(_config(), path, auto_accept=True, ws=ws)
        vals = _excel_values(path, 2)
        last_updated = vals["Last Updated"]
        assert isinstance(last_updated, (date, datetime))
        if isinstance(last_updated, datetime):
            last_updated = last_updated.date()
        assert last_updated == date(2026, 10, 20)


class TestHyperlinkHandling:
    """Hyperlink formula in Excel matches plain URL in Sheet."""

    def test_hyperlink_formula_not_diff(self, tmp_path):
        url = "https://example.com/job/123"
        excel_rows = [
            ["Acme Corp", "Engineer", f'=HYPERLINK("{url}", "{url}")', "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", url, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(_config(), path, auto_accept=True, ws=ws)
        assert updated == 0


class TestHintedRowMatch:
    """Duplicate jobs across rows match by hinted row index."""

    def test_duplicate_companies_match_by_row(self, tmp_path):
        excel_rows = [
            ["Intel", "Software Engineer", "https://intel.com/1", "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
            ["Intel", "Software Engineer", "https://intel.com/2", "Posted today", "6/21/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Intel", "Software Engineer", "https://intel.com/1", "Posted today", "6/20/2026", "Rejected",
             "", "", "", "", ""],
            ["Intel", "Software Engineer", "https://intel.com/2", "Posted today", "6/21/2026", "Applied",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        updated, new = pull_sheet.pull(_config(), path, auto_accept=True, ws=ws)
        assert updated == 1
        assert _excel_values(path, 2)["Outcome"] == "Rejected"
        assert _excel_values(path, 3)["Outcome"] == "Applied"


class TestBackup:
    """A backup is created before writing."""

    def test_backup_created(self, tmp_path):
        excel_rows = [
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Applied",
             "", "", "", "", ""],
        ]
        ws = _sheet_with([
            ["Acme Corp", "Engineer", SHEET_URL_1, "Posted today", "6/20/2026", "Rejected",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, excel_rows)
        pull_sheet.pull(_config(), path, auto_accept=True, ws=ws)
        backups = list((tmp_path / "backups").glob("tracker-*.xlsx"))
        assert len(backups) == 1


class TestErrorHandling:
    """Graceful errors for Sheet unavailable and Excel locked."""

    def test_sheet_unavailable(self, tmp_path, monkeypatch):
        """pull() raises SheetUnavailable when the Sheet can't be opened."""
        path = _make_excel(tmp_path, [])
        config = _config()

        def fail_open(*a, **kw):
            raise pull_sheet.SheetUnavailable("network error")

        monkeypatch.setattr(pull_sheet.sheet_tracker, "open_sheet", fail_open)
        with pytest.raises(pull_sheet.SheetUnavailable):
            pull_sheet.pull(config, path, ws=None)

    def test_sheet_unavailable_cli(self, tmp_path, monkeypatch):
        """main() returns 1 and prints a message when the Sheet is unreachable."""
        path = _make_excel(tmp_path, [])
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            f"sheet_id: test\nlocal_tracker: {path}\n", encoding="utf-8")

        def fail_open(*a, **kw):
            raise pull_sheet.SheetUnavailable("network error")

        monkeypatch.setattr(pull_sheet.sheet_tracker, "open_sheet", fail_open)
        rc = pull_sheet.main(["--config", str(config_path), "--tracker", str(path)])
        assert rc == 1

    def test_excel_locked(self, tmp_path):
        """When the Excel file can't be saved, TrackerLocked is raised."""
        ws = _sheet_with([
            ["New Corp", "Designer", NEW_URL, "Posted today", "7/1/2026", "Applied",
             "", "", "", "", ""],
        ])
        path = _make_excel(tmp_path, [])
        path.chmod(0o444)
        try:
            with pytest.raises(tracker.TrackerLocked):
                pull_sheet.pull(_config(), path, auto_accept=True, ws=ws)
        finally:
            path.chmod(0o644)


class TestCLI:
    """CLI argument parsing and main()."""

    def test_no_sheet_id(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("local_tracker: tracker.xlsx\n", encoding="utf-8")
        rc = pull_sheet.main(["--config", str(config_path)])
        assert rc == 1

    def test_tracker_not_found(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("sheet_id: test\nlocal_tracker: does-not-exist.xlsx\n", encoding="utf-8")
        rc = pull_sheet.main(["--config", str(config_path)])
        assert rc == 1
