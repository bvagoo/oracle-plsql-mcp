from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

import oracledb

from .config import Settings


class OracleDatabase:
    """Small read-only wrapper. Every query uses binds; no business DML API is exposed."""

    def __init__(self, settings: Settings):
        connect = {"user": settings.user, "password": settings.password, "dsn": settings.dsn,
                   "min": settings.pool_min, "max": settings.pool_max, "increment": 1}
        if settings.config_dir:
            connect["config_dir"] = settings.config_dir
        if settings.wallet_location:
            connect["wallet_location"] = settings.wallet_location
        if settings.wallet_password:
            connect["wallet_password"] = settings.wallet_password
        self.pool = oracledb.create_pool(**connect)
        self.default_schema = normalize_identifier(settings.default_schema) if settings.default_schema else None

    @contextmanager
    def connection(self) -> Iterator[oracledb.Connection]:
        connection = self.pool.acquire()
        try:
            yield connection
        finally:
            connection.close()

    def rows(self, sql: str, binds: Mapping[str, Any] | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, binds or {})
            columns = [item[0].lower() for item in cursor.description]
            fetched = cursor.fetchmany(limit + 1)
            result = [dict(zip(columns, row)) for row in fetched[:limit]]
            if len(fetched) > limit:
                result.append({"_truncated": True, "_limit": limit})
            return _json_safe(result)

    def scalar(self, sql: str, binds: Mapping[str, Any] | None = None) -> Any:
        rows = self.rows(sql, binds, 1)
        return next(iter(rows[0].values())) if rows else None

    def explain(self, sql_text: str) -> list[str]:
        """Build and return a DBMS_XPLAN plan using the session's PLAN_TABLE."""
        import uuid

        statement_id = f"MCP_{uuid.uuid4().hex}"
        with self.connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(f"EXPLAIN PLAN SET STATEMENT_ID = '{statement_id}' FOR {sql_text}")
                cursor.execute("SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', :statement_id, 'TYPICAL'))", {"statement_id": statement_id})
                return [str(row[0]) for row in cursor.fetchall()]
            finally:
                cursor.execute("DELETE FROM plan_table WHERE statement_id=:statement_id", {"statement_id": statement_id})
                connection.commit()

    def close(self) -> None:
        self.pool.close(force=True)


def normalize_identifier(value: str | None) -> str:
    if not value or not value.strip():
        raise ValueError("Oracle identifier is required.")
    value = value.strip().upper()
    if not value.replace("_", "A").replace("$", "A").replace("#", "A").isalnum():
        raise ValueError("Identifier may contain only letters, digits, _, $, and #.")
    return value


def owner_or_default(database: OracleDatabase, owner: str | None) -> str:
    return normalize_identifier(owner) if owner else (database.default_schema or database.scalar("SELECT USER FROM DUAL"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, list): return [_json_safe(v) for v in value]
    if isinstance(value, dict): return {key: _json_safe(val) for key, val in value.items()}
    if hasattr(value, "read"): return value.read()
    if hasattr(value, "isoformat"): return value.isoformat()
    return value
