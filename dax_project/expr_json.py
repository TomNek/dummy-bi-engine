from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Union

from dax_engine.ir import (
    CalcGroupItemRef,
    ColumnRef,
    DaxFunction,
    Expr,
    HierarchyRef,
    Literal,
    MeasureRef,
    ParamRef,
    ScalarExpr,
    SetLiteral,
    TableRef,
)

from .errors import ProjectFormatError


JsonValue = Union[None, bool, int, float, str, List["JsonValue"], Dict[str, "JsonValue"]]


def parse_expr(obj: Any) -> Expr:
    """Parse a JSON value into a dax_engine.ir Expr.

    Supported tagged objects:
    - {"type": "ColumnRef", "table": "T", "column": "C"}
    - {"type": "TableRef", "name": "Sales"}
    - {"type": "MeasureRef", "name": "Measure"}
    - {"type": "ParamRef", "name": "AxisField"}
    - {"type": "Literal", "value": ...}
    - {"type": "SetLiteral", "values": [<scalar expr>, ...]}
    - {"type": "DaxFunction", "name": "FUNC", "args": [<expr>, ...]}

    The format is intentionally minimal and explicit.
    """

    if isinstance(obj, Mapping):
        type_tag = obj.get("type")
        if not isinstance(type_tag, str) or not type_tag:
            raise ProjectFormatError("Expression objects must have a non-empty string 'type' field")

        if type_tag == "ColumnRef":
            table = obj.get("table")
            column = obj.get("column")
            # Table is optional for field parameters (unqualified column refs)
            if table is not None and not isinstance(table, str):
                raise ProjectFormatError("ColumnRef.table must be a string if provided")
            if not isinstance(column, str) or not column.strip():
                raise ProjectFormatError("ColumnRef.column must be a non-empty string")
            table_s = table.strip() if isinstance(table, str) and table.strip() else ""
            return ColumnRef(table_s, column.strip())

        if type_tag == "TableRef":
            name = obj.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProjectFormatError("TableRef.name must be a non-empty string")
            return TableRef(name.strip())

        if type_tag == "MeasureRef":
            name = obj.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProjectFormatError("MeasureRef.name must be a non-empty string")
            return MeasureRef(name.strip())

        if type_tag == "ParamRef":
            name = obj.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProjectFormatError("ParamRef.name must be a non-empty string")
            return ParamRef(name.strip())

        if type_tag == "CalcGroupItem" or type_tag == "CalcGroupItemRef":
            # Accept both names for compatibility (UI sends CalcGroupItem, IR uses CalcGroupItemRef)
            group = obj.get("group")
            item = obj.get("item")
            if not isinstance(group, str) or not group.strip():
                raise ProjectFormatError("CalcGroupItem.group must be a non-empty string")
            if not isinstance(item, str) or not item.strip():
                raise ProjectFormatError("CalcGroupItem.item must be a non-empty string")
            return CalcGroupItemRef(group.strip(), item.strip())

        if type_tag == "HierarchyRef":
            name = obj.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProjectFormatError("HierarchyRef.name must be a non-empty string")
            return HierarchyRef(name.strip())

        if type_tag == "Literal":
            # Allow any JSON primitive as a Literal value.
            return Literal(obj.get("value"))

        if type_tag == "SetLiteral":
            values = obj.get("values")
            if not isinstance(values, list):
                raise ProjectFormatError("SetLiteral.values must be a list")
            return SetLiteral([parse_scalar_expr(v) for v in values])

        if type_tag == "DaxFunction":
            name = obj.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProjectFormatError("DaxFunction.name must be a non-empty string")
            args_raw = obj.get("args")
            if args_raw is None:
                args: List[Expr] = []
            else:
                if not isinstance(args_raw, list):
                    raise ProjectFormatError("DaxFunction.args must be a list if provided")
                args = [parse_expr(a) for a in args_raw]
            return DaxFunction(name.strip(), args)

        raise ProjectFormatError(f"Unknown expression type: {type_tag!r}")

    raise ProjectFormatError(f"Unsupported expression JSON: {type(obj).__name__}")


def parse_scalar_expr(obj: Any) -> ScalarExpr:
    expr = parse_expr(obj)
    if not isinstance(expr, ScalarExpr):
        raise ProjectFormatError(f"Expected ScalarExpr, got {type(expr).__name__}")
    return expr


def parse_table_ref(obj: Any) -> TableRef:
    """Parse a JSON value into a TableRef.

    This is for contexts where a bare table identifier is required.
    MeasureRef must never be accepted as a table stand-in.
    """

    expr = parse_expr(obj)
    if isinstance(expr, TableRef):
        return expr
    if isinstance(expr, MeasureRef):
        raise ProjectFormatError(
            f"Bare tables must use TableRef(name); got MeasureRef({expr.name!r})"
        )
    raise ProjectFormatError(f"Expected TableRef, got {type(expr).__name__}")


@dataclass(frozen=True)
class SortSpecJson:
    expr: ScalarExpr
    direction: str


def parse_sort_list(items: Any) -> Sequence[SortSpecJson]:
    if items is None:
        return ()
    if not isinstance(items, list):
        raise ProjectFormatError("spec.sort must be a list")

    parsed: List[SortSpecJson] = []
    for i, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ProjectFormatError(f"spec.sort[{i}] must be an object")
        expr_obj = item.get("expr")
        direction = item.get("direction", "ASC")
        if not isinstance(direction, str) or direction.upper() not in ("ASC", "DESC"):
            raise ProjectFormatError("spec.sort[].direction must be 'ASC' or 'DESC'")
        parsed.append(SortSpecJson(expr=parse_scalar_expr(expr_obj), direction=direction.upper()))

    return parsed
