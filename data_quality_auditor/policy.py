from dataclasses import replace

import pandas as pd

from data_quality_auditor.models import Finding, Severity

MAJORITY_SHARE = 0.90
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
MIXED_DIALECT_COUNT = 3

THRESHOLDS = (
    ("Numeric or date majority", MAJORITY_SHARE),
    ("Near-unique ratio", NEAR_UNIQUE_RATIO),
    ("Missing warning", MISSING_WARNING_SHARE),
    ("Non-negative share", NON_NEGATIVE_SHARE),
    ("Rare-negative share", RARE_NEGATIVE_SHARE),
    ("Category cardinality", CATEGORY_CARDINALITY),
    ("Outlier minimum", OUTLIER_MINIMUM),
    ("Outlier fence", OUTLIER_FENCE),
    ("Outlier distinct limit", OUTLIER_DISTINCT_LIMIT),
    ("Constant minimum", CONSTANT_MINIMUM),
    ("Example rows", EXAMPLE_ROW_LIMIT),
    ("Mixed-dialect count", MIXED_DIALECT_COUNT),
)


def missing_severity(share: float) -> Severity:
    if share >= MISSING_WARNING_SHARE:
        return Severity.WARNING
    return Severity.SUGGESTION


def apply_policy(
    findings: tuple[Finding, ...], affected_rows: pd.DataFrame
) -> tuple[tuple[Finding, ...], pd.DataFrame]:
    adjusted = tuple(_with_final_severity(finding) for finding in findings)
    return adjusted, _match_severity(adjusted, affected_rows)


def _with_final_severity(finding: Finding) -> Finding:
    severity = _final_severity(finding)
    if severity is finding.severity:
        return finding
    return replace(finding, severity=severity)


def _final_severity(finding: Finding) -> Severity:
    if finding.check_id == "missing_values":
        return missing_severity(finding.share)
    return finding.severity


def _match_severity(
    findings: tuple[Finding, ...], affected_rows: pd.DataFrame
) -> pd.DataFrame:
    if affected_rows.empty:
        return affected_rows
    matched = affected_rows.copy()
    for finding in findings:
        same_finding = matched["check_id"].eq(finding.check_id) & matched["column"].eq(
            finding.column
        )
        matched.loc[same_finding, "severity"] = finding.severity.value
    return matched
