from __future__ import annotations

from .database import OracleDatabase, normalize_identifier, owner_or_default
from .validation import validate_explain_query


PLSQL_OBJECT_TYPES = {"PROCEDURE", "FUNCTION", "PACKAGE", "PACKAGE BODY", "TYPE", "TYPE BODY", "TRIGGER"}


class DiagnosticsTools:
    """Read-only diagnostics based on Oracle plan and error dictionary views."""

    def __init__(self, database: OracleDatabase):
        self.database = database

    def explain_sql_query(self, sql_text: str) -> dict:
        query = validate_explain_query(sql_text)
        return {"sql_text": query, "plan": self.database.explain(query)}

    def get_invalid_objects(self, owner: str | None = None, max_results: int = 200) -> dict:
        actual_owner = owner_or_default(self.database, owner)
        types = tuple(sorted(PLSQL_OBJECT_TYPES))
        placeholders = ", ".join(f":type_{index}" for index in range(len(types)))
        binds = {"owner": actual_owner, **{f"type_{index}": value for index, value in enumerate(types)}}
        objects = self.database.rows(f"""SELECT object_name, object_type, status, last_ddl_time
            FROM all_objects WHERE owner=:owner AND status='INVALID' AND object_type IN ({placeholders})
            ORDER BY object_type, object_name""", binds, min(max_results, 500))
        errors = self.database.rows(f"""SELECT name AS object_name, type AS object_type, sequence, line, position, text, attribute, message_number
            FROM all_errors WHERE owner=:owner AND type IN ({placeholders})
            ORDER BY name, type, sequence""", binds, 10000)
        errors_by_object: dict[tuple[str, str], list[dict]] = {}
        for error in errors:
            errors_by_object.setdefault((error["object_name"], error["object_type"]), []).append(error)
        invalid_objects = [{**item, "errors": errors_by_object.get((item["object_name"], item["object_type"]), [])} for item in objects]
        return {"owner": actual_owner, "invalid_objects": invalid_objects}

    def check_syntax_errors(self, object_name: str, owner: str | None = None) -> dict:
        name = normalize_identifier(object_name)
        current_user = str(self.database.scalar("SELECT USER FROM DUAL"))
        actual_owner = owner_or_default(self.database, owner)
        if actual_owner == current_user:
            errors = self.database.rows("""SELECT name AS object_name, type AS object_type, sequence, line, position, text, attribute, message_number
                FROM user_errors WHERE name=:name ORDER BY type, sequence""", {"name": name}, 1000)
            source_view = "USER_ERRORS"
        else:
            errors = self.database.rows("""SELECT name AS object_name, type AS object_type, sequence, line, position, text, attribute, message_number
                FROM all_errors WHERE owner=:owner AND name=:name ORDER BY type, sequence""", {"owner": actual_owner, "name": name}, 1000)
            source_view = "ALL_ERRORS"
        return {"owner": actual_owner, "object_name": name, "source_view": source_view, "errors": errors, "ok": not errors}

    def scheduler_jobs(self, owner: str | None = None, max_results: int = 200) -> dict:
        actual_owner = owner_or_default(self.database, owner)
        limit = min(max_results, 500)
        jobs = self.database.rows("""SELECT owner, job_name, job_style, job_type, job_action,
                program_owner, program_name, schedule_owner, schedule_name, enabled, state,
                last_start_date, next_run_date, run_count, failure_count
            FROM all_scheduler_jobs WHERE owner=:owner ORDER BY job_name""", {"owner": actual_owner}, limit)
        programs = self.database.rows("""SELECT owner, program_name, program_type, program_action,
                number_of_arguments, enabled
            FROM all_scheduler_programs WHERE owner=:owner ORDER BY program_name""", {"owner": actual_owner}, limit)
        return {"owner": actual_owner, "jobs": jobs, "programs": programs}

    def sql_plan_baseline_info(self, sql_handle: str | None = None, plan_name: str | None = None, max_results: int = 100) -> dict:
        """Return baselines visible to the connected user; Oracle exposes no ALL_* baseline view."""
        sql = """SELECT sql_handle, plan_name, enabled, accepted, fixed, reproduced, autopurge,
                origin, creator, created, last_modified, last_executed, executions, version
            FROM user_sql_plan_baselines WHERE 1=1"""
        binds: dict[str, str] = {}
        if sql_handle:
            sql += " AND sql_handle=:sql_handle"
            binds["sql_handle"] = sql_handle.strip()
        if plan_name:
            sql += " AND plan_name=:plan_name"
            binds["plan_name"] = plan_name.strip()
        baselines = self.database.rows(sql + " ORDER BY sql_handle, plan_name", binds, min(max_results, 500))
        return {"source_view": "USER_SQL_PLAN_BASELINES", "baselines": baselines}

    def session_context(self) -> dict:
        """Return connection context that affects object resolution and SQL interpretation."""
        context = self.database.rows("""SELECT USER AS session_user,
                SYS_CONTEXT('USERENV', 'CURRENT_USER') AS current_user,
                SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS current_schema,
                SYS_CONTEXT('USERENV', 'DB_NAME') AS database_name,
                SYS_CONTEXT('USERENV', 'DB_UNIQUE_NAME') AS database_unique_name,
                SYS_CONTEXT('USERENV', 'SERVICE_NAME') AS service_name,
                SYS_CONTEXT('USERENV', 'CON_NAME') AS container_name,
                SYS_CONTEXT('USERENV', 'LANGUAGE') AS language,
                SYS_CONTEXT('USERENV', 'NLS_DATE_FORMAT') AS nls_date_format
            FROM dual""", limit=1)
        version = self.database.rows("""SELECT version FROM product_component_version
            WHERE product LIKE 'Oracle Database%'""", limit=1)
        return {"session": context[0] if context else None,
                "database_version": version[0]["version"] if version else None}
