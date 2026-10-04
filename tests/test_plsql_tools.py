import pytest

from oracle_plsql_mcp.plsql_tools import PlsqlTools


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


class SignatureDatabase:
    default_schema = "APP"

    def rows(self, sql, binds=None, limit=500):
        if "all_procedures" in sql.lower():
            return [{"object_name": "ORDER_API", "procedure_name": "SAVE", "subprogram_id": 2,
                     "overload": None}]
        if "all_arguments" in sql.lower():
            return [{"subprogram_id": 2, "argument_name": "P_ID", "position": 1, "sequence": 1}]
        raise AssertionError(f"Unexpected query: {sql}")


def test_routine_signature_groups_arguments_by_overload() -> None:
    result = PlsqlTools(SignatureDatabase()).routine_signature("save", package_name="order_api")
    assert result["package_name"] == "ORDER_API"
    assert result["overloads"][0]["arguments"][0]["argument_name"] == "P_ID"


class GraphDatabase:
    default_schema = "APP"

    def __init__(self, sources: dict[str, str]) -> None:
        self.sources = sources

    def rows(self, sql, binds=None, limit=500):
        assert "all_source" in sql.lower()
        text = self.sources.get(binds["name"])
        return [{"type": "PROCEDURE", "line": number, "text": line}
                for number, line in enumerate(text.splitlines(), 1)] if text else []


def test_call_graph_stops_at_cycles_without_dropping_edges() -> None:
    database = GraphDatabase({"ROOT": "BEGIN next_step(); END;",
                              "NEXT_STEP": "BEGIN root(); END;"})
    result = PlsqlTools(database).call_graph("root")

    assert result["nodes"] == ["NEXT_STEP", "ROOT"]
    assert [(edge["from"], edge["to"]) for edge in result["edges"]] == [
        ("ROOT", "NEXT_STEP"), ("NEXT_STEP", "ROOT")]
    assert result["truncated"] is False


def test_call_graph_processes_root_even_at_one_node_limit() -> None:
    database = GraphDatabase({"ROOT": "BEGIN\n  EXECUTE IMMEDIATE statement_text;\n  child();\nEND;"})
    result = PlsqlTools(database).call_graph("root", max_nodes=1)

    assert result["nodes"] == ["ROOT"]
    assert result["dynamic_sql"][0]["object_name"] == "ROOT"
    assert result["truncated"] is True


def test_call_graph_never_exceeds_node_limit() -> None:
    database = GraphDatabase({"ROOT": "BEGIN first_child(); second_child(); END;",
                              "FIRST_CHILD": "BEGIN NULL; END;", "SECOND_CHILD": "BEGIN NULL; END;"})
    result = PlsqlTools(database).call_graph("root", max_nodes=2)

    assert result["nodes"] == ["FIRST_CHILD", "ROOT"]
    assert result["truncated"] is True


@pytest.mark.parametrize("max_depth,max_nodes", [(-1, 5), (11, 5), (1, 0), (1, 501)])
def test_call_graph_rejects_invalid_bounds(max_depth: int, max_nodes: int) -> None:
    with pytest.raises(ValueError):
        PlsqlTools(GraphDatabase({})).call_graph("root", max_depth=max_depth, max_nodes=max_nodes)
