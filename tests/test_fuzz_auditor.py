import csv
import random
from dataclasses import dataclass
from io import StringIO

import pandas as pd
import pytest

from data_quality_auditor.loader import LoadError
from data_quality_auditor.main import audit_file
from data_quality_auditor.policy import THRESHOLDS
from data_quality_auditor.report import output_filenames

FINDING_COLUMNS = [
    "column",
    "check_id",
    "severity",
    "row_number",
    "raw_value",
    "message",
]
KNOWN_CHECKS = frozenset(
    {
        "all_null_column",
        "ambiguous_day_month",
        "category_case_collision",
        "constant_column",
        "datetime_parse_failure",
        "email_format",
        "empty_rows",
        "epoch_zero",
        "exact_duplicate_rows",
        "formula_value_unavailable",
        "identifier_duplicates",
        "identifier_missing",
        "leading_trailing_whitespace",
        "missing_values",
        "mixed_datetime_formats",
        "mixed_numeric_dialect",
        "near_unique_duplicates",
        "number_stored_as_text",
        "numeric_outliers",
        "numeric_parse_failure",
        "ragged_rows",
        "rare_negative_values",
        "sentinel_values",
        "whitespace_category_collision",
    }
)
DELIMITER_LABELS = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
NAME_POOL = (
    "id",
    "user_id",
    "orderId",
    "rule_id",
    "uuid",
    "email",
    "created_at",
    "order_date",
    "event_ts",
    "timestamp",
    "amount",
    "price",
    "qty",
    "balance",
    "score",
    "status",
    "city",
    "country",
    "notes",
    "sku",
    "category",
)
VALUE_POOL = (
    "",
    " ",
    "NA",
    "N/A",
    "null",
    "none",
    "-",
    "--",
    "?",
    "#N/A",
    "0",
    "1",
    "-3",
    "12.5",
    "12,50",
    "1,234.56",
    "1.234,56",
    "1.77E+12",
    "0007",
    "2024-01-02",
    "02.03.2024",
    "01/02/2024",
    "13/01/2024",
    "1700000000",
    "ada@example.com",
    "broken",
    "bad @example.com",
    "Paid",
    "paid",
    "UK",
    "UK ",
    "  note",
    "café",
    "München",
    "line\nbreak",
    "x" * 120,
    "=1+1",
)
CHAOS_SEEDS = range(100, 124)


@dataclass(frozen=True)
class Sample:
    name: str
    headers: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    expected: frozenset[str]
    kind: str = "csv"
    delimiter: str = ","
    encoding: str = "utf-8"
    ragged: tuple[tuple[str, ...], ...] = ()
    merged: bool = False
    extra_sheet: bool = False
    must_contain: tuple[str, ...] = ()


def _build(seed):
    if seed < len(_THEMES):
        return _THEMES[seed]()
    return _chaos(seed, random.Random(seed))


def _identifiers():
    rows = []
    for index in range(100):
        if index == 50:
            user_id = ""
        elif index == 99:
            user_id = "1"
        else:
            user_id = str(index + 1)
        rule_id = "R1" if index % 2 == 0 else "R2"
        rows.append((user_id, rule_id))
    return _sample(
        "identifiers",
        ("user_id", "rule_id"),
        rows,
        {"identifier_missing", "identifier_duplicates"},
    )


def _emails():
    values = ["ada@example.com"] * 5 + ["broken", "bad @example.com", "nodot@localhost"]
    return _sample("emails", ("email",), [(value,) for value in values], {"email_format"})


def _mixed_dates():
    values = [f"2024-01-{day:02d}" for day in range(1, 11)]
    values += [f"{day:02d}.02.2024" for day in range(1, 11)]
    values.append("soon")
    return _sample(
        "mixed_dates",
        ("order_date",),
        [(value,) for value in values],
        {"mixed_datetime_formats", "datetime_parse_failure"},
    )


def _ambiguous_dates():
    values = ["02/01/2024", "05/06/2024", "01/02/2024", "03/04/2024"]
    return _sample(
        "ambiguous_dates",
        ("ship_date",),
        [(value,) for value in values],
        {"ambiguous_day_month"},
    )


def _epoch():
    values = ["1700000000"] * 12 + ["0"]
    return _sample("epoch", ("event_ts",), [(value,) for value in values], {"epoch_zero"})


def _mixed_money():
    values = ["12,50", "12,50", "1.234,56", "1,234", "1,234.56", "2,000"]
    return _sample(
        "mixed_money",
        ("amount",),
        [(value,) for value in values],
        {"mixed_numeric_dialect"},
    )


def _broken_amount():
    values = [str(number) for number in range(1, 31)] + ["abc"]
    return _sample(
        "broken_amount",
        ("amount",),
        [(value,) for value in values],
        {"numeric_parse_failure"},
    )


def _rare_sign():
    values = ["10"] * 39 + ["-3"]
    return _sample(
        "rare_sign",
        ("balance",),
        [(value,) for value in values],
        {"rare_negative_values"},
    )


def _outliers():
    values = [str(number) for number in range(1, 40)] + ["1000"]
    return _sample(
        "outliers",
        ("score",),
        [(value,) for value in values],
        {"numeric_outliers"},
    )


def _categories():
    statuses = ["Paid", "paid", "Open", "UK", "UK ", "  note", "NA", ""]
    rows = [(status, f"row-{index}") for index, status in enumerate(statuses)]
    return _sample(
        "categories",
        ("status", "label"),
        rows,
        {
            "category_case_collision",
            "whitespace_category_collision",
            "leading_trailing_whitespace",
            "sentinel_values",
            "missing_values",
        },
    )


def _blank_column():
    rows = [(f"note-{index}", "") for index in range(5)]
    return _sample(
        "blank_column",
        ("notes", "middle_name"),
        rows,
        {"all_null_column"},
    )


def _constant_country():
    rows = [(str(index + 1), "US") for index in range(25)]
    return _sample(
        "constant_country",
        ("id", "country"),
        rows,
        {"constant_column"},
    )


def _duplicate_orders():
    rows = [("1", "Paid"), ("2", "Open"), ("1", "Paid")]
    return _sample(
        "duplicate_orders",
        ("id", "status"),
        rows,
        {"exact_duplicate_rows"},
    )


def _trailer():
    rows = [("1", "Paid"), ("2", "Open"), ("", "")]
    return _sample("trailer", ("id", "status"), rows, {"empty_rows"})


def _ragged():
    return _sample(
        "ragged",
        ("id", "status"),
        [("1", "Paid"), ("2", "Open")],
        {"ragged_rows"},
        ragged=(("1", "Paid", "EXTRA"),),
    )


def _latin_cities():
    return _sample(
        "latin_cities",
        ("city", "amount"),
        [("café", "12,50"), ("lyon", "-")],
        {"sentinel_values"},
        delimiter=";",
        encoding="latin-1",
        must_contain=("café",),
    )


def _excel_amounts():
    rows = [(number, f"row-{number}") for number in range(1, 10)]
    rows.append(("42", "row-10"))
    return _sample(
        "excel_amounts",
        ("amount", "label"),
        rows,
        {"number_stored_as_text"},
        kind="xlsx",
        merged=True,
        extra_sheet=True,
    )


def _formulas():
    rows = [("=1+1", f"row-{index}") for index in range(3)]
    return _sample(
        "formulas",
        ("amount", "label"),
        rows,
        {"formula_value_unavailable"},
        kind="xlsx",
    )


def _skus():
    values = [f"SKU-{index}" for index in range(99)] + ["SKU-0"]
    return _sample(
        "skus",
        ("sku",),
        [(value,) for value in values],
        {"near_unique_duplicates"},
    )


_THEMES = (
    _identifiers,
    _emails,
    _mixed_dates,
    _ambiguous_dates,
    _epoch,
    _mixed_money,
    _broken_amount,
    _rare_sign,
    _outliers,
    _categories,
    _blank_column,
    _constant_country,
    _duplicate_orders,
    _trailer,
    _ragged,
    _latin_cities,
    _excel_amounts,
    _formulas,
    _skus,
)


def _sample(name, headers, rows, expected, **overrides):
    values = {
        "name": name,
        "headers": tuple(headers),
        "rows": tuple(tuple(row) for row in rows),
        "expected": frozenset(expected),
    }
    values.update(overrides)
    return Sample(**values)


def _chaos(seed, rng):
    excel = rng.randrange(2) == 0
    width = rng.randint(2, 6)
    height = rng.randint(8, 36)
    headers = _headers(rng, width)
    junk = rng.randrange(2) == 0
    encoding = "utf-8"
    if not excel and rng.random() < 0.25:
        encoding = rng.choice(("latin-1", "utf-8-sig"))
    rows = []
    for index in range(height):
        row = []
        for name in headers:
            if junk or rng.random() < 0.12:
                row.append(_junk_value(rng, encoding))
            else:
                row.append(_family_value(rng, name, index))
        rows.append(tuple(row))
    if rng.random() < 0.35:
        rows.append(rows[rng.randrange(height)])
    if rng.random() < 0.35:
        rows.append(tuple("" for _ in headers))
    ragged = ()
    if not excel and rng.random() < 0.4:
        base = tuple(_plain(value) for value in rows[0])
        ragged = (base[:-1] or ("",), base + ("EXTRA",))
    return Sample(
        name=f"chaos_{seed}",
        headers=headers,
        rows=tuple(rows),
        expected=frozenset(),
        kind="xlsx" if excel else "csv",
        delimiter=rng.choice(tuple(DELIMITER_LABELS)),
        encoding=encoding,
        ragged=tuple(tuple(item) for item in ragged),
        merged=excel and width >= 2 and rng.random() < 0.4,
        extra_sheet=excel and rng.random() < 0.5,
    )


def _headers(rng, width):
    picked = [rng.choice(NAME_POOL) for _ in range(width)]
    seen = {}
    names = []
    for name in picked:
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return tuple(names)


def _family_value(rng, name, index):
    tokens = set(name.replace("-", "_").casefold().split("_"))
    if "email" in tokens:
        if rng.random() < 0.2:
            return rng.choice(("broken", "bad @example.com", "a@b"))
        return f"user{index}@example.com"
    if "ts" in tokens or "timestamp" in tokens:
        if index == 0:
            return "0"
        return str(1_700_000_000 + index)
    if "date" in tokens or "at" in tokens:
        return f"2024-01-{(index % 27) + 1:02d}"
    if "id" in tokens or "uuid" in tokens or "guid" in tokens:
        if rng.random() < 0.08:
            return rng.choice(("", "NA"))
        return str(index + 1)
    if tokens & {"amount", "price", "qty", "balance", "score"}:
        if rng.random() < 0.15:
            return rng.choice(("12,50", "1,234.56", "abc", "-3"))
        return str((index % 17) + 1)
    return rng.choice(("Paid", "paid", "Open", "UK", "UK ", "NA", ""))


def _junk_value(rng, encoding):
    value = rng.choice(VALUE_POOL)
    if encoding == "latin-1":
        return _latin(value)
    return value


def _latin(value):
    text = _plain(value)
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        return "cafe"
    return text


def _write(directory, sample):
    path = directory / f"{sample.name}.{sample.kind}"
    if sample.kind == "xlsx":
        _write_xlsx(path, sample)
    else:
        _write_csv(path, sample)
    return path


def _write_csv(path, sample):
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=sample.delimiter, lineterminator="\n")
    writer.writerow(sample.headers)
    for row in sample.rows:
        writer.writerow([_plain(value) for value in row])
    for row in sample.ragged:
        writer.writerow(row)
    payload = buffer.getvalue().encode(sample.encoding)
    path.write_bytes(payload)


def _write_xlsx(path, sample):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Orders"
    for column, name in enumerate(sample.headers, start=1):
        sheet.cell(1, column, name)
    for row_number, row in enumerate(sample.rows, start=2):
        for column, value in enumerate(row, start=1):
            _put_cell(sheet.cell(row_number, column), value)
    if sample.merged and len(sample.headers) >= 2:
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
    if sample.extra_sheet:
        archive = book.create_sheet("Archive")
        archive["A1"] = "note"
        archive["A2"] = "kept"
    book.save(path)


def _put_cell(cell, value):
    if value is None or value == "":
        cell.value = None
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cell.value = value
        return
    cell.value = str(value)


def _assert_contract(sample, path, report_path, findings_path):
    report_name, findings_name = output_filenames(path)
    report = report_path.read_text(encoding="utf-8")
    findings = _read_findings(findings_path)
    headings = _heading_checks(report)

    assert report_path.name == report_name
    assert findings_path.name == findings_name
    assert findings_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in report_path.read_bytes()
    assert report.startswith("# Data quality audit\n")
    assert f"- File: `{path}`" in report
    assert f"- Rows: {len(sample.rows)}" in report
    assert f"- Columns: {len(sample.headers)}" in report
    assert report.index("## Findings") < report.index("## Column passport")
    assert report.index("## Column passport") < report.index("## Thresholds")
    assert report.index("### Error") < report.index("### Warning") < report.index("### Suggestion")
    for name, _value in THRESHOLDS:
        assert f"| {name} |" in report
    for text in sample.must_contain:
        assert text in report
    if sample.kind == "csv":
        assert f"- Delimiter: {DELIMITER_LABELS[sample.delimiter]}" in report
    else:
        assert "- Audited sheet: Orders" in report
        assert "- Delimiter: not applicable" in report
    if sample.merged:
        assert "merged cells" in report
    if sample.extra_sheet:
        assert "Archive" in report
    assert list(findings.columns) == FINDING_COLUMNS
    if findings.empty:
        assert headings == set()
        return
    assert set(findings["severity"]) <= {"error", "warning", "suggestion"}
    assert set(findings["check_id"]) <= KNOWN_CHECKS
    assert findings["message"].str.strip().str.endswith(".").all()
    assert findings["row_number"].map(int).ge(2).all()
    assert findings["row_number"].map(int).le(len(sample.rows) + len(sample.ragged) + 1).all()
    assert headings == set(findings["check_id"])
    for message in set(findings["message"]):
        assert message in report
    for (_check_id, _column), group in findings.groupby(["check_id", "column"], sort=False):
        assert group["severity"].nunique() == 1
        assert group["message"].nunique() == 1


def _heading_checks(report):
    found = set()
    for line in report.splitlines():
        if not line.startswith("#### "):
            continue
        found.add(line.removeprefix("#### ").split(" (", 1)[0])
    return found


def _read_findings(path):
    return pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)


def _plain(value):
    if value is None:
        return ""
    return str(value)


@pytest.mark.parametrize("seed", list(range(len(_THEMES))) + list(CHAOS_SEEDS))
def test_a_random_file_obeys_the_audit_contract(tmp_path, seed):
    sample = _build(seed)
    path = _write(tmp_path, sample)
    original = path.read_bytes()
    try:
        report_path, findings_path = audit_file(path, output_dir=tmp_path / "out")
    except LoadError as error:
        raise AssertionError(f"{path.name} (seed {seed}) was rejected: {error}") from error
    assert path.read_bytes() == original
    _assert_contract(sample, path, report_path, findings_path)


def test_random_themes_reach_every_check(tmp_path):
    seen = set()
    for seed in range(len(_THEMES)):
        sample = _build(seed)
        path = _write(tmp_path, sample)
        _report_path, findings_path = audit_file(path, output_dir=tmp_path / sample.name)
        found = set(_read_findings(findings_path)["check_id"])
        missing = sample.expected - found
        assert not missing, f"{sample.name} missed {sorted(missing)}"
        seen.update(found)
    assert seen == KNOWN_CHECKS
