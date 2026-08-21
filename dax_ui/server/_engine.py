"""Community helper module — extracted from dax_ui.server.__init__."""
from __future__ import annotations

import logging
import os
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import dax_compiler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidateResult:
    ok: bool
    value: Optional[Any] = None
    sql: Optional[str] = None
    error: Optional[str] = None

def _ensure_mapping_loaded() -> None:
    # Ensure verified table rewrites (e.g., SUMMARIZECOLUMNS) are registered.
    dax_compiler.load_default_mapping(register_verified_table_rewrites=True, env_var=None)

@dataclass(frozen=True)
class PreparedEngineState:
    project_key: str
    signature: tuple[int, int, int]
    relationships: list[Any]
    measures: dict[str, dax_compiler.ScalarExpr]
    table_sources: dict[str, str]
    calculated_column_sql: dict[str, str]

_ENGINE_LOCK = threading.Lock()

_ENGINE_CACHE: dict[str, PreparedEngineState] = {}

_ACTIVE_ENGINE: Optional[tuple[str, tuple[int, int, int]]] = None

def _norm_project_key(project_path: str) -> str:
    # Normalize for stable cache keys across Windows path casing.
    return os.path.normcase(os.path.abspath(project_path))

def _project_signature(project_path: str) -> tuple[int, int, int]:
    """Compute a simple project signature based on model YAML mtimes."""

    model_dir = Path(project_path) / "model"
    measures_path = model_dir / "measures.yaml"
    rels_path = model_dir / "relationships.yaml"

    tables_dir = model_dir / "tables"

    def _mtime_ns(p: Path) -> int:
        try:
            return int(p.stat().st_mtime_ns)
        except FileNotFoundError:
            return 0


    table_mtime = 0
    if tables_dir.exists() and tables_dir.is_dir():
        for p in tables_dir.glob("*.yaml"):
            table_mtime = max(table_mtime, _mtime_ns(p))

    return (_mtime_ns(measures_path), _mtime_ns(rels_path), int(table_mtime))

def get_prepared_engine(project_path: str, model: Any) -> None:
    """Ensure engine global registry matches this project.

    Uses a per-project cache of compiled measure IR + relationship objects.
    IMPORTANT: callers must hold `_ENGINE_LOCK` across planning.
    """

    global _ACTIVE_ENGINE

    project_key = _norm_project_key(project_path)
    sig = _project_signature(project_path)

    active = _ACTIVE_ENGINE
    if active is not None and active[0] == project_key and active[1] == sig:
        # Restore the complete compiler registry on every cache hit. Other code
        # paths and test/app lifecycles can reset or replace process-global
        # measures, relationships, table sources, or calculated columns without
        # knowing about this module's active-project marker.
        cached_hit = _ENGINE_CACHE.get(project_key)
        if cached_hit is not None:
            dax_compiler.set_relationships(list(cached_hit.relationships))
            dax_compiler.set_measures(dict(cached_hit.measures))
            dax_compiler.set_table_sources(dict(cached_hit.table_sources))
            dax_compiler.set_calculated_column_sql(dict(getattr(cached_hit, "calculated_column_sql", {}) or {}))
            return
        # An active marker without its cache entry is stale; rebuild below.

    cached = _ENGINE_CACHE.get(project_key)
    if cached is None or cached.signature != sig:
        # Build relationships.
        rels = getattr(model, "relationships", [])
        relationships: list[Any] = []
        for r in rels:
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

        # Compile measures once per signature.
        from dax_parser.ir_mapper import ast_to_ir
        from dax_parser.parser import parse_expression

        compiled: dict[str, dax_compiler.ScalarExpr] = {}
        for m in getattr(model, "measures", []) or []:
            name = getattr(m, "name", None)
            dax_text = getattr(m, "dax", None)
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(dax_text, str) or not dax_text.strip():
                continue
            ir = ast_to_ir(parse_expression(dax_text))
            if not isinstance(ir, dax_compiler.ScalarExpr):
                raise TypeError(f"Measure {name!r} must compile to a scalar expression")
            compiled[name] = ir

        # Compile calculated table/column sources (virtual-only) into a table_sources mapping.
        # Also compute calculated-column SQL expressions so ColumnRef(Table, CalcCol) can expand.
        table_sources: dict[str, str] = {}
        calculated_column_sql: dict[str, str] = {}
        try:
            _ensure_mapping_loaded()
            # Ensure compilation sees the correct per-project measures/relationships.
            dax_compiler.reset_engine_state()
            dax_compiler.set_relationships(list(relationships))
            dax_compiler.set_measures(dict(compiled))
            table_sources, calculated_column_sql = _compile_table_sources_for_model(model)
            # Remove entries for tables that will be materialized as real
            # DuckDB tables by _materialize_calculated_tables().  Those tables
            # have is_calculated=True + expression.  Leaving them in
            # table_sources would cause the compiler to expand them inline
            # (wrong column names, etc.) instead of referencing the
            # materialized table.
            materialized_names = {
                str(getattr(t, "name", "")).strip()
                for t in (getattr(model, "tables", []) or [])
                if bool(getattr(t, "is_calculated", False))
                and getattr(t, "expression", None)
            }
            for mname in materialized_names:
                table_sources.pop(mname, None)
        except Exception:
            table_sources = {}
            calculated_column_sql = {}

        cached = PreparedEngineState(
            project_key=project_key,
            signature=sig,
            relationships=relationships,
            measures=compiled,
            table_sources=table_sources,
            calculated_column_sql=calculated_column_sql,
        )
        _ENGINE_CACHE[project_key] = cached

    # Switch global engine state to this cached project.
    dax_compiler.reset_engine_state()
    dax_compiler.set_relationships(list(cached.relationships))
    dax_compiler.set_measures(dict(cached.measures))
    dax_compiler.set_table_sources(dict(cached.table_sources))
    dax_compiler.set_calculated_column_sql(dict(getattr(cached, "calculated_column_sql", {}) or {}))
    _ACTIVE_ENGINE = (project_key, sig)

def _get_engine_table_sources(project_path: str, model: Any) -> dict[str, str]:
    """Return the compiled table_sources dict for the given project.

    Ensures the engine cache is populated, then reads the table_sources entry.
    Falls back to empty dict on error.
    """
    try:
        get_prepared_engine(project_path, model)
        project_key = _norm_project_key(project_path)
        cached = _ENGINE_CACHE.get(project_key)
        if cached is None:
            return {}
        return dict(getattr(cached, "table_sources", {}) or {})
    except Exception:
        return {}

def _has_cross_table_refs(sql: str, alias: str) -> bool:
    """Return True if *sql* contains qualified column references other than *alias*.

    After rewriting the current table to *alias* (e.g. ``t``), any remaining
    ``IDENT."col"`` or ``IDENT.col`` pattern indicates a cross-table reference
    that cannot be inlined inside the table_source wrapper.
    """
    import re
    for m in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_]*)\.(?="|\b[A-Za-z_])', sql):
        if m.group(1) != alias:
            return True
    return False

def _compile_table_sources_for_model(model: Any) -> tuple[dict[str, str], dict[str, str]]:
    """Build a mapping of logical table -> raw SELECT/WITH SQL.

    Notes:
    - Values are raw subqueries (SELECT/WITH) without aliasing.
    - The engine's resolve_table_source_sql() will wrap+alias to the logical table name.
    - This is orchestration only; it does not execute DuckDB.
    """

    from dax_engine.sql_utils import as_from_source, quote_alias, quote_ident, rewrite_table_qualifier_to_alias
    from dax_engine.table_sources import clear_table_sources

    from dax_parser.ir_mapper import ast_to_ir
    from dax_parser.parser import parse_expression

    tables = list(getattr(model, "tables", []) or [])

    # Step 1: compile calculated table expressions (may depend on other calc tables).
    calc_tables = [t for t in tables if bool(getattr(t, "is_calculated", False)) and getattr(t, "expression", None)]

    compiled_tables: dict[str, str] = {}
    clear_table_sources()

    pending = list(calc_tables)
    for _pass in range(0, len(pending) + 2):
        if not pending:
            break
        progressed = False
        still: list[Any] = []
        for t in pending:
            name = str(getattr(t, "name", "")).strip()
            dax_text = getattr(t, "expression", None)
            if not name or not isinstance(dax_text, str) or not dax_text.strip():
                continue
            try:
                ir = ast_to_ir(parse_expression(dax_text))
                sql = dax_compiler.compile_table_expr(ir, dax_compiler.Context())
                # compile_table_expr may return a bare TableRef; normalize to a subquery.
                upper = sql.lstrip().upper()
                if not (sql.strip().startswith("(") or upper.startswith("SELECT") or upper.startswith("WITH")):
                    sql = f"SELECT * FROM {sql}"
                compiled_tables[name] = sql
                # Make it visible for subsequent passes (calc-table dependencies).
                dax_compiler.set_table_sources(dict(compiled_tables))
                progressed = True
            except Exception:
                still.append(t)
        if not progressed:
            # Give up; leave unresolved ones to runtime errors rather than failing engine init.
            break
        pending = still

    # Step 2: wrap tables that have calculated columns.
    out: dict[str, str] = dict(compiled_tables)
    calc_col_sql: dict[str, str] = {}
    for t in tables:
        table_name = str(getattr(t, "name", "")).strip()
        if not table_name:
            continue

        calc_cols = [c for c in (getattr(t, "columns", []) or []) if bool(getattr(c, "is_calculated", False)) and getattr(c, "expression", None)]
        if not calc_cols:
            continue

        # Base raw source for this table (physical name or calc-table SQL).
        base_raw = out.get(table_name, quote_ident(table_name))
        from_src = as_from_source(base_raw, "t")
        if from_src == base_raw.strip():
            from_src = f"{base_raw.strip()} AS t"

        added: list[str] = []
        for c in calc_cols:
            col_name = str(getattr(c, "name", "")).strip()
            dax_text = getattr(c, "expression", None)
            if not col_name or not isinstance(dax_text, str) or not dax_text.strip():
                continue

            try:
                ir = ast_to_ir(parse_expression(dax_text))
            except Exception:
                continue  # Skip unparseable calc column expressions
            if not isinstance(ir, dax_compiler.ScalarExpr):
                continue  # Skip non-scalar calc columns (e.g., table expressions)
            try:
                expr_sql = dax_compiler.compile_expr(ir, dax_compiler.Context())
            except Exception:
                continue  # Skip calc columns that fail to compile
            # Persist the raw compiled expression (unaliased) so ColumnRef(Table, CalcCol)
            # can expand to the expression directly.
            calc_col_sql[f"{table_name}.{col_name}".upper()] = expr_sql
            # Only rewrite the CURRENT table's qualifier to "t"; leave other tables
            # untouched so we can detect cross-table references.
            rewritten = rewrite_table_qualifier_to_alias(expr_sql, table_name, "t")
            # If the expression still references OTHER tables (e.g., a measure that
            # aggregates from Sales), it can't be inlined in the table_source wrapper.
            if _has_cross_table_refs(rewritten, "t"):
                logger.debug(
                    "Skipping calc col %s[%s] from table_source (cross-table refs)",
                    table_name, col_name,
                )
                continue
            added.append(f"{rewritten} AS {quote_alias(col_name)}")

        if not added:
            continue

        out[table_name] = f"SELECT t.*, {', '.join(added)} FROM {from_src}"

    return out, calc_col_sql

def _resolve_project_path(project: Optional[str]) -> str:
    path = (project or os.environ.get("DAX_PROJECT_PATH") or "").strip()
    if not path:
        raise ValueError("Project path is required via ?project=... or DAX_PROJECT_PATH")
    p = Path(path)
    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(str(p))
    # SEC-14: server-mode path restriction
    from dax_ui.server._runtime_helpers import _validate_server_mode_path
    _validate_server_mode_path(p.resolve(), "Project path")
    return str(p)

def _resolve_duckdb_path(duckdb_path: Optional[str]) -> Optional[str]:
    p = (duckdb_path or os.environ.get("DAX_DUCKDB_PATH") or "").strip()
    if not p:
        return None
    return p

def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    # Element-wise merge for lists of dicts (e.g. Plotly figure "data" arrays).
    # This preserves base-list items' properties that the patch does not override,
    # rather than replacing the whole list wholesale.
    if (
        isinstance(base, list)
        and isinstance(patch, list)
        and base
        and patch
        and isinstance(base[0], dict)
        and isinstance(patch[0], dict)
    ):
        out_list = list(base)
        for i, patch_item in enumerate(patch):
            if i < len(out_list) and isinstance(out_list[i], dict):
                out_list[i] = _deep_merge(out_list[i], patch_item)
            else:
                out_list.append(patch_item)
        return out_list
    return patch

