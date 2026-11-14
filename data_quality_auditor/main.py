import argparse
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
    return write_report(table, columns, findings, affected_rows, output_dir)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report_path, findings_path = audit_file(args.path, args.sheet, args.output_dir)
    except LoadError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Wrote {report_path}")
    print(f"Wrote {findings_path}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read one CSV or XLSX file and report where to look first. "
            "The source file is not changed."
        )
    )
    parser.add_argument("path", help="CSV or XLSX file to audit.")
    parser.add_argument(
        "--sheet",
        help=(
            "Worksheet to audit in an XLSX file. "
            "The first sheet is used when this is omitted."
        ),
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Folder for audit_report.md and audit_findings.csv. "
            "The working directory is used when this is omitted."
        ),
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
