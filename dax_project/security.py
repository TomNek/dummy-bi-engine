from __future__ import annotations

from typing import Optional

from dax_engine.ir import ColumnRef, Expr, MeasureRef

from .model import (
    Column,
    FieldParameter,
    FieldParameterItem,
    Hierarchy,
    HierarchyLevel,
    Relationship,
    SecurityRole,
    SemanticModel,
    Table,
)


def resolve_role_name(model: SemanticModel, requested: Optional[str]) -> Optional[str]:
    """Resolve the active role name.

    Resolution order:
    - requested (if provided)
    - model.default_role (if set)
    - None (no security enforcement)
    """

    req = (requested or "").strip()
    if req:
        # Case-insensitive match against configured roles.
        for name in (model.security_roles or {}).keys():
            if name.upper() == req.upper():
                return name
        raise KeyError(f"Unknown role: {requested!r}")

    default = (model.default_role or "").strip()
    if default:
        for name in (model.security_roles or {}).keys():
            if name.upper() == default.upper():
                return name
        raise KeyError(f"Default role not found: {model.default_role!r}")

    return None


def get_role(model: SemanticModel, role_name: Optional[str]) -> Optional[SecurityRole]:
    if role_name is None:
        return None
    for k, v in (model.security_roles or {}).items():
        if k.upper() == str(role_name).upper():
            return v
    raise KeyError(f"Unknown role: {role_name!r}")


def _expr_refs_hidden(
    expr: Expr,
    *,
    hidden_tables: set[str],
    hidden_measures: set[str],
    hidden_columns: dict[str, set[str]],
) -> bool:
    from dax_engine.ir import DaxBinaryOp, DaxFunction, DaxIteratorFunction, DaxWindowFunction, SetLiteral

    def walk(e: Expr) -> bool:
        if isinstance(e, ColumnRef):
            if e.table.upper() in hidden_tables:
                return True
            cols = hidden_columns.get(e.table.upper())
            if cols and e.column.upper() in cols:
                return True
            return False
        if isinstance(e, MeasureRef):
            return e.name.upper() in hidden_measures
        if isinstance(e, SetLiteral):
            return any(walk(v) for v in e.values)
        if isinstance(e, DaxBinaryOp):
            return walk(e.left) or walk(e.right)
        if isinstance(e, DaxFunction):
            return any(walk(a) for a in e.args)
        if isinstance(e, DaxIteratorFunction):
            return walk(e.table) or walk(e.expr)
        if isinstance(e, DaxWindowFunction):
            if walk(e.table) or walk(e.expr):
                return True
            if e.order_by is not None:
                return any(walk(c) for c in e.order_by)
            return False
        return False

    return walk(expr)


def apply_ols(model: SemanticModel, role: Optional[SecurityRole]) -> SemanticModel:
    """Return a role-scoped, OLS-filtered view of the model.

    This is used for UI metadata/autocomplete and for validating planner inputs
    so that hidden objects cannot be referenced.
    """

    if role is None:
        return model

    ols = role.ols

    hidden_tables = {t.upper() for t in (ols.tables or []) if str(t).strip()}
    hidden_measures = {m.upper() for m in (ols.measures or []) if str(m).strip()}

    hidden_columns: dict[str, set[str]] = {}
    for t, cols in (ols.columns or {}).items():
        t_key = str(t).strip().upper()
        if not t_key:
            continue
        hidden_columns[t_key] = {str(c).strip().upper() for c in (cols or []) if str(c).strip()}

    kept_tables: list[Table] = []
    for t in model.tables:
        if t.name.upper() in hidden_tables:
            continue
        cols: list[Column] = []
        t_hidden_cols = hidden_columns.get(t.name.upper(), set())
        for c in t.columns:
            if c.name.upper() in t_hidden_cols:
                continue
            cols.append(c)
        kept_tables.append(
            Table(
                name=t.name,
                columns=cols,
                source=t.source,
                expression=t.expression,
                is_calculated=t.is_calculated,
                description=t.description,
                folder=t.folder,
                table_type=t.table_type,
                storage_mode=t.storage_mode,
                power_query=t.power_query,
            )
        )

    kept_table_names = {t.name.upper() for t in kept_tables}

    kept_relationships: list[Relationship] = []
    for r in model.relationships:
        if r.from_table.upper() in kept_table_names and r.to_table.upper() in kept_table_names:
            kept_relationships.append(r)

    kept_measures = [m for m in model.measures if m.name.upper() not in hidden_measures]

    # Filter field parameter items that reference hidden objects.
    kept_fps: dict[str, FieldParameter] = {}
    for key, fp in (model.field_parameters or {}).items():
        new_items: list[FieldParameterItem] = []
        for item in fp.items:
            if _expr_refs_hidden(
                item.ref,
                hidden_tables=hidden_tables,
                hidden_measures=hidden_measures,
                hidden_columns=hidden_columns,
            ):
                continue
            new_items.append(item)
        if not new_items:
            continue

        default_item = getattr(fp, "default_item", None)

        # Ensure default is still valid after filtering.
        valid = {item.name.upper() for item in new_items}
        if isinstance(default_item, str) and default_item.strip() and default_item.strip().upper() not in valid:
            default_item = None

        if default_item is None:
            # Fall back deterministically.
            default_item = new_items[0].name

        kept_fps[key] = FieldParameter(
            name=fp.name,
            items=new_items,
            default_item=str(default_item) if isinstance(default_item, str) and default_item.strip() else None,
        )

    # Calculation groups are left intact (templates are string-based).

    # Filter hierarchies: drop if table is hidden, remove levels with hidden columns.
    kept_hierarchies: dict[str, Hierarchy] = {}
    for key, h in (model.hierarchies or {}).items():
        if h.table.upper() in hidden_tables:
            continue
        t_hidden_cols = hidden_columns.get(h.table.upper(), set())
        kept_levels = [lvl for lvl in h.levels if lvl.column.upper() not in t_hidden_cols]
        if len(kept_levels) < 2:
            continue  # A hierarchy with < 2 levels is meaningless
        kept_hierarchies[key] = Hierarchy(
            name=h.name,
            table=h.table,
            levels=kept_levels,
        )

    return SemanticModel(
        tables=kept_tables,
        relationships=kept_relationships,
        measures=kept_measures,
        field_parameters=kept_fps,
        calculation_groups=dict(model.calculation_groups or {}),
        what_if_parameters=dict(model.what_if_parameters or {}),
        security_roles=dict(model.security_roles or {}),
        default_role=model.default_role,
        hierarchies=kept_hierarchies,
    )
