from oracle_plsql_mcp.plsql import calls, data_access, dynamic_sql, symbol_declarations
from oracle_plsql_mcp.diagnostics_tools import DiagnosticsTools
from oracle_plsql_mcp.metadata_tools import MetadataTools
from oracle_plsql_mcp.plsql_tools import PlsqlTools
from oracle_plsql_mcp.validation import validate_explain_query


SOURCE = """CREATE OR REPLACE PACKAGE BODY demo AS
  PROCEDURE run_job IS
  BEGIN
    order_api.save(1);
    UPDATE orders SET processed = 1;
    EXECUTE IMMEDIATE 'DELETE FROM audit_log';
  END;
END;
"""


def test_static_calls_and_data_access_are_found() -> None:
    assert calls(SOURCE)["ORDER_API.SAVE"] == 1
    assert data_access(SOURCE)["update"] == ["ORDERS"]


def test_dynamic_sql_is_explicitly_not_resolved() -> None:
    result = dynamic_sql(SOURCE)
    assert result == [{"line": 6, "text": "    EXECUTE IMMEDIATE 'DELETE FROM audit_log';", "risk": "dynamic SQL cannot be resolved reliably"}]


def test_symbol_declaration_has_evidence() -> None:
    result = symbol_declarations(SOURCE, "RUN_JOB")
    assert result[0]["line"] == 2


def test_explain_accepts_select_only() -> None:
    assert validate_explain_query("SELECT * FROM demo") == "SELECT * FROM demo"
    try:
        validate_explain_query("DELETE FROM demo")
    except ValueError as error:
        assert "SELECT" in str(error)
    else:
        raise AssertionError("DML must not be accepted by explain_sql_query")


class SourceDatabase:
    default_schema = "APP"

    def scalar(self, sql, binds=None):
        assert sql == "SELECT USER FROM DUAL"
        return "APP"

    def rows(self, sql, binds=None, limit=500):
        assert "all_source" in sql.lower()
        return [
            {"name": "ORDERS_API", "type": "PACKAGE BODY", "line": 4, "text": "  SELECT o.status FROM orders o;"},
            {"name": "ORDERS_API", "type": "PACKAGE BODY", "line": 5, "text": "  IF orders.status = 'NEW' THEN NULL; END IF;"},
        ]


def test_column_usage_distinguishes_direct_and_candidate_evidence() -> None:
    result = PlsqlTools(SourceDatabase()).find_column_usage("orders", "status")
    assert result["direct_qualified_references"][0]["confidence"] == "direct qualified reference"
    assert result["candidate_source_units"][0]["object_name"] == "ORDERS_API"
    assert "lexical evidence" in result["resolution"]


class DictionaryDatabase:
    default_schema = "APP"

    def __init__(self):
        self.queries = []

    def rows(self, sql, binds=None, limit=500):
        self.queries.append(sql)
        normalized = " ".join(sql.lower().split())
        if "all_procedures" in normalized:
            return [{"object_name": "ORDER_API", "procedure_name": "SAVE", "subprogram_id": 2, "overload": None}]
        if "all_arguments" in normalized:
            return [{"subprogram_id": 2, "argument_name": "P_ID", "position": 1, "sequence": 1}]
        if "all_tab_statistics" in normalized:
            return [{"num_rows": 12, "stale_stats": "YES"}]
        if "all_tab_col_statistics" in normalized:
            return [{"column_name": "ID", "num_distinct": 12}]
        if "product_component_version" in normalized:
            return [{"version": "23.0"}]
        if "from dual" in normalized:
            return [{"session_user": "APP", "current_schema": "APP"}]
        return []


def test_routine_signature_groups_arguments_by_overload() -> None:
    result = PlsqlTools(DictionaryDatabase()).routine_signature("save", package_name="order_api")
    assert result["package_name"] == "ORDER_API"
    assert result["overloads"][0]["arguments"][0]["argument_name"] == "P_ID"


def test_statistics_and_session_tools_return_structured_dictionary_results() -> None:
    database = DictionaryDatabase()
    statistics = MetadataTools(database).table_statistics("orders")
    context = DiagnosticsTools(database).session_context()
    assert statistics["table_statistics"]["stale_stats"] == "YES"
    assert statistics["column_statistics"][0]["column_name"] == "ID"
    assert context["database_version"] == "23.0"
