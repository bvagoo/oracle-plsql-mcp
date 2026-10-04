import pytest

from oracle_plsql_mcp.database import normalize_identifier
from oracle_plsql_mcp.validation import validate_explain_query


def test_explain_accepts_single_select_query() -> None:
    assert validate_explain_query("SELECT * FROM demo") == "SELECT * FROM demo"


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM orders",
        "SELECT * FROM orders; DELETE FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent FOR\nUPDATE",
        "  ",
    ],
)
def test_explain_rejects_writes_multiple_statements_and_locks(query: str) -> None:
    with pytest.raises(ValueError):
        validate_explain_query(query)


def test_explain_accepts_a_single_with_query_and_normalizes_outer_whitespace() -> None:
    query = "  WITH recent AS (SELECT * FROM orders) SELECT * FROM recent  "
    assert validate_explain_query(query) == query.strip()


@pytest.mark.parametrize("value", [None, " ", "APP.ORDERS", "APP;DROP TABLE ORDERS", '"APP"'])
def test_identifier_rejects_missing_qualified_or_unsafe_names(value: str | None) -> None:
    with pytest.raises(ValueError):
        normalize_identifier(value)


def test_identifier_normalizes_a_valid_oracle_name() -> None:
    assert normalize_identifier("  app_orders$1  ") == "APP_ORDERS$1"
