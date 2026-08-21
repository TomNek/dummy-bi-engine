from __future__ import annotations

from typing import cast

from .ast import (
    AstNode,
    BinaryOpNode,
    ColumnRefNode,
    FuncCallNode,
    LiteralNode,
    MeasureRefNode,
    ParenNode,
    UnaryOpNode,
    SetLiteralNode,
    VarRefNode,
    LetNode,
)

# Mapper imports the existing compiler IR types (this is the AST → IR layer).
from dax_compiler import (
    ColumnRef,
    DaxBinaryOp,
    DaxFunction,
    Expr,
    Literal,
    MeasureRef,
    SelectedMeasureRef,
    TableRef,
    ScalarExpr,
    WhatIfRef,
)
from dax_compiler import SetLiteral as IRSetLiteral


def ast_to_ir(
    node: AstNode,
    env: dict[str, ScalarExpr] | None = None,
    *,
    allow_selected_measure: bool = False,
) -> Expr:
    if isinstance(node, ParenNode):
        return ast_to_ir(node.inner, env, allow_selected_measure=allow_selected_measure)

    if isinstance(node, LiteralNode):
        return Literal(node.value)

    if isinstance(node, ColumnRefNode):
        return ColumnRef(node.table, node.column)

    if isinstance(node, MeasureRefNode):
        return MeasureRef(node.name)

    if isinstance(node, FuncCallNode):
        fn = str(node.name or "").strip().upper()
        if fn == "SELECTEDMEASURE":
            if node.args:
                raise ValueError("SELECTEDMEASURE() does not take arguments")
            if not allow_selected_measure:
                raise ValueError("SELECTEDMEASURE() is only allowed inside calculation item expressions")
            return SelectedMeasureRef()

        if fn == "WHATIFVALUE":
            # WHATIFVALUE("ParamName") returns the current selection for a What-If parameter.
            if len(node.args) != 1:
                raise ValueError("WHATIFVALUE() requires exactly one argument (parameter name)")
            arg = node.args[0]
            if not isinstance(arg, LiteralNode) or not isinstance(arg.value, str):
                raise ValueError("WHATIFVALUE() argument must be a string literal (parameter name)")
            param_name = str(arg.value).strip()
            if not param_name:
                raise ValueError("WHATIFVALUE() argument must be a non-empty string")
            return WhatIfRef(param_name)

        return DaxFunction(
            node.name,
            [ast_to_ir(a, env, allow_selected_measure=allow_selected_measure) for a in node.args],
        )

    if isinstance(node, UnaryOpNode):
        inner = ast_to_ir(node.expr, env, allow_selected_measure=allow_selected_measure)
        if node.op == "-":
            return DaxBinaryOp("-", Literal(0), cast(ScalarExpr, inner))
        if node.op.upper() == "NOT":
            return DaxFunction("NOT", [inner])
        return DaxFunction(f"DAX_UNARY_{node.op}", [inner])

    if isinstance(node, BinaryOpNode):
        left = cast(ScalarExpr, ast_to_ir(node.left, env, allow_selected_measure=allow_selected_measure))
        right_ir = ast_to_ir(node.right, env, allow_selected_measure=allow_selected_measure)
        # Allow IN with set literals
        if node.op.upper() == "IN" and isinstance(node.right, SetLiteralNode):
            values = [cast(ScalarExpr, ast_to_ir(v, env, allow_selected_measure=allow_selected_measure)) for v in node.right.values]
            right = IRSetLiteral([cast(Literal, v) for v in values])
        else:
            # IN can take a non-scalar RHS (e.g., VALUES(Table[Col]) / DISTINCT(Table[Col])).
            # Keep it as a generic Expr so the compiler can lower it as a subquery.
            right = right_ir
        op = node.op
        if op == "&&":
            return DaxFunction("AND", [left, right])
        if op == "||":
            return DaxFunction("OR", [left, right])
        if op == "&":
            # DAX string concatenation.
            return DaxBinaryOp("||", left, cast(ScalarExpr, right))
        return DaxBinaryOp(op, left, right)

    if isinstance(node, SetLiteralNode):
        # Standalone set literal (rare); represent as IRSetLiteral
        values = [cast(Literal, ast_to_ir(v, env, allow_selected_measure=allow_selected_measure)) for v in node.values]
        return IRSetLiteral(values)

    if isinstance(node, VarRefNode):
        if env is None or node.name.upper() not in env:
            # Treat unknown var refs as base table refs.
            # DAX measure references are bracketed (e.g. [Total]) and are
            # represented by MeasureRefNode, not VarRefNode.
            return TableRef(node.name)
        return env[node.name.upper()]

    if isinstance(node, LetNode):
        # Inline VAR bindings into body
        new_env: dict[str, ScalarExpr] = {}
        if env:
            new_env.update(env)
        for (name, expr) in node.bindings:
            ir_expr = cast(ScalarExpr, ast_to_ir(expr, new_env, allow_selected_measure=allow_selected_measure))
            new_env[name.upper()] = ir_expr
        return ast_to_ir(node.body, new_env, allow_selected_measure=allow_selected_measure)

    raise TypeError(f"Unsupported AST node: {type(node).__name__}")
