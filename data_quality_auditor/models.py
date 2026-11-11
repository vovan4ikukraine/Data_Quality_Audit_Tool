from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class ColumnKind(StrEnum):
    NUMERIC = "numeric"
    DATETIME = "datetime"
    EMAIL = "email"
    IDENTIFIER = "identifier"
    TEXT = "text"


class EpochUnit(StrEnum):
    SECONDS = "seconds"
    MILLISECONDS = "milliseconds"
    MICROSECONDS = "microseconds"


@dataclass
class ColumnProfile:
    name: str
    kind: ColumnKind
    blank_share: float
    sentinel_share: float
    distinct_count: int
    distinct_ratio: float
    minimum: float | None = None
    maximum: float | None = None
    median: float | None = None
    zero_count: int | None = None
    negative_count: int | None = None
    recognized_format: str | None = None
    datetime_minimum: str | None = None
    datetime_maximum: str | None = None
    frequent_values: tuple[tuple[str, int], ...] = ()
    epoch_unit: EpochUnit | None = None

    def __post_init__(self) -> None:
        self.kind = ColumnKind(self.kind)
        if self.epoch_unit is not None:
            self.epoch_unit = EpochUnit(self.epoch_unit)
        self.frequent_values = tuple(self.frequent_values)

        for field_name, value in (
            ("blank_share", self.blank_share),
            ("sentinel_share", self.sentinel_share),
            ("distinct_ratio", self.distinct_ratio),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{field_name} must be between 0 and 1")
        if self.blank_share + self.sentinel_share > 1 + 1e-9:
            raise ValueError("blank_share and sentinel_share together exceed 1")
        if self.distinct_count < 0:
            raise ValueError("distinct_count must be zero or greater")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum cannot be greater than maximum")
        for field_name, value in (
            ("zero_count", self.zero_count),
            ("negative_count", self.negative_count),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be zero or greater")
        for _value, count in self.frequent_values:
            if count < 0:
                raise ValueError("frequent value counts must be zero or greater")


@dataclass
class Finding:
    check_id: str
    severity: Severity
    column: str
    row_count: int
    share: float
    example: str
    row_numbers: tuple[int, ...]
    message: str

    def __post_init__(self) -> None:
        self.severity = Severity(self.severity)
        self.row_numbers = tuple(self.row_numbers)

        if not self.check_id:
            raise ValueError("check_id must be non-empty")
        if not self.message.strip():
            raise ValueError("message must be non-empty")
        if self.row_count < 0:
            raise ValueError("row_count must be zero or greater")
        if not 0 <= self.share <= 1:
            raise ValueError("share must be between 0 and 1")
        if len(self.row_numbers) > 5:
            raise ValueError("A finding keeps at most 5 row numbers")
        if len(set(self.row_numbers)) != len(self.row_numbers):
            raise ValueError("row_numbers must be unique")
        if any(row < 1 for row in self.row_numbers):
            raise ValueError("Row numbers start at 1")
