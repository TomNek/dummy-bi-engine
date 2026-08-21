"""New database connectors: SQL Server, Snowflake, BigQuery.

Each connector provides:
1. Metadata dict (matching ``_IMPORT_CONNECTORS`` shape in server.py)
2. DuckDB SQL to query the source
3. Extension install/load commands needed
4. Parameter validation
5. SQL to list available tables

All SQL generation uses proper quoting/escaping to prevent injection.
No external dependencies beyond the Python stdlib.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _sql_string_literal(value: str) -> str:
    """Escape a value for use as a SQL string literal (single-quoted).

    Single quotes inside *value* are doubled, which is the ANSI SQL escaping
    convention and the one DuckDB uses.
    """
    return "'" + value.replace("'", "''") + "'"


def _quote_bracket(identifier: str) -> str:
    """Quote a SQL Server identifier using brackets.

    Closing brackets inside the name are doubled (``]`` → ``]]``).
    """
    return "[" + identifier.replace("]", "]]") + "]"


def _quote_backtick(identifier: str) -> str:
    """Quote an identifier using backticks (BigQuery style).

    Backticks inside the name are escaped with a backslash.
    """
    return "`" + identifier.replace("`", "\\`") + "`"


def _quote_double(identifier: str) -> str:
    """Quote an identifier using double-quotes (ANSI / Snowflake style).

    Double-quotes inside the name are doubled.
    """
    return '"' + identifier.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Connector metadata
# ---------------------------------------------------------------------------

SQLSERVER_CONNECTOR: dict[str, Any] = {
    "type": "sqlserver",
    "label": "SQL Server",
    "category": "Database",
    "status": "active",
    "params": [
        {
            "name": "path",
            "label": "Connection string",
            "required": True,
            "kind": "text",
            "placeholder": "Server=host;Database=db;Trusted_Connection=yes",
        },
        {
            "name": "schema",
            "label": "Schema",
            "required": False,
            "kind": "text",
            "placeholder": "dbo",
        },
        {"name": "table", "label": "Table", "required": True, "kind": "text"},
        {
            "name": "auth_mode",
            "label": "Auth mode",
            "required": False,
            "kind": "select",
            "options": ["connection_string", "env_vars"],
        },
    ],
}

SNOWFLAKE_CONNECTOR: dict[str, Any] = {
    "type": "snowflake",
    "label": "Snowflake",
    "category": "Database",
    "status": "active",
    "params": [
        {
            "name": "account",
            "label": "Account identifier",
            "required": True,
            "kind": "text",
            "placeholder": "xy12345.us-east-1",
        },
        {
            "name": "database",
            "label": "Database",
            "required": True,
            "kind": "text",
        },
        {
            "name": "schema",
            "label": "Schema",
            "required": False,
            "kind": "text",
            "placeholder": "PUBLIC",
        },
        {
            "name": "warehouse",
            "label": "Warehouse",
            "required": False,
            "kind": "text",
        },
        {"name": "table", "label": "Table", "required": True, "kind": "text"},
        {
            "name": "auth_mode",
            "label": "Auth mode",
            "required": False,
            "kind": "select",
            "options": ["connection_string", "env_vars"],
        },
    ],
}

BIGQUERY_CONNECTOR: dict[str, Any] = {
    "type": "bigquery",
    "label": "BigQuery",
    "category": "Database",
    "status": "active",
    "params": [
        {
            "name": "project",
            "label": "GCP project",
            "required": True,
            "kind": "text",
            "placeholder": "my-gcp-project",
        },
        {
            "name": "dataset",
            "label": "Dataset",
            "required": True,
            "kind": "text",
        },
        {"name": "table", "label": "Table", "required": True, "kind": "text"},
        {
            "name": "auth_mode",
            "label": "Auth mode",
            "required": False,
            "kind": "select",
            "options": ["service_account_json", "env_vars"],
        },
    ],
}

ALL_NEW_CONNECTORS: list[dict[str, Any]] = [
    SQLSERVER_CONNECTOR,
    SNOWFLAKE_CONNECTOR,
    BIGQUERY_CONNECTOR,
]

# ---------------------------------------------------------------------------
# Extension commands
# ---------------------------------------------------------------------------

_EXTENSION_MAP: dict[str, list[str]] = {
    "sqlserver": ["INSTALL sqlserver;", "LOAD sqlserver;"],
    "snowflake": ["INSTALL snowflake;", "LOAD snowflake;"],
    "bigquery": ["INSTALL bigquery;", "LOAD bigquery;"],
}


def get_duckdb_extension_commands(connector_type: str) -> list[str]:
    """Return DuckDB SQL commands to install/load required extensions.

    Raises ``ValueError`` for unknown connector types.
    """
    key = connector_type.strip().lower()
    if key not in _EXTENSION_MAP:
        raise ValueError(f"Unknown connector type: {connector_type!r}")
    return list(_EXTENSION_MAP[key])


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------


def generate_source_sql(connector_type: str, params: dict[str, Any]) -> str:
    """Generate the DuckDB SQL to read from the external source.

    Returns a ``SELECT`` statement that DuckDB can execute after the
    corresponding extension has been loaded.

    Raises ``ValueError`` for unknown types or missing required params.
    """
    key = connector_type.strip().lower()
    if key == "sqlserver":
        return _generate_sqlserver_sql(params)
    if key == "snowflake":
        return _generate_snowflake_sql(params)
    if key == "bigquery":
        return _generate_bigquery_sql(params)
    raise ValueError(f"Unknown connector type: {connector_type!r}")


def _generate_sqlserver_sql(params: dict[str, Any]) -> str:
    conn_str = str(params.get("path") or "").strip()
    schema = str(params.get("schema") or "dbo").strip() or "dbo"
    table = str(params.get("table") or "").strip()
    if not conn_str:
        raise ValueError("path (connection string) is required for sqlserver")
    if not table:
        raise ValueError("table is required for sqlserver")
    inner_query = f"SELECT * FROM {_quote_bracket(schema)}.{_quote_bracket(table)}"
    return f"SELECT * FROM sqlserver_query({_sql_string_literal(conn_str)}, {_sql_string_literal(inner_query)})"


def _generate_snowflake_sql(params: dict[str, Any]) -> str:
    account = str(params.get("account") or "").strip()
    database = str(params.get("database") or "").strip()
    schema = str(params.get("schema") or "PUBLIC").strip() or "PUBLIC"
    table = str(params.get("table") or "").strip()
    if not account:
        raise ValueError("account is required for snowflake")
    if not database:
        raise ValueError("database is required for snowflake")
    if not table:
        raise ValueError("table is required for snowflake")
    # Snowflake uses DuckDB ATTACH; after attach the table is queryable via
    # a fully-qualified path.  We generate the ATTACH + SELECT pair.
    attach = (
        f"ATTACH {_sql_string_literal(account)} AS snowflake_db (TYPE snowflake, "
        f"database {_sql_string_literal(database)})"
    )
    select = (
        f"SELECT * FROM snowflake_db.{_quote_double(schema)}.{_quote_double(table)}"
    )
    return f"{attach};\n{select}"


def _generate_bigquery_sql(params: dict[str, Any]) -> str:
    project = str(params.get("project") or "").strip()
    dataset = str(params.get("dataset") or "").strip()
    table = str(params.get("table") or "").strip()
    if not project:
        raise ValueError("project is required for bigquery")
    if not dataset:
        raise ValueError("dataset is required for bigquery")
    if not table:
        raise ValueError("table is required for bigquery")
    attach = (
        f"ATTACH {_sql_string_literal(project)} AS bigquery_db (TYPE bigquery, "
        f"project {_sql_string_literal(project)})"
    )
    select = (
        f"SELECT * FROM bigquery_db.{_quote_backtick(dataset)}.{_quote_backtick(table)}"
    )
    return f"{attach};\n{select}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Map of connector type → list of (param_name, human_label) that are required
_REQUIRED_PARAMS: dict[str, list[tuple[str, str]]] = {
    "sqlserver": [("path", "Connection string"), ("table", "Table")],
    "snowflake": [("account", "Account"), ("database", "Database"), ("table", "Table")],
    "bigquery": [("project", "GCP project"), ("dataset", "Dataset"), ("table", "Table")],
}


def validate_source_params(connector_type: str, params: dict[str, Any]) -> list[str]:
    """Validate connector parameters.

    Returns a list of error messages.  An empty list means the params
    are valid.
    """
    key = connector_type.strip().lower()
    if key not in _REQUIRED_PARAMS:
        return [f"Unknown connector type: {connector_type!r}"]
    errors: list[str] = []
    for param_name, label in _REQUIRED_PARAMS[key]:
        value = str(params.get(param_name) or "").strip()
        if not value:
            errors.append(f"{label} ({param_name}) is required")
    return errors


# ---------------------------------------------------------------------------
# List tables
# ---------------------------------------------------------------------------


def list_tables_sql(connector_type: str, params: dict[str, Any]) -> str | None:
    """Return DuckDB SQL to list available tables, or ``None`` if not supported.

    The returned SQL is expected to produce rows of
    ``(table_schema, table_name)``.
    """
    key = connector_type.strip().lower()
    if key == "sqlserver":
        conn_str = str(params.get("path") or "").strip()
        if not conn_str:
            return None
        inner = (
            "SELECT TABLE_SCHEMA, TABLE_NAME "
            "FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE='BASE TABLE' "
            "ORDER BY TABLE_SCHEMA, TABLE_NAME"
        )
        return (
            f"SELECT * FROM sqlserver_query("
            f"{_sql_string_literal(conn_str)}, "
            f"{_sql_string_literal(inner)})"
        )

    if key == "snowflake":
        account = str(params.get("account") or "").strip()
        database = str(params.get("database") or "").strip()
        if not account or not database:
            return None
        attach = (
            f"ATTACH {_sql_string_literal(account)} AS snowflake_db (TYPE snowflake, "
            f"database {_sql_string_literal(database)})"
        )
        select = (
            "SELECT table_schema, table_name "
            "FROM snowflake_db.information_schema.tables "
            "WHERE table_type='BASE TABLE' "
            "ORDER BY table_schema, table_name"
        )
        return f"{attach};\n{select}"

    if key == "bigquery":
        project = str(params.get("project") or "").strip()
        dataset = str(params.get("dataset") or "").strip()
        if not project or not dataset:
            return None
        attach = (
            f"ATTACH {_sql_string_literal(project)} AS bigquery_db (TYPE bigquery, "
            f"project {_sql_string_literal(project)})"
        )
        select = (
            f"SELECT table_schema, table_name "
            f"FROM bigquery_db.information_schema.tables "
            f"WHERE table_schema={_sql_string_literal(dataset)} "
            f"ORDER BY table_schema, table_name"
        )
        return f"{attach};\n{select}"

    return None
