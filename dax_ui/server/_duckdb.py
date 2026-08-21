"""Community helper module — extracted from dax_ui.server.__init__."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, List, Mapping, Optional

import dax_compiler

from dax_ui.server._engine import _resolve_duckdb_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SEC-04: Query timeout via DuckDB interrupt()
# ---------------------------------------------------------------------------
_QUERY_TIMEOUT_S = int(os.environ.get("DAX_QUERY_TIMEOUT_MS", "30000")) / 1000.0


def execute_with_timeout(con: Any, sql: str, params: Any = None, timeout_s: float | None = None):
    """Execute a DuckDB query with a watchdog timer that calls ``con.interrupt()``.

    Returns the DuckDB result object.  Raises ``duckdb.InterruptException``
    (wrapped as ``TimeoutError``) if the query exceeds *timeout_s* seconds.
    """
    if timeout_s is None:
        timeout_s = _QUERY_TIMEOUT_S
    if timeout_s <= 0:
        return con.execute(sql, params) if params else con.execute(sql)

    fired = threading.Event()

    def _watchdog():
        fired.set()
        try:
            con.interrupt()
        except Exception:
            pass

    timer = threading.Timer(timeout_s, _watchdog)
    timer.daemon = True
    timer.start()
    try:
        result = con.execute(sql, params) if params else con.execute(sql)
    except Exception:
        if fired.is_set():
            raise TimeoutError(f"Query exceeded {timeout_s}s timeout") from None
        raise
    finally:
        timer.cancel()
    return result


# DuckDB / project column types that are considered "numeric" and may
# contain human-formatted values (currency symbols, thousands separators)
# in raw CSV exports from tools like Power BI.
_NUMERIC_COL_TYPES = frozenset({
    "DOUBLE", "FLOAT", "DECIMAL",
    "INTEGER", "BIGINT", "INT", "SMALLINT", "TINYINT",
})


def _duckdb_table_exists(con: Any, table_name: str) -> bool:
    try:
        row = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE lower(table_name) = lower(?) LIMIT 1",
            [str(table_name)],
        ).fetchone()
        return bool(row)
    except Exception:
        return False

def _sql_string_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"

def _resolve_source_path(project_path: str, raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValueError("source.path is required")
    p = Path(raw)
    if p.is_absolute():
        return p
    return (Path(project_path) / p)

def _is_remote_path(raw_path: str) -> bool:
    value = str(raw_path or "").strip().lower()
    return "://" in value or value.startswith("s3://") or value.startswith("r2://") or value.startswith("azure://")

# SEC-06: Only these extensions may be installed/loaded
_ALLOWED_EXTENSIONS = frozenset({
    "excel", "azure", "httpfs", "delta", "iceberg",
    "parquet", "json", "csv", "spatial", "icu",
})


def _ensure_duckdb_extension(con: Any, name: str) -> None:
    # SEC-06: Validate against whitelist before executing
    if name not in _ALLOWED_EXTENSIONS:
        raise ValueError(f"DuckDB extension '{name}' is not in the allowed list")
    try:
        con.execute(f"INSTALL {name}")
    except Exception:
        pass
    try:
        con.execute(f"LOAD {name}")
    except Exception as exc:
        raise ValueError(f"Failed to load DuckDB extension '{name}': {exc}")

def _csv_options_from_source(src: Mapping[str, Any]) -> tuple[str, list[Any]]:
    options: list[str] = []
    params: list[Any] = []

    header = src.get("header")
    if header is None:
        header = True
    options.append(f"header={'true' if bool(header) else 'false'}")

    delim = src.get("delimiter")
    if isinstance(delim, str) and delim:
        if len(delim) != 1:
            raise ValueError("csv delimiter must be a single character")
        options.append(f"delim={_sql_string_literal(delim)}")

    encoding = src.get("encoding")
    if isinstance(encoding, str) and encoding.strip():
        options.append(f"encoding={_sql_string_literal(encoding.strip())}")

    nullstr = src.get("nullstr")
    if nullstr is None:
        nullstr = [""]
    if isinstance(nullstr, list):
        safe_vals = [_sql_string_literal(str(v)) for v in nullstr]
        options.append(f"nullstr=[{', '.join(safe_vals)}]")
    elif isinstance(nullstr, str):
        options.append(f"nullstr=[{_sql_string_literal(nullstr)}]")
    else:
        raise ValueError("csv nullstr must be a string or list")

    if not options:
        return ("read_csv_auto(?)", params)
    return (f"read_csv_auto(?, {', '.join(options)})", params)

def _read_by_format_sql(fmt: str, src: Mapping[str, Any]) -> tuple[str, list[Any]]:
    norm = str(fmt or "").strip().lower()
    if norm == "csv":
        return _csv_options_from_source(src)
    if norm == "parquet":
        return ("read_parquet(?)", [])
    if norm == "json":
        return ("read_json_auto(?)", [])
    if norm == "text":
        return ("read_text(?)", [])
    raise ValueError(f"Unsupported format: {fmt!r}")

def _build_typed_csv_select(columns: List[Any], read_from: str) -> str:
    """Build a SELECT statement that casts CSV columns to proper types.

    Uses DuckDB's ``SELECT * REPLACE (...)`` syntax to apply
    ``TRY_CAST(REGEXP_REPLACE(col, currency_chars, '') AS <type>)``
    for each physical column whose declared type is numeric, and
    ``TRY_CAST(col AS TIMESTAMP)`` (or strptime with known format)
    for date/timestamp columns.

    This allows raw CSVs with currency-formatted values (``$1,234.56``)
    or human-readable dates to be loaded without a separate cleaning
    step — the column type metadata from the project YAML drives the
    casting.

    If there are no columns to transform, returns a plain
    ``SELECT * FROM ...``.
    """
    _DATE_COL_TYPES = frozenset({"DATE", "TIMESTAMP", "DATETIME"})
    # Known PBI "Long Date" format → strptime pattern
    _LONG_DATE_STRPTIME = "%A, %B %d, %Y"

    replaces: list[str] = []
    for col in columns:
        col_type = str(getattr(col, "type", "") or "").strip().upper()
        # Skip calculated columns — they don't exist in the CSV
        if getattr(col, "is_calculated", False) or getattr(col, "expression", None):
            continue
        col_name = str(getattr(col, "name", "")).strip()
        if not col_name:
            continue
        quoted = dax_compiler.quote_ident(col_name)

        if col_type in _NUMERIC_COL_TYPES:
            # Strip currency symbols ($€£¥₹) and thousands separators (,)
            # then cast to the declared type.  TRY_CAST returns NULL on failure
            # instead of raising, which is safer for mixed data.
            replaces.append(
                f"TRY_CAST(REGEXP_REPLACE(CAST({quoted} AS VARCHAR), "
                f"'[\\$€£¥₹,]', '', 'g') AS {col_type}) AS {quoted}"
            )
        elif col_type in _DATE_COL_TYPES:
            col_format = str(getattr(col, "format", "") or "").strip()
            target = "TIMESTAMP" if col_type in ("TIMESTAMP", "DATETIME") else "DATE"
            if col_format.lower() in ("long date", "long_date"):
                # "Friday, August 25, 2017" → strptime
                replaces.append(
                    f"TRY_CAST(strptime(CAST({quoted} AS VARCHAR), "
                    f"'{_LONG_DATE_STRPTIME}') AS {target}) AS {quoted}"
                )
            else:
                # Generic: try standard ISO cast first
                replaces.append(
                    f"TRY_CAST({quoted} AS {target}) AS {quoted}"
                )

    if not replaces:
        return f"SELECT * FROM {read_from}"

    replace_clause = ", ".join(replaces)
    return f"SELECT * REPLACE ({replace_clause}) FROM {read_from}"


def _ensure_duckdb_sources_loaded(*, con: Any, project_path: str, model: Any) -> None:
    """Best-effort load physical sources into an in-memory DuckDB connection.

    This supports the runtime UI for projects that define table sources (e.g. CSV)
    but don't provide a persistent DuckDB file via DAX_DUCKDB_PATH.

    Storage mode dispatching (Phase 9):
    - import: CREATE TABLE (materialize data)
    - direct_query / direct_lake: CREATE VIEW (live pass-through)
    """
    from dax_engine.storage_modes import StorageMode, infer_storage_mode, parse_storage_mode

    tables = list(getattr(model, "tables", []) or [])
    root = Path(project_path)
    attached: dict[str, str] = {}

    def _ensure_attach(path: Path) -> str:
        key = str(path)
        if key in attached:
            return attached[key]
        alias = f"src{len(attached) + 1}"
        con.execute(f"ATTACH {_sql_string_literal(str(path))} AS {dax_compiler.quote_ident(alias)}")
        attached[key] = alias
        return alias

    for t in tables:
        name = str(getattr(t, "name", "")).strip()
        if not name:
            continue
        if _duckdb_table_exists(con, name):
            continue

        src = getattr(t, "source", None)
        if not isinstance(src, Mapping):
            continue
        src_type = str(src.get("type") or "").strip().lower()
        src_path = src.get("path")
        if not isinstance(src_path, str) or not src_path.strip():
            continue
        src_path_clean = src_path.strip()
        is_remote = _is_remote_path(src_path_clean)
        full: Optional[Path] = None

        # Phase 9: Resolve storage mode for this table.
        raw_mode = getattr(t, "storage_mode", None)
        try:
            mode = parse_storage_mode(raw_mode)
        except ValueError:
            mode = infer_storage_mode(src)
        # Decide whether to materialize (CREATE TABLE) or pass-through (CREATE VIEW).
        materialize = mode == StorageMode.IMPORT

        local_types = {"csv", "parquet", "json", "text", "blob", "excel", "duckdb", "sqlite"}
        if src_type in local_types or (src_type in {"delta", "iceberg"} and not is_remote):
            try:
                full = _resolve_source_path(project_path, src_path_clean)
            except Exception:
                continue
            if not full.exists():
                continue

        if src_type == "csv":
            read_sql, _params = _csv_options_from_source(src)
            # Use column type metadata to generate typed casts for numeric
            # columns that may contain currency formatting in the raw CSV.
            table_columns = list(getattr(t, "columns", []) or [])
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            if materialize:
                select_sql = _build_typed_csv_select(table_columns, read_sql)
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS {select_sql}",
                    [str(full)],
                )
            else:
                # VIEW requires literal path (no parameterized ?)
                read_sql_lit = read_sql.replace("?", _sql_string_literal(str(full)), 1)
                select_sql = _build_typed_csv_select(table_columns, read_sql_lit)
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS {select_sql}"
                )
        elif src_type == "parquet":
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            if materialize:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_parquet(?)",
                    [str(full)],
                )
            else:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_parquet({_sql_string_literal(str(full))})"
                )
        elif src_type == "json":
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            if materialize:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_json_auto(?)",
                    [str(full)],
                )
            else:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_json_auto({_sql_string_literal(str(full))})"
                )
        elif src_type == "text":
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            text_path = full.as_posix()
            if materialize:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_text(?)",
                    [text_path],
                )
            else:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_text({_sql_string_literal(text_path)})"
                )
        elif src_type == "blob":
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            if materialize:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_blob(?)",
                    [str(full)],
                )
            else:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_blob({_sql_string_literal(str(full))})"
                )
        elif src_type == "excel":
            _ensure_duckdb_extension(con, "excel")
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            if materialize:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_excel(?)",
                    [str(full)],
                )
            else:
                con.execute(
                    f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM read_excel({_sql_string_literal(str(full))})"
                )
        elif src_type == "duckdb":
            schema = str(src.get("schema") or "main").strip() or "main"
            table = str(src.get("table") or "").strip()
            if not table:
                continue
            alias = _ensure_attach(full)
            src_name = f"{dax_compiler.quote_ident(schema)}.{dax_compiler.quote_ident(table)}"
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            con.execute(
                f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM {dax_compiler.quote_ident(alias)}.{src_name}"
            )
        elif src_type == "sqlite":
            table = str(src.get("table") or "").strip()
            if not table:
                continue
            try:
                con.execute("INSTALL sqlite_scanner")
            except Exception:
                # Extension may already be installed; ignore failures here.
                pass
            con.execute("LOAD sqlite_scanner")
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            con.execute(
                f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM sqlite_scan({_sql_string_literal(str(full))}, {_sql_string_literal(table)})"
            )
        elif src_type in {"http", "s3", "azure_blob", "cloudflare_r2"}:
            if src_type == "azure_blob":
                _ensure_duckdb_extension(con, "azure")
            else:
                _ensure_duckdb_extension(con, "httpfs")
            fmt = str(src.get("format") or "").strip().lower()
            read_sql, _params = _read_by_format_sql(fmt, src)
            read_sql = read_sql.replace("?", _sql_string_literal(src_path_clean), 1)
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            con.execute(
                f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM {read_sql}"
            )
        elif src_type in {"delta", "iceberg"}:
            _ensure_duckdb_extension(con, "httpfs")
            ext_name = "delta" if src_type == "delta" else "iceberg"
            _ensure_duckdb_extension(con, ext_name)
            read_fn = "read_delta" if src_type == "delta" else "read_iceberg"
            path_value = src_path_clean
            if full is not None:
                path_value = str(full)
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            con.execute(
                f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM {read_fn}({_sql_string_literal(path_value)})"
            )
        elif src_type == "postgres":
            _ensure_duckdb_extension(con, "postgres")
            schema = str(src.get("schema") or "public").strip() or "public"
            table = str(src.get("table") or "").strip()
            if not table:
                continue
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            con.execute(
                f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM postgres_scan({_sql_string_literal(src_path_clean)}, {_sql_string_literal(schema)}, {_sql_string_literal(table)})"
            )
        elif src_type == "mysql":
            _ensure_duckdb_extension(con, "mysql")
            schema = str(src.get("schema") or "").strip()
            table = str(src.get("table") or "").strip()
            if not schema or not table:
                continue
            ddl = "CREATE TABLE" if materialize else "CREATE VIEW"
            con.execute(
                f"{ddl} {dax_compiler.quote_ident(name)} AS SELECT * FROM mysql_scan({_sql_string_literal(src_path_clean)}, {_sql_string_literal(schema)}, {_sql_string_literal(table)})"
            )

    # ── Phase 2: Materialize calculated tables ──────────────────────────
    # After all physical sources are loaded, compile & materialize
    # calculated tables (is_calculated=true + expression) so they are
    # available as real DuckDB tables for joins and queries.
    _materialize_calculated_tables(con=con, model=model)

    # ── Phase 3: Materialize field parameter tables ──────────────────────
    # Field parameters are virtual tables in the semantic model, but visuals
    # may reference them by their Power BI table name (e.g., "Parameter Columns").
    # Create DuckDB tables so SQL queries against them work.
    _materialize_field_parameter_tables(con=con, model=model)


def _materialize_field_parameter_tables(*, con: Any, model: Any) -> None:
    """Create DuckDB tables for field parameters so SQL queries resolve.

    Power BI field parameter tables (e.g., ``Parameter Columns``) are virtual
    in our semantic model, but visuals may reference them directly via ColumnRef.
    This function creates actual DuckDB tables with columns matching the items
    defined in ``field_parameters.yaml``.

    Columns created per table:
    - Primary column (same name as items) — item display names
    - ``Hierarchy`` column — the locale/grouping value (if items have ``locale``)
    - Sort column — integer sort order

    Both the Power BI table name (e.g. ``Parameter Columns``) and the
    ``FieldParams_`` prefixed name are registered via VIEWs.
    """
    from collections.abc import Mapping as MappingABC

    fps_map = getattr(model, "field_parameters", {}) or {}
    if not isinstance(fps_map, MappingABC):
        return

    for fp_name, fp in fps_map.items():
        name = str(getattr(fp, "name", fp_name) or "").strip()
        if not name:
            continue

        items = list(getattr(fp, "items", []) or [])
        if not items:
            continue

        # Determine the canonical table name (unprefixed Power BI name).
        # Also create a FieldParams_-prefixed alias.
        canonical_name = name
        prefixed_name = f"FieldParams_{name}"

        # Skip if already exists (e.g. DuckDB file already has the table).
        if _duckdb_table_exists(con, canonical_name) and _duckdb_table_exists(con, prefixed_name):
            continue

        # Check if any items have locale data → create Hierarchy column.
        # Locale is stored in custom_props (not a direct attribute on FieldParameterItem).
        def _item_locale(item: Any) -> str:
            cp = getattr(item, "custom_props", None)
            if isinstance(cp, dict):
                loc = cp.get("locale", "")
                if isinstance(loc, str) and loc.strip():
                    return loc.strip()
            return ""

        has_locale = any(_item_locale(item) for item in items)

        # Build values
        rows: list[tuple[str, int, str]] = []
        for item in items:
            iname = str(getattr(item, "name", "")).strip()
            if not iname:
                continue
            sort_val = 0
            raw_sort = getattr(item, "sort", None)
            if raw_sort is not None:
                try:
                    sort_val = int(raw_sort)
                except (TypeError, ValueError):
                    pass
            locale_val = _item_locale(item)
            rows.append((iname, sort_val, locale_val))

        if not rows:
            continue

        # Build the CREATE TABLE statement.
        # Use "_fp_value" as the primary column name to avoid DuckDB ambiguity
        # when the param name matches the table name (e.g., table "Parameter Columns"
        # with a column also named "Parameter Columns" causes struct-field confusion).
        primary_col = '"_fp_value"'
        cols_ddl = [f"{primary_col} VARCHAR", '"Sort" INTEGER']
        if has_locale:
            cols_ddl.append('"Hierarchy" VARCHAR')

        values_parts: list[str] = []
        for iname, sort_val, locale_val in rows:
            if has_locale:
                values_parts.append(
                    f"({_sql_string_literal(iname)}, {sort_val}, {_sql_string_literal(locale_val)})"
                )
            else:
                values_parts.append(
                    f"({_sql_string_literal(iname)}, {sort_val})"
                )

        values_sql = ", ".join(values_parts)

        try:
            if not _duckdb_table_exists(con, canonical_name):
                con.execute(
                    f"CREATE TABLE {dax_compiler.quote_ident(canonical_name)} "
                    f"({', '.join(cols_ddl)})"
                )
                con.execute(
                    f"INSERT INTO {dax_compiler.quote_ident(canonical_name)} VALUES {values_sql}"
                )

            # Create prefixed alias as a VIEW if it doesn't exist.
            if not _duckdb_table_exists(con, prefixed_name):
                con.execute(
                    f"CREATE VIEW {dax_compiler.quote_ident(prefixed_name)} AS "
                    f"SELECT * FROM {dax_compiler.quote_ident(canonical_name)}"
                )
        except Exception as exc:
            logger.warning("Failed to materialize field parameter table %r: %s", canonical_name, exc)


def _materialize_calculated_tables(*, con: Any, model: Any) -> None:
    """Compile and materialize calculated tables into DuckDB.

    Handles dependencies between calculated tables via multi-pass iteration.
    Tables that only serve as measure containers (no expression) are skipped.
    """
    from dax_parser.ir_mapper import ast_to_ir
    from dax_parser.parser import parse_expression

    tables = list(getattr(model, "tables", []) or [])
    calc_tables = [
        t for t in tables
        if bool(getattr(t, "is_calculated", False))
        and getattr(t, "expression", None)
    ]
    if not calc_tables:
        return

    # We need the engine's compile infrastructure.  Set up measures and
    # relationships so compile_table_expr can resolve references.
    from dax_engine.table_sources import clear_table_sources

    # Collect measures for compilation context.
    compiled_measures: dict[str, Any] = {}
    for m in getattr(model, "measures", []) or []:
        mname = getattr(m, "name", None)
        dax_text = getattr(m, "dax", None)
        if not isinstance(mname, str) or not mname.strip():
            continue
        if not isinstance(dax_text, str) or not dax_text.strip():
            continue
        try:
            ir = ast_to_ir(parse_expression(dax_text))
            if isinstance(ir, dax_compiler.ScalarExpr):
                compiled_measures[mname] = ir
        except Exception:
            pass

    # Set up relationships.
    rels = getattr(model, "relationships", []) or []
    relationships: list[Any] = []
    for r in rels:
        try:
            relationships.append(
                dax_compiler.Relationship(
                    getattr(r, "from_table"),
                    getattr(r, "from_column"),
                    getattr(r, "to_table"),
                    getattr(r, "to_column"),
                    active=bool(getattr(r, "active", True)),
                    rel_id=str(getattr(r, "rel_id", "")),
                    cross_filter_direction=str(getattr(r, "cross_filter_direction", "single") or "single"),
                    cardinality=(str(getattr(r, "cardinality", "")).strip() or None),
                )
            )
        except Exception:
            pass

    # Prepare compiler state.
    dax_compiler.reset_engine_state()
    dax_compiler.set_relationships(list(relationships))
    dax_compiler.set_measures(dict(compiled_measures))
    clear_table_sources()

    # Multi-pass: resolve calc tables in dependency order.
    pending = list(calc_tables)
    materialized: dict[str, str] = {}
    for _pass in range(len(pending) + 2):
        if not pending:
            break
        progressed = False
        still: list[Any] = []
        for t in pending:
            name = str(getattr(t, "name", "")).strip()
            dax_text = getattr(t, "expression", None)
            if not name or not isinstance(dax_text, str) or not dax_text.strip():
                continue
            if _duckdb_table_exists(con, name):
                progressed = True
                continue
            try:
                ir = ast_to_ir(parse_expression(dax_text))
                sql = dax_compiler.compile_table_expr(ir, dax_compiler.Context())
                # Normalize: compile_table_expr may return a bare table reference.
                upper = sql.lstrip().upper()
                if not (sql.strip().startswith("(") or upper.startswith("SELECT") or upper.startswith("WITH")):
                    sql = f"SELECT * FROM {sql}"
                con.execute(f"CREATE TABLE {dax_compiler.quote_ident(name)} AS {sql}")
                materialized[name] = sql
                # Rename columns if the YAML defines different names
                # (e.g. GENERATESERIES yields "Value" but YAML says "Parameter").
                yaml_cols = [
                    str(getattr(c, "name", "")).strip()
                    for c in (getattr(t, "columns", []) or [])
                    if getattr(c, "name", None)
                ]
                if yaml_cols:
                    actual_cols = [
                        d[0] for d in
                        con.execute(f"SELECT * FROM {dax_compiler.quote_ident(name)} LIMIT 0").description
                    ]
                    for idx, ycol in enumerate(yaml_cols):
                        if idx < len(actual_cols) and actual_cols[idx] != ycol:
                            try:
                                con.execute(
                                    f"ALTER TABLE {dax_compiler.quote_ident(name)} "
                                    f"RENAME COLUMN {dax_compiler.quote_ident(actual_cols[idx])} "
                                    f"TO {dax_compiler.quote_ident(ycol)}"
                                )
                            except Exception:
                                pass
                # Update table_sources so subsequent calc tables can reference this one.
                dax_compiler.set_table_sources(dict(materialized))
                progressed = True
                logger.info("Materialized calculated table: %s", name)
            except Exception as exc:
                logger.debug("Deferred calculated table %s (pass %d): %s", name, _pass, exc)
                still.append(t)
        if not progressed:
            break
        pending = still

    if pending:
        names = [str(getattr(t, "name", "?")).strip() for t in pending]
        logger.warning("Could not materialize calculated tables: %s", ", ".join(names))

    # Remove materialized tables from the global table_sources registry so
    # that the compiler references them as real DuckDB tables instead of
    # expanding their expression SQL inline.
    if materialized:
        try:
            from dax_engine.table_sources import _TABLE_SOURCES as _ts_registry
            for mat_name in materialized:
                _ts_registry.pop(mat_name.upper(), None)
        except Exception:
            pass


def _materialize_missing_calc_tables(*, con: Any, model: Any) -> None:
    """Materialize calculated tables that exist in the model but not in a file-backed DB.

    Unlike ``_materialize_calculated_tables`` (used for in-memory mode), this
    function does NOT reset engine state — it relies on the engine state already
    set up by ``get_prepared_engine()``.
    """
    from dax_parser.ir_mapper import ast_to_ir
    from dax_parser.parser import parse_expression

    tables = list(getattr(model, "tables", []) or [])
    for t in tables:
        name = str(getattr(t, "name", "")).strip()
        expr = getattr(t, "expression", None)
        is_calc = bool(getattr(t, "is_calculated", False))
        if not name or not is_calc or not isinstance(expr, str) or not expr.strip():
            continue
        if _duckdb_table_exists(con, name):
            continue
        try:
            ir = ast_to_ir(parse_expression(expr))
            # Use the compiler's top-level compile_table_expr which handles
            # DI arguments automatically.
            table_sql = dax_compiler.compile_table_expr(ir, dax_compiler.Context())
            upper = table_sql.lstrip().upper()
            if not (table_sql.strip().startswith("(") or upper.startswith("SELECT") or upper.startswith("WITH")):
                table_sql = f"SELECT * FROM {table_sql}"
            con.execute(
                f"CREATE TABLE {dax_compiler.quote_ident(name)} AS {table_sql}"
            )
            logger.info("Materialized calculated table (file-backed): %s", name)
        except Exception as exc:
            logger.debug("Failed to materialize calc table %r: %s", name, exc)


# ── DuckDB connection cache (performance) ────────────────────────────────
# Creating a DuckDB connection + registering UDFs + (for in-memory mode)
# loading all project sources is expensive (~50-200 ms).  During crossfilter
# bursts 6-14 visuals render concurrently, so per-request connection setup
# adds 300-2800 ms of cumulative overhead.
#
# This cache stores one connection per thread (via threading.local) keyed by
# the resolved db_path.  Reusing the cached connection eliminates redundant
# UDF registration, source loading, and calc-table materialization.
#
# Thread-safety: each thread gets its own DuckDB connection, so there are no
# concurrent access issues within DuckDB.  The cache is invalidated when the
# project_path or db_path changes.
import threading as _threading

_duckdb_conn_local = _threading.local()


def _get_cached_duckdb_connection(*, db_path: Optional[str], project_path: str, model: Any):
    """Return a cached per-thread DuckDB connection, creating one if needed.

    The cache key is (db_path, project_path).  If either changes, a new
    connection is created and the old one is not explicitly closed (DuckDB
    connections are lightweight and cleaned up on GC).
    """
    import duckdb

    cache_key = (db_path, os.path.normcase(os.path.abspath(project_path)))
    cached = getattr(_duckdb_conn_local, 'entry', None)
    if cached is not None:
        cached_key, cached_con = cached
        if cached_key == cache_key:
            try:
                # Quick health check — execute a trivial query to verify the
                # connection is still alive (not closed or corrupted).
                cached_con.execute("SELECT 1")
                return cached_con
            except Exception:
                # Connection is dead — fall through and create a new one.
                pass

    # Create a new connection
    con = duckdb.connect(db_path) if db_path else duckdb.connect()
    try:
        from dax_engine.duckdb_udfs import register_all_udfs
        register_all_udfs(con)
    except Exception as exc:
        logger.warning("Failed to register DuckDB UDFs: %s", exc)
    if not db_path:
        _ensure_duckdb_sources_loaded(con=con, project_path=project_path, model=model)
    else:
        _materialize_missing_calc_tables(con=con, model=model)
        _materialize_field_parameter_tables(con=con, model=model)

    _duckdb_conn_local.entry = (cache_key, con)
    return con


def invalidate_duckdb_connection_cache() -> None:
    """Clear the per-thread DuckDB connection cache.

    Call this after project switch, Save All, or any operation that changes
    the on-disk data sources so the next render uses a fresh connection.
    """
    _duckdb_conn_local.entry = None


def _connect_duckdb_for_project(*, project_path: str, duckdb_path: Optional[str], model: Any):
    import duckdb

    db_path = _resolve_duckdb_path(duckdb_path)

    # Project-aware DuckDB resolution: if the resolved path comes from the
    # global DAX_DUCKDB_PATH env var and belongs to a *different* project,
    # look for a project-local .duckdb file or fall back to auto-loading.
    if db_path and not duckdb_path:
        # Only re-evaluate when the path came from the env var (duckdb_path
        # param was None), not when the caller explicitly passed a path.
        try:
            resolved_db = Path(db_path).resolve()
            resolved_project = Path(project_path).resolve()
            if not str(resolved_db).startswith(str(resolved_project) + os.sep) and resolved_db.parent != resolved_project:
                # DuckDB file is outside this project — look for a local one.
                local_dbs = sorted(resolved_project.glob("*.duckdb"))
                if local_dbs:
                    db_path = str(local_dbs[0])
                else:
                    db_path = None  # Fall back to in-memory + auto-load
        except Exception:
            pass

    # Performance: reuse cached per-thread connection to avoid redundant
    # UDF registration and source loading on every render request.
    return _get_cached_duckdb_connection(db_path=db_path, project_path=project_path, model=model)

_REL_CARDINALITY_SYNONYMS: dict[str, str] = {
    "1:1": "one_to_one",
    "one_to_one": "one_to_one",
    "one-to-one": "one_to_one",
    "1:n": "one_to_many",
    "1:m": "one_to_many",
    "1:*": "one_to_many",
    "one_to_many": "one_to_many",
    "one-to-many": "one_to_many",
    "n:1": "many_to_one",
    "m:1": "many_to_one",
    "*:1": "many_to_one",
    "many_to_one": "many_to_one",
    "many-to-one": "many_to_one",
    "n:n": "many_to_many",
    "m:n": "many_to_many",
    "*:*": "many_to_many",
    "many_to_many": "many_to_many",
    "many-to-many": "many_to_many",
}

def _normalize_relationship_cardinality(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    normalized = _REL_CARDINALITY_SYNONYMS.get(raw)
    if normalized is None:
        allowed = ", ".join(["1:1", "1:n", "n:1", "n:n"])
        raise ValueError(f"Invalid cardinality {value!r}. Use one of: {allowed} (or canonical one_to_* values).")
    return normalized

def _pretty_relationship_cardinality(value: str) -> str:
    return {
        "one_to_one": "1:1",
        "one_to_many": "1:n",
        "many_to_one": "n:1",
        "many_to_many": "n:n",
    }.get(value, value)

def _detect_relationship_cardinality(
    *,
    project_path: str,
    model: Any,
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    duckdb_path: Optional[str] = None,
) -> str:
    con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
    try:
        def _is_unique(table_name: str, column_name: str) -> bool:
            qt = dax_compiler.quote_ident(table_name)
            qc = dax_compiler.quote_ident(column_name)
            row = con.execute(
                f"SELECT COUNT({qc}) AS non_null_count, COUNT(DISTINCT {qc}) AS distinct_non_null_count FROM {qt}"
            ).fetchone()
            non_null_count = int((row[0] if row and row[0] is not None else 0) or 0)
            distinct_non_null_count = int((row[1] if row and row[1] is not None else 0) or 0)
            return non_null_count == distinct_non_null_count

        from_unique = _is_unique(from_table, from_column)
        to_unique = _is_unique(to_table, to_column)

        if from_unique and to_unique:
            return "one_to_one"
        if from_unique and not to_unique:
            return "one_to_many"
        if (not from_unique) and to_unique:
            return "many_to_one"
        return "many_to_many"
    finally:
        try:
            con.close()
        except Exception:
            pass

def _resolve_and_validate_relationship_cardinality(
    *,
    project_path: str,
    model: Any,
    requested_cardinality: Optional[str],
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    duckdb_path: Optional[str] = None,
) -> str:
    requested = _normalize_relationship_cardinality(requested_cardinality)
    try:
        detected = _detect_relationship_cardinality(
            project_path=project_path,
            model=model,
            from_table=from_table,
            from_column=from_column,
            to_table=to_table,
            to_column=to_column,
            duckdb_path=duckdb_path,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "Cardinality auto-detection failed for "
            f"{from_table}[{from_column}] -> {to_table}[{to_column}]: {exc}"
        ) from exc

    if requested is not None and requested != detected:
        raise ValueError(
            "Cardinality mismatch: "
            f"requested {_pretty_relationship_cardinality(requested)} but detected {_pretty_relationship_cardinality(detected)} "
            f"for relationship {from_table}[{from_column}] -> {to_table}[{to_column}]."
        )
    return requested or detected

def _serialize_stat_value(val: Any) -> Any:
    """Serialize a DuckDB statistic value for JSON response."""
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if isinstance(val, float):
        if val != val:  # NaN
            return None
        return round(val, 4)
    if isinstance(val, (int, bool, str)):
        return val
    return str(val)

