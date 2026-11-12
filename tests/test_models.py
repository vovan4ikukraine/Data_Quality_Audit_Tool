import pytest

from data_quality_auditor.models import (
    ColumnKind,
    ColumnProfile,
    EpochUnit,
    Finding,
    Severity,
)


def profile(**overrides):
    values = {
        "name": "amount",
        "kind": ColumnKind.NUMERIC,
        "blank_share": 0.0,
        "sentinel_share": 0.0,
        "distinct_count": 1,
        "distinct_ratio": 1.0,
    }
    values.update(overrides)
    return ColumnProfile(**values)


def finding(**overrides):
    values = {
        "check_id": "ragged_rows",
        "severity": Severity.ERROR,
        "column": "",
        "row_count": 1,
        "share": 0.5,
        "example": "a,b,c",
        "row_numbers": (3,),
        "message": "A row has a different field count.",
    }
    values.update(overrides)
    return Finding(**values)


def test_profile_accepts_string_labels_and_freezes_frequent_values():
    column = profile(
        kind="numeric",
        epoch_unit="seconds",
        frequent_values=[("uk", 2)],
        minimum=1,
        maximum=1,
        zero_count=0,
        negative_count=0,
    )

    assert column.kind is ColumnKind.NUMERIC
    assert column.epoch_unit is EpochUnit.SECONDS
    assert column.frequent_values == (("uk", 2),)


def test_profile_accepts_shares_that_sum_to_one():
    column = profile(blank_share=0.25, sentinel_share=0.75, distinct_count=0, distinct_ratio=0)
    assert column.blank_share + column.sentinel_share == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "measurement"},
        {"blank_share": -0.01},
        {"blank_share": 1.01},
        {"sentinel_share": -0.01},
        {"sentinel_share": 1.01},
        {"distinct_ratio": -0.01},
        {"distinct_ratio": 1.01},
        {"blank_share": 0.6, "sentinel_share": 0.6},
        {"distinct_count": -1},
        {"minimum": 5, "maximum": 1},
        {"zero_count": -1},
        {"negative_count": -1},
        {"frequent_values": (("uk", -1),)},
        {"epoch_unit": "days"},
    ],
)
def test_profile_rejects_invalid_values(overrides):
    with pytest.raises(ValueError):
        profile(**overrides)


def test_finding_accepts_a_dataset_level_row_list():
    item = finding(
        severity="suggestion",
        column="",
        row_count=5,
        share=0,
        row_numbers=[2, 3, 4, 5, 6],
        message="Five rows are blank.",
    )

    assert item.severity is Severity.SUGGESTION
    assert item.column == ""
    assert item.row_numbers == (2, 3, 4, 5, 6)
    assert item.share == 0


def test_finding_accepts_the_full_share():
    assert finding(share=1, row_count=2, row_numbers=(2, 3)).share == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"check_id": ""},
        {"severity": "critical"},
        {"message": ""},
        {"message": "   "},
        {"row_count": -1},
        {"share": -0.01},
        {"share": 1.01},
        {"row_numbers": (1, 2, 3, 4, 5, 6)},
        {"row_numbers": (2, 2)},
        {"row_numbers": (0,)},
    ],
)
def test_finding_rejects_invalid_values(overrides):
    with pytest.raises(ValueError):
        finding(**overrides)
