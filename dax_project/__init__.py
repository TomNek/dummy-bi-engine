"""Minimal on-disk project format + loader.

This package defines a stable project contract and a loader that returns:
- SemanticModel (metadata only)
- list[PageDefinition]
- list[VisualDefinition] (wraps dax_engine.planner.VisualQuerySpec)

Non-goals:
- No new DAX semantics
- No compilation/lowering changes
"""

from .model import (  # noqa: F401
    CalcItem,
    Column,
    CalculationGroup,
    CalculationItem,
    FieldParameter,
    FieldParameterOption,
    MeasureDefinition,
    PageDefinition,
    Relationship,
    SecurityOls,
    SecurityRole,
    SecurityRlsRule,
    SemanticModel,
    Table,
    VisualDefinition,
)
from .loader import load_project, invalidate_load_project_cache  # noqa: F401

from .save import save_measures, update_measure_yaml  # noqa: F401

from .introspection import (  # noqa: F401
    describe_measure,
    get_measure,
    list_columns,
    list_measures,
    list_tables,
    search_symbols,
)

from .visual_types import load_visual_type_registry  # noqa: F401
from .dbt_bridge import (  # noqa: F401
    DbtExportResult,
    DbtImportResult,
    MeasureClassification,
    classify_measure,
    classify_measures,
    export_dbt_project,
    import_dbt_project,
    write_dbt_export,
)

__all__ = [
    "CalcItem",
    "Column",
    "CalculationGroup",
    "CalculationItem",
    "FieldParameter",
    "FieldParameterOption",
    "MeasureDefinition",
    "PageDefinition",
    "Relationship",
    "SecurityOls",
    "SecurityRole",
    "SecurityRlsRule",
    "SemanticModel",
    "Table",
    "VisualDefinition",
    "load_project",
    "invalidate_load_project_cache",
    "save_measures",
    "update_measure_yaml",
    "list_tables",
    "list_columns",
    "list_measures",
    "get_measure",
    "describe_measure",
    "search_symbols",
    "load_visual_type_registry",
    "DbtExportResult",
    "DbtImportResult",
    "MeasureClassification",
    "classify_measure",
    "classify_measures",
    "export_dbt_project",
    "import_dbt_project",
    "write_dbt_export",
]
