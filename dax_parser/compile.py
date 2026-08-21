from __future__ import annotations

from typing import Optional

from .ir_mapper import ast_to_ir
from .parser import parse_expression

import dax_compiler


def compile_dax_expression_to_sql(dax_text: str, ctx: Optional[dax_compiler.Context] = None) -> str:
    """End-to-end helper: DAX expression string -> DuckDB SQL query.

    This keeps the existing compiler engine untouched: it only constructs IR and
    delegates to dax_compiler for context/measure compilation.
    """

    if ctx is None:
        ctx = dax_compiler.Context()
    else:
        # Capture the provided entry context as "outer" selections once.
        ctx = ctx.set_outer_from_current()

    ast = parse_expression(dax_text)
    ir = ast_to_ir(ast)

    # Context functions (e.g., CALCULATE) compile as full queries.
    if isinstance(ir, dax_compiler.DaxFunction):
        spec = dax_compiler.registry.get(ir.fn.upper())
        if spec is not None and spec.kind == "context":
            return dax_compiler.compile_context_function(ir, ctx)

    # Otherwise treat it as a scalar measure expression.
    return dax_compiler.compile_measure(ir, ctx)  # type: ignore[arg-type]
