from pathlib import Path

import pytest
from openpyxl import Workbook

from data_quality_auditor.checks import check_table
from data_quality_auditor.loader import load_file
from data_quality_auditor.models import Severity
from data_quality_auditor.profiler import profile_table

FIXTURES = Path(__file__).resolve().parent / "fixtures"
AFFECTED_COLUMNS = [
    "column",
    "check_id",
    "severity",
    "row_number",
    "raw_value",
    "message",
]


def audit(path, sheet=None):
    table = load_file(path, sheet)
    return table, check_table(table, profile_table(table))


def audit_text(directory, name, text, sheet=None):
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return audit(path, sheet)


def with_labels(column, values):
    lines = [f"{column},label"]
    for number, value in enumerate(values, start=1):
        lines.append(f"{value},r{number}")
    return "\n".join(lines) + "\n"


def one(result, check_id, column):
    matches = [
        item
        for item in result.findings
        if item.check_id == check_id and item.column == column
    ]
    assert len(matches) == 1
    return matches[0]


def pairs(result):
    return {(item.check_id, item.column) for item in result.findings}


def affected(result, check_id, column):
    rows = result.affected_rows
    return rows[(rows["check_id"] == check_id) & (rows["column"] == column)]


def assert_finding(
    item,
    *,
    severity,
    row_count,
    share,
    example,
    row_numbers,
    message,
):
    assert item.severity is severity
    assert item.row_count == row_count
    assert item.share == pytest.approx(share)
    assert item.example == example
    assert item.row_numbers == row_numbers
    assert item.message == message


def test_clean_file_has_no_findings():
    _table, result = audit(FIXTURES / "clean.csv")

    assert result.findings == ()
    assert list(result.affected_rows.columns) == AFFECTED_COLUMNS
    assert result.affected_rows.empty


def test_european_and_us_numbers_in_different_columns_are_clean():
    table, result = audit(FIXTURES / "number_dialects.csv")

    assert list(table.frame.columns) == ["eu_amount", "us_amount"]
    assert table.frame.loc[2, "eu_amount"] == "12,50"
    assert table.frame.loc[2, "us_amount"] == "1,234"
    assert result.findings == ()


def test_mixed_dialect_column_is_a_warning_and_lists_every_row():
    _table, result = audit(FIXTURES / "mixed_dialect.csv")
    item = one(result, "mixed_numeric_dialect", "amount")

    assert pairs(result) == {("mixed_numeric_dialect", "amount")}
    assert_finding(
        item,
        severity=Severity.WARNING,
        row_count=6,
        share=1,
        example="12,50",
        row_numbers=(2, 3, 4, 5, 6),
        message="This column mixes European and US number formats.",
    )
    rows = affected(result, "mixed_numeric_dialect", "amount")
    assert rows["row_number"].tolist() == [2, 3, 4, 5, 6, 7]
    assert rows["raw_value"].tolist()[-1] == "2,000"


def test_sentinels_whitespace_and_case_twins_are_separate_findings(tmp_path):
    text = with_labels("status", ["Paid", "paid", "UK", "UK ", "NA", " Open"])
    _table, result = audit_text(tmp_path, "categories.csv", text)

    assert pairs(result) == {
        ("category_case_collision", "status"),
        ("whitespace_category_collision", "status"),
        ("sentinel_values", "status"),
        ("leading_trailing_whitespace", "status"),
    }
    assert_finding(
        one(result, "category_case_collision", "status"),
        severity=Severity.WARNING,
        row_count=2,
        share=2 / 6,
        example="Paid",
        row_numbers=(2, 3),
        message="Some categories differ only by letter case.",
    )
    assert_finding(
        one(result, "whitespace_category_collision", "status"),
        severity=Severity.WARNING,
        row_count=2,
        share=2 / 6,
        example="UK",
        row_numbers=(4, 5),
        message="Some values match after trimming edge whitespace.",
    )
    assert affected(result, "whitespace_category_collision", "status")[
        "raw_value"
    ].tolist() == ["UK", "UK "]
    assert_finding(
        one(result, "sentinel_values", "status"),
        severity=Severity.WARNING,
        row_count=1,
        share=1 / 6,
        example="NA",
        row_numbers=(6,),
        message="This column uses placeholders such as NA or '-'.",
    )
    assert_finding(
        one(result, "leading_trailing_whitespace", "status"),
        severity=Severity.SUGGESTION,
        row_count=1,
        share=1 / 6,
        example=" Open",
        row_numbers=(7,),
        message="Some values have leading or trailing whitespace.",
    )


def test_near_unique_id_duplicates_and_a_repeated_rule_id(tmp_path):
    lines = ["id,rule_id", "1,R1", "1,R2"]
    lines.extend(f"{number},R{number % 5}" for number in range(2, 50))
    _table, result = audit_text(tmp_path, "identifiers.csv", "\n".join(lines) + "\n")
    item = one(result, "identifier_duplicates", "id")

    assert "rule_id" not in {finding.column for finding in result.findings}
    assert_finding(
        item,
        severity=Severity.ERROR,
        row_count=2,
        share=2 / 50,
        example="1",
        row_numbers=(2, 3),
        message="An identifier value is repeated in a near-unique column.",
    )


def test_id_duplicates_below_the_near_unique_ratio_stay_quiet(tmp_path):
    values = ["1", "1", *[str(number) for number in range(2, 49)]]
    _table, result = audit_text(tmp_path, "ids.csv", with_labels("id", values))

    assert result.findings == ()


def test_exact_duplicate_rows_are_a_warning():
    _table, result = audit(FIXTURES / "duplicate_rows.csv")
    item = one(result, "exact_duplicate_rows", "")

    assert pairs(result) == {("exact_duplicate_rows", "")}
    assert_finding(
        item,
        severity=Severity.WARNING,
        row_count=2,
        share=2 / 3,
        example="1 | Paid",
        row_numbers=(2, 3),
        message="These data rows are exact copies of each other.",
    )


def test_broken_email_values():
    _table, result = audit(FIXTURES / "emails.csv")
    item = one(result, "email_format", "email")

    assert pairs(result) == {("email_format", "email")}
    assert_finding(
        item,
        severity=Severity.ERROR,
        row_count=4,
        share=4 / 5,
        example="not-an-email",
        row_numbers=(3, 4, 5, 6),
        message="A value does not look like an email address.",
    )
    assert affected(result, "email_format", "email")["raw_value"].tolist() == [
        "not-an-email",
        "bad @example.com",
        "two@@example.com",
        "nodot@localhost",
    ]


def test_a_finding_keeps_only_five_row_numbers(tmp_path):
    text = with_labels("email", ["ada@example.com", *["broken"] * 6])
    _table, result = audit_text(tmp_path, "emails.csv", text)
    item = one(result, "email_format", "email")

    assert item.row_count == 6
    assert item.row_numbers == (3, 4, 5, 6, 7)
    assert affected(result, "email_format", "email")["row_number"].tolist() == [
        3,
        4,
        5,
        6,
        7,
        8,
    ]


def test_two_date_formats_are_a_warning():
    _table, result = audit(FIXTURES / "mixed_dates.csv")
    item = one(result, "mixed_datetime_formats", "created_at")

    assert pairs(result) == {("mixed_datetime_formats", "created_at")}
    assert_finding(
        item,
        severity=Severity.WARNING,
        row_count=2,
        share=1,
        example="2024-03-05",
        row_numbers=(2, 3),
        message="This column mixes more than one datetime format.",
    )


def test_an_unparsed_date_is_an_error(tmp_path):
    lines = ["created_at", *[f"2024-01-{day:02d}" for day in range(1, 10)], "soon"]
    _table, result = audit_text(tmp_path, "dates.csv", "\n".join(lines) + "\n")
    item = one(result, "datetime_parse_failure", "created_at")

    assert pairs(result) == {("datetime_parse_failure", "created_at")}
    assert_finding(
        item,
        severity=Severity.ERROR,
        row_count=1,
        share=0.1,
        example="soon",
        row_numbers=(11,),
        message="A value in a datetime column could not be parsed as a date.",
    )


def test_ambiguous_day_and_month_is_not_a_parse_failure():
    _table, result = audit(FIXTURES / "ambiguous_dates.csv")
    item = one(result, "ambiguous_day_month", "event_date")

    assert pairs(result) == {("ambiguous_day_month", "event_date")}
    assert_finding(
        item,
        severity=Severity.WARNING,
        row_count=2,
        share=1,
        example="05/06/2024",
        row_numbers=(2, 3),
        message="A date can be read as either day-first or month-first.",
    )


def test_epoch_zero_is_a_warning():
    _table, result = audit(FIXTURES / "epoch.csv")
    item = one(result, "epoch_zero", "event_ts")

    assert pairs(result) == {("epoch_zero", "event_ts")}
    assert_finding(
        item,
        severity=Severity.WARNING,
        row_count=1,
        share=1 / 3,
        example="0",
        row_numbers=(3,),
        message="An epoch timestamp is zero.",
    )


def test_epoch_zero_is_not_also_an_outlier(tmp_path):
    lines = ["event_ts"]
    lines.extend(str(1700000000 + offset) for offset in range(30))
    lines.extend(["0", "1700100000"])
    _table, result = audit_text(tmp_path, "epoch.csv", "\n".join(lines) + "\n")

    assert_finding(
        one(result, "epoch_zero", "event_ts"),
        severity=Severity.WARNING,
        row_count=1,
        share=1 / 32,
        example="0",
        row_numbers=(32,),
        message="An epoch timestamp is zero.",
    )
    assert_finding(
        one(result, "numeric_outliers", "event_ts"),
        severity=Severity.SUGGESTION,
        row_count=1,
        share=1 / 32,
        example="1700100000",
        row_numbers=(33,),
        message="A value falls outside the 1.5 IQR fence.",
    )


def test_number_stored_as_text_and_the_other_sheet(tmp_path):
    path = tmp_path / "book.xlsx"
    book = Workbook()
    orders = book.active
    orders.title = "Orders"
    archive = book.create_sheet("Archive")
    orders["A1"] = "amount"
    for offset, value in enumerate([12.5, "42", 3, 4, 5, 6, 7, 8, 9, 10], start=2):
        orders.cell(offset, 1, value)
    archive["A1"] = "id"
    archive["A2"] = "9"
    book.save(path)

    _orders, result = audit(path)
    item = one(result, "number_stored_as_text", "amount")
    assert pairs(result) == {("number_stored_as_text", "amount")}
    assert_finding(
        item,
        severity=Severity.ERROR,
        row_count=1,
        share=0.1,
        example="42",
        row_numbers=(3,),
        message="A number is stored as text.",
    )

    _archive, other = audit(path, sheet="Archive")
    assert other.findings == ()


def test_semicolon_file_that_is_not_utf8(tmp_path):
    path = tmp_path / "latin.csv"
    path.write_bytes("city;amount\ncafé;12,50\nlyon;-\n".encode("latin-1"))
    table, result = audit(path)
    item = one(result, "sentinel_values", "amount")

    assert table.frame.loc[2, "city"] == "café"
    assert table.frame.loc[2, "amount"] == "12,50"
    assert pairs(result) == {("sentinel_values", "amount")}
    assert_finding(
        item,
        severity=Severity.WARNING,
        row_count=1,
        share=0.5,
        example="-",
        row_numbers=(3,),
        message="This column uses placeholders such as NA or '-'.",
    )


def test_dirty_file_names_each_structural_and_cell_finding():
    _table, result = audit(FIXTURES / "dirty.csv")

    assert pairs(result) == {
        ("ragged_rows", ""),
        ("empty_rows", ""),
        ("identifier_missing", "id"),
        ("numeric_parse_failure", "amount"),
        ("email_format", "email"),
        ("sentinel_values", "status"),
    }
    assert_finding(
        one(result, "ragged_rows", ""),
        severity=Severity.ERROR,
        row_count=1,
        share=1 / 13,
        example="1,10,ada@example.com,Paid,EXTRA",
        row_numbers=(14,),
        message="A row has a different field count than the header.",
    )
    assert_finding(
        one(result, "empty_rows", ""),
        severity=Severity.SUGGESTION,
        row_count=1,
        share=1 / 13,
        example=" |  |  | ",
        row_numbers=(13,),
        message="A row is empty or contains only placeholders.",
    )
    assert_finding(
        one(result, "identifier_missing", "id"),
        severity=Severity.ERROR,
        row_count=1,
        share=1 / 11,
        example="",
        row_numbers=(12,),
        message="An identifier is blank or a placeholder.",
    )
    assert_finding(
        one(result, "numeric_parse_failure", "amount"),
        severity=Severity.ERROR,
        row_count=1,
        share=1 / 11,
        example="abc",
        row_numbers=(11,),
        message="A value in a numeric column could not be parsed as a number.",
    )
    assert_finding(
        one(result, "email_format", "email"),
        severity=Severity.ERROR,
        row_count=1,
        share=1 / 11,
        example="broken",
        row_numbers=(11,),
        message="A value does not look like an email address.",
    )
    assert_finding(
        one(result, "sentinel_values", "status"),
        severity=Severity.WARNING,
        row_count=1,
        share=1 / 11,
        example="NA",
        row_numbers=(12,),
        message="This column uses placeholders such as NA or '-'.",
    )


def test_a_blank_or_sentinel_identifier_is_one_error(tmp_path):
    _table, result = audit_text(tmp_path, "ids.csv", with_labels("userId", ["1", "NA", ""]))
    item = one(result, "identifier_missing", "userId")

    assert pairs(result) == {("identifier_missing", "userId")}
    assert_finding(
        item,
        severity=Severity.ERROR,
        row_count=2,
        share=2 / 3,
        example="NA",
        row_numbers=(3, 4),
        message="An identifier is blank or a placeholder.",
    )


def test_a_cell_is_explained_once(tmp_path):
    text = with_labels("amount", ["10"] * 9 + ["", "NA", " abc "])
    _table, result = audit_text(tmp_path, "amount.csv", text)

    assert pairs(result) == {
        ("missing_values", "amount"),
        ("sentinel_values", "amount"),
        ("leading_trailing_whitespace", "amount"),
    }
    assert one(result, "missing_values", "amount").severity is Severity.WARNING
    assert one(result, "missing_values", "amount").example == ""
    assert one(result, "sentinel_values", "amount").example == "NA"
    assert one(result, "leading_trailing_whitespace", "amount").example == " abc "


def test_missing_values_change_severity_at_five_percent(tmp_path):
    warning_rows = with_labels("notes", ["", *["a", "b"] * 9, "a"])
    suggestion_rows = with_labels("notes", ["", *["a", "b"] * 10])
    _table, warning = audit_text(tmp_path, "warning.csv", warning_rows)
    _table, suggestion = audit_text(tmp_path, "suggestion.csv", suggestion_rows)

    assert_finding(
        one(warning, "missing_values", "notes"),
        severity=Severity.WARNING,
        row_count=1,
        share=0.05,
        example="",
        row_numbers=(2,),
        message="This column has blank cells.",
    )
    assert_finding(
        one(suggestion, "missing_values", "notes"),
        severity=Severity.SUGGESTION,
        row_count=1,
        share=1 / 21,
        example="",
        row_numbers=(2,),
        message="This column has blank cells.",
    )


def test_all_null_column_replaces_the_sentinel_finding(tmp_path):
    _table, result = audit_text(tmp_path, "notes.csv", with_labels("notes", ["NA", "-", " "]))
    item = one(result, "all_null_column", "notes")

    assert pairs(result) == {("all_null_column", "notes")}
    assert_finding(
        item,
        severity=Severity.WARNING,
        row_count=3,
        share=1,
        example="NA",
        row_numbers=(2, 3, 4),
        message="This column has no substantive value.",
    )


def test_rare_negatives_need_both_gates(tmp_path):
    rare = with_labels("amount", ["-3", *["10"] * 20])
    at_the_gate = with_labels("amount", ["-3", *["10"] * 19])
    signed = with_labels("amount", ["-3"] * 5 + ["10"] * 5)
    _table, warning = audit_text(tmp_path, "rare.csv", rare)
    _table, boundary = audit_text(tmp_path, "boundary.csv", at_the_gate)
    _table, measure = audit_text(tmp_path, "signed.csv", signed)

    assert_finding(
        one(warning, "rare_negative_values", "amount"),
        severity=Severity.WARNING,
        row_count=1,
        share=1 / 21,
        example="-3",
        row_numbers=(2,),
        message="A few values are negative in an otherwise non-negative column.",
    )
    assert boundary.findings == ()
    assert measure.findings == ()


def test_numeric_outliers_follow_the_fence_and_the_exclusions(tmp_path):
    flagged = [str(number) for number in range(1, 41)] + ["100"]
    short = [str(number) for number in range(1, 29)] + ["100"]
    coarse = [str(number % 10) for number in range(40)]
    _table, amounts = audit_text(tmp_path, "amounts.csv", with_labels("amount", flagged))
    _table, few = audit_text(tmp_path, "few.csv", with_labels("amount", short))
    _table, limited = audit_text(tmp_path, "limited.csv", with_labels("amount", coarse))
    _table, identifiers = audit_text(tmp_path, "ids.csv", "userId\n" + "\n".join(flagged) + "\n")

    assert_finding(
        one(amounts, "numeric_outliers", "amount"),
        severity=Severity.SUGGESTION,
        row_count=1,
        share=1 / 41,
        example="100",
        row_numbers=(42,),
        message="A value falls outside the 1.5 IQR fence.",
    )
    assert few.findings == ()
    assert limited.findings == ()
    assert identifiers.findings == ()


def test_case_collision_stops_past_fifty_distinct_values(tmp_path):
    short = "\n".join(["Paid", "paid", *[f"v{number}" for number in range(48)]])
    longer = "\n".join(["Paid", "paid", *[f"v{number}" for number in range(49)]])
    _table, collision = audit_text(tmp_path, "short.csv", f"status\n{short}\n")
    _table, quiet = audit_text(tmp_path, "long.csv", f"status\n{longer}\n")

    assert one(collision, "category_case_collision", "status").row_numbers == (2, 3)
    assert quiet.findings == ()


def test_a_near_unique_text_column_warns_about_duplicates(tmp_path):
    values = ["A", "A", *[f"c{number}" for number in range(2, 50)]]
    _table, result = audit_text(tmp_path, "codes.csv", with_labels("code", values))
    item = one(result, "near_unique_duplicates", "code")

    assert pairs(result) == {("near_unique_duplicates", "code")}
    assert_finding(
        item,
        severity=Severity.WARNING,
        row_count=2,
        share=2 / 50,
        example="A",
        row_numbers=(2, 3),
        message="A value is repeated in a near-unique column.",
    )


def test_constant_column_starts_at_twenty_rows(tmp_path):
    _table, quiet = audit_text(tmp_path, "short.csv", with_labels("status", ["Paid"] * 19))
    _table, result = audit_text(tmp_path, "long.csv", with_labels("status", ["Paid"] * 20))
    item = one(result, "constant_column", "status")

    assert quiet.findings == ()
    assert_finding(
        item,
        severity=Severity.SUGGESTION,
        row_count=20,
        share=1,
        example="Paid",
        row_numbers=(2, 3, 4, 5, 6),
        message="This column has a single distinct value.",
    )
    assert len(affected(result, "constant_column", "status")) == 20


def test_passports_must_match_the_table():
    table, _result = audit(FIXTURES / "clean.csv")
    columns = profile_table(table)

    with pytest.raises(ValueError, match="Each column needs a passport"):
        check_table(table, columns[:1])
    with pytest.raises(ValueError, match="Passport order does not match the table"):
        check_table(table, tuple(reversed(columns)))
