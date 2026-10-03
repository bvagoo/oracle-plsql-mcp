from __future__ import annotations

import atexit
import os
from typing import Any

from fastmcp import FastMCP

from .config import Settings
from .database import OracleDatabase, normalize_identifier, owner_or_default
from .diagnostics_tools import DiagnosticsTools
from .metadata_tools import MetadataTools
from .plsql_tools import PlsqlTools


def create_server(settings: Settings | None = None) -> FastMCP:
    """Create the MCP adapter and register domain-specific tool handlers."""
    database = OracleDatabase(settings or Settings.load())
    atexit.register(database.close)
    metadata, diagnostics, plsql = MetadataTools(database), DiagnosticsTools(database), PlsqlTools(database)
    mcp = FastMCP("Oracle PL/SQL Analysis MCP", instructions=(
        "Read-only Oracle schema and PL/SQL analysis. Use explicit owner where an object may be ambiguous. "
        "Static analysis is evidence-based; dynamic SQL is reported as uncertain, never guessed."))

    @mcp.tool(description="Verify the Oracle connection with SELECT 1 FROM DUAL.")
    def ping_oracle() -> dict: return {"ok": database.scalar("SELECT 1 FROM DUAL") == 1}

    @mcp.tool(description="Generate an Oracle EXPLAIN PLAN for a single, non-locking SELECT or WITH query. Requires an accessible PLAN_TABLE.")
    def explain_sql_query(sql_text: str) -> dict: return diagnostics.explain_sql_query(sql_text)

    @mcp.tool(description="List accessible tables from ALL_TABLES for an owner or the configured default schema.")
    def list_tables(owner: str | None = None, max_results: int = 200) -> dict: return metadata.list_tables(owner, max_results)

    @mcp.tool(description="Describe a table's columns using ALL_TAB_COLUMNS. Read-only metadata only.")
    def describe_table(table_name: str, owner: str | None = None) -> dict: return metadata.describe_table(table_name, owner)

    @mcp.tool(description="Return columns, nullability, statistics, indexes, index columns, constraints, and constraint columns for a table.")
    def get_table_structure_details(table_name: str, owner: str | None = None) -> dict: return metadata.table_structure_details(table_name, owner)

    @mcp.tool(description="Return object- and column-level grants visible through ALL_TAB_PRIVS and ALL_COL_PRIVS.")
    def get_object_privileges(object_name: str, owner: str | None = None, max_results: int = 200) -> dict: return metadata.object_privileges(object_name, owner, max_results)

    @mcp.tool(description="Return incoming and outgoing foreign-key relationships for a table, including mapped columns and delete rules.")
    def get_table_relationships(table_name: str, owner: str | None = None) -> dict: return metadata.table_relationships(table_name, owner)

    @mcp.tool(description="Return grants and synonyms that resolve to an accessible object.")
    def get_object_grants_and_synonyms(object_name: str, owner: str | None = None, max_results: int = 200) -> dict: return metadata.object_grants_and_synonyms(object_name, owner, max_results)

    @mcp.tool(description="Return triggers, materialized-view logs, and VPD policies attached to a table.")
    def get_table_automation(table_name: str, owner: str | None = None) -> dict: return metadata.table_automation(table_name, owner)

    @mcp.tool(description="Return a table's partitioning scheme, partition keys, partitions, and partitioned indexes.")
    def get_partition_details(table_name: str, owner: str | None = None, max_results: int = 500) -> dict: return metadata.partition_details(table_name, owner, max_results)

    @mcp.tool(description="Return a view's query text, projected columns, and direct Oracle dictionary dependencies.")
    def get_view_definition_and_dependencies(view_name: str, owner: str | None = None) -> dict: return metadata.view_details(view_name, owner)

    @mcp.tool(description="Return table- and column-level optimizer statistics, histograms, locks, and stale-statistics status.")
    def get_table_statistics(table_name: str, owner: str | None = None) -> dict: return metadata.table_statistics(table_name, owner)

    @mcp.tool(description="Return index definitions, health, optimizer statistics, and columns. It does not claim historical runtime usage.")
    def get_index_usage(table_name: str, owner: str | None = None) -> dict: return metadata.index_usage(table_name, owner)

    @mcp.tool(description="Find stale table statistics, invalid objects, and non-valid indexes. Standard ALL_* views cannot prove an object is unused.")
    def find_unused_or_stale_objects(owner: str | None = None, max_results: int = 200) -> dict: return metadata.unused_or_stale_objects(owner, max_results)

    @mcp.tool(description="Search accessible Oracle objects by name, type, or status using ALL_OBJECTS.")
    def search_objects(keyword: str, owner: str | None = None, object_type: str | None = None, max_results: int = 100) -> dict: return metadata.search_objects(keyword, owner, object_type, max_results)

    @mcp.tool(description="Return ordered source lines for a stored PL/SQL object. Includes package specs and bodies when accessible.")
    def get_object_source(object_name: str, owner: str | None = None, object_type: str | None = None) -> dict: return plsql.get_object_source(object_name, owner, object_type)

    @mcp.tool(description="Search ALL_SOURCE with matching source line evidence. Use this for broad PL/SQL text discovery.")
    def search_source(keyword: str, owner: str | None = None, object_type: str | None = None, max_results: int = 100) -> dict: return plsql.search_source(keyword, owner, object_type, max_results)

    @mcp.tool(description="Find direct Oracle dictionary dependencies of an object.")
    def find_object_dependencies(object_name: str, owner: str | None = None, object_type: str | None = None) -> dict: return metadata.find_dependencies(object_name, owner, object_type)

    @mcp.tool(description="Find objects that directly depend on the given Oracle object.")
    def find_object_dependents(object_name: str, owner: str | None = None) -> dict: return metadata.find_dependents(object_name, owner)

    @mcp.tool(description="Get object DDL from DBMS_METADATA. Access depends on Oracle privileges.")
    def get_object_ddl(object_name: str, object_type: str, owner: str | None = None) -> dict: return metadata.get_object_ddl(object_name, object_type, owner)

    @mcp.tool(description="List invalid PL/SQL objects and their Oracle compilation errors for an owner or the configured default schema.")
    def get_invalid_objects(owner: str | None = None, max_results: int = 200) -> dict: return diagnostics.get_invalid_objects(owner, max_results)

    @mcp.tool(description="Return the latest Oracle compilation errors for an object without recompiling it. Uses USER_ERRORS for the connected schema and ALL_ERRORS for another accessible owner.")
    def check_syntax_errors(object_name: str, owner: str | None = None) -> dict: return diagnostics.check_syntax_errors(object_name, owner)

    @mcp.tool(description="List accessible DBMS_SCHEDULER jobs and programs for an owner, including state and run counters.")
    def get_scheduler_jobs(owner: str | None = None, max_results: int = 200) -> dict: return diagnostics.scheduler_jobs(owner, max_results)

    @mcp.tool(description="Return SQL plan baselines belonging to the connected user. Optionally filter by exact SQL handle or plan name.")
    def get_sql_plan_baseline_info(sql_handle: str | None = None, plan_name: str | None = None, max_results: int = 100) -> dict: return diagnostics.sql_plan_baseline_info(sql_handle, plan_name, max_results)

    @mcp.tool(description="Return the connected session's user, schema, database, service, PDB/container, NLS context, and Oracle version.")
    def get_session_context() -> dict: return diagnostics.session_context()

    @mcp.tool(description="Map accessible package procedures/functions and their parameters. Uses USER_PROCEDURES and USER_ARGUMENTS for the connected schema, or ALL_* views for another accessible owner.")
    def get_package_hierarchy(package_name: str, owner: str | None = None) -> dict: return plsql.package_hierarchy(package_name, owner)

    @mcp.tool(description="Return a standalone or packaged procedure/function's overloads, argument directions, types, defaults, and return values.")
    def get_routine_signature(routine_name: str, owner: str | None = None, package_name: str | None = None) -> dict: return plsql.routine_signature(routine_name, owner, package_name)

    @mcp.tool(description="Return a trigger's event metadata, source lines, and direct Oracle dictionary dependencies.")
    def get_trigger_source_and_dependencies(trigger_name: str, owner: str | None = None) -> dict:
        actual_owner, trigger = owner_or_default(database, owner), normalize_identifier(trigger_name)
        binds = {"owner": actual_owner, "trigger": trigger}
        trigger_rows = database.rows("""SELECT owner, trigger_name, table_owner, table_name, triggering_event,
                trigger_type, status, when_clause, description
            FROM all_triggers WHERE owner=:owner AND trigger_name=:trigger""", binds, 1)
        source = database.rows("""SELECT line, text FROM all_source
            WHERE owner=:owner AND name=:trigger AND type='TRIGGER' ORDER BY line""", binds, 20000)
        dependencies = database.rows("""SELECT referenced_owner, referenced_name, referenced_type, dependency_type
            FROM all_dependencies WHERE owner=:owner AND name=:trigger AND type='TRIGGER'
            ORDER BY referenced_owner, referenced_name, referenced_type""", binds, 1000)
        return {"owner": actual_owner, "trigger_name": trigger,
                "trigger": trigger_rows[0] if trigger_rows else None, "source": source,
                "dependencies": dependencies}

    @mcp.tool(description="Find declarations of a PL/SQL symbol with exact line evidence.")
    def find_plsql_symbol(symbol: str, owner: str | None = None, object_name: str | None = None, max_results: int = 100) -> dict: return plsql.find_symbol(symbol, owner, object_name, max_results)

    @mcp.tool(description="Find textual PL/SQL usages of a symbol with exact source-line evidence.")
    def find_plsql_references(symbol: str, owner: str | None = None, object_name: str | None = None, max_results: int = 100) -> dict: return plsql.find_references(symbol, owner, object_name, max_results)

    @mcp.tool(description="Find PL/SQL units that call a procedure/function.")
    def find_plsql_callers(symbol: str, owner: str | None = None, max_results: int = 100) -> dict: return plsql.find_callers(symbol, owner, max_results)

    @mcp.tool(description="Find routine calls made by a PL/SQL object.")
    def find_plsql_callees(object_name: str, owner: str | None = None, object_type: str | None = None) -> dict: return plsql.find_callees(object_name, owner, object_type)

    @mcp.tool(description="Build a bounded static PL/SQL call graph from an entry object.")
    def get_plsql_call_graph(object_name: str, owner: str | None = None, max_depth: int = 3, max_nodes: int = 100) -> dict: return plsql.call_graph(object_name, owner, max_depth, max_nodes)

    @mcp.tool(description="Extract static DML target objects used by a PL/SQL routine.")
    def get_routine_data_access(object_name: str, owner: str | None = None, object_type: str | None = None) -> dict: return plsql.routine_data_access(object_name, owner, object_type)

    @mcp.tool(description="Find EXECUTE IMMEDIATE and OPEN ... FOR uses with source-line evidence.")
    def find_dynamic_sql(object_name: str | None = None, owner: str | None = None, max_results: int = 100) -> dict: return plsql.find_dynamic_sql(object_name, owner, max_results)

    @mcp.tool(description="Find lexical PL/SQL evidence that a table column is used. Qualified references are strongest; aliases and dynamic SQL require review.")
    def find_column_usage(table_name: str, column_name: str, owner: str | None = None, max_results: int = 100) -> dict: return plsql.find_column_usage(table_name, column_name, owner, max_results)

    @mcp.tool(description="Analyze likely impact of changing an Oracle object.")
    def analyze_db_change_impact(object_name: str, owner: str | None = None, change_kind: str = "object", max_results: int = 200) -> dict: return plsql.analyze_change_impact(object_name, owner, change_kind, max_results)

    return mcp


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    options: dict[str, Any] = {"transport": transport}
    if transport != "stdio":
        options["host"] = os.getenv("MCP_HOST", "127.0.0.1")
        options["port"] = int(os.getenv("MCP_PORT", "8000"))
    create_server().run(**options)
