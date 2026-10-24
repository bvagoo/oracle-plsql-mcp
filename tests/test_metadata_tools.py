import re

import pytest

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


class ViewDatabase:
    default_schema = "APP"

    def __init__(self):
        self.queries = []

    def rows(self, sql, binds=None, limit=500):
        placeholders = set(re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql))
        assert "view" not in {name.lower() for name in placeholders}, "VIEW is an Oracle reserved word"
        assert placeholders == set(binds)
        self.queries.append((sql, binds, limit))
        return [{"query_number": len(self.queries)}]


@pytest.mark.parametrize("owner, expected_owner", [(None, "APP"), ("other", "OTHER")])
def test_view_details_uses_valid_binds_and_returns_all_results(owner, expected_owner) -> None:
    database = ViewDatabase()
    result = MetadataTools(database).view_details(" orders_view ", owner)

    assert result == {
        "owner": expected_owner,
        "view_name": "ORDERS_VIEW",
        "view": {"query_number": 1},
        "columns": [{"query_number": 2}],
        "dependencies": [{"query_number": 3}],
    }
    assert len(database.queries) == 3
    for _, binds, _ in database.queries:
        assert binds == {"owner": expected_owner, "view_name": "ORDERS_VIEW"}
    assert "FROM all_views" in database.queries[0][0]
    assert "FROM all_tab_columns" in database.queries[1][0]
    assert "FROM all_dependencies" in database.queries[2][0]
