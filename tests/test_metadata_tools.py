from oracle_plsql_mcp.metadata_tools import MetadataTools


class StatisticsDatabase:
    default_schema = "APP"

    def rows(self, sql, binds=None, limit=500):
        normalized = " ".join(sql.lower().split())
        if "all_tab_statistics" in normalized:
            return [{"num_rows": 12, "stale_stats": "YES"}]
        if "all_tab_col_statistics" in normalized:
            return [{"column_name": "ID", "num_distinct": 12}]
        return []


def test_table_statistics_returns_table_and_column_results() -> None:
    result = MetadataTools(StatisticsDatabase()).table_statistics("orders")
    assert result["table_statistics"]["stale_stats"] == "YES"
    assert result["column_statistics"][0]["column_name"] == "ID"
