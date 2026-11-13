import re
from dataclasses import dataclass

import pandas as pd

from data_quality_auditor.loader import SENTINELS, RawTable
from data_quality_auditor.models import ColumnKind, ColumnProfile, EpochUnit
from data_quality_auditor.patterns import (
    is_date_name,
    is_email_name,
    is_epoch_name,
    is_identifier_name,
)
from data_quality_auditor.policy import MAJORITY_SHARE, MIXED_DIALECT_COUNT

SHORT_TEXT_LIMIT = 50
FREQUENT_VALUE_LIMIT = 5

_SPACES = re.compile(r"[ \u00a0]")
_PLAIN_NUMBER = r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"
_US_NUMBER = r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$"
_EUROPEAN_DECIMAL = r"^[+-]?\d+,\d+$"
_EUROPEAN_GROUP = r"^[+-]?\d{1,3}(?:\.\d{3})+,\d+$"
_EUROPEAN_THOUSANDS = r"^[+-]?\d{1,3}(?:\.\d{3}){2,}$"
_INTEGER = r"^[+-]?\d+$"
_SCIENTIFIC = r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)[eE][+-]?\d+$"
_ISO_DATETIME = (
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
_SLASH_DATE = r"^\d{2}/\d{2}/\d{4}$"
_DATE_ONLY = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}|\d{2}\.\d{2}\.\d{4}|\d{8}|\d{2}/\d{2}/\d{4})$"
)
_ZONE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")
_DATE_FORMATS = (
    ("YYYY-MM-DD", r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),
    ("YYYY/MM/DD", r"^\d{4}/\d{2}/\d{2}$", "%Y/%m/%d"),
    ("DD.MM.YYYY", r"^\d{2}\.\d{2}\.\d{4}$", "%d.%m.%Y"),
)
_COMPACT_DATE = ("YYYYMMDD", r"^\d{8}$", "%Y%m%d")
_EPOCH_BANDS = (
    (EpochUnit.SECONDS, 0, 1e11),
    (EpochUnit.MILLISECONDS, 1e11, 1e14),
    (EpochUnit.MICROSECONDS, 1e14, 1e17),
)
_DAY_MONTH = "DD/MM/YYYY"
_MONTH_DAY = "MM/DD/YYYY"
_AMBIGUOUS_DAY_MONTH = "DD/MM/YYYY|MM/DD/YYYY"


@dataclass
class ColumnPassport:
    profile: ColumnProfile
    numeric_values: pd.Series | None
    datetime_values: pd.Series | None
    mixed_numeric_dialect: bool
    mixed_datetime_formats: bool
    ambiguous_day_month: bool
    ambiguous_rows: pd.Series | None


@dataclass
class _Numbers:
    rate: float
    mixed: bool
    parsed: pd.Series


@dataclass
class _Dates:
    rate: float
    parsed: pd.Series
    recognized_format: str | None
    mixed: bool
    ambiguous: bool
    ambiguous_rows: pd.Series


def profile_table(table: RawTable) -> tuple[ColumnPassport, ...]:
    frame = table.frame
    kept = frame.drop(index=list(table.empty_row_numbers), errors="ignore")
    return tuple(
        _profile_column(str(name), frame[name], kept[name]) for name in frame.columns
    )


def _profile_column(name: str, values: pd.Series, kept: pd.Series) -> ColumnPassport:
    blank, sentinel = _blank_and_sentinel(kept)
    content = kept.loc[~(blank | sentinel)]
    distinct_count = int(content.nunique())
    numbers = _read_numbers(content)
    dates = _read_dates(content, is_date_name(name))
    epoch_unit = _epoch_unit(numbers) if _looks_like_epoch(name, numbers) else None
    kind = _infer_kind(name, numbers, dates, epoch_unit)

    minimum = maximum = median = None
    zero_count = negative_count = None
    numeric_values = None
    if kind is ColumnKind.NUMERIC:
        minimum, maximum, median, zero_count, negative_count = _numeric_stats(
            numbers.parsed
        )
        numeric_values = numbers.parsed.reindex(values.index)

    recognized_format = None
    datetime_minimum = datetime_maximum = None
    datetime_values = None
    mixed_dates = False
    ambiguous = False
    ambiguous_rows = None
    if kind is ColumnKind.DATETIME:
        recognized_format = dates.recognized_format
        datetime_minimum, datetime_maximum = _datetime_bounds(dates.parsed, content)
        datetime_values = dates.parsed.reindex(values.index)
        mixed_dates = dates.mixed
        ambiguous = dates.ambiguous
        if ambiguous:
            ambiguous_rows = dates.ambiguous_rows.reindex(values.index, fill_value=False)

    profile = ColumnProfile(
        name=name,
        kind=kind,
        blank_share=_share(int(blank.sum()), len(kept)),
        sentinel_share=_share(int(sentinel.sum()), len(kept)),
        distinct_count=distinct_count,
        distinct_ratio=_share(distinct_count, len(content)),
        minimum=minimum,
        maximum=maximum,
        median=median,
        zero_count=zero_count,
        negative_count=negative_count,
        recognized_format=recognized_format,
        datetime_minimum=datetime_minimum,
        datetime_maximum=datetime_maximum,
        frequent_values=_frequent_values(kind, content, distinct_count),
        epoch_unit=epoch_unit if kind is ColumnKind.NUMERIC else None,
    )
    return ColumnPassport(
        profile=profile,
        numeric_values=numeric_values,
        datetime_values=datetime_values,
        mixed_numeric_dialect=numbers.mixed,
        mixed_datetime_formats=mixed_dates,
        ambiguous_day_month=ambiguous,
        ambiguous_rows=ambiguous_rows,
    )


def _infer_kind(
    name: str, numbers: _Numbers, dates: _Dates, epoch_unit: EpochUnit | None
) -> ColumnKind:
    if is_identifier_name(name):
        return ColumnKind.IDENTIFIER
    if is_email_name(name):
        return ColumnKind.EMAIL
    if is_date_name(name):
        if dates.rate >= MAJORITY_SHARE:
            return ColumnKind.DATETIME
        if epoch_unit is not None:
            return ColumnKind.NUMERIC
        if numbers.mixed:
            return ColumnKind.TEXT
        if numbers.rate >= MAJORITY_SHARE:
            return ColumnKind.NUMERIC
        return ColumnKind.DATETIME
    if not numbers.mixed and numbers.rate >= MAJORITY_SHARE:
        return ColumnKind.NUMERIC
    if dates.rate >= MAJORITY_SHARE:
        return ColumnKind.DATETIME
    return ColumnKind.TEXT


def _looks_like_epoch(name: str, numbers: _Numbers) -> bool:
    return is_epoch_name(name) and not numbers.mixed and numbers.rate >= MAJORITY_SHARE


def _blank_and_sentinel(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    stripped = values.str.strip()
    blank = stripped.eq("")
    sentinel = stripped.str.casefold().isin(SENTINELS) & ~blank
    return blank, sentinel


def _read_numbers(content: pd.Series) -> _Numbers:
    if content.empty:
        return _Numbers(0.0, False, pd.Series(dtype="float64"))
    compact = content.str.replace(_SPACES, "", regex=True)
    plain = _matches(compact, _PLAIN_NUMBER)
    us = _matches(compact, _US_NUMBER)
    european = _european_mask(compact, us)
    if (
        int(european.sum()) >= MIXED_DIALECT_COUNT
        and int(us.sum()) >= MIXED_DIALECT_COUNT
    ):
        return _Numbers(0.0, True, pd.Series(float("nan"), index=content.index))

    parsed_by_dialect = {
        "plain": _parse_plain(compact, plain),
        "us": _parse_us(compact, plain, us),
        "european": _parse_european(compact, european),
    }
    rates = {
        dialect: _share(int(parsed.notna().sum()), len(content))
        for dialect, parsed in parsed_by_dialect.items()
    }
    dialect = max(rates, key=rates.get)
    return _Numbers(rates[dialect], False, parsed_by_dialect[dialect])


def _european_mask(compact: pd.Series, us: pd.Series) -> pd.Series:
    grouped = _matches(compact, _EUROPEAN_GROUP)
    thousands = _matches(compact, _EUROPEAN_THOUSANDS)
    decimal = _matches(compact, _EUROPEAN_DECIMAL) & ~us
    return grouped | thousands | decimal


def _parse_plain(compact: pd.Series, plain: pd.Series) -> pd.Series:
    return pd.to_numeric(compact.where(plain), errors="coerce")


def _parse_us(compact: pd.Series, plain: pd.Series, us: pd.Series) -> pd.Series:
    accepted = compact.where(plain | us)
    return pd.to_numeric(accepted.str.replace(",", "", regex=False), errors="coerce")


def _parse_european(compact: pd.Series, european: pd.Series) -> pd.Series:
    grouped = compact.where(european)
    grouped = grouped.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    plain = compact.where(_matches(compact, _INTEGER) | _matches(compact, _SCIENTIFIC))
    return pd.to_numeric(grouped.fillna(plain), errors="coerce")


def _epoch_unit(numbers: _Numbers) -> EpochUnit | None:
    parsed = numbers.parsed.dropna()
    if parsed.empty:
        return None
    nonzero = parsed[parsed != 0]
    if nonzero.empty:
        return EpochUnit.SECONDS
    absolute = nonzero.abs()
    for unit, low, high in _EPOCH_BANDS:
        if float(((absolute >= low) & (absolute < high)).mean()) >= MAJORITY_SHARE:
            return unit
    return None


def _numeric_stats(
    parsed: pd.Series,
) -> tuple[float | None, float | None, float | None, int, int]:
    numbers = parsed.dropna()
    if numbers.empty:
        return None, None, None, 0, 0
    return (
        float(numbers.min()),
        float(numbers.max()),
        float(numbers.median()),
        int((numbers == 0).sum()),
        int((numbers < 0).sum()),
    )


def _read_dates(content: pd.Series, date_name: bool) -> _Dates:
    if content.empty:
        return _Dates(
            0.0,
            pd.Series(dtype="datetime64[us]"),
            None,
            False,
            False,
            pd.Series(dtype=bool),
        )

    labels: list[str] = []
    parts: list[pd.Series] = []
    recognized = pd.Series(False, index=content.index)
    for label, pattern, fmt in _date_formats(date_name):
        parsed = pd.to_datetime(
            content.where(_matches(content, pattern)), format=fmt, errors="coerce"
        )
        if parsed.notna().any():
            labels.append(label)
            parts.append(parsed)
            recognized = recognized | parsed.notna()

    iso = _parse_iso_datetimes(content, _matches(content, _ISO_DATETIME))
    if iso.notna().any():
        labels.append("ISO-8601")
        parts.append(iso)
        recognized = recognized | iso.notna()

    slash_parsed, slash_label, ambiguous, slash_matched = _read_slash_dates(content)
    if slash_label is not None:
        labels.append(slash_label)
    if slash_parsed is not None:
        parts.append(slash_parsed)
    recognized = recognized | slash_matched

    parsed = _combine_dates(parts, content.index)
    recognized_format = labels[0] if len(labels) == 1 and not ambiguous else None
    ambiguous_rows = slash_matched if ambiguous else pd.Series(False, index=content.index)
    return _Dates(
        _share(int(recognized.sum()), len(content)),
        parsed,
        recognized_format,
        len(labels) > 1,
        ambiguous,
        ambiguous_rows,
    )


def _date_formats(date_name: bool):
    yield from _DATE_FORMATS
    if date_name:
        yield _COMPACT_DATE


def _parse_iso_datetimes(values: pd.Series, mask: pd.Series) -> pd.Series:
    selected = values.where(mask)
    zoned = selected.str.contains(_ZONE, na=False)
    naive = pd.to_datetime(selected.where(~zoned), format="ISO8601", errors="coerce")
    if not bool(zoned.any()):
        return naive
    aware = pd.to_datetime(
        selected.where(zoned), format="ISO8601", errors="coerce", utc=True
    )
    return naive.fillna(aware.dt.tz_localize(None))


def _read_slash_dates(
    content: pd.Series,
) -> tuple[pd.Series | None, str | None, bool, pd.Series]:
    mask = _matches(content, _SLASH_DATE)
    matched = pd.Series(False, index=content.index)
    if not bool(mask.any()):
        return None, None, False, matched
    day_first = pd.to_datetime(content.where(mask), format="%d/%m/%Y", errors="coerce")
    month_first = pd.to_datetime(content.where(mask), format="%m/%d/%Y", errors="coerce")
    only_day = day_first.notna() & month_first.isna()
    only_month = month_first.notna() & day_first.isna()
    matched = day_first.notna() | month_first.notna()
    if only_day.any() and only_month.any():
        return None, _AMBIGUOUS_DAY_MONTH, True, matched
    if only_day.any():
        return day_first, _DAY_MONTH, False, matched
    if only_month.any():
        return month_first, _MONTH_DAY, False, matched
    if matched.any():
        return None, _AMBIGUOUS_DAY_MONTH, True, matched
    return None, None, False, matched


def _combine_dates(parts: list[pd.Series], index: pd.Index) -> pd.Series:
    if not parts:
        return pd.Series(pd.NaT, index=index, dtype="datetime64[us]")
    combined = parts[0]
    for part in parts[1:]:
        combined = combined.fillna(part)
    return combined


def _datetime_bounds(
    parsed: pd.Series, source: pd.Series
) -> tuple[str | None, str | None]:
    present = parsed.dropna()
    if present.empty:
        return None, None
    return (
        _datetime_text(parsed, source, present.min()),
        _datetime_text(parsed, source, present.max()),
    )


def _datetime_text(parsed: pd.Series, source: pd.Series, stamp: pd.Timestamp) -> str:
    origin = str(source.loc[parsed == stamp].iloc[0])
    if _DATE_ONLY.fullmatch(origin):
        return stamp.date().isoformat()
    text = stamp.isoformat()
    if _ZONE.search(origin):
        return text + "+00:00"
    return text


def _frequent_values(
    kind: ColumnKind, content: pd.Series, distinct_count: int
) -> tuple[tuple[str, int], ...]:
    if kind is not ColumnKind.TEXT or not 0 < distinct_count <= SHORT_TEXT_LIMIT:
        return ()
    counts = content.value_counts().head(FREQUENT_VALUE_LIMIT)
    return tuple((str(value), int(count)) for value, count in counts.items())


def _matches(values: pd.Series, pattern: str) -> pd.Series:
    return values.str.match(pattern).fillna(False)


def _share(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return count / total
