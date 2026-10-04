from oracle_plsql_mcp.diagnostics_tools import DiagnosticsTools


class SessionDatabase:
    def rows(self, sql, binds=None, limit=500):
        if "product_component_version" in sql.lower():
            return [{"version": "23.0"}]
        if "from dual" in sql.lower():
            return [{"session_user": "APP", "current_schema": "APP"}]
        raise AssertionError(f"Unexpected query: {sql}")


def test_session_context_includes_database_version() -> None:
    result = DiagnosticsTools(SessionDatabase()).session_context()
    assert result["database_version"] == "23.0"
