"""Visual query planner.

This package composes existing IR nodes (no SQL parsing, no DAX query grammar)
and reuses the existing compiler to produce DuckDB SQL suitable for visuals.
"""

from .visual_planner import (
    SortSpec,
    VisualQuerySpec,
    plan_card_query,
    plan_visual_query,
    resolve_facade_column_refs,
    resolve_params,
)

from .matrix_planner import (
    AxisItem,
    CellValue,
    ColHeaderCell,
    ExpandedPath,
    MatrixResult,
    MatrixSpec,
    MatrixSortSpec,
    MeasureColumn,
    RowNode,
    execute_matrix_query,
    matrix_spec_from_visual,
    plan_matrix_query,
)

from .tablix import (
    CellRole,
    TablixCell,
    TablixColDef,
    TablixPlan,
    TablixRegion,
    TablixRowDef,
)

from .tablix_compiler import (
    compile_matrix_to_tablix,
)

__all__ = [
    "SortSpec",
    "VisualQuerySpec",
    "plan_card_query",
    "plan_visual_query",
    "resolve_facade_column_refs",
    "resolve_params",
    # Matrix planner
    "AxisItem",
    "CellValue",
    "ColHeaderCell",
    "ExpandedPath",
    "MatrixResult",
    "MatrixSpec",
    "MatrixSortSpec",
    "MeasureColumn",
    "RowNode",
    "execute_matrix_query",
    "matrix_spec_from_visual",
    "plan_matrix_query",
    # Tablix layout
    "CellRole",
    "TablixCell",
    "TablixColDef",
    "TablixPlan",
    "TablixRegion",
    "TablixRowDef",
    "compile_matrix_to_tablix",
]
