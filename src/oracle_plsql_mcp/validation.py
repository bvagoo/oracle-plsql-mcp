from __future__ import annotations

import re


def validate_explain_query(sql_text: str) -> str:
    """Permit only one non-locking SELECT statement for EXPLAIN PLAN."""
    query = sql_text.strip()
    if not re.match(r"^(SELECT|WITH)\b", query, re.IGNORECASE):
        raise ValueError("explain_sql_query accepts only SELECT or WITH queries.")
    if ";" in query or re.search(r"\bFOR\s+UPDATE\b", query, re.IGNORECASE):
        raise ValueError("The query must be a single non-locking SELECT statement.")
    return query
