"""Community helper module — extracted from dax_ui.server.__init__."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import dax_compiler
from dax_engine import ir as _ir
from starlette.requests import Request

from dax_project.introspection import list_columns, list_measures, list_tables
from dax_project.security import apply_ols, get_role, resolve_role_name

from dax_ui.server._engine import _ENGINE_LOCK, _ensure_mapping_loaded, get_prepared_engine
from dax_ui.server._ir_walkers import _is_booleanish_security_filter

logger = logging.getLogger(__name__)


def _security_roles_to_json(model: Any) -> list[dict[str, Any]]:
    roles = getattr(model, "security_roles", {}) or {}
    out: list[dict[str, Any]] = []
    for _k, role in roles.items():
        name = str(getattr(role, "name", "") or "").strip()
        if not name:
            continue

        rls_out: list[dict[str, str]] = []
        for rr in list(getattr(role, "rls", []) or []):
            t = str(getattr(rr, "table", "") or "").strip()
            f = getattr(rr, "filter", None)
            if t and isinstance(f, str) and f.strip():
                rls_out.append({"table": t, "filter": f})

        ols = getattr(role, "ols", None)
        ols_tables = list(getattr(ols, "tables", []) or []) if ols is not None else []
        ols_measures = list(getattr(ols, "measures", []) or []) if ols is not None else []
        ols_cols = dict(getattr(ols, "columns", {}) or {}) if ols is not None else {}

        out.append(
            {
                "name": name,
                "rls": rls_out,
                "ols": {
                    "tables": [str(x) for x in ols_tables if str(x).strip()],
                    "measures": [str(x) for x in ols_measures if str(x).strip()],
                    "columns": {
                        str(t): [str(c) for c in (cols or []) if str(c).strip()]
                        for t, cols in (ols_cols or {}).items()
                        if isinstance(t, str) and t.strip()
                    },
                },
            }
        )
    return out

def _collect_param_refs(expr: Any) -> list[Any]:
    from dax_engine.ir import (
        DaxBinaryOp as _DaxBinaryOp,
        DaxFunction as _DaxFunction,
        DaxIteratorFunction as _DaxIteratorFunction,
        DaxWindowFunction as _DaxWindowFunction,
        ParamRef as _ParamRef,
        SetLiteral as _SetLiteral,
    )

    out: list[Any] = []

    def walk(e: Any) -> None:
        if isinstance(e, _ParamRef):
            out.append(e)
            return
        if isinstance(e, _SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, _DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return
        if isinstance(e, _DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, _DaxIteratorFunction):
            walk(e.table)
            walk(e.expr)
            return
        if isinstance(e, _DaxWindowFunction):
            walk(e.table)
            walk(e.expr)
            if e.order_by is not None:
                for c in e.order_by:
                    walk(c)
            return

    walk(expr)
    return out

def _collect_column_refs(expr: Any) -> list[Any]:
    from dax_engine.ir import (
        ColumnRef as _ColumnRef,
        DaxBinaryOp as _DaxBinaryOp,
        DaxFunction as _DaxFunction,
        DaxIteratorFunction as _DaxIteratorFunction,
        DaxWindowFunction as _DaxWindowFunction,
        SetLiteral as _SetLiteral,
    )

    out: list[Any] = []

    def walk(e: Any) -> None:
        if isinstance(e, _ColumnRef):
            out.append(e)
            return
        if isinstance(e, _SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, _DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return
        if isinstance(e, _DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, _DaxIteratorFunction):
            walk(e.table)
            walk(e.expr)
            return
        if isinstance(e, _DaxWindowFunction):
            walk(e.table)
            walk(e.expr)
            if e.order_by is not None:
                for c in e.order_by:
                    walk(c)
            return

    walk(expr)
    return out

def _collect_measure_refs(expr: Any) -> list[Any]:
    from dax_engine.ir import (
        DaxBinaryOp as _DaxBinaryOp,
        DaxFunction as _DaxFunction,
        DaxIteratorFunction as _DaxIteratorFunction,
        DaxWindowFunction as _DaxWindowFunction,
        MeasureRef as _MeasureRef,
        SetLiteral as _SetLiteral,
    )

    out: list[Any] = []

    def walk(e: Any) -> None:
        if isinstance(e, _MeasureRef):
            out.append(e)
            return
        if isinstance(e, _SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, _DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return
        if isinstance(e, _DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, _DaxIteratorFunction):
            walk(e.table)
            walk(e.expr)
            return
        if isinstance(e, _DaxWindowFunction):
            walk(e.table)
            walk(e.expr)
            if e.order_by is not None:
                for c in e.order_by:
                    walk(c)
            return

    walk(expr)
    return out

def _validate_single_role_payload(
    *,
    project_path: str,
    model: Any,
    role_payload: Any,
) -> list[str]:
    """Validate a single role payload. Returns a list of user-readable errors."""

    errors: list[str] = []
    if not isinstance(role_payload, Mapping):
        return ["role must be an object"]

    name = role_payload.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("role.name must be a non-empty string")
        name_norm = "(invalid)"
    else:
        name_norm = name.strip()

    table_lookup = {str(t).upper() for t in list_tables(model)}
    column_lookup: set[tuple[str, str]] = set()
    for t in list_tables(model):
        for c in list_columns(model, t):
            column_lookup.add((str(t).upper(), str(c).upper()))
    measure_lookup = {str(m).upper() for m in list_measures(model)}

    rls_raw = role_payload.get("rls")
    if rls_raw is None:
        rls_raw = []
    if not isinstance(rls_raw, list):
        errors.append("role.rls must be a list")
        rls_raw = []

    from dax_parser.ir_mapper import ast_to_ir
    from dax_parser.parser import parse_expression

    for i, rr in enumerate(rls_raw):
        if not isinstance(rr, Mapping):
            errors.append(f"role.rls[{i}] must be an object")
            continue
        tname = rr.get("table")
        dax_text = rr.get("filter")
        if not isinstance(tname, str) or not tname.strip():
            errors.append(f"role.rls[{i}].table must be a non-empty string")
            continue
        if not isinstance(dax_text, str) or not dax_text.strip():
            errors.append(f"role.rls[{i}].filter must be a non-empty string")
            continue

        t_norm = tname.strip()
        if t_norm.upper() not in table_lookup:
            errors.append(f"role {name_norm!r}: unknown table in RLS: {t_norm!r}")
            continue

        try:
            ir = ast_to_ir(parse_expression(dax_text))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"role {name_norm!r}: RLS filter parse error for table {t_norm!r}: {exc}")
            continue

        if not isinstance(ir, dax_compiler.ScalarExpr):
            errors.append(f"role {name_norm!r}: RLS filter must be a scalar expression")
            continue

        if not _is_booleanish_security_filter(ir):
            errors.append(f"role {name_norm!r}: RLS filter must be boolean-like")
            continue

        # RLS v1 contract: only allow ColumnRefs to the same table; disallow MeasureRef and ParamRef.
        for mr in _collect_measure_refs(ir):
            errors.append(f"role {name_norm!r}: RLS filter must not reference measures: {mr.name!r}")
        for pr in _collect_param_refs(ir):
            errors.append(f"role {name_norm!r}: RLS filter must not reference field parameters: {pr.name!r}")
        for cr in _collect_column_refs(ir):
            if cr.table.upper() != t_norm.upper():
                errors.append(
                    f"role {name_norm!r}: RLS filter for table {t_norm!r} cannot reference other table: {cr.table!r}"
                )
            elif (cr.table.upper(), cr.column.upper()) not in column_lookup:
                errors.append(
                    f"role {name_norm!r}: unknown column in RLS filter: {cr.table!r}[{cr.column!r}]"
                )

        # Compilation check: must compile to SQL under engine state.
        try:
            with _ENGINE_LOCK:
                _ensure_mapping_loaded()
                get_prepared_engine(project_path, model)
                ctx = dax_compiler.Context()
                _ = dax_compiler.compile_expr(ir, ctx)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"role {name_norm!r}: RLS filter failed to compile: {exc}")

    ols_raw = role_payload.get("ols")
    if ols_raw is None:
        ols_raw = {}
    if not isinstance(ols_raw, Mapping):
        errors.append("role.ols must be an object")
        ols_raw = {}

    ols_tables_raw = ols_raw.get("tables")
    ols_measures_raw = ols_raw.get("measures")
    ols_columns_raw = ols_raw.get("columns")

    if ols_tables_raw is None:
        ols_tables_raw = []
    if ols_measures_raw is None:
        ols_measures_raw = []
    if ols_columns_raw is None:
        ols_columns_raw = {}

    if not isinstance(ols_tables_raw, list) or not all(isinstance(x, str) for x in ols_tables_raw):
        errors.append("role.ols.tables must be a list of strings")
        ols_tables_raw = []
    if not isinstance(ols_measures_raw, list) or not all(isinstance(x, str) for x in ols_measures_raw):
        errors.append("role.ols.measures must be a list of strings")
        ols_measures_raw = []
    if not isinstance(ols_columns_raw, Mapping):
        errors.append("role.ols.columns must be an object")
        ols_columns_raw = {}

    ols_tables = [str(x).strip() for x in ols_tables_raw if str(x).strip()]
    ols_measures = [str(x).strip() for x in ols_measures_raw if str(x).strip()]

    ols_columns: dict[str, list[str]] = {}
    for t, cols in ols_columns_raw.items():
        if not isinstance(t, str) or not t.strip():
            errors.append("role.ols.columns keys must be non-empty strings")
            continue
        if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
            errors.append(f"role.ols.columns[{t!r}] must be a list of strings")
            continue
        ols_columns[t.strip()] = [str(c).strip() for c in cols if str(c).strip()]

    for t in ols_tables:
        if t.upper() not in table_lookup:
            errors.append(f"role {name_norm!r}: unknown table in OLS.tables: {t!r}")
    for m in ols_measures:
        if m.upper() not in measure_lookup:
            errors.append(f"role {name_norm!r}: unknown measure in OLS.measures: {m!r}")
    for t, cols in ols_columns.items():
        if t.upper() not in table_lookup:
            errors.append(f"role {name_norm!r}: unknown table in OLS.columns: {t!r}")
            continue
        for c in cols:
            if (t.upper(), c.upper()) not in column_lookup:
                errors.append(f"role {name_norm!r}: unknown column in OLS.columns: {t!r}[{c!r}]")

    return errors

def _role_from_request(request: Request, payload: Any) -> Optional[str]:
    # Body has priority over header.
    if isinstance(payload, Mapping):
        raw = payload.get("role")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()

    try:
        hdr = request.headers.get("X-Role")
    except Exception:
        hdr = None
    if isinstance(hdr, str) and hdr.strip():
        return hdr.strip()
    return None

def _resolve_security_for_request(*, model: Any, request: Request, payload: Any) -> tuple[Optional[str], Any]:
    """Return (active_role_name, role_obj|None) or raise ValueError for invalid role."""

    requested = _role_from_request(request, payload)
    try:
        role_name = resolve_role_name(model, requested)
        role = get_role(model, role_name)
        return role_name, role
    except KeyError as exc:
        raise ValueError(str(exc)) from exc

def _compile_rls_security_predicates(*, role: Any, base_ctx: dax_compiler.Context) -> dict[str, str]:
    """Compile role RLS rules to non-removable Context security predicates.

    Keys are stable and table-prefixed so they participate in WHERE planning.
    """

    if role is None:
        return {}

    rules = list(getattr(role, "rls", []) or [])
    if not rules:
        return {}

    from dax_parser.ir_mapper import ast_to_ir
    from dax_parser.parser import parse_expression

    out: dict[str, str] = {}
    for rr in rules:
        table = str(getattr(rr, "table", "") or "").strip()
        dax_text = getattr(rr, "filter", None)
        if not table or not isinstance(dax_text, str) or not dax_text.strip():
            continue

        try:
            ir = ast_to_ir(parse_expression(dax_text))
            if not isinstance(ir, dax_compiler.ScalarExpr):
                raise ValueError(f"RLS filter must be scalar for table {table!r}")
            pred_sql = dax_compiler.compile_expr(ir, base_ctx)
        except Exception as exc:
            raise ValueError(
                f"Failed to compile RLS filter for table {table!r}: {exc}"
            ) from exc
        key = f"{table}.__RLS__"
        if key in out and out[key]:
            out[key] = f"({out[key]}) AND ({pred_sql})"
        else:
            out[key] = pred_sql

    return out

def _validate_columnref_in_model(model: Any, table: str, column: str) -> None:
    tables = list_tables(model)
    if str(table).upper() not in {t.upper() for t in tables}:
        raise ValueError(f"Unknown table: {table!r}")
    cols = list_columns(model, table)
    if str(column).upper() not in {c.upper() for c in cols}:
        raise ValueError(f"Unknown column: {table}[{column}]")

def _validate_measureref_in_model(model: Any, name: str) -> None:
    names = list_measures(model)
    if str(name).upper() not in {m.upper() for m in names}:
        raise ValueError(f"Unknown measure: {name!r}")

def _resolve_role_and_scope_model(
    *,
    model: Any,
    request: Request,
    payload: Any,
) -> tuple[Optional[str], Any, Any]:
    """Resolve active role and apply OLS to return a scoped model view."""

    role_name, role = _resolve_security_for_request(model=model, request=request, payload=payload)
    model_scoped = apply_ols(model, role)
    return role_name, role, model_scoped

@dataclass(frozen=True)
class _RuntimeSecurityState:
    role_name: Optional[str]
    role: Any
    model_scoped: Any
    ctx: dax_compiler.Context
    sec_predicates: dict[str, str]

def _build_runtime_security_state(
    *,
    project_path: str,
    model: Any,
    request: Request,
    payload: Any,
) -> _RuntimeSecurityState:
    """Resolve role + apply OLS + build a Context with non-removable RLS predicates."""

    role_name, role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload=payload)

    with _ENGINE_LOCK:
        _ensure_mapping_loaded()
        get_prepared_engine(project_path, model)
        ctx = dax_compiler.Context()
        sec = _compile_rls_security_predicates(role=role, base_ctx=ctx)
        if sec:
            ctx = ctx.apply_security_predicates(sec)

    return _RuntimeSecurityState(
        role_name=role_name,
        role=role,
        model_scoped=model_scoped,
        ctx=ctx,
        sec_predicates=sec,
    )

def _case_insensitive_dict_get(src: Mapping[str, Any], key: str) -> Any:
    for k, v in src.items():
        if str(k).upper() == str(key).upper():
            return v
    return None

def _validate_ir_objects_against_model_scoped(ir: Any, model_scoped: Any) -> None:
    """Enforce OLS by validating all referenced objects against the role-scoped model."""

    from dax_engine.ir import (
        ColumnRef as _ColumnRef,
        DaxBinaryOp as _DaxBinaryOp,
        DaxFunction as _DaxFunction,
        DaxIteratorFunction as _DaxIteratorFunction,
        DaxWindowFunction as _DaxWindowFunction,
        MeasureRef as _MeasureRef,
        ParamRef as _ParamRef,
        SetLiteral as _SetLiteral,
        TableRef as _TableRef,
    )

    def _validate_table_in_model_scoped(table: str) -> None:
        if not any(
            str(getattr(t, "name", "")).upper() == str(table).upper() for t in getattr(model_scoped, "tables", []) or []
        ):
            raise ValueError(f"Unknown or hidden table: {table!r}")

    def walk(e: Any) -> None:
        if isinstance(e, _TableRef):
            _validate_table_in_model_scoped(e.name)
            return
        if isinstance(e, _ColumnRef):
            _validate_columnref_in_model(model_scoped, e.table, e.column)
            return
        if isinstance(e, _MeasureRef):
            _validate_measureref_in_model(model_scoped, e.name)
            return
        if isinstance(e, _ParamRef):
            raise ValueError(f"Unresolved field parameter not supported here: {e.name!r}")
        if isinstance(e, _SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, _DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return
        if isinstance(e, _DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, _DaxIteratorFunction):
            walk(e.table)
            walk(e.expr)
            return
        if isinstance(e, _DaxWindowFunction):
            walk(e.table)
            walk(e.expr)
            if e.order_by is not None:
                for c in e.order_by:
                    walk(c)
            return

    walk(ir)

