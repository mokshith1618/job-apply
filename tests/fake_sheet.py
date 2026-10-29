"""A stand-in for a gspread Worksheet: tests never call the real Google Sheet."""
from __future__ import annotations

import re

from openpyxl.utils.cell import column_index_from_string, get_column_letter

HEADER = ["Company", "Position", "URL", "Posted date/ Source", "Date", "Outcome", "Stage",
          "Last Updated", "Remarks", "Experience", "Key Skills"]


class FakeSpreadsheet:
    def __init__(self, rules):
        self.requests = []
        self.rules = rules  # column letter -> the data validation rule on its row 2, as the Sheets API returns it
        self.metadata_params = []

    def batch_update(self, body):
        self.requests.extend(body["requests"])

    def fetch_sheet_metadata(self, params=None):
        self.metadata_params.append(params)
        rule = self.rules.get(re.search(r"!([A-Z]+)2$", params["ranges"]).group(1))
        cell = {"dataValidation": rule} if rule else {}
        return {"sheets": [{"properties": {"sheetId": 7}, "data": [{"rowData": [{"values": [cell]}]}]}]}


class FakeWorksheet:
    """Holds display values and URL-column formulas like a gspread Worksheet, and records writes."""

    def __init__(self, rows, formulas=None, row_count=1000, fail=None, validation=None, stage_validation=None):
        self.values = [list(r) for r in rows]
        self.title = "Sheet1"
        self.formulas = dict(formulas or {})  # row number -> formula in the URL column
        self.row_count = row_count
        self.id = 7
        header = self.values[0] if self.values else []

        def letter(name):
            return get_column_letter(header.index(name) + 1) if name in header else None

        self.url_letter = letter("URL")
        self.spreadsheet = FakeSpreadsheet({letter("Outcome"): validation, letter("Stage"): stage_validation})
        self.fail = fail
        self.updates = []  # [(cell, value)] in the order written
        self.input_options = {}  # cell -> "RAW" or "USER_ENTERED", as last written
        self.added_rows = 0

    def _check(self):
        if self.fail:
            raise self.fail

    def get_all_values(self):
        self._check()
        return [list(r) for r in self.values]

    def get(self, range_name, value_render_option=None):
        self._check()
        m = re.fullmatch(r"([A-Z]+):\1", range_name)
        assert m and m.group(1) == self.url_letter and value_render_option == "FORMULA"
        i = column_index_from_string(m.group(1)) - 1
        return [[self.formulas.get(r, (row + [""] * (i + 1))[i])] for r, row in enumerate(self.values, start=1)]

    def add_rows(self, n):
        self._check()
        self.row_count += n
        self.added_rows += n

    def batch_update(self, data, value_input_option=None):
        self._check()
        assert value_input_option in ("RAW", "USER_ENTERED")
        for item in data:
            (value,), = item["values"]
            self._set(item["range"], value, value_input_option)

    def _set(self, cell, value, option):
        m = re.fullmatch(r"([A-Z]+)(\d+)", cell)
        assert m, f"one cell per range, got {cell}"
        col, r = column_index_from_string(m.group(1)), int(m.group(2))
        assert 2 <= r <= self.row_count, "wrote past the end of the sheet"
        self.updates.append((cell, value))
        self.input_options[cell] = option
        while len(self.values) < r:
            self.values.append([])
        row = self.values[r - 1]
        row += [""] * (col - len(row))
        link = re.match(r'=HYPERLINK\("((?:[^"]|"")*)"', value)
        if option == "USER_ENTERED" and link and m.group(1) == self.url_letter:
            self.formulas[r] = value
            value = link.group(1).replace('""', '"')
        row[col - 1] = value  # RAW: stored exactly as sent
