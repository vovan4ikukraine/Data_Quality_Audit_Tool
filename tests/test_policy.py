import pandas as pd
import pytest

from data_quality_auditor.models import Finding, Severity
from data_quality_auditor.policy import THRESHOLDS, apply_policy, missing_severity

COLUMNS = ["column", "check_id", "severity", "row_number", "raw_value", "message"]


def finding(**overrides):
    values = {
        "check_id": "missing_values",
        "severity": Severity.SUGGESTION,
        "column": "notes",
        "row_count": 1,
        "share": 0.01,
        "example": "",
        "row_numbers": (2,),
        "message": "This column has blank cells.",
    }
    values.update(overrides)
    return Finding(**values)


def affected(*rows):
    return pd.DataFrame(rows, columns=COLUMNS)


def test_thresholds_match_the_specification():
    assert THRESHOLDS == (
        ("Numeric or date majority", 0.90),
        ("Near-unique ratio", 0.98),
        ("Missing warning", 0.05),
        ("Non-negative share", 0.95),
        ("Rare-negative share", 0.05),
        ("Category cardinality", 50),
        ("Outlier minimum", 30),
        ("Outlier fence", 1.5),
        ("Outlier distinct limit", 10),
        ("Constant minimum", 20),
        ("Example rows", 5),
        ("Mixed-dialect count", 3),
    )


@pytest.mark.parametrize("share", [0, 0.01, 1 / 21])
def test_missing_values_below_five_percent_are_a_suggestion(share):
    assert missing_severity(share) is Severity.SUGGESTION


@pytest.mark.parametrize("share", [0.05, 0.5, 1])
def test_missing_values_at_five_percent_or_more_are_a_warning(share):
    assert missing_severity(share) is Severity.WARNING


def test_policy_raises_and_lowers_only_missing_values():
    low = finding(column="notes", share=0.01, severity=Severity.WARNING)
    high = finding(column="city", share=0.05, severity=Severity.SUGGESTION)
    email = finding(
        check_id="email_format",
        severity=Severity.ERROR,
        column="email",
        share=0.5,
        example="broken",
        message="A value does not look like an email address.",
    )
    empty = finding(
        check_id="empty_rows",
        severity=Severity.SUGGESTION,
        column="",
        share=0.5,
        example="",
        message="A row is empty or contains only placeholders.",
    )

    adjusted, _rows = apply_policy((low, high, email, empty), affected())

    assert adjusted[0].severity is Severity.SUGGESTION
    assert adjusted[1].severity is Severity.WARNING
    assert adjusted[2] is email
    assert adjusted[3] is empty
    assert adjusted[0] is not low
    assert adjusted[0].column == "notes"
    assert adjusted[0].share == pytest.approx(0.01)
    assert adjusted[0].message == low.message
    assert low.severity is Severity.WARNING


def test_a_missing_finding_keeps_its_object_when_the_severity_already_matches():
    low = finding(share=0.01, severity=Severity.SUGGESTION)
    high = finding(column="city", share=0.5, severity=Severity.WARNING)

    adjusted, _rows = apply_policy((low, high), affected())

    assert adjusted == (low, high)
    assert adjusted[0] is low
    assert adjusted[1] is high


def test_affected_rows_follow_the_final_severity():
    low = finding(column="notes", share=0.01, severity=Severity.WARNING)
    high = finding(column="city", share=0.05, severity=Severity.SUGGESTION)
    rows = affected(
        {
            "column": "notes",
            "check_id": "missing_values",
            "severity": "warning",
            "row_number": 2,
            "raw_value": "",
            "message": low.message,
        },
        {
            "column": "notes",
            "check_id": "missing_values",
            "severity": "warning",
            "row_number": 4,
            "raw_value": "",
            "message": low.message,
        },
        {
            "column": "city",
            "check_id": "missing_values",
            "severity": "suggestion",
            "row_number": 3,
            "raw_value": "",
            "message": high.message,
        },
        {
            "column": "email",
            "check_id": "email_format",
            "severity": "error",
            "row_number": 3,
            "raw_value": "broken",
            "message": "A value does not look like an email address.",
        },
    )
    original = rows.copy()

    _findings, matched = apply_policy((low, high), rows)

    assert rows["severity"].tolist() == original["severity"].tolist()
    assert matched["severity"].tolist() == ["suggestion", "suggestion", "warning", "error"]
    assert matched["row_number"].tolist() == [2, 4, 3, 3]
    assert matched["raw_value"].tolist() == ["", "", "", "broken"]


def test_an_empty_affected_table_stays_empty():
    rows = affected()
    low = finding(share=0.2, severity=Severity.SUGGESTION)

    adjusted, matched = apply_policy((low,), rows)

    assert adjusted[0].severity is Severity.WARNING
    assert matched is rows
    assert matched.empty
