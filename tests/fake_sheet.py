"""A stand-in for a gspread Worksheet: tests never call the real Google Sheet."""
from __future__ import annotations

import re

HEADER = ["Company", "Position", "URL", "Posted date/ Source", "Date", "Outcome",
          "Remarks", "Experience", "Key Skills"]


class FakeSpreadsheet:
    def __init__(self):
        self.requests = []

    def batch_update(self, body):
        self.requests.extend(body["requests"])


class FakeWorksheet:
    """Holds display values and C-column formulas like a gspread Worksheet, and records writes."""

    def __init__(self, rows, formulas=None, row_count=1000, fail=None):
        self.values = [list(r) for r in rows]
        self.formulas = dict(formulas or {})  # row number -> formula in C
        self.row_count = row_count
        self.id = 7
        self.spreadsheet = FakeSpreadsheet()
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
        r = int(re.match(r"A(\d+):F\d+$", range_name).group(1))
        assert r <= self.row_count, "wrote past the end of the sheet"
        while len(self.values) < r:
            self.values.append([""] * 9)
        entered = values[0]
        display = list(entered)
        m = re.match(r'=HYPERLINK\("((?:[^"]|"")*)"', entered[2])
        if m:
            self.formulas[r] = entered[2]
            display[2] = m.group(1).replace('""', '"')
        self.values[r - 1][:6] = display
