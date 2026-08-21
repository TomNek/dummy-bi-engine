from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dax_engine.ir import ColumnRef, DaxBinaryOp, DaxFunction, Expr, Literal, MeasureRef, ParamRef, ScalarExpr, SetLiteral
from dax_engine.planner import SortSpec, VisualQuerySpec

from .errors import ProjectFormatError, ProjectValidationError
from .expr_json import parse_expr, parse_sort_list
from .model import (
    CalcItem,
    Column,
    CalculationGroup,
    CalculationItem,
    FieldParameter,
    FieldParameterItem,
    FieldParameterOption,
    Hierarchy,
    HierarchyLevel,
    MeasureDefinition,
    PageDefinition,
    Relationship,
    SecurityOls,
    SecurityRole,
    SecurityRlsRule,
    SemanticModel,
    Table,
    VisualDefinition,
    WhatIfParameter,
)


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(str(path))

    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "PyYAML is required to load project YAML files. Please install 'pyyaml'."
        ) from exc

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _as_list_root(data: Any, *, label: str) -> List[Any]:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        items = data.get(label)
        if items is None:
            return []
        if isinstance(items, list):
            return items
    raise ProjectFormatError(f"Expected {label} YAML root to be a list or a mapping containing '{label}': {label}")


def _load_tables(tables_dir: Path) -> List[Table]:
    if not tables_dir.exists() or not tables_dir.is_dir():
        raise ProjectFormatError(f"Missing model tables directory: {tables_dir}")

    tables: List[Table] = []
    for path in sorted(tables_dir.glob("*.yaml")):
        raw = _load_yaml(path)
        if raw is None:
            raw = {}
        if not isinstance(raw, Mapping):
            raise ProjectFormatError(f"Table file must be a mapping: {path}")

        default_name = path.stem
        name = raw.get("name", default_name)
        if not isinstance(name, str) or not name.strip():
            raise ProjectFormatError(f"Table.name must be a non-empty string: {path}")

        columns_raw = raw.get("columns")
        if columns_raw is None:
            columns_raw = []
        if not isinstance(columns_raw, list):
            raise ProjectFormatError(f"Table.columns must be a list: {path}")

        table_expr = raw.get("expression")
        if table_expr is not None and not isinstance(table_expr, str):
            raise ProjectFormatError(f"Table.expression must be a string if provided: {path}")

        table_desc = raw.get("description")
        if table_desc is not None and not isinstance(table_desc, str):
            raise ProjectFormatError(f"Table.description must be a string if provided: {path}")

        table_folder = raw.get("folder")
        if table_folder is not None and not isinstance(table_folder, str):
            raise ProjectFormatError(f"Table.folder must be a string if provided: {path}")

        is_calc_table_raw = raw.get("is_calculated")
        is_calc_table = bool(is_calc_table_raw) if is_calc_table_raw is not None else False
        if table_expr is not None and str(table_expr).strip():
            is_calc_table = True

        columns: List[Column] = []
        for i, c in enumerate(columns_raw):
            if not isinstance(c, Mapping):
                raise ProjectFormatError(f"{path}: columns[{i}] must be a mapping")
            col_name = c.get("name")
            col_type = c.get("type")
            if not isinstance(col_name, str) or not col_name.strip():
                raise ProjectFormatError(f"{path}: columns[{i}].name must be a non-empty string")
            if not isinstance(col_type, str) or not col_type.strip():
                raise ProjectFormatError(f"{path}: columns[{i}].type must be a non-empty string")
            source = c.get("source")
            if source is not None and not isinstance(source, Mapping):
                raise ProjectFormatError(f"{path}: columns[{i}].source must be a mapping if provided")

            col_expr = c.get("expression")
            if col_expr is not None and not isinstance(col_expr, str):
                raise ProjectFormatError(f"{path}: columns[{i}].expression must be a string if provided")

            col_desc = c.get("description")
            if col_desc is not None and not isinstance(col_desc, str):
                raise ProjectFormatError(f"{path}: columns[{i}].description must be a string if provided")

            col_folder = c.get("folder")
            if col_folder is not None and not isinstance(col_folder, str):
                raise ProjectFormatError(f"{path}: columns[{i}].folder must be a string if provided")

            col_format = c.get("format")
            col_sort_by = c.get("sort_by_column")

            is_calc_col_raw = c.get("is_calculated")
            is_calc_col = bool(is_calc_col_raw) if is_calc_col_raw is not None else False
            if col_expr is not None and str(col_expr).strip():
                is_calc_col = True

            if is_calc_col and source is not None:
                raise ProjectFormatError(f"{path}: columns[{i}] cannot have both source and expression")

            columns.append(
                Column(
                    name=col_name.strip(),
                    type=col_type.strip(),
                    source=dict(source) if source else None,
                    expression=str(col_expr) if isinstance(col_expr, str) and col_expr.strip() else None,
                    is_calculated=is_calc_col,
                    description=str(col_desc) if isinstance(col_desc, str) and col_desc.strip() else None,
                    folder=str(col_folder) if isinstance(col_folder, str) and col_folder.strip() else None,
                    format=str(col_format) if isinstance(col_format, str) and col_format.strip() else None,
                    sort_by_column=str(col_sort_by).strip() if isinstance(col_sort_by, str) and col_sort_by.strip() else None,
                )
            )

        source = raw.get("source")
        if source is not None and not isinstance(source, Mapping):
            raise ProjectFormatError(f"{path}: source must be a mapping if provided")

        power_query = raw.get("power_query")
        if power_query is not None and not isinstance(power_query, Mapping):
            raise ProjectFormatError(f"{path}: power_query must be a mapping if provided")

        if is_calc_table and source is not None and not (isinstance(table_expr, str) and table_expr.strip()):
            is_calc_table = False

        if is_calc_table and source is not None:
            raise ProjectFormatError(f"{path}: table cannot have both source and expression")

        table_type_raw = raw.get("table_type")
        table_type_val = None
        if isinstance(table_type_raw, str) and table_type_raw.strip().lower() in ("fact", "dim", "bridge"):
            table_type_val = table_type_raw.strip().lower()

        # Phase 9: parse and validate storage_mode.
        storage_mode_raw = raw.get("storage_mode")
        storage_mode_val: Optional[str] = None
        if storage_mode_raw is not None:
            if is_calc_table:
                raise ProjectFormatError(
                    f"{path}: calculated tables cannot have a storage_mode"
                )
            from dax_engine.storage_modes import (
                parse_storage_mode,
                storage_mode_to_str,
                validate_storage_mode_source,
            )

            try:
                parsed_mode = parse_storage_mode(storage_mode_raw)
            except ValueError as exc:
                raise ProjectFormatError(f"{path}: {exc}") from exc

            if source is not None:
                try:
                    validate_storage_mode_source(
                        parsed_mode,
                        dict(source) if source else None,
                        table_name=name.strip(),
                    )
                except ValueError as exc:
                    raise ProjectFormatError(f"{path}: {exc}") from exc

            storage_mode_val = storage_mode_to_str(parsed_mode)

        tables.append(
            Table(
                name=name.strip(),
                columns=columns,
                source=dict(source) if source else None,
                expression=str(table_expr) if isinstance(table_expr, str) and table_expr.strip() else None,
                is_calculated=is_calc_table,
                description=str(table_desc) if isinstance(table_desc, str) and table_desc.strip() else None,
                folder=str(table_folder) if isinstance(table_folder, str) and table_folder.strip() else None,
                table_type=table_type_val,
                storage_mode=storage_mode_val,
                power_query=dict(power_query) if power_query else None,
            )
        )

    return tables


def _load_relationships(path: Path) -> List[Relationship]:
    if not path.exists():
        return []
    raw = _load_yaml(path)
    rels_raw = _as_list_root(raw, label="relationships")

    rels: List[Relationship] = []
    for i, r in enumerate(rels_raw):
        if not isinstance(r, Mapping):
            raise ProjectFormatError(f"relationships[{i}] must be a mapping")
        frm = r.get("from") or {}
        to = r.get("to") or {}
        if not isinstance(frm, Mapping) or not isinstance(to, Mapping):
            raise ProjectFormatError(f"relationships[{i}].from/to must be mappings")

        ft = frm.get("table")
        fc = frm.get("column")
        tt = to.get("table")
        tc = to.get("column")
        if not isinstance(ft, str) or not ft.strip():
            raise ProjectFormatError(f"relationships[{i}].from.table is required")
        if not isinstance(fc, str) or not fc.strip():
            raise ProjectFormatError(f"relationships[{i}].from.column is required")
        if not isinstance(tt, str) or not tt.strip():
            raise ProjectFormatError(f"relationships[{i}].to.table is required")
        if not isinstance(tc, str) or not tc.strip():
            raise ProjectFormatError(f"relationships[{i}].to.column is required")

        cross_filter_direction_raw = r.get("cross_filter_direction", "single")
        if not isinstance(cross_filter_direction_raw, str):
            raise ProjectFormatError(f"relationships[{i}].cross_filter_direction must be a string if provided")
        cross_filter_direction = cross_filter_direction_raw.strip().lower() or "single"
        if cross_filter_direction not in ("single", "both"):
            raise ProjectFormatError(
                f"relationships[{i}].cross_filter_direction must be 'single' or 'both'"
            )

        cardinality_raw = r.get("cardinality")
        cardinality: Optional[str]
        if cardinality_raw is None:
            cardinality = None
        elif isinstance(cardinality_raw, str):
            cardinality = cardinality_raw.strip() or None
        else:
            raise ProjectFormatError(f"relationships[{i}].cardinality must be a string if provided")

        rels.append(
            Relationship(
                from_table=ft.strip(),
                from_column=fc.strip(),
                to_table=tt.strip(),
                to_column=tc.strip(),
                active=bool(r.get("active", True)),
                rel_id=str(r.get("rel_id", "")),
                cross_filter_direction=cross_filter_direction,
                cardinality=cardinality,
            )
        )

    return rels


def _load_measures(path: Path) -> List[MeasureDefinition]:
    if not path.exists():
        return []
    raw = _load_yaml(path)
    measures_raw = _as_list_root(raw, label="measures")

    measures: List[MeasureDefinition] = []
    for i, m in enumerate(measures_raw):
        if not isinstance(m, Mapping):
            raise ProjectFormatError(f"measures[{i}] must be a mapping")
        name = m.get("name")
        dax_text = m.get("dax")
        if not isinstance(name, str) or not name.strip():
            raise ProjectFormatError(f"measures[{i}].name is required")
        if not isinstance(dax_text, str) or not dax_text.strip():
            raise ProjectFormatError(f"measures[{i}].dax is required")

        def _opt_str(key: str) -> Optional[str]:
            v = m.get(key)
            if v is None:
                return None
            if not isinstance(v, str):
                raise ProjectFormatError(f"measures[{i}].{key} must be a string if provided")
            return v

        measures.append(
            MeasureDefinition(
                name=name.strip(),
                dax=dax_text,
                description=_opt_str("description"),
                folder=_opt_str("folder"),
                format=_opt_str("format"),
            )
        )

    return measures


def _load_field_parameters(path: Path) -> Dict[str, FieldParameter]:
    """Load field parameters with Power BI parity.
    
    Supports both new schema (items with name/ref) and legacy schema (options with key/label/expr).
    Legacy fields kind/allow_multi/default_items are silently ignored for back-compat.
    """
    if not path.exists():
        return {}

    raw = _load_yaml(path)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ProjectFormatError(f"field_parameters.yaml must be a mapping: {path}")

    fps_raw = raw.get("field_parameters")
    if fps_raw is None:
        return {}
    if not isinstance(fps_raw, Mapping):
        raise ProjectFormatError(f"field_parameters.yaml: field_parameters must be a mapping")

    out: Dict[str, FieldParameter] = {}
    for name, spec in fps_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ProjectFormatError("field_parameters keys must be non-empty strings")
        if not isinstance(spec, Mapping):
            raise ProjectFormatError(f"field_parameters[{name!r}] must be a mapping")

        # Support both new schema (items) and legacy schema (options).
        items_raw = spec.get("items") or spec.get("options")
        if not isinstance(items_raw, list) or not items_raw:
            raise ProjectFormatError(f"field_parameters[{name!r}].items must be a non-empty list")

        items: List[FieldParameterItem] = []
        names_seen: set[str] = set()
        for i, o in enumerate(items_raw):
            if not isinstance(o, Mapping):
                raise ProjectFormatError(f"field_parameters[{name!r}].items[{i}] must be a mapping")
            
            # New schema: name + ref
            # Legacy schema: key + label + expr (use label as name, key for back-compat lookup)
            item_name = o.get("name") or o.get("label") or o.get("key")
            if not isinstance(item_name, str) or not item_name.strip():
                raise ProjectFormatError(f"field_parameters[{name!r}].items[{i}].name must be a non-empty string")
            
            ref_obj = o.get("ref") or o.get("expr")
            if not isinstance(ref_obj, Mapping):
                raise ProjectFormatError(f"field_parameters[{name!r}].items[{i}].ref must be an object")
            
            sort_raw = o.get("sort")
            if sort_raw is not None and not isinstance(sort_raw, int):
                raise ProjectFormatError(f"field_parameters[{name!r}].items[{i}].sort must be an int if provided")

            item_name_norm = item_name.strip()
            if item_name_norm.upper() in names_seen:
                raise ProjectFormatError(f"field_parameters[{name!r}] has duplicate item name: {item_name_norm!r}")
            names_seen.add(item_name_norm.upper())

            ref = parse_expr(ref_obj)
            if not isinstance(ref, (ColumnRef, MeasureRef)):
                raise ProjectFormatError(
                    f"field_parameters[{name!r}].items[{i}].ref must be ColumnRef or MeasureRef"
                )

            # Extract custom properties (any key not in standard fields)
            standard_keys = {"name", "label", "key", "ref", "expr", "sort", "sortColumn"}
            custom_props: Dict[str, str] = {}
            for k, v in o.items():
                if k not in standard_keys and isinstance(v, str):
                    custom_props[k] = v.strip() if v.strip() else ""

            items.append(
                FieldParameterItem(
                    name=item_name_norm,
                    ref=ref,
                    sort=int(sort_raw) if isinstance(sort_raw, int) else None,
                    custom_props=custom_props if custom_props else None,
                )
            )

        # Default item: accept default_item (new) or default (legacy).
        default_item = spec.get("default_item") or spec.get("default")
        if default_item is not None:
            if not isinstance(default_item, str) or not default_item.strip():
                raise ProjectFormatError(f"field_parameters[{name!r}].default_item must be a non-empty string if provided")
            default_item = default_item.strip()
            # Validate default_item exists in items (match by name or legacy key).
            valid_names = {it.name.upper() for it in items}
            # Also check legacy key matching for back-compat.
            legacy_keys = set()
            for o in items_raw:
                if isinstance(o, Mapping):
                    k = o.get("key")
                    if isinstance(k, str) and k.strip():
                        legacy_keys.add(k.strip().upper())
            if default_item.upper() not in valid_names and default_item.upper() not in legacy_keys:
                raise ProjectFormatError(
                    f"field_parameters[{name!r}].default_item {default_item!r} is not a valid item name"
                )
        else:
            # Default to first item.
            default_item = items[0].name if items else None

        out[name.strip()] = FieldParameter(
            name=name.strip(),
            items=items,
            default_item=default_item,
            dax=str(spec.get("dax")).strip() if isinstance(spec.get("dax"), str) and str(spec.get("dax")).strip() else None,
        )

    return out


def _load_hierarchies(path: Path) -> Dict[str, Hierarchy]:
    """Load hierarchy definitions from model/hierarchies.yaml.

    Expected shape:
      hierarchies:
        <hierarchy_name>:
          table: <table_name>
          levels:
            - column: <column_name>
              name: <display_name>  # optional, defaults to column name
    """
    if not path.exists():
        return {}

    raw = _load_yaml(path)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ProjectFormatError(f"hierarchies.yaml must be a mapping: {path}")

    h_raw = raw.get("hierarchies")
    if h_raw is None:
        return {}
    if not isinstance(h_raw, Mapping):
        raise ProjectFormatError("hierarchies.yaml: hierarchies must be a mapping")

    out: Dict[str, Hierarchy] = {}
    for h_name, h_spec in h_raw.items():
        if not isinstance(h_name, str) or not h_name.strip():
            raise ProjectFormatError("hierarchy keys must be non-empty strings")
        if not isinstance(h_spec, Mapping):
            raise ProjectFormatError(f"hierarchies[{h_name!r}] must be a mapping")

        table = h_spec.get("table")
        if not isinstance(table, str) or not table.strip():
            raise ProjectFormatError(f"hierarchies[{h_name!r}].table is required and must be a non-empty string")

        levels_raw = h_spec.get("levels")
        if not isinstance(levels_raw, list) or len(levels_raw) < 2:
            raise ProjectFormatError(
                f"hierarchies[{h_name!r}].levels must be a list with at least 2 levels"
            )

        levels: list[HierarchyLevel] = []
        names_seen: set[str] = set()
        for i, lvl in enumerate(levels_raw):
            if not isinstance(lvl, Mapping):
                raise ProjectFormatError(f"hierarchies[{h_name!r}].levels[{i}] must be a mapping")

            col_name = lvl.get("column")
            if not isinstance(col_name, str) or not col_name.strip():
                raise ProjectFormatError(
                    f"hierarchies[{h_name!r}].levels[{i}].column is required and must be a non-empty string"
                )

            display_name = lvl.get("name")
            if display_name is None:
                display_name = col_name.strip()
            elif not isinstance(display_name, str) or not display_name.strip():
                raise ProjectFormatError(
                    f"hierarchies[{h_name!r}].levels[{i}].name must be a non-empty string if provided"
                )
            else:
                display_name = display_name.strip()

            if display_name.upper() in names_seen:
                raise ProjectFormatError(
                    f"hierarchies[{h_name!r}] has duplicate level name: {display_name!r}"
                )
            names_seen.add(display_name.upper())

            levels.append(HierarchyLevel(column=col_name.strip(), name=display_name))

        out[h_name.strip()] = Hierarchy(
            name=h_name.strip(),
            table=table.strip(),
            levels=levels,
        )

    return out


def _load_what_if_parameters(path: Path) -> Dict[str, WhatIfParameter]:
    """Load What-If parameters."""
    if not path.exists():
        return {}

    raw = _load_yaml(path)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ProjectFormatError(f"what_if_parameters.yaml must be a mapping: {path}")

    params_raw = raw.get("what_if_parameters")
    if params_raw is None:
        return {}
    if not isinstance(params_raw, Mapping):
        raise ProjectFormatError(f"what_if_parameters.yaml: what_if_parameters must be a mapping")

    out: Dict[str, WhatIfParameter] = {}
    for name, spec in params_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ProjectFormatError("what_if_parameters keys must be non-empty strings")
        if not isinstance(spec, Mapping):
            raise ProjectFormatError(f"what_if_parameters[{name!r}] must be a mapping")

        min_val = spec.get("min")
        max_val = spec.get("max")
        step = spec.get("step")
        default_val = spec.get("default")
        format_str = spec.get("format")

        if not isinstance(min_val, (int, float)):
            raise ProjectFormatError(f"what_if_parameters[{name!r}].min must be a number")
        if not isinstance(max_val, (int, float)):
            raise ProjectFormatError(f"what_if_parameters[{name!r}].max must be a number")
        if not isinstance(step, (int, float)) or step <= 0:
            raise ProjectFormatError(f"what_if_parameters[{name!r}].step must be a positive number")
        if not isinstance(default_val, (int, float)):
            raise ProjectFormatError(f"what_if_parameters[{name!r}].default must be a number")
        if format_str is not None and not isinstance(format_str, str):
            raise ProjectFormatError(f"what_if_parameters[{name!r}].format must be a string if provided")

        if min_val > max_val:
            raise ProjectFormatError(f"what_if_parameters[{name!r}].min must be <= max")
        if default_val < min_val or default_val > max_val:
            raise ProjectFormatError(f"what_if_parameters[{name!r}].default must be between min and max")

        out[name.strip()] = WhatIfParameter(
            name=name.strip(),
            min_value=float(min_val),
            max_value=float(max_val),
            step=float(step),
            default_value=float(default_val),
            format=format_str.strip() if format_str else None,
        )

    return out


def _load_calc_groups(path: Path) -> Dict[str, CalculationGroup]:
    """Load calculation groups.

    Supports:
    - New schema (preferred): item{name, expression[, format_string]} + group{precedence}
    - Legacy schema: item{key, label, template} with {{MEASURE}} placeholder
    """

    if not path.exists():
        return {}

    raw = _load_yaml(path)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ProjectFormatError(f"calculation_groups.yaml must be a mapping: {path}")

    groups_raw = raw.get("calculation_groups")
    if groups_raw is None:
        return {}
    if not isinstance(groups_raw, Mapping):
        raise ProjectFormatError("calculation_groups.yaml: calculation_groups must be a mapping")

    def _canon_expr(expr_text: str) -> str:
        # Authoring sugar: {{MEASURE}} is equivalent to SELECTEDMEASURE().
        return expr_text.replace("{{MEASURE}}", "SELECTEDMEASURE()")

    out: Dict[str, CalculationGroup] = {}
    for name, spec in groups_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ProjectFormatError("calculation_groups keys must be non-empty strings")
        if not isinstance(spec, Mapping):
            raise ProjectFormatError(f"calculation_groups[{name!r}] must be a mapping")

        precedence_raw = spec.get("precedence", 0)
        if precedence_raw is None:
            precedence_raw = 0
        if not isinstance(precedence_raw, int):
            raise ProjectFormatError(f"calculation_groups[{name!r}].precedence must be an int")

        items_raw = spec.get("items")
        if not isinstance(items_raw, list) or not items_raw:
            raise ProjectFormatError(f"calculation_groups[{name!r}].items must be a non-empty list")

        items: List[CalculationItem] = []
        keys_seen: set[str] = set()
        for i, item in enumerate(items_raw):
            if not isinstance(item, Mapping):
                raise ProjectFormatError(f"calculation_groups[{name!r}].items[{i}] must be a mapping")

            # New schema.
            item_name = item.get("name")
            expr = item.get("expression")
            fmt = item.get("format_string")

            # Legacy schema (v0): key/label/template.
            if item_name is None and expr is None:
                item_name = item.get("key")
                expr = item.get("template")

            if not isinstance(item_name, str) or not item_name.strip():
                raise ProjectFormatError(
                    f"calculation_groups[{name!r}].items[{i}].name must be a non-empty string"
                )
            if not isinstance(expr, str) or not expr.strip():
                raise ProjectFormatError(
                    f"calculation_groups[{name!r}].items[{i}].expression must be a non-empty string"
                )

            if fmt is not None and (not isinstance(fmt, str) or not fmt.strip()):
                raise ProjectFormatError(
                    f"calculation_groups[{name!r}].items[{i}].format_string must be a non-empty string if provided"
                )

            k_norm = item_name.strip()
            if k_norm.upper() in keys_seen:
                raise ProjectFormatError(
                    f"calculation_groups[{name!r}] has duplicate item name: {k_norm!r}"
                )
            keys_seen.add(k_norm.upper())

            items.append(
                CalculationItem(
                    name=k_norm,
                    expression=_canon_expr(expr.strip()),
                    format_string=fmt.strip() if isinstance(fmt, str) and fmt.strip() else None,
                )
            )

        out[name.strip()] = CalculationGroup(name=name.strip(), precedence=int(precedence_raw), items=items)

    return out


def _is_booleanish_security_filter(expr: Expr) -> bool:
    """Best-effort boolean check for RLS filters.

    The IR has no formal type system. We conservatively accept:
    - literals (bool/None)
    - comparisons (DaxBinaryOp with comparison ops)
    - IN
    - boolean combinators AND/OR/NOT
    """

    from dax_engine.ir import DaxBinaryOp as _DaxBinaryOp
    from dax_engine.ir import DaxFunction as _DaxFunction
    from dax_engine.ir import Literal as _Literal

    if isinstance(expr, _Literal):
        return isinstance(expr.value, (bool, type(None)))
    if isinstance(expr, _DaxBinaryOp):
        op = str(expr.operator or "").strip().upper()
        if op in {"=", "==", "<>", "!=", ">", ">=", "<", "<=", "IN"}:
            return True
    if isinstance(expr, _DaxFunction):
        fn = str(expr.fn or "").strip().upper()
        if fn in {"AND", "OR", "NOT", "TRUE", "FALSE", "ISBLANK", "ISERROR"}:
            return True
    return False


def _load_security(
    path: Path,
    *,
    tables: List[Table],
    measures: List[MeasureDefinition],
) -> tuple[Dict[str, SecurityRole], Optional[str]]:
    if not path.exists():
        return ({}, None)

    raw = _load_yaml(path)
    if raw is None:
        return ({}, None)
    if not isinstance(raw, Mapping):
        raise ProjectFormatError(f"security.yaml must be a mapping: {path}")

    default_role = raw.get("default_role")
    if default_role is not None and (not isinstance(default_role, str) or not default_role.strip()):
        raise ProjectFormatError("security.yaml: default_role must be a non-empty string if provided")

    roles_raw = raw.get("roles")
    if roles_raw is None:
        roles_raw = []
    if not isinstance(roles_raw, list):
        raise ProjectFormatError("security.yaml: roles must be a list")

    table_lookup: Dict[str, Table] = {t.name.upper(): t for t in tables}
    column_lookup: set[tuple[str, str]] = set()
    for t in tables:
        for c in t.columns:
            column_lookup.add((t.name.upper(), c.name.upper()))
    measure_lookup: set[str] = {m.name.upper() for m in measures}

    out: Dict[str, SecurityRole] = {}
    seen: set[str] = set()

    from dax_parser.ir_mapper import ast_to_ir
    from dax_parser.parser import parse_expression

    for i, rr in enumerate(roles_raw):
        if not isinstance(rr, Mapping):
            raise ProjectFormatError(f"security.yaml: roles[{i}] must be a mapping")
        name = rr.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProjectFormatError(f"security.yaml: roles[{i}].name must be a non-empty string")
        name_norm = name.strip()
        if name_norm.upper() in seen:
            raise ProjectFormatError(f"security.yaml: duplicate role name: {name_norm!r}")
        seen.add(name_norm.upper())

        # --- RLS ---
        rls_rules: List[SecurityRlsRule] = []
        rls_raw = rr.get("rls")
        if rls_raw is None:
            rls_raw = []
        if not isinstance(rls_raw, list):
            raise ProjectFormatError(f"security.yaml: roles[{i}].rls must be a list")
        for j, rule in enumerate(rls_raw):
            if not isinstance(rule, Mapping):
                raise ProjectFormatError(f"security.yaml: roles[{i}].rls[{j}] must be a mapping")
            tname = rule.get("table")
            dax_text = rule.get("filter")
            if not isinstance(tname, str) or not tname.strip():
                raise ProjectFormatError(f"security.yaml: roles[{i}].rls[{j}].table must be a non-empty string")
            if not isinstance(dax_text, str) or not dax_text.strip():
                raise ProjectFormatError(f"security.yaml: roles[{i}].rls[{j}].filter must be a non-empty string")

            t_norm = tname.strip()
            if t_norm.upper() not in table_lookup:
                raise ProjectValidationError(
                    f"Project validation failed:\n- security role {name_norm!r}: unknown table in RLS: {t_norm!r}"
                )

            ir = ast_to_ir(parse_expression(dax_text))
            if not isinstance(ir, ScalarExpr):
                raise ProjectValidationError(
                    f"Project validation failed:\n- security role {name_norm!r}: RLS filter must be a scalar expression"
                )

            if not _is_booleanish_security_filter(ir):
                raise ProjectValidationError(
                    f"Project validation failed:\n- security role {name_norm!r}: RLS filter must be boolean-like"
                )

            # RLS v1 contract: only allow ColumnRefs to the same table; disallow MeasureRef and ParamRef.
            for mr in _collect_measure_refs(ir):
                raise ProjectValidationError(
                    f"Project validation failed:\n- security role {name_norm!r}: RLS filter must not reference measures: {mr.name!r}"
                )
            for pr in _collect_param_refs(ir):
                raise ProjectValidationError(
                    f"Project validation failed:\n- security role {name_norm!r}: RLS filter must not reference field parameters: {pr.name!r}"
                )

            for cr in _collect_column_refs(ir):
                if cr.table.upper() != t_norm.upper():
                    raise ProjectValidationError(
                        "Project validation failed:\n"
                        + f"- security role {name_norm!r}: RLS filter for table {t_norm!r} cannot reference other table: {cr.table!r}"
                    )
                if (cr.table.upper(), cr.column.upper()) not in column_lookup:
                    raise ProjectValidationError(
                        "Project validation failed:\n"
                        + f"- security role {name_norm!r}: unknown column in RLS filter: {cr.table!r}[{cr.column!r}]"
                    )

            rls_rules.append(SecurityRlsRule(table=t_norm, filter=dax_text))

        # --- OLS ---
        ols_raw = rr.get("ols")
        if ols_raw is None:
            ols_raw = {}
        if not isinstance(ols_raw, Mapping):
            raise ProjectFormatError(f"security.yaml: roles[{i}].ols must be a mapping if provided")

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
            raise ProjectFormatError(f"security.yaml: roles[{i}].ols.tables must be a list of strings")
        if not isinstance(ols_measures_raw, list) or not all(isinstance(x, str) for x in ols_measures_raw):
            raise ProjectFormatError(f"security.yaml: roles[{i}].ols.measures must be a list of strings")
        if not isinstance(ols_columns_raw, Mapping):
            raise ProjectFormatError(f"security.yaml: roles[{i}].ols.columns must be a mapping")

        ols_tables = [str(x).strip() for x in ols_tables_raw if str(x).strip()]
        ols_measures = [str(x).strip() for x in ols_measures_raw if str(x).strip()]
        ols_columns: Dict[str, List[str]] = {}

        for t, cols in ols_columns_raw.items():
            if not isinstance(t, str) or not t.strip():
                raise ProjectFormatError(f"security.yaml: roles[{i}].ols.columns keys must be non-empty strings")
            if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
                raise ProjectFormatError(
                    f"security.yaml: roles[{i}].ols.columns[{t!r}] must be a list of strings"
                )
            ols_columns[t.strip()] = [str(c).strip() for c in cols if str(c).strip()]

        # Strict validation: referenced objects must exist.
        for t in ols_tables:
            if t.upper() not in table_lookup:
                raise ProjectValidationError(
                    "Project validation failed:\n"
                    + f"- security role {name_norm!r}: unknown table in OLS.tables: {t!r}"
                )
        for m in ols_measures:
            if m.upper() not in measure_lookup:
                raise ProjectValidationError(
                    "Project validation failed:\n"
                    + f"- security role {name_norm!r}: unknown measure in OLS.measures: {m!r}"
                )
        for t, cols in ols_columns.items():
            if t.upper() not in table_lookup:
                raise ProjectValidationError(
                    "Project validation failed:\n"
                    + f"- security role {name_norm!r}: unknown table in OLS.columns: {t!r}"
                )
            for c in cols:
                if (t.upper(), c.upper()) not in column_lookup:
                    raise ProjectValidationError(
                        "Project validation failed:\n"
                        + f"- security role {name_norm!r}: unknown column in OLS.columns: {t!r}[{c!r}]"
                    )

        out[name_norm] = SecurityRole(
            name=name_norm,
            rls=rls_rules,
            ols=SecurityOls(tables=ols_tables, measures=ols_measures, columns=ols_columns),
        )

    if default_role is not None and default_role.strip():
        if default_role.strip().upper() not in {k.upper() for k in out.keys()}:
            raise ProjectValidationError(
                "Project validation failed:\n" + f"- default_role not found in roles: {default_role!r}"
            )

    return (out, default_role.strip() if isinstance(default_role, str) and default_role.strip() else None)


def _load_pages(path: Path) -> List[PageDefinition]:
    if not path.exists():
        return [PageDefinition(id="page1", title="Page 1", order=1)]
    raw = _load_yaml(path)
    pages_raw = _as_list_root(raw, label="pages")

    pages: List[PageDefinition] = []
    seen: set[str] = set()
    for i, p in enumerate(pages_raw):
        if not isinstance(p, Mapping):
            raise ProjectFormatError(f"pages[{i}] must be a mapping")
        page_id = p.get("id")
        title = p.get("title")
        order = p.get("order")
        page_type = p.get("page_type")
        placeholder_containers = p.get("placeholder_containers")
        if not isinstance(page_id, str) or not page_id.strip():
            raise ProjectFormatError(f"pages[{i}].id is required")
        if not isinstance(title, str) or not title.strip():
            raise ProjectFormatError(f"pages[{i}].title is required")

        page_id_norm = page_id.strip()
        if page_id_norm.upper() in seen:
            raise ProjectFormatError(f"Duplicate page id: {page_id_norm!r}")
        seen.add(page_id_norm.upper())

        if order is not None and not isinstance(order, int):
            raise ProjectFormatError(f"pages[{i}].order must be an int if provided")

        if page_type is not None and (not isinstance(page_type, str) or not page_type.strip()):
            raise ProjectFormatError(f"pages[{i}].page_type must be a non-empty string if provided")

        if placeholder_containers is not None:
            if not isinstance(placeholder_containers, list) or not all(isinstance(item, str) for item in placeholder_containers):
                raise ProjectFormatError(f"pages[{i}].placeholder_containers must be a list of strings if provided")

        # Back-compat: older pages.yaml variants may include a 'visuals' list.
        visuals = p.get("visuals")
        if visuals is not None and (not isinstance(visuals, list) or not all(isinstance(v, str) for v in visuals)):
            raise ProjectFormatError(f"pages[{i}].visuals must be a list of strings if provided")

        # Drillthrough support (Phase 4.2)
        drillthrough = bool(p.get("drillthrough", False))
        dt_cols_raw = p.get("drillthrough_columns")
        dt_cols: list[dict[str, str]] = []
        if dt_cols_raw is not None:
            if not isinstance(dt_cols_raw, list):
                raise ProjectFormatError(f"pages[{i}].drillthrough_columns must be a list if provided")
            for ci, col_spec in enumerate(dt_cols_raw):
                if not isinstance(col_spec, Mapping):
                    raise ProjectFormatError(f"pages[{i}].drillthrough_columns[{ci}] must be a mapping")
                tbl = col_spec.get("table")
                col = col_spec.get("column")
                if not isinstance(tbl, str) or not tbl.strip():
                    raise ProjectFormatError(f"pages[{i}].drillthrough_columns[{ci}].table is required")
                if not isinstance(col, str) or not col.strip():
                    raise ProjectFormatError(f"pages[{i}].drillthrough_columns[{ci}].column is required")
                dt_cols.append({"table": tbl.strip(), "column": col.strip()})

        pages.append(
            PageDefinition(
                id=page_id_norm,
                title=title.strip(),
                order=order,
                page_type=page_type.strip() if isinstance(page_type, str) and page_type.strip() else None,
                placeholder_containers=[item.strip() for item in placeholder_containers if item.strip()]
                if isinstance(placeholder_containers, list)
                else [],
                drillthrough=drillthrough,
                drillthrough_columns=dt_cols,
                hidden=bool(p.get("hidden", False)),
            )
        )

    if not pages:
        return [PageDefinition(id="page1", title="Page 1", order=1)]
    return pages


def _load_visual_file(path: Path, *, default_page_id: str = "page1") -> VisualDefinition:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ProjectFormatError(f"Visual JSON must be an object: {path}")

    visual_id = raw.get("id", path.stem)
    title = raw.get("title", path.stem)
    visual_type = raw.get("visual_type", raw.get("type", ""))
    page_id = raw.get("page_id", default_page_id)
    spec_raw = raw.get("spec")
    layout_raw = raw.get("layout")
    encodings_raw = raw.get("encodings")
    plotly_patch_raw = raw.get("advanced_plotly_patch")
    param_values_raw = raw.get("param_values")
    calc_groups_raw = raw.get("calc_groups")

    if not isinstance(visual_id, str) or not visual_id.strip():
        raise ProjectFormatError(f"Visual.id must be a non-empty string: {path}")
    if not isinstance(title, str) or not title.strip():
        raise ProjectFormatError(f"Visual.title must be a non-empty string: {path}")
    if not isinstance(visual_type, str):
        raise ProjectFormatError(f"Visual.type/visual_type must be a string: {path}")
    if not isinstance(default_page_id, str) or not default_page_id.strip():
        raise ProjectFormatError(f"default_page_id must be a non-empty string: {path}")
    if not isinstance(page_id, str) or not page_id.strip():
        raise ProjectFormatError(f"Visual.page_id must be a non-empty string if provided: {path}")
    if spec_raw is not None and not isinstance(spec_raw, Mapping):
        raise ProjectFormatError(f"Visual.spec must be an object if provided: {path}")
    if encodings_raw is not None and not isinstance(encodings_raw, Mapping):
        raise ProjectFormatError(f"Visual.encodings must be an object if provided: {path}")
    if layout_raw is not None and not isinstance(layout_raw, Mapping):
        raise ProjectFormatError(f"Visual.layout must be an object if provided: {path}")
    if plotly_patch_raw is not None and not isinstance(plotly_patch_raw, Mapping):
        raise ProjectFormatError(f"Visual.advanced_plotly_patch must be an object if provided: {path}")
    if param_values_raw is not None and not isinstance(param_values_raw, Mapping):
        raise ProjectFormatError(f"Visual.param_values must be an object if provided: {path}")
    if calc_groups_raw is not None and not isinstance(calc_groups_raw, Mapping):
        raise ProjectFormatError(f"Visual.calc_groups must be an object if provided: {path}")

    # Optional canvas layout.
    layout: Dict[str, float] | None = None
    if isinstance(layout_raw, Mapping):
        required = ("x", "y", "w", "h")
        missing = [k for k in required if k not in layout_raw]
        if missing:
            raise ProjectFormatError(f"{path}: layout missing keys: {missing}")
        out_layout: Dict[str, float] = {}
        for k in required:
            v = layout_raw.get(k)
            if not isinstance(v, (int, float)):
                raise ProjectFormatError(f"{path}: layout.{k} must be a number")
            out_layout[k] = float(v)
        layout = out_layout

    # Optional encodings (slot -> Expr | [Expr] | None).
    encodings: Dict[str, Any] = {}
    if isinstance(encodings_raw, Mapping):
        for slot, v in encodings_raw.items():
            if not isinstance(slot, str) or not slot.strip():
                raise ProjectFormatError(f"{path}: encodings keys must be non-empty strings")
            # Skip non-expression encodings fields (e.g., tablix layout properties)
            if slot == "tablix":
                encodings[slot] = v
                continue
            # Combo layers: parse y/color inside each layer dict, pass rest through.
            if slot == "layers" and isinstance(v, list):
                resolved_layers: list[dict[str, Any]] = []
                for lyr in v:
                    if not isinstance(lyr, Mapping):
                        continue
                    rl: dict[str, Any] = {}
                    for lk, lv in lyr.items():
                        if lk in ("y", "color") and lv is not None:
                            if isinstance(lv, Mapping) and lv.get("type") == "ExplanationRef":
                                rl[lk] = dict(lv)
                            elif isinstance(lv, Mapping):
                                rl[lk] = parse_expr(lv)
                            else:
                                rl[lk] = lv
                        else:
                            rl[lk] = lv
                    resolved_layers.append(rl)
                encodings[slot] = resolved_layers
                continue
            # String pass-through encoding options (not IR expressions)
            if slot in ("layout_mode",) and isinstance(v, str):
                encodings[slot] = v
                continue
            if v is None:
                encodings[slot] = None
            elif isinstance(v, list):
                parsed: list[Any] = []
                for e in v:
                    # ExplanationRef is a pass-through annotation, not an IR expression.
                    if isinstance(e, Mapping) and e.get("type") == "ExplanationRef":
                        parsed.append(dict(e))   # keep as raw dict
                    else:
                        parsed.append(parse_expr(e))
                encodings[slot] = parsed
            else:
                if isinstance(v, Mapping) and v.get("type") == "ExplanationRef":
                    encodings[slot] = dict(v)
                else:
                    encodings[slot] = parse_expr(v)

    advanced_plotly_patch = dict(plotly_patch_raw) if isinstance(plotly_patch_raw, Mapping) else None

    # Legacy visuals provide a full VisualQuerySpec in 'spec'. Canvas visuals can omit
    # 'spec' and instead provide 'encodings'; we derive a minimal spec for validation.
    if isinstance(spec_raw, Mapping):
        dims_raw = spec_raw.get("dimensions") or []
        meas_raw = spec_raw.get("measures") or []
        filters_raw = spec_raw.get("filters") or []
        limit = spec_raw.get("limit")

        if not isinstance(dims_raw, list):
            raise ProjectFormatError(f"{path}: spec.dimensions must be a list")
        if not isinstance(meas_raw, list):
            raise ProjectFormatError(f"{path}: spec.measures must be a list")
        if not isinstance(filters_raw, list):
            raise ProjectFormatError(f"{path}: spec.filters must be a list")
        if limit is not None and not isinstance(limit, int):
            raise ProjectFormatError(f"{path}: spec.limit must be an int if provided")

        dims: List[Expr] = []
        for i, d in enumerate(dims_raw):
            expr = parse_expr(d)
            if not isinstance(expr, (ColumnRef, ParamRef)):
                raise ProjectFormatError(f"{path}: spec.dimensions[{i}] must be a ColumnRef or ParamRef")
            dims.append(expr)

        measures: List[Expr] = []
        for i, m in enumerate(meas_raw):
            expr = parse_expr(m)
            if not isinstance(expr, (MeasureRef, ParamRef)):
                raise ProjectFormatError(f"{path}: spec.measures[{i}] must be a MeasureRef or ParamRef")
            measures.append(expr)

        filters: List[Expr] = [parse_expr(f) for f in filters_raw]

        sort_json = parse_sort_list(spec_raw.get("sort"))
        sort: List[SortSpec] = [SortSpec(expr=s.expr, direction=s.direction) for s in sort_json]

        spec = VisualQuerySpec(dimensions=dims, measures=measures, filters=filters, sort=sort, limit=limit)
    elif encodings:
        # Derive dimensions/measures by scanning encodings in JSON key order.
        dims_out: List[Expr] = []
        meas_out: List[Expr] = []
        seen_dim: set[str] = set()
        seen_meas: set[str] = set()

        def _walk_expr(e: Any) -> None:
            # ExplanationRef pass-through dicts are not IR expressions; skip them.
            if isinstance(e, dict) and e.get("type") == "ExplanationRef":
                return
            # Combo layers: walk into y/color of each layer dict.
            if isinstance(e, list) and e and isinstance(e[0], dict) and "type" in e[0] and "y" in e[0]:
                for lyr in e:
                    if isinstance(lyr, dict):
                        for lk in ("y", "color"):
                            if lk in lyr and lyr[lk] is not None:
                                _walk_expr(lyr[lk])
                return
            if isinstance(e, ColumnRef):
                key = f"{e.table}.{e.column}".upper()
                if key not in seen_dim:
                    seen_dim.add(key)
                    dims_out.append(e)
                return
            if isinstance(e, MeasureRef):
                key = e.name.upper()
                if key not in seen_meas:
                    seen_meas.add(key)
                    meas_out.append(e)
                return
            if isinstance(e, list):
                for it in e:
                    _walk_expr(it)
                return

        for _slot, v in encodings.items():
            if v is None:
                continue
            _walk_expr(v)

        spec = VisualQuerySpec(dimensions=dims_out, measures=meas_out)
    elif isinstance(encodings_raw, Mapping):
        # Empty encodings dict is valid for static visuals (textbox, button, shape, image)
        spec = VisualQuerySpec(dimensions=[], measures=[])
    else:
        raise ProjectFormatError(f"Visual must provide either 'spec' or 'encodings': {path}")

    param_values: Dict[str, str] = {}
    if isinstance(param_values_raw, Mapping):
        for k, v in param_values_raw.items():
            if not isinstance(k, str) or not k.strip():
                raise ProjectFormatError(f"{path}: param_values keys must be non-empty strings")
            if not isinstance(v, str) or not v.strip():
                raise ProjectFormatError(f"{path}: param_values[{k!r}] must be a non-empty string")
            param_values[k.strip()] = v.strip()

    calc_groups: Dict[str, str] = {}
    if isinstance(calc_groups_raw, Mapping):
        for k, v in calc_groups_raw.items():
            if not isinstance(k, str) or not k.strip():
                raise ProjectFormatError(f"{path}: calc_groups keys must be non-empty strings")
            if not isinstance(v, str) or not v.strip():
                raise ProjectFormatError(f"{path}: calc_groups[{k!r}] must be a non-empty string")
            calc_groups[k.strip()] = v.strip()

    return VisualDefinition(
        id=visual_id.strip(),
        title=title.strip(),
        type=visual_type,
        page_id=str(page_id).strip() or "page1",
        spec=spec,
        param_values=param_values,
        calc_groups=calc_groups,
        layout=layout,
        encodings=encodings,
        advanced_plotly_patch=advanced_plotly_patch,
    )


def _collect_param_refs(expr: Expr) -> List[ParamRef]:
    out: List[ParamRef] = []

    def walk(e: Expr) -> None:
        if isinstance(e, ParamRef):
            out.append(e)
            return
        if isinstance(e, DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return

    walk(expr)
    return out


def _collect_column_refs(expr: Expr) -> List[ColumnRef]:
    out: List[ColumnRef] = []

    def walk(e: Expr) -> None:
        if isinstance(e, ColumnRef):
            out.append(e)
            return
        if isinstance(e, DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return

    walk(expr)
    return out


def _collect_measure_refs(expr: Expr) -> List[MeasureRef]:
    out: List[MeasureRef] = []

    def walk(e: Expr) -> None:
        if isinstance(e, MeasureRef):
            out.append(e)
            return
        if isinstance(e, DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return

    walk(expr)
    return out


def _validate_hierarchies(model: SemanticModel) -> None:
    """Validate hierarchy definitions against the semantic model.

    Checks:
    - Hierarchy table must exist
    - Each level column must exist in the hierarchy's table
    """
    table_lookup: Dict[str, Table] = {t.name.upper(): t for t in model.tables}
    column_lookup: Dict[Tuple[str, str], Column] = {}
    for t in model.tables:
        for c in t.columns:
            column_lookup[(t.name.upper(), c.name.upper())] = c

    errors: List[str] = []
    for h_name, h in model.hierarchies.items():
        t_key = h.table.upper()
        if t_key not in table_lookup:
            errors.append(f"hierarchy {h_name!r}: unknown table {h.table!r}")
            continue
        for lvl in h.levels:
            c_key = lvl.column.upper()
            if (t_key, c_key) not in column_lookup:
                errors.append(
                    f"hierarchy {h_name!r}: unknown column {h.table!r}[{lvl.column!r}]"
                )

    if errors:
        raise ProjectValidationError(
            "Project validation failed:\n" + "\n".join(f"- {e}" for e in errors)
        )


def _validate_visuals(model: SemanticModel, visuals: Sequence[VisualDefinition]) -> None:
    table_lookup: Dict[str, Table] = {t.name.upper(): t for t in model.tables}
    column_lookup: Dict[Tuple[str, str], Column] = {}
    for t in model.tables:
        for c in t.columns:
            column_lookup[(t.name.upper(), c.name.upper())] = c

    measure_lookup: Dict[str, MeasureDefinition] = {m.name.upper(): m for m in model.measures}

    errors: List[str] = []

    fp_lookup = {k.upper(): v for k, v in model.field_parameters.items()}
    cg_lookup = {k.upper(): v for k, v in model.calculation_groups.items()}

    # Field parameter table names are virtual — ColumnRefs targeting them are
    # valid even though they don't appear in model.tables.
    fp_table_names: set[str] = set(fp_lookup.keys())

    for v in visuals:
        # Validate param_values mapping.
        for p_name, p_value in (v.param_values or {}).items():
            fp = fp_lookup.get(p_name.upper())
            if fp is None:
                errors.append(f"visual {v.id!r}: param_values references unknown field parameter: {p_name!r}")
                continue
            valid_names = {item.name for item in fp.items}
            if p_value not in valid_names:
                errors.append(
                    f"visual {v.id!r}: invalid field parameter value for {p_name!r}: {p_value!r}; valid names: {sorted(valid_names)}"
                )

        # Validate calc group selections.
        for cg_name, item_key in (v.calc_groups or {}).items():
            group = cg_lookup.get(cg_name.upper())
            if group is None:
                errors.append(f"visual {v.id!r}: calc_groups references unknown group: {cg_name!r}")
                continue
            valid_item_keys = {it.key for it in group.items}
            if item_key not in valid_item_keys:
                errors.append(
                    f"visual {v.id!r}: calc_groups has invalid item for {cg_name!r}: {item_key!r}; valid keys: {sorted(valid_item_keys)}"
                )

        # Dimensions can be ColumnRef or ParamRef.
        for d in v.spec.dimensions:
            if isinstance(d, ColumnRef):
                t_key = d.table.upper()
                c_key = d.column.upper()
                if t_key not in table_lookup and t_key not in fp_table_names:
                    errors.append(f"visual {v.id!r}: unknown table in ColumnRef: {d.table!r}")
                elif t_key not in fp_table_names and (t_key, c_key) not in column_lookup:
                    errors.append(f"visual {v.id!r}: unknown column in ColumnRef: {d.table!r}[{d.column!r}]")
            elif isinstance(d, ParamRef):
                fp = fp_lookup.get(d.name.upper())
                if fp is None:
                    errors.append(f"visual {v.id!r}: unknown field parameter: {d.name!r}")
                    continue
                selected = (v.param_values or {}).get(fp.name, fp.default_item)
                item = next((item for item in fp.items if item.name == selected), None)
                if item is None:
                    errors.append(
                        f"visual {v.id!r}: invalid selection for field parameter {fp.name!r}: {selected!r}"
                    )
                    continue
                if not isinstance(item.ref, ColumnRef):
                    errors.append(
                        f"visual {v.id!r}: field parameter {fp.name!r} selection {selected!r} must resolve to a ColumnRef when used as a dimension"
                    )
                    continue
                t_key = item.ref.table.upper()
                c_key = item.ref.column.upper()
                if t_key not in table_lookup:
                    errors.append(f"visual {v.id!r}: unknown table in field parameter: {item.ref.table!r}")
                elif (t_key, c_key) not in column_lookup:
                    errors.append(
                        f"visual {v.id!r}: unknown column in field parameter: {item.ref.table!r}[{item.ref.column!r}]"
                    )

        # Measures can be MeasureRef or ParamRef.
        for m in v.spec.measures:
            if isinstance(m, MeasureRef):
                if m.name.upper() not in measure_lookup:
                    errors.append(f"visual {v.id!r}: unknown measure: {m.name!r}")
            elif isinstance(m, ParamRef):
                fp = fp_lookup.get(m.name.upper())
                if fp is None:
                    errors.append(f"visual {v.id!r}: unknown field parameter: {m.name!r}")
                    continue
                selected = (v.param_values or {}).get(fp.name, fp.default_item)
                item = next((item for item in fp.items if item.name == selected), None)
                if item is None:
                    errors.append(
                        f"visual {v.id!r}: invalid selection for field parameter {fp.name!r}: {selected!r}"
                    )
                    continue
                if not isinstance(item.ref, MeasureRef):
                    errors.append(
                        f"visual {v.id!r}: field parameter {fp.name!r} selection {selected!r} must resolve to a MeasureRef when used as a measure"
                    )
                    continue
                if item.ref.name.upper() not in measure_lookup:
                    errors.append(f"visual {v.id!r}: unknown measure in field parameter: {item.ref.name!r}")

        # Filters/sorts can contain nested refs.
        for f in v.spec.filters:
            for cr in _collect_column_refs(f):
                t_key = cr.table.upper()
                c_key = cr.column.upper()
                if t_key not in table_lookup and t_key not in fp_table_names:
                    errors.append(f"visual {v.id!r}: unknown table in filter ColumnRef: {cr.table!r}")
                elif t_key not in fp_table_names and (t_key, c_key) not in column_lookup:
                    errors.append(
                        f"visual {v.id!r}: unknown column in filter ColumnRef: {cr.table!r}[{cr.column!r}]"
                    )
            for mr in _collect_measure_refs(f):
                if mr.name.upper() not in measure_lookup:
                    errors.append(f"visual {v.id!r}: unknown measure in filter: {mr.name!r}")

            for pr in _collect_param_refs(f):
                if pr.name.upper() not in fp_lookup:
                    errors.append(f"visual {v.id!r}: unknown field parameter in filter: {pr.name!r}")

        for s in v.spec.sort:
            for cr in _collect_column_refs(s.expr):
                t_key = cr.table.upper()
                c_key = cr.column.upper()
                if t_key not in table_lookup and t_key not in fp_table_names:
                    errors.append(f"visual {v.id!r}: unknown table in sort ColumnRef: {cr.table!r}")
                elif t_key not in fp_table_names and (t_key, c_key) not in column_lookup:
                    errors.append(
                        f"visual {v.id!r}: unknown column in sort ColumnRef: {cr.table!r}[{cr.column!r}]"
                    )
            for mr in _collect_measure_refs(s.expr):
                if mr.name.upper() not in measure_lookup:
                    errors.append(f"visual {v.id!r}: unknown measure in sort: {mr.name!r}")

            for pr in _collect_param_refs(s.expr):
                if pr.name.upper() not in fp_lookup:
                    errors.append(f"visual {v.id!r}: unknown field parameter in sort: {pr.name!r}")

    if errors:
        raise ProjectValidationError("Project validation failed:\n" + "\n".join(f"- {e}" for e in errors))


# ── load_project() mtime-based cache ────────────────────────────────────
# Avoids re-parsing YAML/JSON files on every render call.
# Cache is invalidated when any relevant file's mtime changes.

_LP_LOCK = threading.Lock()
_LP_CACHE: dict[str, tuple[
    tuple[int, ...],                               # signature (mtimes)
    tuple["SemanticModel", list, list],             # cached result
]] = {}


def _load_project_signature(root: Path) -> tuple[int, ...]:
    """Compute a signature tuple from mtimes of all project-relevant files."""
    model_dir = root / "model"
    reports_dir = root / "reports"

    paths: list[Path] = [
        model_dir / "measures.yaml",
        model_dir / "relationships.yaml",
        model_dir / "security.yaml",
        model_dir / "hierarchies.yaml",
        model_dir / "field_parameters.yaml",
        model_dir / "what_if_parameters.yaml",
        model_dir / "calculation_groups.yaml",
        model_dir / "calc_groups.yaml",
        reports_dir / "pages.yaml",
    ]

    tables_dir = model_dir / "tables"
    if tables_dir.exists() and tables_dir.is_dir():
        paths.extend(sorted(tables_dir.glob("*.yaml")))

    visuals_dir = reports_dir / "visuals"
    if visuals_dir.exists() and visuals_dir.is_dir():
        paths.extend(sorted(visuals_dir.glob("*.json")))

    def _mtime_ns(p: Path) -> int:
        try:
            return int(p.stat().st_mtime_ns)
        except (FileNotFoundError, OSError):
            return 0

    return tuple(_mtime_ns(p) for p in paths)


def invalidate_load_project_cache(project_path: str | None = None) -> None:
    """Explicitly invalidate the load_project cache.

    Args:
        project_path: If provided, only invalidate for this project.
                      If None, clear the entire cache.
    """
    with _LP_LOCK:
        if project_path is None:
            _LP_CACHE.clear()
        else:
            key = os.path.normcase(os.path.abspath(project_path))
            _LP_CACHE.pop(key, None)


def load_project(project_path: str) -> tuple[SemanticModel, list[PageDefinition], list[VisualDefinition]]:
    """Load a project directory.

    Expected layout:
      <project_path>/
        model/
          tables/<Table>.yaml
          relationships.yaml
          measures.yaml
        reports/
          pages.yaml
          visuals/<visual_id>.json

    Returns:
      (semantic_model, pages, visuals)

    Uses an mtime-based cache to avoid re-parsing YAML/JSON files on
    every call.  The cache is thread-safe and invalidated automatically
    when any relevant file changes on disk.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    # ── Cache check ─────────────────────────────────────────────────────
    cache_key = os.path.normcase(os.path.abspath(project_path))
    sig = _load_project_signature(root)

    with _LP_LOCK:
        cached = _LP_CACHE.get(cache_key)
        if cached is not None and cached[0] == sig:
            return cached[1]

    # ── Cache miss — parse from disk ────────────────────────────────────
    model_dir = root / "model"
    reports_dir = root / "reports"

    tables = _load_tables(model_dir / "tables")
    relationships = _load_relationships(model_dir / "relationships.yaml")
    measures = _load_measures(model_dir / "measures.yaml")
    field_parameters = _load_field_parameters(model_dir / "field_parameters.yaml")
    what_if_parameters = _load_what_if_parameters(model_dir / "what_if_parameters.yaml")
    # Calculation groups: prefer the canonical file name, but support legacy.
    calc_groups_path = model_dir / "calculation_groups.yaml"
    if not calc_groups_path.exists():
        calc_groups_path = model_dir / "calc_groups.yaml"
    calculation_groups = _load_calc_groups(calc_groups_path)

    security_roles, default_role = _load_security(
        model_dir / "security.yaml",
        tables=tables,
        measures=measures,
    )

    hierarchies = _load_hierarchies(model_dir / "hierarchies.yaml")

    model = SemanticModel(
        tables=tables,
        relationships=relationships,
        measures=measures,
        field_parameters=field_parameters,
        calculation_groups=calculation_groups,
        what_if_parameters=what_if_parameters,
        security_roles=security_roles,
        default_role=default_role,
        hierarchies=hierarchies,
    )

    pages = _load_pages(reports_dir / "pages.yaml")

    default_page_id = pages[0].id if pages else "page1"

    visuals_dir = reports_dir / "visuals"
    visuals: List[VisualDefinition] = []
    if visuals_dir.exists() and visuals_dir.is_dir():
        for path in sorted(visuals_dir.glob("*.json")):
            visuals.append(_load_visual_file(path, default_page_id=default_page_id))

    page_ids = {p.id.upper(): p for p in pages}
    bad_pages: List[str] = []
    for v in visuals:
        if v.page_id.upper() not in page_ids:
            bad_pages.append(f"visual {v.id!r}: invalid page_id {v.page_id!r}")
    if bad_pages:
        raise ProjectValidationError(
            "Project validation failed:\n" + "\n".join(f"- {e}" for e in bad_pages)
        )

    _validate_hierarchies(model)
    _validate_visuals(model, visuals)

    result = (model, pages, visuals)

    # ── Store in cache ──────────────────────────────────────────────────
    with _LP_LOCK:
        _LP_CACHE[cache_key] = (sig, result)

    return result
