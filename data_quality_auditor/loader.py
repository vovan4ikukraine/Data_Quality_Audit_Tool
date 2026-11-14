import csv
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
from charset_normalizer import from_bytes
from openpyxl.packaging.relationship import get_dependents, get_rels_path
from openpyxl.reader.excel import ExcelReader
from openpyxl.styles.stylesheet import apply_stylesheet
from openpyxl.worksheet._reader import FORMULA_TAG, WorkSheetParser

SENTINELS = frozenset({"na", "n/a", "null", "none", "-", "--", "?", "#n/a"})
DELIMITERS = (",", ";", "\t", "|")
_ENCODING_CHAOS_LIMIT = 0.2
_OLE_HEADER = b"\xd0\xcf\x11\xe0"
_ZIP_HEADER = b"PK"
_PIVOT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotTable"
_COULD_NOT_PROCESS = "The file could not be processed."
_EXCEL_SUFFIXES = frozenset({".xlsx", ".xlsm"})
_FILE_IN_USE = (
    "The file is open in another program and could not be read. Close it and try again."
)


class LoadError(Exception):
    pass


class _CachedFormulaParser(WorkSheetParser):
    def parse_cell(self, element):
        cell = super().parse_cell(element)
        formula = element.find(FORMULA_TAG)
        if formula is None or cell["value"] is not None:
            return cell
        text = formula.text or ""
        if text and not text.startswith("="):
            text = f"={text}"
        cell["value"] = text or None
        cell["data_type"] = "f"
        return cell


@dataclass(frozen=True)
class _SheetRef:
    name: str
    target: str
    auditable: bool


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


def auditable_sheets(path: str | Path) -> tuple[str, ...]:
    source = _require_file(path)
    if source.suffix.lower() not in _EXCEL_SUFFIXES:
        raise LoadError("The sheet option applies to .xlsx and .xlsm files.")
    payload = _read_bytes(source)
    _require_xlsx_container(payload)
    package = _open_package(payload)
    try:
        return tuple(item.name for item in _sheet_refs(package) if item.auditable)
    finally:
        package.archive.close()


def load_file(path: str | Path, sheet: str | None = None) -> RawTable:
    source = _require_file(path)
    suffix = source.suffix.lower()
    if suffix == ".xls":
        raise LoadError(
            "Legacy .xls workbooks are not supported. Save the file as .xlsx, .xlsm, or .csv."
        )
    if suffix not in {".csv", *_EXCEL_SUFFIXES}:
        label = suffix if suffix else "no extension"
        raise LoadError(f"Unsupported file format '{label}'. Use .csv, .xlsx, or .xlsm.")
    if suffix == ".csv" and sheet is not None:
        raise LoadError("The sheet option applies to .xlsx and .xlsm files.")
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
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        if isinstance(exc, PermissionError) or winerror in {32, 33}:
            raise LoadError(_FILE_IN_USE) from exc
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
    package = _open_package(payload)
    try:
        sheets = _sheet_refs(package)
        names = [item.name for item in sheets]
        if not names:
            raise LoadError(_COULD_NOT_PROCESS)
        chosen = _choose_sheet(sheets, sheet)
        headers, records, type_rows, row_numbers, has_merged = _read_sheet(package, chosen)
    finally:
        package.archive.close()
    if not records and all(name == "" for name in headers):
        raise LoadError(f"The sheet is empty: {chosen.name}")
    frame = _string_frame(headers, records, row_numbers)
    cell_types = pd.DataFrame(type_rows, columns=frame.columns)
    cell_types.index = frame.index
    cell_types.index.name = frame.index.name
    others = tuple(name for name in names if name != chosen.name)
    return RawTable(
        path=str(path),
        frame=frame,
        cell_types=cell_types,
        encoding=None,
        encoding_is_fallback=False,
        delimiter=None,
        sheet=chosen.name,
        other_sheets=others,
        has_merged_cells=has_merged,
        ragged_rows=(),
        empty_row_numbers=_empty_row_numbers(frame),
    )


def _open_package(payload: bytes) -> ExcelReader:
    package = None
    try:
        package = ExcelReader(
            BytesIO(payload), read_only=True, data_only=False, keep_links=False
        )
        package.read_manifest()
        package.read_strings()
        package.read_workbook()
        apply_stylesheet(package.archive, package.wb)
    except Exception as exc:
        if package is not None:
            package.archive.close()
        raise LoadError(_COULD_NOT_PROCESS) from exc
    return package


def _sheet_refs(package: ExcelReader) -> tuple[_SheetRef, ...]:
    refs = []
    for sheet, rel in package.parser.find_sheets():
        kind = rel.Type or ""
        is_worksheet = "worksheet" in kind and "chartsheet" not in kind
        auditable = is_worksheet and not _has_pivot(package, rel.target)
        if auditable:
            auditable = _has_values(package, rel.target)
        refs.append(_SheetRef(sheet.name, rel.target, auditable))
    return tuple(refs)


def _has_pivot(package: ExcelReader, target: str) -> bool:
    rels_path = get_rels_path(target)
    if rels_path not in package.valid_files:
        return False
    try:
        rels = get_dependents(package.archive, rels_path)
    except Exception:
        return True
    return any(rels.find(_PIVOT_REL))


def _has_values(package: ExcelReader, target: str) -> bool:
    try:
        with package.archive.open(target) as source:
            parser = _sheet_parser(package, source)
            for _row_number, cells in parser.parse():
                for cell in cells:
                    if _cell_has_content(cell):
                        return True
    except Exception:
        return False
    return False


def _choose_sheet(sheets: tuple[_SheetRef, ...], sheet: str | None) -> _SheetRef:
    if sheet is None:
        for item in sheets:
            if item.auditable:
                return item
        raise LoadError(_COULD_NOT_PROCESS)
    for item in sheets:
        if item.name == sheet:
            if not item.auditable:
                raise LoadError(_COULD_NOT_PROCESS)
            return item
    available = ", ".join(item.name for item in sheets)
    raise LoadError(f"Sheet '{sheet}' was not found. Available sheets: {available}.")


def _read_sheet(
    package: ExcelReader, sheet: _SheetRef
) -> tuple[list[str], list[list[str]], list[list[str]], list[int], bool]:
    try:
        with package.archive.open(sheet.target) as source:
            parser = _sheet_parser(package, source)
            parsed = list(parser.parse())
            merged = parser.merged_cells
            has_merged = bool(merged is not None and merged.mergeCell)
    except Exception as exc:
        raise LoadError(_COULD_NOT_PROCESS) from exc
    lookup: dict[tuple[int, int], dict] = {}
    last_row = 0
    last_column = 0
    for row_number, cells in parsed:
        last_row = max(last_row, row_number)
        for cell in cells:
            lookup[(row_number, cell["column"])] = cell
            if _cell_has_content(cell):
                last_column = max(last_column, cell["column"])
    if last_column == 0:
        raise LoadError(f"The sheet is empty: {sheet.name}")
    headers = [
        "" if (1, column) not in lookup else _excel_text(lookup[(1, column)]["value"]).strip()
        for column in range(1, last_column + 1)
    ]
    records = []
    type_rows = []
    row_numbers = []
    for row_number in range(2, last_row + 1):
        values = []
        kinds = []
        for column in range(1, last_column + 1):
            cell = lookup.get((row_number, column))
            if cell is None:
                values.append("")
                kinds.append("")
            else:
                values.append(_excel_text(cell["value"]))
                kinds.append(_parsed_type(cell))
        records.append(values)
        type_rows.append(kinds)
        row_numbers.append(row_number)
    return headers, records, type_rows, row_numbers, has_merged


def _sheet_parser(package: ExcelReader, source) -> WorkSheetParser:
    workbook = package.wb
    return _CachedFormulaParser(
        source,
        package.shared_strings,
        data_only=True,
        epoch=workbook.epoch,
        date_formats=set(getattr(workbook, "_date_formats", ())),
        timedelta_formats=set(getattr(workbook, "_timedelta_formats", ())),
    )


def _cell_has_content(cell: dict) -> bool:
    return cell.get("data_type") == "f" or _excel_text(cell["value"]) != ""


def column_blocks(frame: pd.DataFrame) -> tuple[tuple[int, int], ...]:
    gaps = []
    for name in frame.columns:
        values = frame[name].fillna("").astype(str)
        empty_header = str(name).strip() == ""
        empty_cells = bool(values.str.strip().eq("").all())
        gaps.append(empty_header and empty_cells)
    blocks: list[tuple[int, int]] = []
    start = None
    for index, is_gap in enumerate(gaps):
        if is_gap:
            if start is not None:
                blocks.append((start, index))
                start = None
            continue
        if start is None:
            start = index
    if start is not None:
        blocks.append((start, len(gaps)))
    if not blocks and len(frame.columns):
        return ((0, len(frame.columns)),)
    return tuple(blocks)


def take_columns(table: RawTable, start: int, end: int) -> RawTable:
    frame = table.frame.iloc[:, start:end].copy()
    cell_types = None
    if table.cell_types is not None:
        cell_types = table.cell_types.iloc[:, start:end].copy()
    return replace(
        table,
        frame=frame,
        cell_types=cell_types,
        empty_row_numbers=_empty_row_numbers(frame),
    )


def _parsed_type(cell: dict) -> str:
    if cell.get("data_type") == "f":
        return "f"
    if _excel_text(cell["value"]) == "":
        return ""
    if cell["data_type"] == "d":
        return "d"
    return str(cell["data_type"])


def _require_xlsx_container(payload: bytes) -> None:
    if payload.startswith(_OLE_HEADER):
        raise LoadError(
            "This workbook is password-protected or saved in the legacy .xls format."
        )
    if not payload.startswith(_ZIP_HEADER):
        raise LoadError("The file is not a valid .xlsx workbook.")


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
