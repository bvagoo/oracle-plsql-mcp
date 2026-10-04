from __future__ import annotations

from collections import deque
import re
from typing import Any

from .database import OracleDatabase, normalize_identifier, owner_or_default
from .plsql import PLSQL_TYPES, calls, data_access, dynamic_sql, source_text, symbol_declarations


class PlsqlTools:
    """PL/SQL source, dependency, call-graph, and package-signature queries."""

    def __init__(self, database: OracleDatabase):
        self.database = database

    def routine_source(self, owner: str | None, name: str, object_type: str | None = None) -> tuple[str, str, str, list[dict]]:
        actual_owner, actual_name = owner_or_default(self.database, owner), normalize_identifier(name)
        types = [object_type.upper()] if object_type else list(PLSQL_TYPES)
        placeholders = ", ".join(f":t{index}" for index in range(len(types)))
        binds = {"owner": actual_owner, "name": actual_name, **{f"t{index}": value for index, value in enumerate(types)}}
        rows = self.database.rows(f"""SELECT type, line, text FROM all_source
            WHERE owner=:owner AND name=:name AND type IN ({placeholders}) ORDER BY type, line""", binds, 20000)
        if not rows:
            raise ValueError(f"No accessible PL/SQL source for {actual_owner}.{actual_name}.")
        return actual_owner, actual_name, str(rows[0]["type"]), rows

    def objects_using(self, owner: str, name: str, limit: int = 100) -> list[dict]:
        return self.database.rows("""SELECT owner, name, type FROM all_dependencies
            WHERE referenced_owner=:owner AND referenced_name=:name
              AND owner NOT IN ('SYS','SYSTEM') ORDER BY owner, name""", {"owner": owner, "name": name}, limit)

    def get_object_source(self, object_name: str, owner: str | None = None, object_type: str | None = None) -> dict:
        actual_owner, name, actual_type, rows = self.routine_source(owner, object_name, object_type)
        return {"owner": actual_owner, "object_name": name, "object_type": actual_type, "source": rows}

    def search_source(self, keyword: str, owner: str | None = None, object_type: str | None = None, max_results: int = 100) -> dict:
        actual_owner = owner_or_default(self.database, owner)
        sql = "SELECT owner, name, type, line, text FROM all_source WHERE owner=:owner AND UPPER(text) LIKE :keyword"
        binds: dict[str, Any] = {"owner": actual_owner, "keyword": f"%{keyword.upper()}%"}
        if object_type:
            sql += " AND type=:type"
            binds["type"] = object_type.upper()
        return {"matches": self.database.rows(sql + " ORDER BY name, type, line", binds, min(max_results, 500))}

    def find_symbol(self, symbol: str, owner: str | None = None, object_name: str | None = None, max_results: int = 100) -> dict:
        actual_owner, target = owner_or_default(self.database, owner), normalize_identifier(symbol)
        sql = "SELECT name, type, line, text FROM all_source WHERE owner=:owner"
        binds: dict[str, Any] = {"owner": actual_owner}
        if object_name:
            sql += " AND name=:name"
            binds["name"] = normalize_identifier(object_name)
        rows = self.database.rows(sql + " ORDER BY name, type, line", binds, 20000)
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            grouped.setdefault((row["name"], row["type"]), []).append(row)
        matches = []
        for (name, typ), lines in grouped.items():
            for hit in symbol_declarations(source_text(lines), target):
                matches.append({"owner": actual_owner, "object_name": name, "object_type": typ, **hit})
                if len(matches) >= max_results:
                    return {"symbol": target, "matches": matches, "truncated": True}
        return {"symbol": target, "matches": matches, "truncated": False}

    def find_references(self, symbol: str, owner: str | None = None, object_name: str | None = None, max_results: int = 100) -> dict:
        actual_owner, target = owner_or_default(self.database, owner), normalize_identifier(symbol)
        sql = "SELECT name, type, line, text FROM all_source WHERE owner=:owner AND REGEXP_LIKE(UPPER(text), :pattern)"
        binds: dict[str, Any] = {"owner": actual_owner, "pattern": rf"(^|[^A-Z0-9_$#]){target}([^A-Z0-9_$#]|$)"}
        if object_name:
            sql += " AND name=:name"
            binds["name"] = normalize_identifier(object_name)
        rows = self.database.rows(sql + " ORDER BY name, type, line", binds, min(max_results, 500))
        return {"symbol": target, "references": rows, "resolution": "lexical", "truncated": len(rows) >= max_results}

    def find_callers(self, symbol: str, owner: str | None = None, max_results: int = 100) -> dict:
        actual_owner, target = owner_or_default(self.database, owner), normalize_identifier(symbol)
        references = self.find_references(target, actual_owner, max_results=max_results)["references"]
        return {"callee": f"{actual_owner}.{target}", "callers": references, "dictionary_dependents": self.objects_using(actual_owner, target, max_results), "resolution": "lexical + dictionary"}

    def find_callees(self, object_name: str, owner: str | None = None, object_type: str | None = None) -> dict:
        actual_owner, name, typ, rows = self.routine_source(owner, object_name, object_type)
        text = source_text(rows)
        return {"owner": actual_owner, "object_name": name, "object_type": typ, "callees": [{"name": key, "count": count} for key, count in calls(text).most_common()], "dynamic_sql": dynamic_sql(text)}

    def call_graph(self, object_name: str, owner: str | None = None, max_depth: int = 3, max_nodes: int = 100) -> dict:
        if not 0 <= max_depth <= 10 or not 1 <= max_nodes <= 500:
            raise ValueError("max_depth must be 0..10 and max_nodes 1..500.")
        actual_owner, root = owner_or_default(self.database, owner), normalize_identifier(object_name)
        queue, seen, edges, uncertain = deque([(root, 0)]), {root}, [], []
        truncated = False
        while queue:
            current, depth = queue.popleft()
            try:
                _, _, _, rows = self.routine_source(actual_owner, current)
            except ValueError:
                continue
            text = source_text(rows)
            uncertain.extend({"object_name": current, **item} for item in dynamic_sql(text))
            if depth == max_depth:
                continue
            for callee in calls(text):
                simple = callee.rsplit(".", 1)[-1]
                edges.append({"from": current, "to": callee, "resolution": "static lexical"})
                if simple not in seen:
                    if len(seen) >= max_nodes:
                        truncated = True
                        continue
                    seen.add(simple)
                    queue.append((simple, depth + 1))
        return {"root": f"{actual_owner}.{root}", "nodes": sorted(seen), "edges": edges, "dynamic_sql": uncertain, "truncated": truncated}

    def routine_data_access(self, object_name: str, owner: str | None = None, object_type: str | None = None) -> dict:
        actual_owner, name, typ, rows = self.routine_source(owner, object_name, object_type)
        text = source_text(rows)
        return {"owner": actual_owner, "object_name": name, "object_type": typ, "access": data_access(text), "dynamic_sql": dynamic_sql(text), "resolution": "static lexical"}

    def find_dynamic_sql(self, object_name: str | None = None, owner: str | None = None, max_results: int = 100) -> dict:
        actual_owner = owner_or_default(self.database, owner)
        sql = "SELECT name, type, line, text FROM all_source WHERE owner=:owner AND REGEXP_LIKE(UPPER(text), 'EXECUTE[[:space:]]+IMMEDIATE|OPEN[[:space:]]+[A-Z0-9_$#]+[[:space:]]+FOR')"
        binds: dict[str, Any] = {"owner": actual_owner}
        if object_name:
            sql += " AND name=:name"
            binds["name"] = normalize_identifier(object_name)
        return {"owner": actual_owner, "matches": self.database.rows(sql + " ORDER BY name, type, line", binds, min(max_results, 500)), "resolution": "lexical"}

    def find_column_usage(self, table_name: str, column_name: str, owner: str | None = None, max_results: int = 100) -> dict:
        """Return source evidence only; Oracle does not publish column-level PL/SQL dependencies."""
        actual_owner = owner_or_default(self.database, owner)
        table, column = normalize_identifier(table_name), normalize_identifier(column_name)
        rows = self.database.rows("""SELECT name, type, line, text FROM all_source
            WHERE owner=:owner AND (UPPER(text) LIKE :table_pattern OR UPPER(text) LIKE :column_pattern)
            ORDER BY name, type, line""", {"owner": actual_owner, "table_pattern": f"%{table}%", "column_pattern": f"%{column}%"}, 20000)
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            grouped.setdefault((row["name"], row["type"]), []).append(row)
        qualified = re.compile(rf"(?<![A-Z0-9_$#])(?:{re.escape(actual_owner)}\s*\.\s*)?{re.escape(table)}\s*\.\s*{re.escape(column)}(?![A-Z0-9_$#])", re.I)
        table_token = re.compile(rf"(?<![A-Z0-9_$#]){re.escape(table)}(?![A-Z0-9_$#])", re.I)
        column_token = re.compile(rf"(?<![A-Z0-9_$#]){re.escape(column)}(?![A-Z0-9_$#])", re.I)
        direct, candidates = [], []
        for (name, typ), source_rows in grouped.items():
            table_lines = [{"line": row["line"], "text": row["text"].rstrip()} for row in source_rows if table_token.search(str(row["text"]))]
            column_lines = [{"line": row["line"], "text": row["text"].rstrip()} for row in source_rows if column_token.search(str(row["text"]))]
            for row in source_rows:
                if qualified.search(str(row["text"])):
                    direct.append({"owner": actual_owner, "object_name": name, "object_type": typ, "line": row["line"], "text": row["text"].rstrip(), "confidence": "direct qualified reference"})
            if table_lines and column_lines:
                candidates.append({"owner": actual_owner, "object_name": name, "object_type": typ,
                                   "table_evidence": table_lines[:10], "column_evidence": column_lines[:10],
                                   "confidence": "same source unit; review SQL aliases and scopes"})
        return {"owner": actual_owner, "table_name": table, "column_name": column,
                "direct_qualified_references": direct[:max_results], "candidate_source_units": candidates[:max_results],
                "resolution": "lexical evidence only; dynamic SQL and aliases can hide or overstate usage",
                "truncated": len(rows) >= 20000 or len(direct) > max_results or len(candidates) > max_results}

    def analyze_change_impact(self, object_name: str, owner: str | None = None, change_kind: str = "object", max_results: int = 200) -> dict:
        actual_owner, target = owner_or_default(self.database, owner), normalize_identifier(object_name)
        impacts = [{"kind": "dictionary_dependency", **item} for item in self.objects_using(actual_owner, target, max_results)]
        impacts.extend({"kind": "source_reference", **item} for item in self.find_references(target, actual_owner, max_results=max_results)["references"])
        return {"changed_object": f"{actual_owner}.{target}", "change_kind": change_kind, "impact": impacts[:max_results], "notes": ["Dynamic SQL can hide dependencies; inspect find_dynamic_sql output.", "Column-level impact needs the column name and source review; ALL_DEPENDENCIES is object-level."]}

    def package_hierarchy(self, package_name: str, owner: str | None = None) -> dict:
        actual_owner, package = owner_or_default(self.database, owner), normalize_identifier(package_name)
        current_user = str(self.database.scalar("SELECT USER FROM DUAL"))
        if actual_owner == current_user:
            routines = self.database.rows("SELECT procedure_name, subprogram_id FROM user_procedures WHERE object_name=:package AND procedure_name IS NOT NULL ORDER BY subprogram_id", {"package": package}, 1000)
            arguments = self.database.rows("""SELECT package_name, object_name, subprogram_id, argument_name, position, sequence,
                data_level, in_out, data_type, type_owner, type_name, defaulted
                FROM user_arguments WHERE package_name=:package ORDER BY subprogram_id, sequence""", {"package": package}, 5000)
            source_views = {"routines": "USER_PROCEDURES", "arguments": "USER_ARGUMENTS"}
        else:
            routines = self.database.rows("SELECT procedure_name, subprogram_id FROM all_procedures WHERE owner=:owner AND object_name=:package AND procedure_name IS NOT NULL ORDER BY subprogram_id", {"owner": actual_owner, "package": package}, 1000)
            arguments = self.database.rows("""SELECT package_name, object_name, subprogram_id, argument_name, position, sequence,
                data_level, in_out, data_type, type_owner, type_name, defaulted
                FROM all_arguments WHERE owner=:owner AND package_name=:package ORDER BY subprogram_id, sequence""", {"owner": actual_owner, "package": package}, 5000)
            source_views = {"routines": "ALL_PROCEDURES", "arguments": "ALL_ARGUMENTS"}
        arguments_by_subprogram: dict[int, list[dict]] = {}
        for argument in arguments:
            arguments_by_subprogram.setdefault(int(argument["subprogram_id"]), []).append(argument)
        routines_with_arguments = [{**routine, "arguments": arguments_by_subprogram.get(int(routine["subprogram_id"]), [])} for routine in routines]
        return {"owner": actual_owner, "package_name": package, "source_views": source_views, "routines": routines_with_arguments}

    def routine_signature(self, routine_name: str, owner: str | None = None, package_name: str | None = None) -> dict:
        """Return every accessible overload and its arguments for a standalone or packaged routine."""
        actual_owner, routine = owner_or_default(self.database, owner), normalize_identifier(routine_name)
        package = normalize_identifier(package_name) if package_name else None
        if package:
            routine_filter = "object_name=:package AND procedure_name=:routine"
            argument_filter = "package_name=:package AND object_name=:routine"
            binds: dict[str, Any] = {"owner": actual_owner, "package": package, "routine": routine}
        else:
            routine_filter = "object_name=:routine AND procedure_name IS NULL"
            argument_filter = "package_name IS NULL AND object_name=:routine"
            binds = {"owner": actual_owner, "routine": routine}
        routines = self.database.rows(f"""SELECT object_name, procedure_name, subprogram_id, overload,
                object_type, aggregate, pipelined, deterministic, authid
            FROM all_procedures WHERE owner=:owner AND {routine_filter}
            ORDER BY subprogram_id""", binds, 1000)
        arguments = self.database.rows(f"""SELECT object_name, package_name, subprogram_id, overload,
                argument_name, position, sequence, data_level, in_out, data_type, type_owner, type_name,
                defaulted
            FROM all_arguments WHERE owner=:owner AND {argument_filter}
            ORDER BY subprogram_id, sequence""", binds, 5000)
        arguments_by_subprogram: dict[int, list[dict]] = {}
        for argument in arguments:
            arguments_by_subprogram.setdefault(int(argument["subprogram_id"]), []).append(argument)
        return {"owner": actual_owner, "routine_name": routine, "package_name": package,
                "source_views": {"routines": "ALL_PROCEDURES", "arguments": "ALL_ARGUMENTS"},
                "overloads": [{**item, "arguments": arguments_by_subprogram.get(int(item["subprogram_id"]), [])} for item in routines]}
