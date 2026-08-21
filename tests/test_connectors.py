"""Unit tests for dax_engine.connectors — SQL Server, Snowflake, BigQuery.

These are pure-unit tests: they validate metadata, SQL generation, parameter
validation, and extension commands without any live database connections.
"""

from __future__ import annotations

import pytest

from dax_engine.connectors import (
    ALL_NEW_CONNECTORS,
    BIGQUERY_CONNECTOR,
    SNOWFLAKE_CONNECTOR,
    SQLSERVER_CONNECTOR,
    generate_source_sql,
    get_duckdb_extension_commands,
    list_tables_sql,
    validate_source_params,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

_REQUIRED_KEYS = {"type", "label", "category", "status", "params"}
_REQUIRED_PARAM_KEYS = {"name", "label", "required", "kind"}


def _assert_connector_shape(conn: dict) -> None:
    """Assert that a connector dict has the required top-level keys and that
    every param entry has the minimal expected keys."""
    assert _REQUIRED_KEYS.issubset(conn.keys()), f"Missing keys: {_REQUIRED_KEYS - conn.keys()}"
    assert isinstance(conn["params"], list) and len(conn["params"]) > 0
    for p in conn["params"]:
        assert _REQUIRED_PARAM_KEYS.issubset(p.keys()), f"Param {p.get('name')!r} missing: {_REQUIRED_PARAM_KEYS - p.keys()}"
    # type must be lowercase
    assert conn["type"] == conn["type"].lower()
    assert conn["status"] in {"active", "beta", "planned"}


# ── 1–3  Metadata structure ─────────────────────────────────────────────────


class TestConnectorMetadata:
    def test_sqlserver_connector_metadata(self) -> None:
        _assert_connector_shape(SQLSERVER_CONNECTOR)
        assert SQLSERVER_CONNECTOR["type"] == "sqlserver"
        assert SQLSERVER_CONNECTOR["category"] == "Database"
        param_names = [p["name"] for p in SQLSERVER_CONNECTOR["params"]]
        assert "path" in param_names
        assert "table" in param_names

    def test_snowflake_connector_metadata(self) -> None:
        _assert_connector_shape(SNOWFLAKE_CONNECTOR)
        assert SNOWFLAKE_CONNECTOR["type"] == "snowflake"
        assert SNOWFLAKE_CONNECTOR["category"] == "Database"
        param_names = [p["name"] for p in SNOWFLAKE_CONNECTOR["params"]]
        assert "account" in param_names
        assert "database" in param_names
        assert "table" in param_names

    def test_bigquery_connector_metadata(self) -> None:
        _assert_connector_shape(BIGQUERY_CONNECTOR)
        assert BIGQUERY_CONNECTOR["type"] == "bigquery"
        assert BIGQUERY_CONNECTOR["category"] == "Database"
        param_names = [p["name"] for p in BIGQUERY_CONNECTOR["params"]]
        assert "project" in param_names
        assert "dataset" in param_names
        assert "table" in param_names

    def test_all_new_connectors_list(self) -> None:
        assert len(ALL_NEW_CONNECTORS) == 3
        types = {c["type"] for c in ALL_NEW_CONNECTORS}
        assert types == {"sqlserver", "snowflake", "bigquery"}


# ── 4–6  SQL generation ─────────────────────────────────────────────────────


class TestSqlGeneration:
    def test_sqlserver_sql_generation(self) -> None:
        sql = generate_source_sql("sqlserver", {
            "path": "Server=host;Database=mydb",
            "schema": "dbo",
            "table": "Sales",
        })
        assert "sqlserver_query" in sql
        assert "[dbo]" in sql
        assert "[Sales]" in sql
        assert "SELECT * FROM" in sql

    def test_snowflake_sql_generation(self) -> None:
        sql = generate_source_sql("snowflake", {
            "account": "xy12345.us-east-1",
            "database": "MYDB",
            "schema": "PUBLIC",
            "table": "Orders",
        })
        assert "ATTACH" in sql
        assert "snowflake" in sql.lower()
        assert '"PUBLIC"' in sql
        assert '"Orders"' in sql

    def test_bigquery_sql_generation(self) -> None:
        sql = generate_source_sql("bigquery", {
            "project": "my-gcp-project",
            "dataset": "analytics",
            "table": "events",
        })
        assert "ATTACH" in sql
        assert "bigquery" in sql.lower()
        assert "`analytics`" in sql
        assert "`events`" in sql


# ── 7–9  Extension commands ─────────────────────────────────────────────────


class TestExtensionCommands:
    def test_sqlserver_extension_commands(self) -> None:
        cmds = get_duckdb_extension_commands("sqlserver")
        assert any("INSTALL" in c and "sqlserver" in c for c in cmds)
        assert any("LOAD" in c and "sqlserver" in c for c in cmds)

    def test_snowflake_extension_commands(self) -> None:
        cmds = get_duckdb_extension_commands("snowflake")
        assert any("INSTALL" in c and "snowflake" in c for c in cmds)
        assert any("LOAD" in c and "snowflake" in c for c in cmds)

    def test_bigquery_extension_commands(self) -> None:
        cmds = get_duckdb_extension_commands("bigquery")
        assert any("INSTALL" in c and "bigquery" in c for c in cmds)
        assert any("LOAD" in c and "bigquery" in c for c in cmds)

    def test_unknown_connector_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown connector type"):
            get_duckdb_extension_commands("oracle")


# ── 10–13  Validation ───────────────────────────────────────────────────────


class TestValidation:
    def test_validate_sqlserver_missing_path(self) -> None:
        errors = validate_source_params("sqlserver", {"table": "Sales"})
        assert any("path" in e.lower() or "connection string" in e.lower() for e in errors)

    def test_validate_sqlserver_missing_table(self) -> None:
        errors = validate_source_params("sqlserver", {"path": "Server=host;Database=db"})
        assert any("table" in e.lower() for e in errors)

    def test_validate_snowflake_params(self) -> None:
        # All required fields missing
        errors = validate_source_params("snowflake", {})
        assert len(errors) == 3  # account, database, table
        # Only account provided
        errors = validate_source_params("snowflake", {"account": "xy12345"})
        assert len(errors) == 2  # database, table
        # All provided → valid
        errors = validate_source_params("snowflake", {
            "account": "xy12345",
            "database": "MYDB",
            "table": "Orders",
        })
        assert errors == []

    def test_validate_bigquery_params(self) -> None:
        errors = validate_source_params("bigquery", {})
        assert len(errors) == 3  # project, dataset, table
        errors = validate_source_params("bigquery", {
            "project": "my-proj",
            "dataset": "ds",
            "table": "t",
        })
        assert errors == []


# ── 14–15  List tables ──────────────────────────────────────────────────────


class TestListTables:
    def test_list_tables_sqlserver(self) -> None:
        sql = list_tables_sql("sqlserver", {"path": "Server=host;Database=db"})
        assert sql is not None
        assert "INFORMATION_SCHEMA" in sql
        assert "sqlserver_query" in sql

    def test_list_tables_snowflake(self) -> None:
        sql = list_tables_sql("snowflake", {"account": "xy12345", "database": "MYDB"})
        assert sql is not None
        assert "information_schema" in sql.lower()
        assert "ATTACH" in sql

    def test_list_tables_bigquery(self) -> None:
        sql = list_tables_sql("bigquery", {"project": "my-proj", "dataset": "ds"})
        assert sql is not None
        assert "information_schema" in sql.lower()
        assert "ATTACH" in sql

    def test_list_tables_missing_params_returns_none(self) -> None:
        assert list_tables_sql("sqlserver", {}) is None
        assert list_tables_sql("snowflake", {}) is None
        assert list_tables_sql("bigquery", {}) is None
        assert list_tables_sql("unknown_type", {}) is None


# ── 16  SQL injection prevention ────────────────────────────────────────────


class TestSqlInjectionPrevention:
    def test_sqlserver_injection_in_table(self) -> None:
        """A table name containing SQL-injection characters must be safely quoted."""
        sql = generate_source_sql("sqlserver", {
            "path": "Server=host;Database=db",
            "table": "Robert]; DROP TABLE Students;--",
        })
        # The bracket-quoting doubles any ] inside the name
        assert "Robert]]; DROP TABLE Students;--" in sql
        # The raw unquoted injection string must NOT appear
        assert "Robert]; DROP TABLE" not in sql

    def test_snowflake_injection_in_table(self) -> None:
        sql = generate_source_sql("snowflake", {
            "account": "acct",
            "database": "DB",
            "table": 'evil"table',
        })
        # Double-quote quoting doubles the inner "
        assert 'evil""table' in sql

    def test_bigquery_injection_in_dataset(self) -> None:
        sql = generate_source_sql("bigquery", {
            "project": "proj",
            "dataset": "ds`; DROP ALL",
            "table": "t",
        })
        # Backtick quoting escapes the inner `
        assert "ds\\`; DROP ALL" in sql

    def test_sqlserver_injection_in_connection_string(self) -> None:
        """Single quotes in the connection string must be escaped."""
        sql = generate_source_sql("sqlserver", {
            "path": "Server=host'; DROP TABLE x;--",
            "table": "t",
        })
        # Doubled single-quote escaping
        assert "host''; DROP TABLE x;--" in sql
        # The raw single-quote injection must NOT appear unescaped
        assert "host'; DROP TABLE x;--" not in sql
