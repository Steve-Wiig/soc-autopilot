"""Shared queue-priority policy for the numeric Wazuh queue contract."""

from __future__ import annotations

from numbers import Real


DEFAULT_PRIORITY = 5

# Lower queue priority number means earlier worker claim.
# Wazuh intake normalizes rule levels to the inclusive range 0..5.
NUMERIC_SEVERITY_PRIORITY: dict[int, int] = {
    0: 5,
    1: 5,
    2: 4,
    3: 3,
    4: 2,
    5: 1,
}

STRING_SEVERITY_PRIORITY: dict[str, int] = {
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
}


def severity_to_priority(severity: object) -> int:
    """Map a legacy numeric or string severity to queue priority.

    Numeric behavior intentionally mirrors the worker's migration semantics:
    >=5 -> 1, 4 -> 2, 3 -> 3, 2 -> 4, 0/1 -> 5, everything else -> 5.
    String behavior supports the worker's named-severity compatibility path.
    """
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
    """Return the canonical SQLite CASE expression for queue priority."""
    if not column.replace("_", "").isalnum():
        raise ValueError("column must contain only simple identifier characters")

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
