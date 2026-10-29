"""A stand-in for a gspread Worksheet: tests never call the real Google Sheet."""
from __future__ import annotations

import re

HEADER = ["Company", "Position", "URL", "Posted date/ Source", "Date", "Outcome", "Stage",
          "Remarks", "Experience", "Key Skills"]


class FakeSpreadsheet:
    def __init__(self, validation=None, stage_validation=None):
        self.requests = []
        self.validation = validation  # the data validation rule on F2, as the Sheets API returns it
        self.stage_validation = stage_validation  # the same for G2
        self.metadata_params = []

    def batch_update(self, body):
        self.requests.extend(body["requests"])

    def fetch_sheet_metadata(self, params=None):
        self.metadata_params.append(params)
        rule = self.stage_validation if params["ranges"].endswith("!G2") else self.validation
        cell = {"dataValidation": rule} if rule else {}
        return {"sheets": [{"properties": {"sheetId": 7}, "data": [{"rowData": [{"values": [cell]}]}]}]}


class FakeWorksheet:
    """Holds display values and C-column formulas like a gspread Worksheet, and records writes."""

    def __init__(self, rows, formulas=None, row_count=1000, fail=None, validation=None, stage_validation=None):
        self.values = [list(r) for r in rows]
        self.title = "Sheet1"
        self.formulas = dict(formulas or {})  # row number -> formula in C
        self.row_count = row_count
        self.id = 7
        self.spreadsheet = FakeSpreadsheet(validation, stage_validation)
        self.fail = fail
        self.updates = []
        self.added_rows = 0

    def _check(self):
        if self.fail:
            raise self.fail

    def get_all_values(self):
        self._check()
        return [list(r) for r in self.values]

    def get(self, range_name, value_render_option=None):
        self._check()
        assert range_name == "C:C" and value_render_option == "FORMULA"
        return [[self.formulas.get(i, (r + [""] * 3)[2])] for i, r in enumerate(self.values, start=1)]

    def add_rows(self, n):
        self._check()
        self.row_count += n
        self.added_rows += n

    def update(self, values, range_name, value_input_option):
        self._check()
        assert value_input_option == "USER_ENTERED"
        self.updates.append((range_name, values))
        m = re.match(r"F(\d+)(?::[GH]\1)?$", range_name)
        if m:  # Outcome, Outcome + Stage, or Outcome + Stage + Remarks
            r = int(m.group(1))
            assert 2 <= r <= len(self.values), "updated a row that isn't there"
            self.values[r - 1] += [""] * (8 - len(self.values[r - 1]))
            self.values[r - 1][5:5 + len(values[0])] = values[0]
            return
        r = int(re.match(r"A(\d+):F\d+$", range_name).group(1))
        assert r <= self.row_count, "wrote past the end of the sheet"
        while len(self.values) < r:
            self.values.append([""] * 10)
        entered = values[0]
        display = list(entered)
        m = re.match(r'=HYPERLINK\("((?:[^"]|"")*)"', entered[2])
        if m:
            self.formulas[r] = entered[2]
            display[2] = m.group(1).replace('""', '"')
        self.values[r - 1][:6] = display
