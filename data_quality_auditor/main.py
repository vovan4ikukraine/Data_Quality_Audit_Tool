import sys
from pathlib import Path

from data_quality_auditor.checks import check_table
from data_quality_auditor.loader import LoadError, load_file
from data_quality_auditor.policy import apply_policy
from data_quality_auditor.profiler import profile_table
from data_quality_auditor.report import write_report

_INPUT_SUFFIXES = frozenset({".csv", ".xlsx"})


def audit_file(
    path: str | Path,
    sheet: str | None = None,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    table = load_file(path, sheet)
    columns = profile_table(table)
    result = check_table(table, columns)
    findings, affected_rows = apply_policy(result.findings, result.affected_rows)
    destination = _reports_dir() if output_dir is None else output_dir
    return write_report(table, columns, findings, affected_rows, destination)


def main() -> int:
    print("Data quality audit")
    print("The source file is not changed.")
    print(f"Reports are saved in {_reports_dir()}.")
    folder = _prepare_input_dir()
    if folder is None:
        return 1
    print(f"Place CSV and XLSX files in {folder}.")
    print()
    files = _input_files(folder)
    if not files:
        print("The input folder is empty. Add files to process.")
        _pause()
        return 1
    chosen = _choose_file(files)
    if chosen is None:
        return 1
    try:
        report_path, findings_path = audit_file(chosen)
    except LoadError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Wrote {report_path}")
    print(f"Wrote {findings_path}")
    return 0


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


def _choose_file(files: tuple[Path, ...]) -> Path | None:
    print("Choose a file:")
    for number, path in enumerate(files, start=1):
        print(f"{number}. {path.name}")
    prompt = f"Enter a number from 1 to {len(files)}."
    while True:
        try:
            entered = input("Number: ")
        except EOFError:
            print("A file number is required.", file=sys.stderr)
            return None
        if entered.strip().isdigit():
            choice = int(entered.strip())
            if 1 <= choice <= len(files):
                return files[choice - 1]
        print(prompt)


if __name__ == "__main__":
    raise SystemExit(main())
