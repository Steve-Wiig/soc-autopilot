"""Shared queue-priority policy for the numeric Wazuh queue contract."""

from __future__ import annotations

from numbers import Real
from typing import Union

# Public type alias documenting the accepted severity inputs.
# Numeric severities are Wazuh rule levels (int/float, normalized 0..5).
# String severities are legacy/compatibility named levels.
SeverityInput = Union[int, float, str]


DEFAULT_PRIORITY = 5

# Lower queue priority number means earlier worker claim.
# Wazuh intake normalizes rule levels to the inclusive range 0..5.
#
# NOTE: This table documents the numeric severity -> priority contract for
# external consumers. `severity_to_priority` does not look values up in this
# dict directly (it uses equivalent inline comparisons to match the
# worker's migration semantics), but the mapping here must stay in sync
# with that logic.
NUMERIC_SEVERITY_PRIORITY: dict[int, int] = {
    0: 5,
    1: 5,
    2: 4,
    3: 3,
    4: 2,
    5: 1,
}

# Legacy/compatibility mapping from named severities to queue priority.
# Used directly by `severity_to_priority` for non-numeric inputs.
STRING_SEVERITY_PRIORITY: dict[str, int] = {
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
}


def severity_to_priority(severity: SeverityInput) -> int:
    """Map a legacy numeric or string severity to queue priority.

    Numeric behavior intentionally mirrors the worker's migration semantics:
    >=5 -> 1, 4 -> 2, 3 -> 3, 2 -> 4, 0/1 -> 5, everything else -> 5.
    String behavior supports the worker's named-severity compatibility path.

    Args:
        severity: A Wazuh rule level (int/float) or a legacy named severity
            string (e.g. "critical", "high", "medium", "low"). Any other
            value falls back to `DEFAULT_PRIORITY`.

    Returns:
        The resolved integer queue priority, where a lower number means the
        item is claimed earlier by workers.
    """
    # `bool` is a subclass of `int`, which is a subclass of `numbers.Real`,
    # so it must be checked before the `Real` branch to avoid misclassifying
    # True/False as numeric severities.
    if isinstance(severity, bool):
        return DEFAULT_PRIORITY

    if isinstance(severity, Real):
        numeric = int(severity)

        if numeric >= 5:
            return 1
        if numeric == 4:
            return 2
        if numeric == 3:
            return 3
        if numeric == 2:
            return 4
        if numeric in (0, 1):
            return 5

        return DEFAULT_PRIORITY

    normalized = str(severity).strip().lower()

    return STRING_SEVERITY_PRIORITY.get(
        normalized,
        DEFAULT_PRIORITY,
    )


def priority_case_sql(column: str = "severity") -> str:
    """Return the canonical SQLite CASE expression for queue priority.

    The returned SQL fragment mirrors the semantics of
    `severity_to_priority`, allowing the same numeric/string priority
    resolution to be expressed directly in a SQL query (e.g. for ORDER BY
    clauses).

    Args:
        column: The name of the column holding the severity value. Must
            contain only simple identifier characters (alphanumeric plus
            underscore) to guard against SQL injection, since this value is
            interpolated directly into the returned SQL string.

    Returns:
        A SQLite `CASE ... END` SQL expression (as a string) that resolves
        the given column's severity to an integer queue priority.

    Raises:
        ValueError: If `column` contains characters other than letters,
            digits, and underscores.
    """
    if not column.replace("_", "").isalnum():
        raise ValueError(
            "column must contain only simple identifier characters "
            "(letters, digits, and underscores)"
        )

    return f"""
        CASE
            WHEN typeof({column}) IN ('integer', 'real') THEN
                CASE
                    WHEN CAST({column} AS INTEGER) >= 5 THEN 1
                    WHEN CAST({column} AS INTEGER) = 4 THEN 2
                    WHEN CAST({column} AS INTEGER) = 3 THEN 3
                    WHEN CAST({column} AS INTEGER) = 2 THEN 4
                    WHEN CAST({column} AS INTEGER) IN (0, 1) THEN 5
                    ELSE {DEFAULT_PRIORITY}
                END
            WHEN lower(trim(CAST({column} AS TEXT))) = 'critical' THEN 1
            WHEN lower(trim(CAST({column} AS TEXT))) = 'high' THEN 2
            WHEN lower(trim(CAST({column} AS TEXT))) = 'medium' THEN 3
            WHEN lower(trim(CAST({column} AS TEXT))) = 'low' THEN 4
            ELSE {DEFAULT_PRIORITY}
        END
    """.strip()
