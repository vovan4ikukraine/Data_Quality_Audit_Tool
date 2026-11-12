import csv
import math
from dataclasses import dataclass
from datetime import date, datetime, time
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
from charset_normalizer import from_bytes
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

SENTINELS = frozenset({"na", "n/a", "null", "none", "-", "--", "?", "#n/a"})
DELIMITERS = (",", ";", "\t", "|")
_ENCODING_CHAOS_LIMIT = 0.2
_OLE_HEADER = b"\xd0\xcf\x11\xe0"
_ZIP_HEADER = b"PK"


class LoadError(Exception):
    pass


@dataclass(frozen=True)
class RaggedRow:
    row_number: int
    field_count: int
    raw_value: str


@dataclass
class RawTable:
    path: str
    frame: pd.DataFrame
    cell_types: pd.DataFrame | None
    encoding: str | None
    encoding_is_fallback: bool
    delimiter: str | None
    sheet: str | None
    other_sheets: tuple[str, ...]
    has_merged_cells: bool
    ragged_rows: tuple[RaggedRow, ...]
    empty_row_numbers: tuple[int, ...]


def is_blank_or_sentinel(value: str) -> bool:
    text = value.strip().casefold()
    return text == "" or text in SENTINELS


def load_file(path: str | Path, sheet: str | None = None) -> RawTable:
    source = _require_file(path)
    suffix = source.suffix.lower()
    if suffix == ".xls":
        raise LoadError(
            "Legacy .xls workbooks are not supported. Save the file as .xlsx or .csv."
        )
    if suffix not in {".csv", ".xlsx"}:
        label = suffix if suffix else "no extension"
        raise LoadError(f"Unsupported file format '{label}'. Use .csv or .xlsx.")
    if suffix == ".csv" and sheet is not None:
        raise LoadError("The sheet option applies to .xlsx files.")
    payload = _read_bytes(source)
    if suffix == ".csv":
        return _load_csv(source, payload)
    return _load_xlsx(source, payload, sheet)


def _require_file(path: str | Path) -> Path:
    source = Path(path)
    if not source.exists():
        raise LoadError(f"File not found: {source}")
    if not source.is_file():
        raise LoadError(f"Path is not a file: {source}")
    return source


def _read_bytes(path: Path) -> bytes:
    try:
        payload = path.read_bytes()
    except PermissionError as exc:
        raise LoadError(f"Permission denied: {path}") from exc
    except OSError as exc:
        raise LoadError(f"The file could not be read: {path}") from exc
    if not payload:
        raise LoadError(f"The file is empty: {path}")
    return payload


def _load_csv(path: Path, payload: bytes) -> RawTable:
    text, encoding, encoding_is_fallback = _decode_csv(payload)
    if not text.strip():
        raise LoadError(f"The file has no rows to read: {path}")
    delimiter = _detect_delimiter(text)
    headers, records, row_numbers, ragged_rows = _parse_csv(text, delimiter)
    if not records and all(name == "" for name in headers):
        raise LoadError(f"The file has no columns to audit: {path}")
    frame = _string_frame(headers, records, row_numbers)
    return RawTable(
        path=str(path),
        frame=frame,
        cell_types=None,
        encoding=encoding,
        encoding_is_fallback=encoding_is_fallback,
        delimiter=delimiter,
        sheet=None,
        other_sheets=(),
        has_merged_cells=False,
        ragged_rows=tuple(ragged_rows),
        empty_row_numbers=_empty_row_numbers(frame),
    )


def _decode_csv(payload: bytes) -> tuple[str, str, bool]:
    has_bom = payload.startswith(b"\xef\xbb\xbf")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = None
    if text is not None:
        return text, "utf-8-sig" if has_bom else "utf-8", False
    match = from_bytes(payload).best()
    if match is not None and match.chaos < _ENCODING_CHAOS_LIMIT:
        return str(match), match.encoding.replace("_", "-"), False
    return payload.decode("latin-1"), "latin-1", True


def _detect_delimiter(text: str) -> str:
    sample = []
    for line in text.splitlines():
        if line.strip():
            sample.append(line)
        if len(sample) == 20:
            break
    if not sample:
        raise LoadError("The file has no rows to read.")
    best = ","
    best_score = (-1, -1)
    for delimiter in DELIMITERS:
        counts = []
        for line in sample:
            try:
                fields = next(csv.reader([line], delimiter=delimiter))
            except csv.Error:
                continue
            counts.append(len(fields))
        if not counts:
            continue
        width = max(set(counts), key=lambda item: (counts.count(item), item))
        score = (counts.count(width), width) if width > 1 else (0, 1)
        if score > best_score:
            best_score = score
            best = delimiter
    return best


def _parse_csv(
    text: str, delimiter: str
) -> tuple[list[str], list[list[str]], list[int], list[RaggedRow]]:
    try:
        parsed = list(enumerate(csv.reader(StringIO(text), delimiter=delimiter), start=1))
    except csv.Error as exc:
        raise LoadError(f"The CSV could not be parsed: {exc}") from exc
    if not parsed:
        raise LoadError("The file has no rows to read.")
    _, header_fields = parsed[0]
    if not header_fields:
        raise LoadError("The header row is empty.")
    headers = [name.strip() for name in header_fields]
    width = len(headers)
    records = []
    row_numbers = []
    ragged_rows = []
    for row_number, fields in parsed[1:]:
        if len(fields) != width:
            ragged_rows.append(
                RaggedRow(
                    row_number=row_number,
                    field_count=len(fields),
                    raw_value=delimiter.join(fields),
                )
            )
            continue
        records.append(fields)
        row_numbers.append(row_number)
    return headers, records, row_numbers, ragged_rows


def _load_xlsx(path: Path, payload: bytes, sheet: str | None) -> RawTable:
    _require_xlsx_container(payload)
    try:
        workbook = load_workbook(BytesIO(payload), data_only=False, read_only=False)
    except (InvalidFileException, OSError, ValueError, KeyError) as exc:
        raise LoadError(f"The workbook could not be read: {exc}") from exc
    try:
        names = list(workbook.sheetnames)
        if not names:
            raise LoadError("The workbook has no sheets.")
        if sheet is None:
            chosen = names[0]
        elif sheet in names:
            chosen = sheet
        else:
            available = ", ".join(names)
            raise LoadError(f"Sheet '{sheet}' was not found. Available sheets: {available}.")
        worksheet = workbook[chosen]
        has_merged_cells = bool(worksheet.merged_cells.ranges)
        headers, records, type_rows, row_numbers = _read_worksheet(worksheet)
    finally:
        workbook.close()
    if not records and all(name == "" for name in headers):
        raise LoadError(f"The sheet is empty: {chosen}")
    frame = _string_frame(headers, records, row_numbers)
    cell_types = pd.DataFrame(type_rows, columns=frame.columns)
    cell_types.index = frame.index
    cell_types.index.name = frame.index.name
    others = tuple(name for name in names if name != chosen)
    return RawTable(
        path=str(path),
        frame=frame,
        cell_types=cell_types,
        encoding=None,
        encoding_is_fallback=False,
        delimiter=None,
        sheet=chosen,
        other_sheets=others,
        has_merged_cells=has_merged_cells,
        ragged_rows=(),
        empty_row_numbers=_empty_row_numbers(frame),
    )


def _require_xlsx_container(payload: bytes) -> None:
    if payload.startswith(_OLE_HEADER):
        raise LoadError(
            "This workbook is password-protected or saved in the legacy .xls format."
        )
    if not payload.startswith(_ZIP_HEADER):
        raise LoadError("The file is not a valid .xlsx workbook.")


def _read_worksheet(
    worksheet,
) -> tuple[list[str], list[list[str]], list[list[str]], list[int]]:
    if not worksheet.max_row or not worksheet.max_column:
        raise LoadError(f"The sheet is empty: {worksheet.title}")
    grid: list[list[tuple[str, str]]] = []
    last_column = 0
    for excel_row in worksheet.iter_rows(
        max_row=worksheet.max_row,
        max_col=worksheet.max_column,
    ):
        parsed: list[tuple[str, str]] = []
        for cell in excel_row:
            text = _excel_text(cell.value)
            parsed.append((text, _excel_type(cell)))
            if text != "":
                last_column = max(last_column, cell.column)
        grid.append(parsed)
    if last_column == 0:
        raise LoadError(f"The sheet is empty: {worksheet.title}")
    header = _fit_row(grid[0], last_column)
    headers = [text.strip() for text, _kind in header]
    records = []
    type_rows = []
    row_numbers = []
    for offset, row in enumerate(grid[1:], start=2):
        fitted = _fit_row(row, last_column)
        records.append([text for text, _kind in fitted])
        type_rows.append([kind for _text, kind in fitted])
        row_numbers.append(offset)
    return headers, records, type_rows, row_numbers


def _fit_row(row: list[tuple[str, str]], width: int) -> list[tuple[str, str]]:
    fitted = row[:width]
    if len(fitted) < width:
        fitted.extend([("", "")] * (width - len(fitted)))
    return fitted


def _excel_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        if value.tzinfo is None and value.time() == time.min:
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer() and abs(value) < 10**15:
            return str(int(value))
        return format(value, ".15g")
    if isinstance(value, int):
        return str(value)
    return str(value)


def _excel_type(cell) -> str:
    if cell.value is None:
        return ""
    if cell.is_date:
        return "d"
    return cell.data_type


def _string_frame(
    headers: list[str], rows: list[list[str]], row_numbers: list[int]
) -> pd.DataFrame:
    columns = _unique_headers(headers)
    frame = pd.DataFrame(rows, columns=columns).fillna("").astype(str)
    if row_numbers:
        frame.index = row_numbers
    frame.index.name = "row_number"
    return frame


def _unique_headers(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        if seen[name] == 1:
            unique.append(name)
        else:
            unique.append(f"{name} ({seen[name]})")
    return unique


def _empty_row_numbers(frame: pd.DataFrame) -> tuple[int, ...]:
    if frame.empty:
        return ()
    folded = frame.map(lambda value: value.strip().casefold())
    missing = folded.eq("") | folded.isin(SENTINELS)
    matched = frame.index[missing.all(axis=1)]
    return tuple(int(number) for number in matched)
