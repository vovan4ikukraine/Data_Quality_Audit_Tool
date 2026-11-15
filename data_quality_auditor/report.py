from pathlib import Path

import pandas as pd

from data_quality_auditor.loader import RawTable
from data_quality_auditor.models import ColumnKind, ColumnProfile, Finding, Severity
from data_quality_auditor.policy import THRESHOLDS
from data_quality_auditor.profiler import ColumnPassport


def output_filenames(source: str | Path) -> tuple[str, str]:
    stem = Path(source).stem
    return f"{stem}_audit.md", f"{stem}_findings.csv"


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
_COUNT_LABELS = (
    (Severity.ERROR, "error", "errors"),
    (Severity.WARNING, "warning", "warnings"),
    (Severity.SUGGESTION, "suggestion", "suggestions"),
)
_PROFILE_HEADER = (
    "| Column | Kind | Blank | Sentinel | Distinct | Distinct ratio |",
    "| --- | --- | --- | --- | --- | --- |",
)
_PREVIEW_CHARS = 80


def write_report(
    table: RawTable,
    columns: tuple[ColumnPassport, ...],
    findings: tuple[Finding, ...],
    affected_rows: pd.DataFrame,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    directory = Path.cwd() if output_dir is None else Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    report_name, findings_name = output_filenames(table.path)
    report_path = directory / report_name
    findings_path = directory / findings_name
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
    sections = [_summary(table, findings), _findings(findings), _profile(columns)]
    details = _details(columns)
    if details is not None:
        sections.append(details)
    sections.append(_technical(table))
    return "\n\n".join(sections) + "\n"


def _summary(table: RawTable, findings: tuple[Finding, ...]) -> str:
    return "\n".join(
        [
            "# Data quality audit",
            "",
            _file_line(table),
            "",
            _counts(findings),
        ]
    )


def _file_line(table: RawTable) -> str:
    rows = _unit(len(table.frame), "row", "rows")
    columns = _unit(int(table.frame.shape[1]), "column", "columns")
    place = f"`{table.path}`"
    if table.sheet is not None:
        place = f"{place} · sheet {table.sheet}"
    return f"{place} · {rows} · {columns}"


def _counts(findings: tuple[Finding, ...]) -> str:
    if not findings:
        return "No findings."
    parts = [
        _unit(sum(item.severity == severity for item in findings), singular, plural)
        for severity, singular, plural in _COUNT_LABELS
    ]
    return ", ".join(parts) + "."


def _unit(count: int, singular: str, plural: str) -> str:
    label = singular if count == 1 else plural
    return f"{count} {label}"


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
    column = " ".join(item.column.split())
    title = item.check_id if not column else f"{item.check_id} ({column})"
    shown = column if column else "(dataset)"
    lines = [
        f"#### {title}",
        "",
        f"- Column: {shown}",
        f"- Row count: {item.row_count}",
        f"- Share: {_percent(item.share)}",
    ]
    lines.extend(_example_lines(item.example))
    lines.extend(
        [
            f"- Row numbers: {_row_numbers(item)}",
            f"- Message: {item.message}",
            "",
        ]
    )
    return lines


def _example_lines(text: str) -> list[str]:
    inline = _inline_example(text)
    if inline is None:
        return ["- Example:", "", "```", text, "```"]
    return [f"- Example: {inline}"]


def _inline_example(text: str) -> str | None:
    if text == "":
        return "(blank)"
    if _is_brief(text) and ("\n" in text or "`" in text):
        return None
    if _is_brief(text):
        return f"`{text}`"
    return f"`{_one_line(text)}`"


def _row_numbers(item: Finding) -> str:
    if not item.row_numbers:
        return "none"
    shown = ", ".join(str(number) for number in item.row_numbers)
    if item.row_count > len(item.row_numbers):
        return f"{shown} (first {len(item.row_numbers)})"
    return shown


def _profile(columns: tuple[ColumnPassport, ...]) -> str:
    lines = ["## Column profile", ""]
    if not columns:
        lines.append("None.")
        return "\n".join(lines)
    lines.extend(_PROFILE_HEADER)
    for column in columns:
        lines.append(_profile_row(column.profile))
    return "\n".join(lines)


def _profile_row(profile: ColumnProfile) -> str:
    kind = profile.kind.value
    if profile.epoch_unit is not None:
        kind = f"{kind} ({profile.epoch_unit.value})"
    return (
        f"| {_table_cell(profile.name)} | {kind} | {_percent(profile.blank_share)} | "
        f"{_percent(profile.sentinel_share)} | {profile.distinct_count} | "
        f"{_percent(profile.distinct_ratio)} |"
    )


def _table_cell(name: str) -> str:
    return _column_label(name).replace("|", "\\|")


def _column_label(name: str) -> str:
    text = " ".join(name.split())
    return text if text else "(unnamed)"


def _details(columns: tuple[ColumnPassport, ...]) -> str | None:
    blocks = []
    for column in columns:
        block = _detail(column.profile)
        if block:
            blocks.append(block)
    if not blocks:
        return None
    lines = ["## Column details", ""]
    for block in blocks:
        lines.extend(block)
    return "\n".join(lines).rstrip()


def _detail(profile: ColumnProfile) -> list[str]:
    rows = _metric_rows(profile)
    if not rows:
        return []
    return [
        f"### {_column_label(profile.name)}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        *rows,
        "",
    ]


def _metric_rows(profile: ColumnProfile) -> list[str]:
    metrics: list[tuple[str, str]] = []
    if profile.kind is ColumnKind.NUMERIC:
        metrics.extend(
            [
                ("Minimum", _number(profile.minimum)),
                ("Maximum", _number(profile.maximum)),
                ("Median", _number(profile.median)),
                ("Zero count", _whole(profile.zero_count)),
                ("Negative count", _whole(profile.negative_count)),
            ]
        )
    if profile.kind is ColumnKind.DATETIME:
        metrics.extend(
            [
                ("Recognized format", profile.recognized_format or "none"),
                ("Minimum", profile.datetime_minimum or "none"),
                ("Maximum", profile.datetime_maximum or "none"),
            ]
        )
    if profile.frequent_values:
        metrics.append(("Frequent values", _frequent(profile.frequent_values)))
    return [f"| {name} | {_metric_cell(value)} |" for name, value in metrics]


def _metric_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _frequent(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{_inline(value)} ({count})" for value, count in values)


def _inline(text: str) -> str:
    if text == "":
        return "(blank)"
    return f"`{_one_line(text)}`"


def _is_brief(text: str) -> bool:
    return len(text) <= _PREVIEW_CHARS and text.count("\n") <= 2


def _one_line(text: str) -> str:
    single = text.replace("\r", " ").replace("\n", " ").replace("`", "'")
    if len(single) <= _PREVIEW_CHARS:
        return single
    return single[: _PREVIEW_CHARS - 3].rstrip() + "..."


def _technical(table: RawTable) -> str:
    lines = [
        "---",
        "",
        "## Technical details",
        "",
        f"- Encoding: {_encoding(table)}",
        f"- Delimiter: {_delimiter(table)}",
        f"- Audited sheet: {_sheet(table.sheet)}",
        f"- Other sheets: {_other_sheets(table.other_sheets)}",
        "- Row numbers: the header is row 1 and the first record is row 2.",
        "- Examples are copied from the raw data.",
    ]
    if table.has_merged_cells:
        lines.append("- Structural warning: this sheet contains merged cells.")
    lines.extend(["", _threshold_table()])
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


def _threshold_table() -> str:
    lines = [
        "### Thresholds",
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
