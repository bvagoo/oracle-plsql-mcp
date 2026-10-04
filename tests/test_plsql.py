from oracle_plsql_mcp.plsql import calls, data_access, dynamic_sql, symbol_declarations


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
    assert dynamic_sql(SOURCE) == [{"line": 6, "text": "    EXECUTE IMMEDIATE 'DELETE FROM audit_log';",
                                    "risk": "dynamic SQL cannot be resolved reliably"}]


def test_symbol_declaration_has_evidence() -> None:
    assert symbol_declarations(SOURCE, "RUN_JOB")[0]["line"] == 2


def test_static_analysis_ignores_comments_strings_and_insert_column_lists() -> None:
    source = """BEGIN
  -- ignored_api.call(1); UPDATE hidden_table SET x = 1;
  message := 'ignored_api.call(2)';
  /* DELETE FROM hidden_table; */
  real_api.call(3);
  INSERT INTO visible_table (id) VALUES (1);
END;"""

    assert calls(source) == {"REAL_API.CALL": 1}
    assert data_access(source) == {"select": [], "insert": ["VISIBLE_TABLE"],
                                   "update": [], "delete": [], "merge": []}


def test_dynamic_sql_flags_open_for_with_source_line() -> None:
    source = "BEGIN\n  OPEN result_cursor FOR query_text;\nEND;"
    assert dynamic_sql(source) == [{"line": 2, "text": "  OPEN result_cursor FOR query_text;",
                                    "risk": "dynamic SQL cannot be resolved reliably"}]
