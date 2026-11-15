import itertools
import sys
import threading
from pathlib import Path

from data_quality_auditor.checks import check_table
from openpyxl.utils import get_column_letter

from data_quality_auditor.loader import (
    LoadError,
    auditable_sheets,
    column_blocks,
    load_file,
    take_columns,
)
from data_quality_auditor.policy import apply_policy
from data_quality_auditor.profiler import profile_table
from data_quality_auditor.report import write_report

_INPUT_SUFFIXES = frozenset({".csv", ".xlsx", ".xlsm"})
_EXCEL_SUFFIXES = frozenset({".xlsx", ".xlsm"})


def audit_table(
    table,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    columns = profile_table(table)
    result = check_table(table, columns)
    findings, affected_rows = apply_policy(result.findings, result.affected_rows)
    destination = _reports_dir() if output_dir is None else output_dir
    return write_report(table, columns, findings, affected_rows, destination)


def audit_file(
    path: str | Path,
    sheet: str | None = None,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    return audit_table(load_file(path, sheet), output_dir)


def main() -> int:
    try:
        return _run()
    except KeyboardInterrupt:
        print()
        print("Stopped.")
        return 1


def _run() -> int:
    print("Data quality audit")
    print("The source file is not changed.")
    print(f"Reports are saved in {_reports_dir()}.")
    folder = _prepare_input_dir()
    if folder is None:
        return 1
    print(f"Place CSV, XLSX, and XLSM files in {folder}.")
    print()
    while True:
        files = _input_files(folder)
        if not files:
            print("The input folder is empty. Add files to process.")
            _pause()
            return 1
        chosen = _choose_file(files)
        if chosen is None:
            return 1
        finished = _audit_chosen(chosen)
        if finished is None:
            return 1
        report_path, findings_path = finished
        print("Done.")
        print(f"Reports are saved in {report_path.parent}.")
        print(report_path.name)
        print(findings_path.name)
        print()


def _audit_chosen(chosen: Path) -> tuple[Path, Path] | None:
    sheet = None
    if chosen.suffix.lower() in _EXCEL_SUFFIXES:
        sheet = _choose_sheet(chosen)
        if sheet is None:
            return None
    try:
        with _Spinner():
            table = load_file(chosen, sheet)
            blocks = column_blocks(table.frame)
        if len(blocks) > 1:
            print("This sheet has more than one table.")
            choice = _choose_number(
                "Choose a table:",
                tuple(_block_label(*block) for block in blocks),
            )
            if choice is None:
                return None
            table = take_columns(table, *blocks[choice - 1])
        with _Spinner():
            return audit_table(table)
    except LoadError as error:
        _show_error(error)
        return None
    except Exception as error:
        _show_error(error)
        return None


def _program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _reports_dir() -> Path:
    return _program_dir() / "reports"


def _prepare_input_dir() -> Path | None:
    folder = _program_dir() / "input"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        print(f"The input folder could not be created: {folder}", file=sys.stderr)
        return None
    return folder


def _input_files(folder: Path) -> tuple[Path, ...]:
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in _INPUT_SUFFIXES
    ]
    return tuple(sorted(files, key=lambda path: path.name.casefold()))


def _pause() -> None:
    try:
        input("Press Enter to close.")
    except EOFError:
        return


class _Spinner:
    _LABEL = "Processing"

    def __enter__(self):
        self._stop = threading.Event()
        self._thread = None
        if not sys.stdout.isatty():
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r" + " " * (len(self._LABEL) + 2) + "\r")
        sys.stdout.flush()

    def _run(self) -> None:
        frames = itertools.cycle("\\|/-")
        while not self._stop.is_set():
            sys.stdout.write(f"\r{self._LABEL} {next(frames)}")
            sys.stdout.flush()
            self._stop.wait(0.15)


def _show_error(error: BaseException) -> None:
    print(_error_line(error), file=sys.stderr)
    _pause()


def _error_line(error: BaseException) -> str:
    if isinstance(error, LoadError):
        message = str(error).strip() or "The file could not be processed."
        cause = error.__cause__
    else:
        message = "The file could not be processed."
        cause = error
    if cause is None:
        return message
    text = " ".join(str(cause).split())
    if len(text) > 160:
        text = text[:157] + "..."
    if text and text in message:
        return message
    hint = type(cause).__name__ if not text else f"{type(cause).__name__}: {text}"
    return f"{message} ({hint})"


def _choose_file(files: tuple[Path, ...]) -> Path | None:
    choice = _choose_number("Choose a file:", tuple(path.name for path in files))
    if choice is None:
        return None
    return files[choice - 1]


def _choose_sheet(path: Path) -> str | None:
    try:
        with _Spinner():
            sheets = auditable_sheets(path)
    except LoadError as error:
        _show_error(error)
        return None
    if not sheets:
        print(
            "The file could not be processed. (No sheet with a table was found.)",
            file=sys.stderr,
        )
        _pause()
        return None
    choice = _choose_number("Choose a sheet:", sheets)
    if choice is None:
        return None
    return sheets[choice - 1]


def _block_label(start: int, end: int) -> str:
    left = get_column_letter(start + 1)
    right = get_column_letter(end)
    if left == right:
        return f"Column {left}"
    return f"Columns {left}-{right}"


def _choose_number(title: str, labels: tuple[str, ...]) -> int | None:
    print(title)
    for number, label in enumerate(labels, start=1):
        print(f"{number}. {label}")
    prompt = f"Enter a number from 1 to {len(labels)}."
    while True:
        try:
            entered = input("Number: ")
        except EOFError:
            print("A number is required.", file=sys.stderr)
            return None
        if entered.strip().isdigit():
            choice = int(entered.strip())
            if 1 <= choice <= len(labels):
                return choice
        print(prompt)


if __name__ == "__main__":
    raise SystemExit(main())
