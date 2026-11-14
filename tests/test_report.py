import pandas as pd
import pytest

from data_quality_auditor.loader import RawTable
from data_quality_auditor.models import (
    ColumnKind,
    ColumnProfile,
    EpochUnit,
    Finding,
    Severity,
)
from data_quality_auditor.policy import THRESHOLDS
from data_quality_auditor.profiler import ColumnPassport
from data_quality_auditor.report import FINDINGS_FILENAME, REPORT_FILENAME, write_report

FINDING_COLUMNS = [
    "column",
    "check_id",
    "severity",
    "row_number",
    "raw_value",
    "message",
]


def profile(**overrides):
    values = {
        "name": "amount",
        "kind": ColumnKind.TEXT,
        "blank_share": 0.0,
        "sentinel_share": 0.0,
        "distinct_count": 1,
        "distinct_ratio": 1.0,
    }
    values.update(overrides)
    return ColumnProfile(**values)


def passport(column):
    return ColumnPassport(
        profile=column,
        numeric_values=None,
        datetime_values=None,
        mixed_numeric_dialect=False,
        mixed_datetime_formats=False,
        ambiguous_day_month=False,
        ambiguous_rows=None,
    )


def finding(**overrides):
    values = {
        "check_id": "email_format",
        "severity": Severity.ERROR,
        "column": "email",
        "row_count": 1,
        "share": 0.5,
        "example": "broken",
        "row_numbers": (3,),
        "message": "A value does not look like an email address.",
    }
    values.update(overrides)
    return Finding(**values)


def table(**overrides):
    frame = overrides.pop(
        "frame",
        pd.DataFrame({"amount": ["10", "20"], "email": ["ada@example.com", "broken"]}),
    )
    values = {
        "path": "orders.csv",
        "frame": frame,
        "cell_types": None,
        "encoding": "utf-8",
        "encoding_is_fallback": False,
        "delimiter": ",",
        "sheet": None,
        "other_sheets": (),
        "has_merged_cells": False,
        "ragged_rows": (),
        "empty_row_numbers": (),
    }
    values.update(overrides)
    return RawTable(**values)


def affected(*rows):
    return pd.DataFrame(list(rows), columns=FINDING_COLUMNS)


def render(directory, source, columns, findings, rows):
    report_path, findings_path = write_report(source, columns, findings, rows, directory)
    return report_path.read_text(encoding="utf-8"), findings_path


def read_findings(path):
    return pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)


def test_markdown_findings_and_csv_describe_the_same_finding(tmp_path):
    item = finding(row_count=2, row_numbers=(3, 4), example="broken")
    rows = affected(
        {
            "column": "email",
            "check_id": "email_format",
            "severity": "error",
            "row_number": 3,
            "raw_value": "broken",
            "message": item.message,
        },
        {
            "column": "email",
            "check_id": "email_format",
            "severity": "error",
            "row_number": 4,
            "raw_value": "bad @example.com",
            "message": item.message,
        },
    )
    report, findings_path = render(
        tmp_path,
        table(),
        (passport(profile(name="email", kind=ColumnKind.EMAIL)),),
        (item,),
        rows.iloc[:, ::-1],
    )
    found = read_findings(findings_path)

    assert findings_path.name == FINDINGS_FILENAME
    assert findings_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "## Findings" in report
    assert "#### email_format (email)" in report
    assert "- Column: email" in report
    assert "- Row count: 2" in report
    assert "- Share: 50.0%" in report
    assert "- Example: `broken`" in report
    assert "- Row numbers: 3, 4" in report
    assert f"- Message: {item.message}" in report
    assert "### Warning\n\nNone." in report
    assert "### Suggestion\n\nNone." in report
    assert list(found.columns) == FINDING_COLUMNS
    assert found.to_dict("records") == rows.to_dict("records")


def test_header_names_the_csv_file(tmp_path):
    report, _path = render(tmp_path, table(delimiter=";"), (), (), affected())

    assert report.startswith("# Data quality audit\n")
    assert "- File: `orders.csv`" in report
    assert "- Rows: 2" in report
    assert "- Columns: 2" in report
    assert "- Encoding: utf-8" in report
    assert "- Delimiter: semicolon" in report
    assert "- Audited sheet: not applicable" in report
    assert "- Other sheets: none" in report
    assert "- Row numbers: the header is row 1 and the first record is row 2." in report
    assert "- Examples are copied from the raw data." in report
    assert "merged cells" not in report
    assert b"\r\n" not in (tmp_path / REPORT_FILENAME).read_bytes()


@pytest.mark.parametrize(
    ("delimiter", "label"),
    [(",", "comma"), (";", "semicolon"), ("\t", "tab"), ("|", "pipe")],
)
def test_delimiter_is_named(tmp_path, delimiter, label):
    report, _path = render(tmp_path, table(delimiter=delimiter), (), (), affected())
    assert f"- Delimiter: {label}" in report


def test_header_names_the_workbook_sheet_and_merged_cells(tmp_path):
    report, _path = render(
        tmp_path,
        table(
            path="orders.xlsx",
            encoding=None,
            delimiter=None,
            sheet="Orders",
            other_sheets=("Archive", "Notes"),
            has_merged_cells=True,
        ),
        (),
        (),
        affected(),
    )

    assert "- Encoding: not applicable" in report
    assert "- Delimiter: not applicable" in report
    assert "- Audited sheet: Orders" in report
    assert "- Other sheets: Archive, Notes" in report
    assert "- Structural warning: this sheet contains merged cells." in report


def test_a_latin1_fallback_is_stated(tmp_path):
    report, _path = render(
        tmp_path,
        table(encoding="latin-1", encoding_is_fallback=True),
        (),
        (),
        affected(),
    )

    assert (
        "- Encoding: latin-1 (no confident encoding was found, "
        "so the file was read as Latin-1)"
    ) in report


def test_findings_keep_severity_order_and_raw_examples(tmp_path):
    suggestion = finding(
        check_id="missing_values",
        severity=Severity.SUGGESTION,
        column="notes",
        row_count=1,
        share=0.0001,
        example="",
        row_numbers=(),
        message="This column has blank cells.",
    )
    warning = finding(
        check_id="sentinel_values",
        severity=Severity.WARNING,
        column="status",
        row_count=8,
        share=0.4,
        example="NA\nstill NA",
        row_numbers=(2, 3, 4, 5, 6),
        message="This column uses placeholders such as NA or '-'.",
    )
    error = finding(
        check_id="ragged_rows",
        severity=Severity.ERROR,
        column="",
        row_count=1,
        share=1,
        example="a,b,c",
        row_numbers=(14,),
        message="A row has a different field count than the header.",
    )
    report, _path = render(
        tmp_path,
        table(),
        (),
        (suggestion, warning, error),
        affected(),
    )

    assert report.index("### Error") < report.index("### Warning") < report.index("### Suggestion")
    assert "#### ragged_rows" in report
    assert "- Column: (dataset)" in report
    assert "- Example: `a,b,c`" in report
    assert "- Share: 100.0%" in report
    assert "- Example: (blank)" in report
    assert "- Share: 0.010%" in report
    assert "- Row numbers: none" in report
    assert "- Row numbers: 2, 3, 4, 5, 6 (first 5)" in report
    assert "```\nNA\nstill NA\n```" in report


def test_passport_shows_each_kind(tmp_path):
    columns = (
        passport(
            profile(
                name="amount",
                kind=ColumnKind.NUMERIC,
                blank_share=0.1,
                distinct_count=4,
                distinct_ratio=0.8,
                minimum=-3,
                maximum=12.5,
                median=6.25,
                zero_count=1,
                negative_count=2,
                epoch_unit=EpochUnit.SECONDS,
            )
        ),
        passport(
            profile(
                name="created_at",
                kind=ColumnKind.DATETIME,
                distinct_count=2,
                recognized_format="YYYY-MM-DD",
                datetime_minimum="2024-01-02",
                datetime_maximum="2024-03-05",
            )
        ),
        passport(
            profile(
                name="event_date",
                kind=ColumnKind.DATETIME,
                distinct_count=2,
            )
        ),
        passport(
            profile(
                name="status",
                kind=ColumnKind.TEXT,
                sentinel_share=0.2,
                distinct_count=2,
                distinct_ratio=0.5,
                frequent_values=(("Paid", 3), ("", 1)),
            )
        ),
        passport(profile(name="", distinct_count=0, distinct_ratio=0)),
    )
    report, _path = render(tmp_path, table(), columns, (), affected())

    assert "## Column passport" in report
    assert "- Kind: numeric" in report
    assert "- Blank share: 10.0%" in report
    assert "- Distinct ratio: 80.0%" in report
    assert "- Epoch: seconds" in report
    assert "- Minimum: -3" in report
    assert "- Maximum: 12.5" in report
    assert "- Median: 6.25" in report
    assert "- Zero count: 1" in report
    assert "- Negative count: 2" in report
    assert "- Kind: datetime" in report
    assert "- Recognized format: YYYY-MM-DD" in report
    assert "- Minimum: 2024-01-02" in report
    assert "- Maximum: 2024-03-05" in report
    assert "- Recognized format: none" in report
    assert "- Minimum: none" in report
    assert "- Maximum: none" in report
    assert "- Sentinel share: 20.0%" in report
    assert "- Frequent values: `Paid` (3), (blank) (1)" in report
    assert "### (unnamed)" in report
    assert "- Distinct count: 0" in report


def test_an_empty_audit_still_lists_the_thresholds(tmp_path):
    report, findings_path = render(tmp_path, table(), (), (), affected())
    found = read_findings(findings_path)

    assert report.index("# Data quality audit") < report.index("## Findings")
    assert report.index("## Findings") < report.index("## Column passport")
    assert report.index("## Column passport") < report.index("## Thresholds")
    assert "## Column passport\n\nNone." in report
    assert found.empty
    assert list(found.columns) == FINDING_COLUMNS
    for name, value in THRESHOLDS:
        assert f"| {name} |" in report
    assert "| Numeric or date majority | 0.9 |" in report
    assert "| Missing warning | 0.05 |" in report
    assert "| Outlier fence | 1.5 |" in report
    assert "| Category cardinality | 50 |" in report
    assert "| Mixed-dialect count | 3 |" in report


def test_the_output_directory_is_created(tmp_path):
    destination = tmp_path / "nested" / "out"
    report_path, findings_path = write_report(
        table(),
        (),
        (),
        affected(),
        destination,
    )

    assert report_path == destination / REPORT_FILENAME
    assert findings_path == destination / FINDINGS_FILENAME
    assert report_path.exists()
    assert findings_path.exists()


def test_without_an_output_dir_the_report_lands_in_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report_path, findings_path = write_report(table(), (), (), affected())

    assert report_path == tmp_path / REPORT_FILENAME
    assert findings_path == tmp_path / FINDINGS_FILENAME
    assert report_path.exists()
