from __future__ import annotations

from typing import Any

from .database import OracleDatabase, normalize_identifier, owner_or_default


class MetadataTools:
    """Read-only Oracle dictionary queries for objects and tables."""

    def __init__(self, database: OracleDatabase):
        self.database = database

    def list_tables(self, owner: str | None = None, max_results: int = 200) -> dict:
        actual_owner = owner_or_default(self.database, owner)
        tables = self.database.rows("SELECT table_name, tablespace_name, num_rows, last_analyzed FROM all_tables WHERE owner=:owner ORDER BY table_name", {"owner": actual_owner}, max_results)
        return {"owner": actual_owner, "tables": tables}

    def describe_table(self, table_name: str, owner: str | None = None) -> dict:
        actual_owner, table = owner_or_default(self.database, owner), normalize_identifier(table_name)
        columns = self.database.rows("""SELECT column_id, column_name, data_type, data_length, data_precision, data_scale, nullable, data_default
            FROM all_tab_columns WHERE owner=:owner AND table_name=:table ORDER BY column_id""", {"owner": actual_owner, "table": table}, 1000)
        return {"owner": actual_owner, "table_name": table, "columns": columns}

    def search_objects(self, keyword: str, owner: str | None = None, object_type: str | None = None, max_results: int = 100) -> dict:
        actual_owner = owner_or_default(self.database, owner)
        sql = "SELECT owner, object_name, object_type, status, created, last_ddl_time FROM all_objects WHERE owner=:owner AND UPPER(object_name) LIKE :keyword"
        binds: dict[str, Any] = {"owner": actual_owner, "keyword": f"%{keyword.upper()}%"}
        if object_type:
            sql += " AND object_type=:type"
            binds["type"] = object_type.upper()
        return {"objects": self.database.rows(sql + " ORDER BY object_type, object_name", binds, min(max_results, 500))}

    def find_dependencies(self, object_name: str, owner: str | None = None, object_type: str | None = None) -> dict:
        actual_owner, name = owner_or_default(self.database, owner), normalize_identifier(object_name)
        sql = "SELECT referenced_owner, referenced_name, referenced_type, dependency_type FROM all_dependencies WHERE owner=:owner AND name=:name"
        binds: dict[str, Any] = {"owner": actual_owner, "name": name}
        if object_type:
            sql += " AND type=:type"
            binds["type"] = object_type.upper()
        return {"dependencies": self.database.rows(sql + " ORDER BY referenced_owner, referenced_name", binds, 1000)}

    def find_dependents(self, object_name: str, owner: str | None = None) -> dict:
        actual_owner, name = owner_or_default(self.database, owner), normalize_identifier(object_name)
        dependents = self.database.rows("""SELECT owner, name, type FROM all_dependencies
            WHERE referenced_owner=:owner AND referenced_name=:name
              AND owner NOT IN ('SYS','SYSTEM') ORDER BY owner, name""", {"owner": actual_owner, "name": name}, 1000)
        return {"dependents": dependents}

    def get_object_ddl(self, object_name: str, object_type: str, owner: str | None = None) -> dict:
        actual_owner, name = owner_or_default(self.database, owner), normalize_identifier(object_name)
        ddl = self.database.scalar("SELECT DBMS_METADATA.GET_DDL(:type, :name, :owner) FROM dual", {"type": object_type.upper(), "name": name, "owner": actual_owner})
        return {"owner": actual_owner, "object_name": name, "object_type": object_type.upper(), "ddl": ddl}

    def table_structure_details(self, table_name: str, owner: str | None = None) -> dict:
        actual_owner, table = owner_or_default(self.database, owner), normalize_identifier(table_name)
        binds = {"owner": actual_owner, "table": table}
        table_details = self.database.rows("""SELECT table_name, tablespace_name, num_rows, blocks, avg_row_len, last_analyzed, temporary, partitioned
            FROM all_tables WHERE owner=:owner AND table_name=:table""", binds, 1)
        columns = self.database.rows("""SELECT column_id, column_name, data_type, data_length, data_precision, data_scale, nullable, data_default
            FROM all_tab_columns WHERE owner=:owner AND table_name=:table ORDER BY column_id""", binds, 1000)
        indexes = self.database.rows("""SELECT index_name, index_type, uniqueness, status, visibility, tablespace_name
            FROM all_indexes WHERE table_owner=:owner AND table_name=:table ORDER BY index_name""", binds, 1000)
        index_columns = self.database.rows("""SELECT index_name, column_position, column_name, descend
            FROM all_ind_columns WHERE table_owner=:owner AND table_name=:table ORDER BY index_name, column_position""", binds, 5000)
        constraints = self.database.rows("""SELECT constraint_name, constraint_type, status, validated, deferrable, deferred,
                r_owner, r_constraint_name, delete_rule, search_condition
            FROM all_constraints WHERE owner=:owner AND table_name=:table ORDER BY constraint_name""", binds, 1000)
        constraint_columns = self.database.rows("""SELECT constraint_name, position, column_name
            FROM all_cons_columns WHERE owner=:owner AND table_name=:table ORDER BY constraint_name, position""", binds, 5000)
        return {"owner": actual_owner, "table_name": table, "table": table_details[0] if table_details else None, "columns": columns, "indexes": indexes, "index_columns": index_columns, "constraints": constraints, "constraint_columns": constraint_columns}

    def object_privileges(self, object_name: str, owner: str | None = None, max_results: int = 200) -> dict:
        actual_owner, name = owner_or_default(self.database, owner), normalize_identifier(object_name)
        binds = {"owner": actual_owner, "name": name}
        limit = min(max_results, 500)
        object_grants = self.database.rows("""SELECT grantor, grantee, privilege, grantable, hierarchy, common, inherited
            FROM all_tab_privs WHERE table_schema=:owner AND table_name=:name
            ORDER BY grantee, privilege""", binds, limit)
        column_grants = self.database.rows("""SELECT grantor, grantee, table_name, column_name, privilege, grantable, common, inherited
            FROM all_col_privs WHERE owner=:owner AND table_name=:name
            ORDER BY grantee, column_name, privilege""", binds, limit)
        return {"owner": actual_owner, "object_name": name, "object_grants": object_grants, "column_grants": column_grants}

    def table_relationships(self, table_name: str, owner: str | None = None) -> dict:
        actual_owner, table = owner_or_default(self.database, owner), normalize_identifier(table_name)
        binds = {"owner": actual_owner, "table": table}
        outgoing = self.database.rows("""SELECT c.constraint_name, c.status, c.validated, c.delete_rule,
                cc.column_name AS child_column, cc.position, p.owner AS parent_owner,
                p.table_name AS parent_table, pc.column_name AS parent_column
            FROM all_constraints c
            JOIN all_cons_columns cc ON cc.owner=c.owner AND cc.constraint_name=c.constraint_name
            JOIN all_constraints p ON p.owner=c.r_owner AND p.constraint_name=c.r_constraint_name
            LEFT JOIN all_cons_columns pc ON pc.owner=p.owner AND pc.constraint_name=p.constraint_name AND pc.position=cc.position
            WHERE c.owner=:owner AND c.table_name=:table AND c.constraint_type='R'
            ORDER BY c.constraint_name, cc.position""", binds, 5000)
        incoming = self.database.rows("""SELECT c.owner AS child_owner, c.table_name AS child_table, c.constraint_name,
                c.status, c.validated, c.delete_rule, cc.column_name AS child_column, cc.position,
                pc.column_name AS parent_column
            FROM all_constraints c
            JOIN all_cons_columns cc ON cc.owner=c.owner AND cc.constraint_name=c.constraint_name
            JOIN all_constraints p ON p.owner=c.r_owner AND p.constraint_name=c.r_constraint_name
            LEFT JOIN all_cons_columns pc ON pc.owner=p.owner AND pc.constraint_name=p.constraint_name AND pc.position=cc.position
            WHERE p.owner=:owner AND p.table_name=:table AND c.constraint_type='R'
            ORDER BY c.owner, c.table_name, c.constraint_name, cc.position""", binds, 5000)
        return {"owner": actual_owner, "table_name": table, "outgoing_foreign_keys": outgoing, "incoming_foreign_keys": incoming}

    def object_grants_and_synonyms(self, object_name: str, owner: str | None = None, max_results: int = 200) -> dict:
        result = self.object_privileges(object_name, owner, max_results)
        binds = {"owner": result["owner"], "name": result["object_name"]}
        result["synonyms"] = self.database.rows("""SELECT owner AS synonym_owner, synonym_name,
                table_owner AS target_owner, table_name AS target_name, db_link
            FROM all_synonyms WHERE table_owner=:owner AND table_name=:name
            ORDER BY owner, synonym_name""", binds, min(max_results, 500))
        return result

    def table_automation(self, table_name: str, owner: str | None = None) -> dict:
        actual_owner, table = owner_or_default(self.database, owner), normalize_identifier(table_name)
        binds = {"owner": actual_owner, "table": table}
        triggers = self.database.rows("""SELECT owner, trigger_name, triggering_event, trigger_type, status,
                when_clause, description
            FROM all_triggers WHERE table_owner=:owner AND table_name=:table ORDER BY owner, trigger_name""", binds, 1000)
        mview_logs = self.database.rows("""SELECT log_owner, master, log_table, rowids, primary_key, object_id,
                filter_columns, sequence, include_new_values, purge_asynchronous
            FROM all_mview_logs WHERE log_owner=:owner AND master=:table ORDER BY log_table""", binds, 1000)
        policies = self.database.rows("""SELECT policy_name, pf_owner, package, function, sel, ins, upd, del,
                enabled, static_policy, policy_type
            FROM all_policies WHERE object_owner=:owner AND object_name=:table ORDER BY policy_name""", binds, 1000)
        return {"owner": actual_owner, "table_name": table, "triggers": triggers, "materialized_view_logs": mview_logs, "vpd_policies": policies}

    def partition_details(self, table_name: str, owner: str | None = None, max_results: int = 500) -> dict:
        actual_owner, table = owner_or_default(self.database, owner), normalize_identifier(table_name)
        binds, limit = {"owner": actual_owner, "table": table}, min(max_results, 1000)
        table_details = self.database.rows("""SELECT partitioning_type, subpartitioning_type, partition_count,
                def_tablespace_name, interval, autolist
            FROM all_part_tables WHERE owner=:owner AND table_name=:table""", binds, 1)
        key_columns = self.database.rows("""SELECT column_name, column_position
            FROM all_part_key_columns WHERE owner=:owner AND name=:table AND object_type='TABLE'
            ORDER BY column_position""", binds, 100)
        partitions = self.database.rows("""SELECT partition_name, high_value, partition_position, tablespace_name,
                num_rows, last_analyzed
            FROM all_tab_partitions WHERE table_owner=:owner AND table_name=:table ORDER BY partition_position""", binds, limit)
        indexes = self.database.rows("""SELECT index_name, locality, alignment, partitioning_type, subpartitioning_type
            FROM all_part_indexes WHERE table_owner=:owner AND table_name=:table ORDER BY index_name""", binds, limit)
        index_partitions = self.database.rows("""SELECT p.index_owner, p.index_name, p.partition_name, p.high_value,
                p.partition_position, p.tablespace_name, p.status
            FROM all_ind_partitions p JOIN all_part_indexes i ON i.owner=p.index_owner AND i.index_name=p.index_name
            WHERE i.table_owner=:owner AND i.table_name=:table ORDER BY p.index_name, p.partition_position""", binds, limit)
        return {"owner": actual_owner, "table_name": table, "table_partitioning": table_details[0] if table_details else None,
                "partition_key_columns": key_columns, "partitions": partitions, "partitioned_indexes": indexes, "index_partitions": index_partitions}

    def view_details(self, view_name: str, owner: str | None = None) -> dict:
        """Return a view definition together with dictionary dependencies Oracle records for it."""
        actual_owner, view = owner_or_default(self.database, owner), normalize_identifier(view_name)
        binds = {"owner": actual_owner, "view_name": view}
        definition = self.database.rows("""SELECT view_name, text, text_length, read_only
            FROM all_views WHERE owner=:owner AND view_name=:view_name""", binds, 1)
        columns = self.database.rows("""SELECT column_id, column_name, data_type, data_length,
                data_precision, data_scale, nullable
            FROM all_tab_columns WHERE owner=:owner AND table_name=:view_name ORDER BY column_id""", binds, 1000)
        dependencies = self.database.rows("""SELECT referenced_owner, referenced_name, referenced_type,
                dependency_type FROM all_dependencies
            WHERE owner=:owner AND name=:view_name AND type='VIEW'
            ORDER BY referenced_owner, referenced_name, referenced_type""", binds, 1000)
        return {"owner": actual_owner, "view_name": view,
                "view": definition[0] if definition else None, "columns": columns,
                "dependencies": dependencies}

    def table_statistics(self, table_name: str, owner: str | None = None) -> dict:
        actual_owner, table = owner_or_default(self.database, owner), normalize_identifier(table_name)
        binds = {"owner": actual_owner, "table": table}
        table_stats = self.database.rows("""SELECT num_rows, blocks, empty_blocks, avg_row_len, sample_size,
                last_analyzed, global_stats, user_stats, stattype_locked, stale_stats
            FROM all_tab_statistics WHERE owner=:owner AND table_name=:table
              AND object_type='TABLE' AND partition_name IS NULL""", binds, 1)
        column_stats = self.database.rows("""SELECT column_name, num_distinct, density, num_nulls, num_buckets,
                avg_col_len, histogram, sample_size, last_analyzed, global_stats, user_stats
            FROM all_tab_col_statistics WHERE owner=:owner AND table_name=:table ORDER BY column_name""", binds, 1000)
        return {"owner": actual_owner, "table_name": table,
                "table_statistics": table_stats[0] if table_stats else None,
                "column_statistics": column_stats}

    def index_usage(self, table_name: str, owner: str | None = None) -> dict:
        """Return index health and optimizer statistics, not inferred runtime usage."""
        actual_owner, table = owner_or_default(self.database, owner), normalize_identifier(table_name)
        binds = {"owner": actual_owner, "table": table}
        indexes = self.database.rows("""SELECT owner, index_name, index_type, uniqueness, status, visibility,
                num_rows, distinct_keys, leaf_blocks, clustering_factor, last_analyzed, tablespace_name
            FROM all_indexes WHERE table_owner=:owner AND table_name=:table ORDER BY index_name""", binds, 1000)
        columns = self.database.rows("""SELECT index_name, column_position, column_name, column_length, descend
            FROM all_ind_columns WHERE table_owner=:owner AND table_name=:table
            ORDER BY index_name, column_position""", binds, 5000)
        return {"owner": actual_owner, "table_name": table, "indexes": indexes,
                "index_columns": columns,
                "usage_note": "Oracle does not expose reliable historical index usage through ALL_INDEXES. Runtime usage requires separately enabled index monitoring and suitable dictionary privileges."}

    def unused_or_stale_objects(self, owner: str | None = None, max_results: int = 200) -> dict:
        """Surface safe dictionary health signals without claiming that an object is unused."""
        actual_owner, limit = owner_or_default(self.database, owner), min(max_results, 500)
        stale_tables = self.database.rows("""SELECT table_name, num_rows, last_analyzed, stale_stats, stattype_locked
            FROM all_tab_statistics WHERE owner=:owner AND object_type='TABLE' AND partition_name IS NULL
              AND stale_stats='YES' ORDER BY table_name""", {"owner": actual_owner}, limit)
        invalid_objects = self.database.rows("""SELECT object_name, object_type, status, last_ddl_time
            FROM all_objects WHERE owner=:owner AND status='INVALID'
            ORDER BY object_type, object_name""", {"owner": actual_owner}, limit)
        non_valid_indexes = self.database.rows("""SELECT index_name, table_name, status, visibility, last_analyzed
            FROM all_indexes WHERE table_owner=:owner AND status <> 'VALID'
            ORDER BY table_name, index_name""", {"owner": actual_owner}, limit)
        return {"owner": actual_owner, "stale_table_statistics": stale_tables,
                "invalid_objects": invalid_objects, "non_valid_indexes": non_valid_indexes,
                "usage_note": "No object is labelled unused: reliable usage data is not available from standard ALL_* views. Enable Oracle monitoring separately if runtime index-use evidence is required."}
