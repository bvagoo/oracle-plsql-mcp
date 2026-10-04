from __future__ import annotations

from datetime import date

import pytest

from oracle_plsql_mcp.database import OracleDatabase


class FakeCursor:
    description = [("VALUE",), ("CREATED",)]

    def __init__(self, *, fail_plan_display: bool = False) -> None:
        self.fail_plan_display = fail_plan_display
        self.executed: list[tuple[str, dict]] = []
        self.fetch_limit: int | None = None

    def execute(self, sql: str, binds: dict | None = None) -> None:
        self.executed.append((sql, binds or {}))
        if self.fail_plan_display and "DBMS_XPLAN.DISPLAY" in sql:
            raise RuntimeError("plan display failed")

    def fetchmany(self, limit: int) -> list[tuple]:
        self.fetch_limit = limit
        return [("first", date(2026, 1, 2)), ("second", date(2026, 1, 3)),
                ("third", date(2026, 1, 4))][:limit]

    def fetchall(self) -> list[tuple]:
        return [("plan line",)]


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False
        self.committed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None:
        self.committed = True


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> FakeConnection:
        return self.connection


def database_with_cursor(cursor: FakeCursor) -> tuple[OracleDatabase, FakeConnection]:
    connection = FakeConnection(cursor)
    database = OracleDatabase.__new__(OracleDatabase)
    database.pool = FakePool(connection)
    return database, connection


def test_rows_uses_binds_marks_truncation_and_releases_connection() -> None:
    cursor = FakeCursor()
    database, connection = database_with_cursor(cursor)

    rows = database.rows("SELECT value, created FROM events WHERE owner=:owner", {"owner": "APP"}, limit=2)

    assert rows == [
        {"value": "first", "created": "2026-01-02"},
        {"value": "second", "created": "2026-01-03"},
        {"_truncated": True, "_limit": 2},
    ]
    assert cursor.executed == [("SELECT value, created FROM events WHERE owner=:owner", {"owner": "APP"})]
    assert cursor.fetch_limit == 3
    assert connection.closed


def test_explain_cleans_plan_table_and_releases_connection_on_failure() -> None:
    cursor = FakeCursor(fail_plan_display=True)
    database, connection = database_with_cursor(cursor)

    with pytest.raises(RuntimeError, match="plan display failed"):
        database.explain("SELECT * FROM orders")

    assert len(cursor.executed) == 3
    assert cursor.executed[0][0].startswith("EXPLAIN PLAN SET STATEMENT_ID = 'MCP_")
    assert "DBMS_XPLAN.DISPLAY" in cursor.executed[1][0]
    assert cursor.executed[2][0] == "DELETE FROM plan_table WHERE statement_id=:statement_id"
    assert cursor.executed[1][1]["statement_id"] == cursor.executed[2][1]["statement_id"]
    assert connection.committed
    assert connection.closed
