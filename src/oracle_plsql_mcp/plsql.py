from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


PLSQL_TYPES = ("PACKAGE", "PACKAGE BODY", "PROCEDURE", "FUNCTION", "TRIGGER", "TYPE", "TYPE BODY")
IDENTIFIER = r"[A-Z][A-Z0-9_$#]*"


def source_text(rows: list[dict]) -> str:
    return "\n".join(str(row.get("text", "")) for row in rows)


def scrub(source: str) -> str:
    """Retain line count while removing comments and quoted values from static analysis."""
    source = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.S)
    source = re.sub(r"--[^\n]*", "", source)
    return re.sub(r"'(?:''|[^'])*'", "''", source, flags=re.S)


def lines_matching(source: str, pattern: str, limit: int = 100) -> list[dict]:
    expression = re.compile(pattern, re.I)
    return [{"line": number, "text": line.rstrip()} for number, line in enumerate(source.splitlines(), 1)
            if expression.search(line)][:limit]


def symbol_declarations(source: str, symbol: str) -> list[dict]:
    name = re.escape(symbol.upper())
    return lines_matching(source, rf"\b(PROCEDURE|FUNCTION|TYPE|SUBTYPE|CURSOR)\s+{name}\b|\b{ name }\s+(CONSTANT|EXCEPTION|[A-Z][A-Z0-9_$#]*(?:\s*\([^)]*\))?)")


def calls(source: str) -> Counter[str]:
    cleaned = scrub(source).upper()
    # An INSERT target followed by a column list has the same shape as a call.
    cleaned = re.sub(rf"\bINSERT\s+INTO\s+(?:{IDENTIFIER}\.)?{IDENTIFIER}(?=\s*\()",
                     lambda match: " " * len(match.group(0)), cleaned)
    ignored = {"IF", "ELSIF", "WHILE", "LOOP", "FOR", "CASE", "NVL", "TO_CHAR", "TO_DATE", "COUNT", "SUM", "MAX", "MIN", "SUBSTR", "RAISE", "RETURN", "OPEN", "CLOSE", "VALUES"}
    found = re.findall(rf"\b({IDENTIFIER})(?:\s*\.\s*({IDENTIFIER}))?\s*\(", cleaned)
    return Counter(".".join(part for part in pair if part) for pair in found if pair[-1] not in ignored and pair[0] not in ignored)


def data_access(source: str) -> dict:
    cleaned = scrub(source).upper()
    patterns = {
        "select": rf"\bSELECT\b[\s\S]*?\bFROM\s+((?:{IDENTIFIER}\.)?{IDENTIFIER})",
        "insert": rf"\bINSERT\s+INTO\s+((?:{IDENTIFIER}\.)?{IDENTIFIER})",
        "update": rf"\bUPDATE\s+((?:{IDENTIFIER}\.)?{IDENTIFIER})",
        "delete": rf"\bDELETE\s+FROM\s+((?:{IDENTIFIER}\.)?{IDENTIFIER})",
        "merge": rf"\bMERGE\s+INTO\s+((?:{IDENTIFIER}\.)?{IDENTIFIER})",
    }
    return {kind: sorted(set(re.findall(pattern, cleaned, re.I))) for kind, pattern in patterns.items()}


def dynamic_sql(source: str) -> list[dict]:
    lines = source.splitlines()
    matches = []
    for number, line in enumerate(lines, 1):
        if re.search(r"\bEXECUTE\s+IMMEDIATE\b|\bOPEN\s+\w+\s+FOR\b", line, re.I):
            matches.append({"line": number, "text": line.rstrip(), "risk": "dynamic SQL cannot be resolved reliably"})
    return matches
