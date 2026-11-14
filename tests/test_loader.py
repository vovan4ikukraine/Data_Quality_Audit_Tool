from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from data_quality_auditor.loader import LoadError, is_blank_or_sentinel, load_file


def write_csv(directory, name, text):
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "value",
    ["", "   ", "NA", " N/A ", "Null", "NONE", "-", "--", "?", "#N/A", " #n/a "],
)
def test_blank_or_sentinel_values(value):
    assert is_blank_or_sentinel(value) is True


@pytest.mark.parametrize("value", ["0", "nan", "paid", "N/A/A"])
def test_ordinary_text_is_not_a_sentinel(value):
    assert is_blank_or_sentinel(value) is False


def test_missing_file(tmp_path):
    with pytest.raises(LoadError, match="File not found"):
        load_file(tmp_path / "missing.csv")


def test_directory_is_not_a_file(tmp_path):
    with pytest.raises(LoadError, match="Path is not a file"):
        load_file(tmp_path)


def test_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    with pytest.raises(LoadError, match="The file is empty"):
        load_file(path)


def test_whitespace_only_csv(tmp_path):
    path = write_csv(tmp_path, "blank.csv", "  \n\t\n")
    with pytest.raises(LoadError, match="no rows"):
        load_file(path)


def test_unsupported_extension(tmp_path):
    path = write_csv(tmp_path, "notes.txt", "name,value\n1,2\n")
    with pytest.raises(LoadError, match="Unsupported file format '.txt'"):
        load_file(path)


def test_missing_extension(tmp_path):
    path = write_csv(tmp_path, "notes", "name,value\n1,2\n")
    with pytest.raises(LoadError, match="no extension"):
        load_file(path)


def test_legacy_xls_is_rejected(tmp_path):
    path = tmp_path / "book.xls"
    path.write_bytes(b"not an xls workbook")
    with pytest.raises(LoadError, match="Legacy .xls"):
        load_file(path)


def test_sheet_option_rejects_csv(tmp_path):
    path = write_csv(tmp_path, "data.csv", "name,value\na,1\n")
    with pytest.raises(LoadError, match="sheet option"):
        load_file(path, sheet="Orders")


def test_empty_header_row(tmp_path):
    path = write_csv(tmp_path, "bad.csv", "\nname\n1\n")
    with pytest.raises(LoadError, match="header row is empty"):
        load_file(path)


def test_blank_header_with_no_records(tmp_path):
    path = write_csv(tmp_path, "nocols.csv", ",\n")
    with pytest.raises(LoadError, match="no columns"):
        load_file(path)


@pytest.mark.parametrize(
    ("delimiter", "text"),
    [
        (",", "code,amount\n001,100\n"),
        (";", "code;amount\n001;100\n"),
        ("\t", "code\tamount\n001\t100\n"),
        ("|", "code|amount\n001|100\n"),
    ],
)
def test_delimiter_detection_keeps_text(tmp_path, delimiter, text):
    table = load_file(write_csv(tmp_path, "data.csv", text))

    assert table.delimiter == delimiter
    assert table.encoding == "utf-8"
    assert table.encoding_is_fallback is False
    assert table.frame.index.name == "row_number"
    assert list(table.frame.index) == [2]
    assert table.frame.loc[2, "code"] == "001"
    assert table.frame.loc[2, "amount"] == "100"


def test_csv_keeps_raw_cell_text(tmp_path):
    path = write_csv(tmp_path, "amounts.csv", "amount;code;label\n12,50;001; 100 \n")
    table = load_file(path)
    row = table.frame.loc[2]

    assert row["amount"] == "12,50"
    assert row["code"] == "001"
    assert row["label"] == " 100 "


def test_utf8_bom(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes("name,value\nalpha,1\n".encode("utf-8-sig"))
    table = load_file(path)

    assert table.encoding == "utf-8-sig"
    assert table.encoding_is_fallback is False
    assert list(table.frame.columns) == ["name", "value"]


def test_non_utf8_csv_keeps_the_character(tmp_path):
    path = tmp_path / "latin.csv"
    path.write_bytes(b"city;name\ncaf\xe9;ada\n")
    table = load_file(path)

    assert table.delimiter == ";"
    assert table.frame.loc[2, "city"] == "café"


def test_headers_are_stripped_and_made_unique(tmp_path):
    table = load_file(write_csv(tmp_path, "headers.csv", " amount ,amount\n1,2\n"))
    assert list(table.frame.columns) == ["amount", "amount (2)"]


def test_header_only_csv(tmp_path):
    table = load_file(write_csv(tmp_path, "header.csv", "name,value\n"))
    assert list(table.frame.columns) == ["name", "value"]
    assert table.frame.empty
    assert table.empty_row_numbers == ()


def test_ragged_row_stays_out_of_the_table(tmp_path):
    text = "name,value\na,1\nb,2,extra\nc,3\n"
    table = load_file(write_csv(tmp_path, "ragged.csv", text))

    assert list(table.frame.index) == [2, 4]
    assert table.frame.loc[4, "name"] == "c"
    assert len(table.ragged_rows) == 1
    ragged = table.ragged_rows[0]
    assert ragged.row_number == 3
    assert ragged.field_count == 3
    assert ragged.raw_value == "b,2,extra"


def test_empty_and_sentinel_rows_stay_in_the_frame(tmp_path):
    text = "name,value\na,1\n   ,   \nNA,-\nc,3\n"
    table = load_file(write_csv(tmp_path, "gaps.csv", text))

    assert list(table.frame.index) == [2, 3, 4, 5]
    assert table.frame.loc[3, "name"] == "   "
    assert table.empty_row_numbers == (3, 4)


def workbook(path, merged=False):
    book = Workbook()
    orders = book.active
    orders.title = "Orders"
    archive = book.create_sheet("Archive")
    orders["A1"] = "when"
    orders["B1"] = "amount"
    orders["C1"] = "code"
    orders["A2"] = datetime(2024, 3, 5)
    orders["B2"] = 12.5
    orders["C2"] = "001"
    orders["A3"] = datetime(2024, 1, 2)
    orders["B3"] = "42"
    orders["C3"] = "x"
    orders["A4"] = ""
    orders["B4"] = ""
    orders["C4"] = ""
    if merged:
        orders.merge_cells("A1:B1")
    archive["A1"] = "id"
    archive["A2"] = "9"
    book.save(path)
    return path


def test_xlsx_reads_the_first_sheet_and_keeps_cell_text(tmp_path):
    table = load_file(workbook(tmp_path / "book.xlsx"))

    assert table.sheet == "Orders"
    assert table.other_sheets == ("Archive",)
    assert table.encoding is None
    assert table.delimiter is None
    assert table.ragged_rows == ()
    assert table.has_merged_cells is False
    assert table.frame.loc[2, "when"] == "2024-03-05"
    assert table.cell_types.loc[2, "when"] == "d"
    assert table.frame.loc[2, "amount"] == "12.5"
    assert table.cell_types.loc[2, "amount"] == "n"
    assert table.frame.loc[2, "code"] == "001"
    assert table.frame.loc[3, "amount"] == "42"
    assert table.cell_types.loc[3, "amount"] == "s"
    assert table.empty_row_numbers == (4,)


def test_xlsx_selects_a_named_sheet(tmp_path):
    table = load_file(workbook(tmp_path / "book.xlsx"), sheet="Archive")

    assert table.sheet == "Archive"
    assert table.other_sheets == ("Orders",)
    assert table.frame.loc[2, "id"] == "9"


def test_xlsx_records_merged_cells(tmp_path):
    table = load_file(workbook(tmp_path / "merged.xlsx", merged=True))
    assert table.has_merged_cells is True
    assert table.frame.loc[2, "when"] == "2024-03-05"


def test_missing_sheet(tmp_path):
    path = workbook(tmp_path / "book.xlsx")
    with pytest.raises(LoadError, match="Sheet 'Missing' was not found"):
        load_file(path, sheet="Missing")


def test_xlsx_must_be_a_zip(tmp_path):
    path = tmp_path / "fake.xlsx"
    path.write_bytes(b"this is not a workbook")
    with pytest.raises(LoadError, match="not a valid .xlsx"):
        load_file(path)


def test_ole_workbook_is_rejected(tmp_path):
    path = tmp_path / "locked.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0rest")
    with pytest.raises(LoadError, match="password-protected or saved in the legacy"):
        load_file(path)


def test_xlsx_offers_data_sheets_and_skips_charts_and_pivots(tmp_path):
    from io import BytesIO
    import zipfile

    from openpyxl.chart import BarChart, Reference
    from openpyxl.packaging.relationship import get_rels_path
    from openpyxl.reader.excel import ExcelReader

    from data_quality_auditor.loader import auditable_sheets

    path = tmp_path / "book.xlsx"
    book = Workbook()
    orders = book.active
    orders.title = "Orders"
    orders["A1"] = "amount"
    orders["A2"] = 10
    chart = BarChart()
    chart.add_data(Reference(orders, min_col=1, min_row=1, max_row=2), titles_from_data=True)
    orders.add_chart(chart, "C2")
    book.create_chartsheet("Chart")
    pivot = book.create_sheet("Pivot")
    pivot["A1"] = "total"
    book.save(path)

    package = ExcelReader(path, read_only=True, keep_links=False)
    package.read_manifest()
    package.read_workbook()
    target = next(
        rel.target for sheet, rel in package.parser.find_sheets() if sheet.name == "Pivot"
    )
    package.archive.close()
    rels_path = get_rels_path(target)
    pivot_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId9" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotTable" '
        'Target="../pivotTables/pivotTable1.xml"/>'
        "</Relationships>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(buffer, "w") as output:
        for item in source.infolist():
            if item.filename != rels_path:
                output.writestr(item, source.read(item.filename))
        output.writestr(rels_path, pivot_rels)
    path.write_bytes(buffer.getvalue())

    assert auditable_sheets(path) == ("Orders",)
    table = load_file(path, sheet="Orders")
    assert table.frame.loc[2, "amount"] == "10"
    assert table.other_sheets == ("Chart", "Pivot")
    with pytest.raises(LoadError, match="could not be processed"):
        load_file(path, sheet="Chart")
    with pytest.raises(LoadError, match="could not be processed"):
        load_file(path, sheet="Pivot")


def test_xlsm_is_read_like_a_workbook(tmp_path):
    table = load_file(workbook(tmp_path / "book.xlsm"))
    assert table.sheet == "Orders"
    assert table.frame.loc[2, "amount"] == "12.5"


def test_a_workbook_open_in_another_program_is_reported(tmp_path, monkeypatch):
    path = tmp_path / "busy.xlsx"
    path.write_bytes(b"PK\x03\x04")

    def locked(self):
        error = PermissionError(13, "denied")
        error.winerror = 32
        raise error

    monkeypatch.setattr(Path, "read_bytes", locked)
    with pytest.raises(LoadError, match="open in another program"):
        load_file(path)


def test_side_by_side_tables_stay_separate(tmp_path):
    from data_quality_auditor.loader import column_blocks, take_columns

    book = Workbook()
    sheet = book.active
    sheet["A1"] = "name"
    sheet["B1"] = "age"
    sheet["A2"] = "Ada"
    sheet["B2"] = 30
    sheet["D1"] = "city"
    sheet["E1"] = "code"
    sheet["D2"] = "Paris"
    sheet["E2"] = "75000"
    path = tmp_path / "sides.xlsx"
    book.save(path)

    table = load_file(path)
    blocks = column_blocks(table.frame)
    left = take_columns(table, *blocks[0])
    right = take_columns(table, *blocks[1])

    assert blocks == ((0, 2), (3, 5))
    assert list(left.frame.columns) == ["name", "age"]
    assert list(right.frame.columns) == ["city", "code"]
    assert left.frame.loc[2, "name"] == "Ada"
    assert right.frame.loc[2, "city"] == "Paris"
