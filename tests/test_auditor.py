from pathlib import Path

import pandas as pd

from data_quality_auditor.main import audit_file
from data_quality_auditor.policy import THRESHOLDS

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FINDING_COLUMNS = [
    "column",
    "check_id",
    "severity",
    "row_number",
    "raw_value",
    "message",
]
EXPECTED = {
    ("ragged_rows", "", "error", "1,10,ada@example.com,Paid,EXTRA", (14,)),
    ("empty_rows", "", "suggestion", " |  |  | ", (13,)),
    ("identifier_missing", "id", "error", "", (12,)),
    ("numeric_parse_failure", "amount", "error", "abc", (11,)),
    ("email_format", "email", "error", "broken", (11,)),
    ("sentinel_values", "status", "warning", "NA", (12,)),
}


def test_a_fixture_runs_through_the_pipeline_into_valid_reports(tmp_path):
    source = FIXTURES / "dirty.csv"
    original = source.read_bytes()
    report_path, findings_path = audit_file(source, output_dir=tmp_path)
    report = report_path.read_text(encoding="utf-8")
    findings = _read_findings(findings_path)
    described = _findings(report)

    assert source.read_bytes() == original
    assert report_path == tmp_path / "dirty_audit.md"
    assert findings_path == tmp_path / "dirty_findings.csv"
    assert findings_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in report_path.read_bytes()
    assert report.startswith("# Data quality audit\n")
    assert f"- File: `{source}`" in report
    assert "- Rows: 12" in report
    assert "- Columns: 4" in report
    assert "- Encoding: utf-8" in report
    assert "- Delimiter: comma" in report
    assert "- Audited sheet: not applicable" in report
    assert "- Other sheets: none" in report
    assert "- Row numbers: the header is row 1 and the first record is row 2." in report
    assert "- Examples are copied from the raw data." in report
    assert report.index("# Data quality audit") < report.index("## Findings")
    assert report.index("## Findings") < report.index("## Column passport")
    assert report.index("## Column passport") < report.index("## Thresholds")
    assert report.index("### Error") < report.index("### Warning") < report.index("### Suggestion")
    assert "None." not in report
    assert "### id" in report
    assert "### amount" in report
    assert "### email" in report
    assert "### status" in report
    assert "- Kind: identifier" in report
    assert "- Kind: numeric" in report
    assert "- Kind: email" in report
    assert "- Kind: text" in report
    for name, _value in THRESHOLDS:
        assert f"| {name} |" in report
    assert list(findings.columns) == FINDING_COLUMNS
    assert not findings.empty
    assert set(findings["severity"]) <= {"error", "warning", "suggestion"}
    assert findings["message"].str.endswith(".").all()
    assert described == EXPECTED
    assert _csv_findings(findings) == EXPECTED


def _read_findings(path):
    return pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)


def _findings(report):
    severity = None
    title = None
    fields = {}
    found = set()

    def close():
        nonlocal title, fields
        if title is None:
            return
        found.add(_described(severity, title, fields))
        title = None
        fields = {}

    for line in report.splitlines():
        if line.startswith("#### "):
            close()
            title = line.removeprefix("#### ")
            fields = {}
            continue
        if line in {"### Error", "### Warning", "### Suggestion"}:
            close()
            severity = line.removeprefix("### ").lower()
            continue
        if line.startswith("## "):
            close()
            continue
        if title is None or not line.startswith("- "):
            continue
        label, value = line.removeprefix("- ").split(": ", 1)
        fields[label] = value
    close()
    return found


def _described(severity, title, fields):
    column = fields["Column"]
    if column == "(dataset)":
        column = ""
    check_id = _check_id(title, column)
    return (
        check_id,
        column,
        severity,
        _example(fields["Example"]),
        _row_numbers(fields["Row numbers"]),
    )


def _check_id(title, column):
    suffix = f" ({column})"
    if column and title.endswith(suffix):
        return title[: -len(suffix)]
    return title


def _example(value):
    if value == "(blank)":
        return ""
    assert value.startswith("`") and value.endswith("`")
    return value[1:-1]


def _row_numbers(value):
    shown = value.split(" (first ", 1)[0]
    return tuple(int(number) for number in shown.split(", "))


def _csv_findings(findings):
    found = set()
    for keys, rows in findings.groupby(["check_id", "column"], sort=False):
        check_id, column = keys
        ordered = rows.sort_values("row_number")
        assert ordered["message"].nunique() == 1
        assert ordered["severity"].nunique() == 1
        found.add(
            (
                check_id,
                column,
                ordered["severity"].iloc[0],
                ordered["raw_value"].iloc[0],
                tuple(int(number) for number in ordered["row_number"].head(5)),
            )
        )
    return found
