import sys
from pathlib import Path

from data_quality_auditor.checks import check_table
from data_quality_auditor.loader import LoadError, load_file
from data_quality_auditor.policy import apply_policy
from data_quality_auditor.profiler import profile_table
from data_quality_auditor.report import write_report


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
    print()
    try:
        entered = input("File: ")
    except EOFError:
        print("A file path is required.", file=sys.stderr)
        return 1
    path = entered.strip().strip('"').strip("'")
    if not path:
        print("A file path is required.", file=sys.stderr)
        return 1
    try:
        report_path, findings_path = audit_file(path)
    except LoadError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Wrote {report_path}")
    print(f"Wrote {findings_path}")
    return 0


def _reports_dir() -> Path:
    if getattr(sys, "frozen", False):
        program_dir = Path(sys.executable).resolve().parent
    else:
        program_dir = Path(__file__).resolve().parent.parent
    return program_dir / "reports"


if __name__ == "__main__":
    raise SystemExit(main())
