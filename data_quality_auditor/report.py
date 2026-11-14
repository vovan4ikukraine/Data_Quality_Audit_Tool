from pathlib import Path

import pandas as pd

from data_quality_auditor.loader import RawTable
from data_quality_auditor.models import ColumnKind, ColumnProfile, Finding, Severity
from data_quality_auditor.policy import THRESHOLDS
from data_quality_auditor.profiler import ColumnPassport

REPORT_FILENAME = "audit_report.md"
FINDINGS_FILENAME = "audit_findings.csv"

_FINDINGS_COLUMNS = (
    "column",
    "check_id",
    "severity",
    "row_number",
    "raw_value",
    "message",
)
_DELIMITER_NAMES = {
    ",": "comma",
    ";": "semicolon",
    "\t": "tab",
    "|": "pipe",
}
_GROUP_TITLES = {
    Severity.ERROR: "Error",
    Severity.WARNING: "Warning",
    Severity.SUGGESTION: "Suggestion",
}


def write_report(
    table: RawTable,
    columns: tuple[ColumnPassport, ...],
    findings: tuple[Finding, ...],
    affected_rows: pd.DataFrame,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    directory = Path.cwd() if output_dir is None else Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / REPORT_FILENAME
    findings_path = directory / FINDINGS_FILENAME
    report_path.write_text(
        _markdown(table, columns, findings),
        encoding="utf-8",
        newline="\n",
    )
    _write_findings(findings_path, affected_rows)
    return report_path, findings_path


def _markdown(
    table: RawTable,
    columns: tuple[ColumnPassport, ...],
    findings: tuple[Finding, ...],
) -> str:
    sections = (
        _header(table),
        _findings(findings),
        _passport(columns),
        _thresholds(),
    )
    return "\n\n".join(sections) + "\n"


def _header(table: RawTable) -> str:
    lines = [
        "# Data quality audit",
        "",
        f"- File: `{table.path}`",
        f"- Rows: {len(table.frame)}",
        f"- Columns: {table.frame.shape[1]}",
        f"- Encoding: {_encoding(table)}",
        f"- Delimiter: {_delimiter(table)}",
        f"- Audited sheet: {_sheet(table.sheet)}",
        f"- Other sheets: {_other_sheets(table.other_sheets)}",
        "- Row numbers: the header is row 1 and the first record is row 2.",
        "- Examples are copied from the raw data.",
    ]
    if table.has_merged_cells:
        lines.append("- Structural warning: this sheet contains merged cells.")
    return "\n".join(lines)


def _encoding(table: RawTable) -> str:
    if table.encoding is None:
        return "not applicable"
    if table.encoding_is_fallback:
        return (
            f"{table.encoding} (no confident encoding was found, "
            "so the file was read as Latin-1)"
        )
    return table.encoding


def _delimiter(table: RawTable) -> str:
    if table.delimiter is None:
        return "not applicable"
    return _DELIMITER_NAMES.get(table.delimiter, table.delimiter)


def _sheet(name: str | None) -> str:
    if name is None:
        return "not applicable"
    return name


def _other_sheets(names: tuple[str, ...]) -> str:
    if not names:
        return "none"
    return ", ".join(names)


def _findings(findings: tuple[Finding, ...]) -> str:
    lines = ["## Findings", ""]
    for severity, title in _GROUP_TITLES.items():
        lines.append(f"### {title}")
        lines.append("")
        group = [item for item in findings if item.severity == severity]
        if not group:
            lines.append("None.")
            lines.append("")
            continue
        for item in group:
            lines.extend(_finding(item))
    return "\n".join(lines).rstrip()


def _finding(item: Finding) -> list[str]:
    column = item.column if item.column else "(dataset)"
    return [
        f"#### {_finding_title(item)}",
        "",
        f"- Column: {column}",
        f"- Row count: {item.row_count}",
        f"- Share: {_percent(item.share)}",
        *_example(item.example),
        f"- Row numbers: {_row_numbers(item)}",
        f"- Message: {item.message}",
        "",
    ]


def _finding_title(item: Finding) -> str:
    if not item.column:
        return item.check_id
    column = " ".join(item.column.split())
    return f"{item.check_id} ({column})"


def _example(text: str) -> list[str]:
    if text == "":
        return ["- Example: (blank)"]
    if "\n" in text or "`" in text:
        return ["- Example:", "", "```", text, "```"]
    return [f"- Example: `{text}`"]


def _row_numbers(item: Finding) -> str:
    if not item.row_numbers:
        return "none"
    shown = ", ".join(str(number) for number in item.row_numbers)
    if item.row_count > len(item.row_numbers):
        return f"{shown} (first {len(item.row_numbers)})"
    return shown


def _passport(columns: tuple[ColumnPassport, ...]) -> str:
    lines = ["## Column passport", ""]
    if not columns:
        lines.append("None.")
        return "\n".join(lines)
    for column in columns:
        lines.extend(_column(column.profile))
    return "\n".join(lines).rstrip()


def _column(profile: ColumnProfile) -> list[str]:
    name = profile.name if profile.name else "(unnamed)"
    lines = [
        f"### {name}",
        "",
        f"- Kind: {profile.kind.value}",
        f"- Blank share: {_percent(profile.blank_share)}",
        f"- Sentinel share: {_percent(profile.sentinel_share)}",
        f"- Distinct count: {profile.distinct_count}",
        f"- Distinct ratio: {_percent(profile.distinct_ratio)}",
    ]
    if profile.epoch_unit is not None:
        lines.append(f"- Epoch: {profile.epoch_unit.value}")
    if profile.kind is ColumnKind.NUMERIC:
        lines.extend(_numeric_lines(profile))
    if profile.kind is ColumnKind.DATETIME:
        lines.extend(_datetime_lines(profile))
    if profile.frequent_values:
        lines.append(f"- Frequent values: {_frequent(profile.frequent_values)}")
    lines.append("")
    return lines


def _numeric_lines(profile: ColumnProfile) -> list[str]:
    return [
        f"- Minimum: {_number(profile.minimum)}",
        f"- Maximum: {_number(profile.maximum)}",
        f"- Median: {_number(profile.median)}",
        f"- Zero count: {_whole(profile.zero_count)}",
        f"- Negative count: {_whole(profile.negative_count)}",
    ]


def _datetime_lines(profile: ColumnProfile) -> list[str]:
    recognized = profile.recognized_format or "none"
    return [
        f"- Recognized format: {recognized}",
        f"- Minimum: {profile.datetime_minimum or 'none'}",
        f"- Maximum: {profile.datetime_maximum or 'none'}",
    ]


def _frequent(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{_inline(value)} ({count})" for value, count in values)


def _inline(text: str) -> str:
    if text == "":
        return "(blank)"
    single_line = text.replace("\r", " ").replace("\n", " ")
    if "`" in single_line:
        return single_line
    return f"`{single_line}`"


def _thresholds() -> str:
    lines = [
        "## Thresholds",
        "",
        "| Threshold | Value |",
        "| --- | --- |",
    ]
    for name, value in THRESHOLDS:
        lines.append(f"| {name} | {_threshold(value)} |")
    return "\n".join(lines)


def _percent(share: float) -> str:
    percent = share * 100
    text = f"{percent:.1f}"
    if share > 0 and text == "0.0":
        text = f"{percent:.3f}"
    return f"{text}%"


def _number(value: float | None) -> str:
    if value is None:
        return "none"
    return f"{value:.12g}"


def _whole(value: int | None) -> str:
    if value is None:
        return "none"
    return str(value)


def _threshold(value: float) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _write_findings(path: Path, affected_rows: pd.DataFrame) -> None:
    frame = affected_rows.loc[:, list(_FINDINGS_COLUMNS)]
    frame.to_csv(path, index=False, encoding="utf-8-sig")
