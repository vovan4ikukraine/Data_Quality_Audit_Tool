from dataclasses import dataclass

import pandas as pd

from data_quality_auditor.loader import SENTINELS, RawTable
from data_quality_auditor.models import ColumnKind, Finding, Severity
from data_quality_auditor.patterns import is_identifier_name
from data_quality_auditor.profiler import ColumnPassport

NEAR_UNIQUE_RATIO = 0.98
MISSING_WARNING_SHARE = 0.05
NON_NEGATIVE_SHARE = 0.95
RARE_NEGATIVE_SHARE = 0.05
CATEGORY_CARDINALITY = 50
OUTLIER_MINIMUM = 30
OUTLIER_FENCE = 1.5
OUTLIER_DISTINCT_LIMIT = 10
CONSTANT_MINIMUM = 20
EXAMPLE_ROW_LIMIT = 5

_AFFECTED_COLUMNS = (
    "column",
    "check_id",
    "severity",
    "row_number",
    "raw_value",
    "message",
)
_ROW_JOIN = " | "
_TEXT_NUMBER_TYPES = frozenset({"s", "inlineStr"})


@dataclass(frozen=True)
class CheckResult:
    findings: tuple[Finding, ...]
    affected_rows: pd.DataFrame


@dataclass
class _Column:
    name: str
    passport: ColumnPassport
    values: pd.Series
    blank: pd.Series
    sentinel: pd.Series
    edge: pd.Series
    population: int
    cell_types: pd.Series | None
    numbers: pd.Series | None
    dates: pd.Series | None
    ambiguous: pd.Series | None


def check_table(table: RawTable, columns: tuple[ColumnPassport, ...]) -> CheckResult:
    _require_alignment(table, columns)
    hits: list[tuple[Finding, pd.DataFrame]] = []
    population = len(table.frame) + len(table.ragged_rows)
    _collect(hits, _ragged_rows(table, population))
    _collect(hits, _empty_rows(table, population))
    kept = table.frame.drop(index=list(table.empty_row_numbers), errors="ignore")
    _collect(hits, _exact_duplicate_rows(kept))
    if not kept.empty:
        for name, passport in zip(table.frame.columns, columns, strict=True):
            for hit in _column_hits(table, kept, name, passport):
                _collect(hits, hit)
    return _result(hits)


def _require_alignment(table: RawTable, columns: tuple[ColumnPassport, ...]) -> None:
    names = [str(name) for name in table.frame.columns]
    if len(columns) != len(names):
        raise ValueError("Each column needs a passport")
    for name, column in zip(names, columns, strict=True):
        if column.profile.name != name:
            raise ValueError("Passport order does not match the table")


def _column_hits(
    table: RawTable, kept: pd.DataFrame, name: object, passport: ColumnPassport
) -> list[tuple[Finding, pd.DataFrame]]:
    column = _view(table, kept, name, passport)
    hits: list[tuple[Finding, pd.DataFrame]] = []
    hits.extend(_absence_hits(column))
    hits.extend(_whitespace_hits(column))
    _collect(hits, _case_collision(column))
    _collect(hits, _number_stored_as_text(column))
    _collect(hits, _mixed_numeric_dialect(column))
    _collect(hits, _numeric_parse_failure(column))
    _collect(hits, _rare_negatives(column))
    _collect(hits, _epoch_zero(column))
    _collect(hits, _numeric_outliers(column))
    _collect(hits, _datetime_parse_failure(column))
    _collect(hits, _mixed_datetime_formats(column))
    _collect(hits, _ambiguous_day_month(column))
    _collect(hits, _email_format(column))
    _collect(hits, _duplicate_values(column))
    _collect(hits, _constant_column(column))
    return hits


def _view(
    table: RawTable, kept: pd.DataFrame, name: object, passport: ColumnPassport
) -> _Column:
    values = kept[name].fillna("").astype(str)
    blank, sentinel = _blank_and_sentinel(values)
    substantive = ~(blank | sentinel)
    index = values.index
    ambiguous = _align(passport.ambiguous_rows, index)
    if ambiguous is not None:
        ambiguous = ambiguous.fillna(False).astype(bool)
    cell_types = None
    if table.cell_types is not None:
        cell_types = table.cell_types.loc[index, name]
    return _Column(
        name=passport.profile.name,
        passport=passport,
        values=values,
        blank=blank,
        sentinel=sentinel,
        edge=values.ne(values.str.strip()) & substantive,
        population=len(values),
        cell_types=cell_types,
        numbers=_align(passport.numeric_values, index),
        dates=_align(passport.datetime_values, index),
        ambiguous=ambiguous,
    )


def _absence_hits(column: _Column) -> list[tuple[Finding, pd.DataFrame]]:
    profile = column.passport.profile
    if profile.kind is ColumnKind.IDENTIFIER:
        return _only(
            _hit(
                "identifier_missing",
                Severity.ERROR,
                column.name,
                column.blank | column.sentinel,
                column.population,
                column.values,
                "An identifier is blank or a placeholder.",
            )
        )
    if profile.distinct_count == 0:
        return _only(
            _hit(
                "all_null_column",
                Severity.WARNING,
                column.name,
                _true_mask(column),
                column.population,
                column.values,
                "This column has no substantive value.",
            )
        )
    hits = []
    blank_count = int(column.blank.sum())
    if blank_count:
        severity = (
            Severity.WARNING
            if blank_count / column.population >= MISSING_WARNING_SHARE
            else Severity.SUGGESTION
        )
        _collect(
            hits,
            _hit(
                "missing_values",
                severity,
                column.name,
                column.blank,
                column.population,
                column.values,
                "This column has blank cells.",
            ),
        )
    _collect(
        hits,
        _hit(
            "sentinel_values",
            Severity.WARNING,
            column.name,
            column.sentinel,
            column.population,
            column.values,
            "This column uses placeholders such as NA or '-'.",
        ),
    )
    return hits


def _whitespace_hits(column: _Column) -> list[tuple[Finding, pd.DataFrame]]:
    collision = _trim_collision(column.values, ~(column.blank | column.sentinel))
    return _only(
        _hit(
            "whitespace_category_collision",
            Severity.WARNING,
            column.name,
            collision,
            column.population,
            column.values,
            "Some values match after trimming edge whitespace.",
        ),
        _hit(
            "leading_trailing_whitespace",
            Severity.SUGGESTION,
            column.name,
            column.edge & ~collision,
            column.population,
            column.values,
            "Some values have leading or trailing whitespace.",
        ),
    )


def _case_collision(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    profile = column.passport.profile
    if not 0 < profile.distinct_count <= CATEGORY_CARDINALITY:
        return None
    substantive = ~(column.blank | column.sentinel)
    raw = column.values.loc[substantive]
    if raw.empty:
        return None
    stripped = raw.str.strip()
    folded = stripped.str.casefold()
    variety = stripped.groupby(folded).nunique()
    mask = folded.map(variety).gt(1).reindex(column.values.index, fill_value=False)
    return _hit(
        "category_case_collision",
        Severity.WARNING,
        column.name,
        mask,
        column.population,
        column.values,
        "Some categories differ only by letter case.",
    )


def _number_stored_as_text(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if (
        column.cell_types is None
        or column.numbers is None
        or column.passport.profile.kind is not ColumnKind.NUMERIC
    ):
        return None
    mask = column.cell_types.isin(_TEXT_NUMBER_TYPES) & column.numbers.notna()
    return _hit(
        "number_stored_as_text",
        Severity.ERROR,
        column.name,
        mask,
        column.population,
        column.values,
        "A number is stored as text.",
    )


def _mixed_numeric_dialect(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if not column.passport.mixed_numeric_dialect:
        return None
    return _hit(
        "mixed_numeric_dialect",
        Severity.WARNING,
        column.name,
        ~(column.blank | column.sentinel),
        column.population,
        column.values,
        "This column mixes European and US number formats.",
    )


def _numeric_parse_failure(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if column.passport.mixed_numeric_dialect or column.numbers is None:
        return None
    if column.passport.profile.kind is not ColumnKind.NUMERIC:
        return None
    return _hit(
        "numeric_parse_failure",
        Severity.ERROR,
        column.name,
        _unexplained(column) & column.numbers.isna(),
        column.population,
        column.values,
        "A value in a numeric column could not be parsed as a number.",
    )


def _rare_negatives(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if column.numbers is None:
        return None
    present = column.numbers.dropna()
    total = len(present)
    if total == 0:
        return None
    negative = present.lt(0)
    count = int(negative.sum())
    if count == 0:
        return None
    negative_share = count / total
    if (total - count) / total < NON_NEGATIVE_SHARE or negative_share >= RARE_NEGATIVE_SHARE:
        return None
    return _hit(
        "rare_negative_values",
        Severity.WARNING,
        column.name,
        negative.reindex(column.values.index, fill_value=False),
        column.population,
        column.values,
        "A few values are negative in an otherwise non-negative column.",
    )


def _epoch_zero(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if column.numbers is None or column.passport.profile.epoch_unit is None:
        return None
    return _hit(
        "epoch_zero",
        Severity.WARNING,
        column.name,
        column.numbers.eq(0).fillna(False),
        column.population,
        column.values,
        "An epoch timestamp is zero.",
    )


def _numeric_outliers(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if column.numbers is None or is_identifier_name(column.name):
        return None
    present = column.numbers.dropna()
    if len(present) < OUTLIER_MINIMUM or present.nunique() <= OUTLIER_DISTINCT_LIMIT:
        return None
    q1 = float(present.quantile(0.25))
    q3 = float(present.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0:
        return None
    low = q1 - OUTLIER_FENCE * iqr
    high = q3 + OUTLIER_FENCE * iqr
    outside = present.lt(low) | present.gt(high)
    if column.passport.profile.epoch_unit is not None:
        outside = outside & present.ne(0)
    return _hit(
        "numeric_outliers",
        Severity.SUGGESTION,
        column.name,
        outside.reindex(column.values.index, fill_value=False),
        column.population,
        column.values,
        "A value falls outside the 1.5 IQR fence.",
    )


def _datetime_parse_failure(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if column.passport.mixed_numeric_dialect or column.dates is None:
        return None
    if column.passport.profile.kind is not ColumnKind.DATETIME:
        return None
    ambiguous = column.ambiguous
    if ambiguous is None:
        ambiguous = pd.Series(False, index=column.values.index)
    mask = _unexplained(column) & column.dates.isna() & ~ambiguous
    return _hit(
        "datetime_parse_failure",
        Severity.ERROR,
        column.name,
        mask,
        column.population,
        column.values,
        "A value in a datetime column could not be parsed as a date.",
    )


def _mixed_datetime_formats(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if not column.passport.mixed_datetime_formats or column.dates is None:
        return None
    return _hit(
        "mixed_datetime_formats",
        Severity.WARNING,
        column.name,
        column.dates.notna(),
        column.population,
        column.values,
        "This column mixes more than one datetime format.",
    )


def _ambiguous_day_month(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if not column.passport.ambiguous_day_month or column.ambiguous is None:
        return None
    return _hit(
        "ambiguous_day_month",
        Severity.WARNING,
        column.name,
        column.ambiguous,
        column.population,
        column.values,
        "A date can be read as either day-first or month-first.",
    )


def _email_format(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    if column.passport.profile.kind is not ColumnKind.EMAIL:
        return None
    raw = column.values.loc[_unexplained(column)]
    if raw.empty:
        return None
    domain = raw.str.split("@").str[-1].fillna("")
    bad = (
        raw.str.count("@").ne(1)
        | raw.str.contains(r"\s", na=False)
        | ~domain.str.contains(".", regex=False, na=False)
    )
    return _hit(
        "email_format",
        Severity.ERROR,
        column.name,
        bad.reindex(column.values.index, fill_value=False),
        column.population,
        column.values,
        "A value does not look like an email address.",
    )


def _duplicate_values(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    profile = column.passport.profile
    if profile.distinct_ratio < NEAR_UNIQUE_RATIO:
        return None
    raw = column.values.loc[~(column.blank | column.sentinel)]
    if raw.empty:
        return None
    repeated = raw.map(raw.value_counts()).gt(1)
    if not bool(repeated.any()):
        return None
    mask = repeated.reindex(column.values.index, fill_value=False)
    if profile.kind is ColumnKind.IDENTIFIER:
        return _hit(
            "identifier_duplicates",
            Severity.ERROR,
            column.name,
            mask,
            column.population,
            column.values,
            "An identifier value is repeated in a near-unique column.",
        )
    return _hit(
        "near_unique_duplicates",
        Severity.WARNING,
        column.name,
        mask,
        column.population,
        column.values,
        "A value is repeated in a near-unique column.",
    )


def _constant_column(column: _Column) -> tuple[Finding, pd.DataFrame] | None:
    profile = column.passport.profile
    substantive = ~(column.blank | column.sentinel)
    if profile.distinct_count != 1 or int(substantive.sum()) < CONSTANT_MINIMUM:
        return None
    return _hit(
        "constant_column",
        Severity.SUGGESTION,
        column.name,
        substantive,
        column.population,
        column.values,
        "This column has a single distinct value.",
    )


def _ragged_rows(
    table: RawTable, population: int
) -> tuple[Finding, pd.DataFrame] | None:
    rows = table.ragged_rows
    if not rows or population <= 0:
        return None
    index = [row.row_number for row in rows]
    raw = pd.Series([row.raw_value for row in rows], index=index)
    return _hit(
        "ragged_rows",
        Severity.ERROR,
        "",
        pd.Series(True, index=index),
        population,
        raw,
        "A row has a different field count than the header.",
    )


def _empty_rows(table: RawTable, population: int) -> tuple[Finding, pd.DataFrame] | None:
    numbers = list(table.empty_row_numbers)
    if not numbers or population <= 0:
        return None
    raw = _row_text(table.frame).reindex(numbers).fillna("")
    return _hit(
        "empty_rows",
        Severity.SUGGESTION,
        "",
        pd.Series(True, index=numbers),
        population,
        raw,
        "A row is empty or contains only placeholders.",
    )


def _exact_duplicate_rows(kept: pd.DataFrame) -> tuple[Finding, pd.DataFrame] | None:
    if len(kept) < 2:
        return None
    mask = kept.duplicated(keep=False)
    if not bool(mask.any()):
        return None
    return _hit(
        "exact_duplicate_rows",
        Severity.WARNING,
        "",
        mask,
        len(kept),
        _row_text(kept),
        "These data rows are exact copies of each other.",
    )


def _blank_and_sentinel(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    stripped = values.str.strip()
    blank = stripped.eq("")
    sentinel = stripped.str.casefold().isin(SENTINELS) & ~blank
    return blank, sentinel


def _trim_collision(values: pd.Series, substantive: pd.Series) -> pd.Series:
    raw = values.loc[substantive]
    if raw.empty:
        return pd.Series(False, index=values.index)
    key = raw.str.strip()
    variety = raw.groupby(key).nunique()
    return key.map(variety).gt(1).reindex(values.index, fill_value=False)


def _unexplained(column: _Column) -> pd.Series:
    return ~(column.blank | column.sentinel | column.edge)


def _true_mask(column: _Column) -> pd.Series:
    return pd.Series(True, index=column.values.index)


def _align(series: pd.Series | None, index: pd.Index) -> pd.Series | None:
    if series is None:
        return None
    return series.loc[index]


def _row_text(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="object")
    return frame.astype(str).agg(_ROW_JOIN.join, axis=1)


def _hit(
    check_id: str,
    severity: Severity,
    column: str,
    mask: pd.Series,
    population: int,
    raw: pd.Series,
    message: str,
) -> tuple[Finding, pd.DataFrame] | None:
    if population <= 0:
        return None
    selected = mask.fillna(False).astype(bool)
    selected = selected.loc[selected].sort_index()
    if selected.empty:
        return None
    count = int(len(selected))
    example = raw.loc[selected.index[0]]
    finding = Finding(
        check_id=check_id,
        severity=severity,
        column=column,
        row_count=count,
        share=count / population,
        example="" if pd.isna(example) else str(example),
        row_numbers=tuple(int(number) for number in selected.index[:EXAMPLE_ROW_LIMIT]),
        message=message,
    )
    values = raw.reindex(selected.index).fillna("")
    detail = pd.DataFrame(
        {
            "column": column,
            "check_id": check_id,
            "severity": severity.value,
            "row_number": values.index.to_numpy(dtype="int64"),
            "raw_value": values.astype(str).to_numpy(),
            "message": message,
        }
    )
    return finding, detail


def _collect(
    hits: list[tuple[Finding, pd.DataFrame]],
    hit: tuple[Finding, pd.DataFrame] | None,
) -> None:
    if hit is not None:
        hits.append(hit)


def _only(*hits: tuple[Finding, pd.DataFrame] | None) -> list[tuple[Finding, pd.DataFrame]]:
    return [hit for hit in hits if hit is not None]


def _result(hits: list[tuple[Finding, pd.DataFrame]]) -> CheckResult:
    if not hits:
        return CheckResult((), _empty_affected())
    findings = tuple(finding for finding, _detail in hits)
    affected = pd.concat((detail for _finding, detail in hits), ignore_index=True)
    return CheckResult(findings, affected)


def _empty_affected() -> pd.DataFrame:
    return pd.DataFrame(columns=list(_AFFECTED_COLUMNS))
