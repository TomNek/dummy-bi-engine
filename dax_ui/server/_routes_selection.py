"""Selection State Engine — computes possible/excluded values for slicer fields.

Qlik-inspired 3-state selection model:
- **selected**: values explicitly chosen by the user
- **possible**: values that have associated data under current filters
- **excluded**: values that have NO associated data under current filters

Architecture:
- For each slicer field, run `SELECT DISTINCT col FROM ... WHERE <current_filters_excluding_self>`
  to get the "all possible" set.  The "excluded" set is the complement: all values minus possible.
- Uses relationship-aware FROM planning so cross-table filters propagate.
- Batches all queries into a single DuckDB connection for performance.
- Incremental mode: `affected_fields` parameter limits recomputation to impacted fields only.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, Optional

from fastapi import Body, Request

import dax_compiler
from dax_project.save import load_slicer_defs
from dax_project.loader import load_project
from dax_ui.server._engine import (
    _ENGINE_LOCK,
    _ensure_mapping_loaded,
    get_prepared_engine,
)
from dax_ui.server._runtime_helpers import (
    _resolve_project_path_runtime,
    _slicer_error_code_from_exc,
)
from dax_ui.server._security import (
    _RuntimeSecurityState,
    _build_runtime_security_state,
    _compile_rls_security_predicates,
)
from dax_ui.server._filters import (
    _parse_scoped_filters_payload,
)
from dax_ui.server._routes_core import (
    _materialize_slicer_defs_to_filter_payload_items,
    _normalize_slicer_defs_payload,
)
from dax_ui.server._duckdb import (
    _connect_duckdb_for_project,
)
from dax_ui.server import (
    _json_safe_with_path,
)

logger = logging.getLogger(__name__)


def _ok(data: Any) -> dict:
    return {"ok": True, **data}


def _err(status: int, msg: str, error_code: str = "E_SELECTION_STATE") -> dict:
    from fastapi.responses import JSONResponse
    del msg
    return JSONResponse(
        status_code=status,
        content={
            "ok": False,
            "error": error_code,
            "message": "Selection state could not be calculated.",
        },
    )


def register_selection_routes(app: Any) -> None:
    """Register selection state engine endpoints."""

    @app.post("/runtime/selection/state")
    def runtime_selection_state(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Compute possible/excluded value sets for all active slicer fields.

        Payload:
          {
            filters?: [...],             # current runtime filters
            slicer_defs?: {...},          # optional override (unsaved state)
            page_id?: string,            # current page (for page-scoped slicers)
            affected_fields?: [           # incremental: only recompute these fields
              { table: string, column: string }
            ],
            include_counts?: bool,       # include per-value row counts
          }

        Response:
          {
            ok: true,
            fields: {
              "Table.Column": {
                all_values: [...],        # all distinct values (unfiltered)
                possible: [...],          # values with data under current filters
                excluded: [...],          # values without data under current filters
                counts?: { value: count } # per-value row counts (if include_counts)
              }
            },
            elapsed_ms: number
          }
        """
        t0 = time.monotonic()

        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
        except Exception as exc:
            return _err(400, str(exc))

        page_id = safe.get("page_id")
        if page_id is not None:
            if not isinstance(page_id, str) or not page_id.strip():
                return _err(400, "page_id must be a non-empty string if provided")
            page_id = page_id.strip()

        include_counts = bool(safe.get("include_counts", False))

        # Parse affected_fields for incremental mode
        affected_fields_raw = safe.get("affected_fields")
        affected_fields: set[str] | None = None
        if affected_fields_raw is not None:
            if not isinstance(affected_fields_raw, list):
                return _err(400, "affected_fields must be a list")
            affected_fields = set()
            for af in affected_fields_raw:
                if not isinstance(af, Mapping):
                    return _err(400, "affected_fields items must be {table, column} objects")
                t_name = str(af.get("table") or "").strip()
                c_name = str(af.get("column") or "").strip()
                if not t_name or not c_name:
                    return _err(400, "affected_fields items must have non-empty table and column")
                affected_fields.add(f"{t_name}.{c_name}")

        try:
            model, pages, _visuals = load_project(project_path)
        except Exception as exc:
            return _err(400, str(exc))

        # Security scope
        try:
            sec_state = _build_runtime_security_state(
                project_path=project_path, model=model, request=request, payload=safe,
            )
            model_scoped = sec_state.model_scoped
        except Exception as exc:
            return _err(400, str(exc))

        # Resolve slicer defs
        try:
            defs_obj = _normalize_slicer_defs_payload(
                safe.get("slicer_defs") if "slicer_defs" in safe else None
            )
            if not (defs_obj.get("defs") or []):
                defs_obj = load_slicer_defs(project_path)
            # Note: full validation happens in /slicers/values; here we just
            # need well-formed defs with table+column — bad refs will fail
            # gracefully in _compute_field_state with a per-field error.
        except Exception as exc:
            code = _slicer_error_code_from_exc(exc, default="E_SELECTION_STATE")
            return _err(400, str(exc), error_code=code)

        # Collect slicer fields to compute
        slicer_fields: list[dict[str, str]] = []
        for d in defs_obj.get("defs") or []:
            if not isinstance(d, Mapping):
                continue
            col_raw = d.get("column")
            if not isinstance(col_raw, Mapping):
                continue
            table = str(col_raw.get("table") or "").strip()
            column = str(col_raw.get("column") or "").strip()
            if not table or not column:
                continue
            field_key = f"{table}.{column}"
            # Skip duplicates
            if any(sf["key"] == field_key for sf in slicer_fields):
                continue
            # Incremental: skip if not in affected_fields
            if affected_fields is not None and field_key not in affected_fields:
                continue
            # Skip virtual tables (field params, calc groups, what-if)
            virtual_prefixes = ("FieldParams_", "CalcGroup_", "WhatIf_")
            if any(table.startswith(p) or table.upper().startswith(p.upper()) for p in virtual_prefixes):
                continue

            slicer_fields.append({
                "key": field_key,
                "table": table,
                "column": column,
                "def_id": str(d.get("id") or ""),
            })

        if not slicer_fields:
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            return _ok({"fields": {}, "elapsed_ms": elapsed})

        # Parse runtime filters
        try:
            runtime_filters = _parse_scoped_filters_payload(
                safe.get("filters"),
                project_path=project_path,
                model=model_scoped,
            )
        except Exception as exc:
            return _err(400, str(exc))

        # Build queries for each slicer field
        fields_result: dict[str, Any] = {}
        con = None

        try:
            con = _connect_duckdb_for_project(
                project_path=project_path, duckdb_path=duckdb_path, model=model,
            )

            for sf in slicer_fields:
                table = sf["table"]
                column = sf["column"]
                def_id = sf["def_id"]
                field_key = sf["key"]

                try:
                    field_data = _compute_field_state(
                        con=con,
                        model=model,
                        model_scoped=model_scoped,
                        sec_state=sec_state,
                        project_path=project_path,
                        duckdb_path=duckdb_path,
                        table=table,
                        column=column,
                        def_id=def_id,
                        defs_obj=defs_obj,
                        runtime_filters=runtime_filters,
                        page_id=page_id,
                        include_counts=include_counts,
                    )
                    fields_result[field_key] = field_data
                except Exception as exc:
                    logger.warning("Selection state failed for %s: %s", field_key, exc)
                    # Safe fallback: all values are possible
                    fields_result[field_key] = {
                        "all_values": [],
                        "possible": [],
                        "excluded": [],
                        "error": "Selection query failed",
                    }

        except Exception as exc:
            return _err(400, str(exc), error_code="E_SELECTION_STATE")
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        elapsed = round((time.monotonic() - t0) * 1000, 1)
        return _ok({"fields": fields_result, "elapsed_ms": elapsed})


def _compute_field_state(
    *,
    con: Any,
    model: Any,
    model_scoped: Any,
    sec_state: Any,
    project_path: str,
    duckdb_path: str | None,
    table: str,
    column: str,
    def_id: str,
    defs_obj: dict,
    runtime_filters: Any,
    page_id: str | None,
    include_counts: bool,
) -> dict[str, Any]:
    """Compute all_values, possible, and excluded for a single slicer field."""

    from dax_engine.ir import ColumnRef
    from dax_engine.relationships import _build_rowset_plan_ctx
    from dax_engine.compiler import compile_expr
    from dax_engine.filters_ir import apply_scoped_filters_to_context

    with _ENGINE_LOCK:
        _ensure_mapping_loaded()
        get_prepared_engine(project_path, model)

        col_ir = ColumnRef(table=table, column=column)

        # --- Query 1: All values (unfiltered, RLS only) ---
        ctx_all = dax_compiler.Context()
        sec = _compile_rls_security_predicates(role=sec_state.role, base_ctx=ctx_all)
        if sec:
            ctx_all = ctx_all.apply_security_predicates(sec)

        col_sql = compile_expr(col_ir, ctx_all)
        required_all: set[str] = {table}
        for k in ctx_all.all_filter_keys():
            if "." in k:
                required_all.add(k.split(".", 1)[0])

        from_all, connected_all, _ = _build_rowset_plan_ctx(
            table, sorted(required_all), ctx_all,
        )
        where_all = ctx_all.where_clause_for_tables(sorted(connected_all))
        sql_all = (
            f"SELECT DISTINCT {col_sql} AS v "
            f"FROM {from_all} "
            f"{where_all} "
            f"ORDER BY (v IS NULL) ASC, v "
            f"LIMIT 2000"
        )

        # --- Query 2: Possible values (with filters, excluding self-slicer) ---
        ctx_filtered = dax_compiler.Context()
        sec2 = _compile_rls_security_predicates(role=sec_state.role, base_ctx=ctx_filtered)
        if sec2:
            ctx_filtered = ctx_filtered.apply_security_predicates(sec2)

        # Materialize other slicer filters (excluding self)
        try:
            slicer_filter_payload = _materialize_slicer_defs_to_filter_payload_items(
                defs_obj,
                exclude_def_id=def_id,
                project_path=project_path,
                model=model,
                sec_state=sec_state,
                duckdb_path=duckdb_path,
                runtime_filters=list(runtime_filters),
                page_id=page_id,
                visual_id=None,
            )
            slicer_filters = _parse_scoped_filters_payload(
                slicer_filter_payload,
                project_path=project_path,
                model=model_scoped,
            )
        except Exception:
            slicer_filters = []

        # Exclude runtime filters that target the same field (self-slicer exclusion)
        # This implements the Qlik-style "exclude self" semantics: a slicer's own
        # filter should not restrict its own possible values.
        filtered_runtime = []
        for rf in runtime_filters:
            cond = getattr(rf, "condition", None)
            if cond is None:
                filtered_runtime.append(rf)
                continue
            col = getattr(cond, "column", None)
            if col is None:
                filtered_runtime.append(rf)
                continue
            rf_table = getattr(col, "table", None)
            rf_column = getattr(col, "column", None)
            # Skip any slicer-sourced filter targeting the same table.column
            rf_source = getattr(rf, "source", None)
            if rf_source in ("slicer", "interaction") and rf_table == table and rf_column == column:
                continue
            filtered_runtime.append(rf)

        ctx_filtered, _ = apply_scoped_filters_to_context(
            ctx_filtered,
            filtered_runtime + list(slicer_filters),
            page_id=page_id,
            visual_id=None,
        )

        col_sql_f = compile_expr(col_ir, ctx_filtered)
        required_filtered: set[str] = {table}
        for k in ctx_filtered.all_filter_keys():
            if "." in k:
                required_filtered.add(k.split(".", 1)[0])

        from_filtered, connected_filtered, _ = _build_rowset_plan_ctx(
            table, sorted(required_filtered), ctx_filtered,
        )
        where_filtered = ctx_filtered.where_clause_for_tables(sorted(connected_filtered))

        if include_counts:
            sql_filtered = (
                f"SELECT {col_sql_f} AS v, COUNT(*) AS cnt "
                f"FROM {from_filtered} "
                f"{where_filtered} "
                f"GROUP BY v "
                f"ORDER BY (v IS NULL) ASC, v "
                f"LIMIT 2000"
            )
        else:
            sql_filtered = (
                f"SELECT DISTINCT {col_sql_f} AS v "
                f"FROM {from_filtered} "
                f"{where_filtered} "
                f"ORDER BY (v IS NULL) ASC, v "
                f"LIMIT 2000"
            )

    # Execute outside the lock
    rows_all = con.execute(sql_all).fetchall()
    all_values = [r[0] for r in rows_all]

    rows_filtered = con.execute(sql_filtered).fetchall()
    if include_counts:
        possible = [r[0] for r in rows_filtered]
        counts = {str(r[0]): r[1] for r in rows_filtered}
    else:
        possible = [r[0] for r in rows_filtered]
        counts = None

    # Compute excluded = all_values - possible
    possible_set = set(str(v) for v in possible)
    excluded = [v for v in all_values if str(v) not in possible_set]

    result: dict[str, Any] = {
        "all_values": all_values,
        "possible": possible,
        "excluded": excluded,
    }
    if counts is not None:
        result["counts"] = counts

    return result
