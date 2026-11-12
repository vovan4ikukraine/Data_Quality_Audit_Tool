import pandas as pd
import pytest

from data_quality_auditor.loader import RawTable
from data_quality_auditor.models import ColumnKind, EpochUnit
from data_quality_auditor.profiler import profile_table


def table_from(columns, empty_rows=()):
    frame = pd.DataFrame(columns).astype(str)
    frame.index = range(2, len(frame) + 2)
    frame.index.name = "row_number"
    return RawTable(
        path="fixture.csv",
        frame=frame,
        cell_types=None,
        encoding="utf-8",
        encoding_is_fallback=False,
        delimiter=",",
        sheet=None,
        other_sheets=(),
        has_merged_cells=False,
        ragged_rows=(),
        empty_row_numbers=tuple(empty_rows),
    )


def passports(columns, empty_rows=()):
    return profile_table(table_from(columns, empty_rows))


def passport(name, values, empty_rows=()):
    found = passports({name: list(values)}, empty_rows)
    assert len(found) == 1
    return found[0]


def test_kind_follows_the_values_and_the_name():
    found = passports(
        {
            "amount": ["100", "12.5", "-3"],
            "userId": ["10", "20", "10"],
            "createdAt": ["2024-01-02", "2024-03-05", "2024-03-05"],
            "email": ["ada@example.com", "nope@example.com", "nope@example.com"],
        }
    )

    assert [item.profile.kind for item in found] == [
        ColumnKind.NUMERIC,
        ColumnKind.IDENTIFIER,
        ColumnKind.DATETIME,
        ColumnKind.EMAIL,
    ]


def test_plain_numbers_keep_a_shadow_series_and_stats():
    column = passport("amount", ["100", "12.5", "-3", "0"])

    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.profile.minimum == pytest.approx(-3)
    assert column.profile.maximum == pytest.approx(100)
    assert column.profile.median == pytest.approx(6.25)
    assert column.profile.zero_count == 1
    assert column.profile.negative_count == 1
    assert column.profile.frequent_values == ()
    assert column.profile.epoch_unit is None
    assert column.mixed_numeric_dialect is False
    assert column.numeric_values.tolist() == pytest.approx([100, 12.5, -3, 0])
    assert column.datetime_values is None


def test_european_decimals_are_parsed_with_a_dot():
    column = passport("amount", ["12,50", "1.234,56", "-3"])

    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.mixed_numeric_dialect is False
    assert column.profile.minimum == pytest.approx(-3)
    assert column.profile.median == pytest.approx(12.5)
    assert column.profile.maximum == pytest.approx(1234.56)
    assert column.profile.negative_count == 1
    assert column.numeric_values.tolist() == pytest.approx([12.5, 1234.56, -3])


def test_us_thousands_keep_the_plain_numbers_in_the_same_column():
    column = passport("amount", ["1,234", "1,234.56", "12.5"])

    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.mixed_numeric_dialect is False
    assert column.numeric_values.tolist() == pytest.approx([1234, 1234.56, 12.5])


def test_scientific_notation_stays_a_number():
    column = passport("amount", ["1.77E+12", "10"])

    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.numeric_values.iloc[0] == pytest.approx(1.77e12)


def test_spaces_are_removed_before_a_number_is_recognized():
    column = passport("amount", [" 100 ", "\u00a012,50", "1\u00a0234"])

    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.numeric_values.tolist() == pytest.approx([100, 12.5, 1234])


def test_three_european_and_three_us_values_stay_unparsed():
    column = passport(
        "amount",
        ["12,50", "12,50", "1.234,56", "1,234", "1,234.56", "2,000"],
    )

    assert column.mixed_numeric_dialect is True
    assert column.profile.kind is ColumnKind.TEXT
    assert column.numeric_values is None
    assert column.profile.minimum is None


def test_plain_numbers_beside_european_decimals_are_not_a_mixed_dialect():
    column = passport("amount", ["12,50", "12,50", "12,50", "100", "100", "100"])

    assert column.mixed_numeric_dialect is False
    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.numeric_values.tolist() == pytest.approx([12.5, 12.5, 12.5, 100, 100, 100])


def test_numeric_kind_needs_ninety_percent_of_the_remaining_values():
    assert passport("amount", ["10"] * 9 + ["abc"]).profile.kind is ColumnKind.NUMERIC
    assert passport("amount", ["10"] * 8 + ["abc", "abc"]).profile.kind is ColumnKind.TEXT


def test_blanks_do_not_count_against_the_numeric_majority():
    column = passport("amount", [""] * 9 + ["12.5"])

    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.profile.blank_share == pytest.approx(0.9)
    assert column.profile.sentinel_share == 0
    assert column.profile.minimum == pytest.approx(12.5)


def test_sentinels_are_counted_apart_from_blanks():
    column = passport("amount", ["", "NA", "N/A", "10", "20"])

    assert column.profile.blank_share == pytest.approx(0.2)
    assert column.profile.sentinel_share == pytest.approx(0.4)
    assert column.profile.distinct_count == 2
    assert column.profile.distinct_ratio == pytest.approx(1)
    assert pd.isna(column.numeric_values.loc[2])
    assert pd.isna(column.numeric_values.loc[3])
    assert pd.isna(column.numeric_values.loc[4])
    assert column.numeric_values.loc[5] == pytest.approx(10)
    assert column.numeric_values.loc[6] == pytest.approx(20)


def test_empty_rows_are_left_out_of_the_shares():
    column = passport("amount", ["", "NA", "10", "20"], empty_rows=(2,))

    assert column.profile.blank_share == 0
    assert column.profile.sentinel_share == pytest.approx(1 / 3)
    assert column.profile.kind is ColumnKind.NUMERIC
    assert list(column.numeric_values.index) == [2, 3, 4, 5]
    assert pd.isna(column.numeric_values.loc[2])


def test_identifier_wins_over_numeric_values():
    column = passport("userId", ["10", "20", "10"])

    assert column.profile.kind is ColumnKind.IDENTIFIER
    assert column.profile.distinct_count == 2
    assert column.profile.distinct_ratio == pytest.approx(2 / 3)
    assert column.profile.minimum is None
    assert column.numeric_values is None


def test_repeated_rule_id_stays_an_identifier():
    column = passport("rule_id", ["A", "A", "A", "B"])

    assert column.profile.kind is ColumnKind.IDENTIFIER
    assert column.profile.distinct_count == 2
    assert column.profile.distinct_ratio == pytest.approx(0.5)


def test_blank_identifier_stays_an_identifier():
    column = passport("userId", ["", "NA", " - "])

    assert column.profile.kind is ColumnKind.IDENTIFIER
    assert column.profile.blank_share == pytest.approx(1 / 3)
    assert column.profile.sentinel_share == pytest.approx(2 / 3)
    assert column.profile.distinct_count == 0


def test_email_token_sets_the_email_kind():
    column = passport("email", ["ada@example.com", "not-an-email"])

    assert column.profile.kind is ColumnKind.EMAIL
    assert column.profile.frequent_values == ()
    assert column.numeric_values is None


def test_iso_dates_record_the_format_and_the_bounds():
    column = passport("createdAt", ["2024-01-02", "2024-03-05"])

    assert column.profile.kind is ColumnKind.DATETIME
    assert column.profile.recognized_format == "YYYY-MM-DD"
    assert column.profile.datetime_minimum == "2024-01-02"
    assert column.profile.datetime_maximum == "2024-03-05"
    assert column.mixed_datetime_formats is False
    assert column.ambiguous_day_month is False
    assert column.datetime_values.loc[2].date().isoformat() == "2024-01-02"
    assert column.datetime_values.loc[3].date().isoformat() == "2024-03-05"


def test_dates_without_a_date_token_are_still_dates():
    column = passport("seen", ["02.01.2024", "05.03.2024"])

    assert column.profile.kind is ColumnKind.DATETIME
    assert column.profile.recognized_format == "DD.MM.YYYY"
    assert column.profile.datetime_minimum == "2024-01-02"
    assert column.profile.datetime_maximum == "2024-03-05"


def test_compact_dates_need_a_date_name():
    dated = passport("order_date", ["20240101", "20240202"])
    coded = passport("code", ["20240101", "20240202"])

    assert dated.profile.kind is ColumnKind.DATETIME
    assert dated.profile.recognized_format == "YYYYMMDD"
    assert dated.profile.datetime_minimum == "2024-01-01"
    assert dated.profile.datetime_maximum == "2024-02-02"
    assert coded.profile.kind is ColumnKind.NUMERIC
    assert coded.profile.minimum == pytest.approx(20240101)


def test_a_date_name_stays_datetime_when_the_values_do_not_parse():
    column = passport("createdAt", ["soon", "later"])

    assert column.profile.kind is ColumnKind.DATETIME
    assert column.profile.recognized_format is None
    assert column.datetime_values.isna().all()


def test_an_unambiguous_day_and_month_order_is_chosen():
    day_first = passport("when", ["13/01/2024", "05/06/2024"])
    month_first = passport("when", ["01/13/2024", "06/05/2024"])

    assert day_first.profile.recognized_format == "DD/MM/YYYY"
    assert day_first.ambiguous_day_month is False
    assert day_first.profile.datetime_minimum == "2024-01-13"
    assert day_first.profile.datetime_maximum == "2024-06-05"
    assert month_first.profile.recognized_format == "MM/DD/YYYY"
    assert month_first.profile.datetime_minimum == "2024-01-13"
    assert month_first.profile.datetime_maximum == "2024-06-05"


def test_both_day_and_month_orders_stay_unparsed():
    column = passport("when", ["05/06/2024", "07/08/2024"])

    assert column.profile.kind is ColumnKind.DATETIME
    assert column.ambiguous_day_month is True
    assert column.profile.recognized_format is None
    assert column.profile.datetime_minimum is None
    assert column.datetime_values.isna().all()
    assert column.ambiguous_rows.tolist() == [True, True]


def test_several_date_formats_are_flagged_and_still_bounded():
    column = passport("createdAt", ["2024-03-05", "02.01.2024"])

    assert column.mixed_datetime_formats is True
    assert column.profile.recognized_format is None
    assert column.profile.datetime_minimum == "2024-01-02"
    assert column.profile.datetime_maximum == "2024-03-05"
    assert column.datetime_values.loc[2].date().isoformat() == "2024-03-05"
    assert column.datetime_values.loc[3].date().isoformat() == "2024-01-02"


def test_an_iso_timestamp_keeps_the_clock_time():
    column = passport("createdAt", ["2024-03-05T15:30:00"])

    assert column.profile.recognized_format == "ISO-8601"
    assert column.profile.datetime_minimum == "2024-03-05T15:30:00"
    assert column.profile.datetime_maximum == "2024-03-05T15:30:00"


@pytest.mark.parametrize(
    ("raw", "unit"),
    [
        ("1700000000", EpochUnit.SECONDS),
        ("1700000000000", EpochUnit.MILLISECONDS),
        ("1700000000000000", EpochUnit.MICROSECONDS),
    ],
)
def test_epoch_magnitude_sets_the_unit(raw, unit):
    column = passport("event_ts", [raw, raw])

    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.profile.epoch_unit is unit
    assert column.datetime_values is None
    assert column.profile.recognized_format is None


def test_epoch_zero_stays_a_number():
    column = passport("ts", ["1700000000", "0"])

    assert column.profile.kind is ColumnKind.NUMERIC
    assert column.profile.epoch_unit is EpochUnit.SECONDS
    assert column.profile.zero_count == 1
    assert column.profile.minimum == pytest.approx(0)
    assert column.datetime_values is None


def test_short_text_lists_the_most_frequent_raw_values():
    column = passport("status", ["Paid", "Paid", "Paid", "Open", "Open", "UK "])

    assert column.profile.kind is ColumnKind.TEXT
    assert column.profile.frequent_values == (("Paid", 3), ("Open", 2), ("UK ", 1))


def test_frequent_values_stop_past_fifty_distinct_values():
    common = ["a"] * 6 + ["b"] * 5 + ["c"] * 4 + ["d"] * 3 + ["e"] * 2
    short = common + [f"n{i}" for i in range(45)]
    longer = short + ["n45"]

    assert passport("status", short).profile.frequent_values == (
        ("a", 6),
        ("b", 5),
        ("c", 4),
        ("d", 3),
        ("e", 2),
    )
    assert passport("status", longer).profile.distinct_count == 51
    assert passport("status", longer).profile.frequent_values == ()


def test_a_header_only_column_is_empty_text():
    found = profile_table(table_from({"amount": pd.Series(dtype=str)}))

    assert len(found) == 1
    column = found[0]
    assert column.profile.kind is ColumnKind.TEXT
    assert column.profile.blank_share == 0
    assert column.profile.sentinel_share == 0
    assert column.profile.distinct_count == 0
    assert column.profile.distinct_ratio == 0
    assert column.numeric_values is None
