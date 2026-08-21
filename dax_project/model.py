from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dax_engine.ir import Expr
from dax_engine.planner import VisualQuerySpec


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    source: Optional[Dict[str, Any]] = None
    # v1 calculated column support (virtual-only). When provided, column is treated as calculated.
    expression: Optional[str] = None
    is_calculated: bool = False
    description: Optional[str] = None
    folder: Optional[str] = None
    format: Optional[str] = None
    # Power BI "Sort by Column": when set, visuals sort this column using the values of another column.
    sort_by_column: Optional[str] = None


@dataclass(frozen=True)
class Table:
    name: str
    columns: List[Column]
    source: Optional[Dict[str, Any]] = None
    # v1 calculated table support (virtual-only). When provided, table is treated as calculated.
    expression: Optional[str] = None
    is_calculated: bool = False
    description: Optional[str] = None
    folder: Optional[str] = None
    # Model view: classify table as fact/dim/bridge for layout purposes.
    # None means unclassified (auto-infer or user hasn't set it yet).
    table_type: Optional[str] = None  # "fact" | "dim" | "bridge" | None
    # Phase 9: per-table storage mode. None → default ("import").
    # Valid values: "import" | "direct_query" | "direct_lake"
    storage_mode: Optional[str] = None
    power_query: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class Relationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    active: bool = True
    rel_id: str = ""
    cross_filter_direction: str = "single"  # "single" | "both"
    cardinality: Optional[str] = None


@dataclass(frozen=True)
class MeasureDefinition:
    name: str
    dax: str
    description: Optional[str] = None
    folder: Optional[str] = None
    format: Optional[str] = None


@dataclass(frozen=True)
class FieldParameterItem:
    """An item in a Field Parameter.
    
    Power BI parity: each item has a name (label) and references a column or measure.
    """
    name: str  # Display label (replaces key/label pair)
    ref: Expr  # ColumnRef or MeasureRef
    sort: Optional[int] = None
    custom_props: Optional[dict] = None  # Custom properties (e.g., locale, category)


@dataclass(frozen=True)
class FieldParameter:
    """Field Parameter (Power BI parity).
    
    A field parameter is a list of selectable fields (columns or measures).
    Selection is always single-select in Power BI. Multi-select is a slicer
    behavior, not a field parameter property.
    """
    name: str
    items: List[FieldParameterItem] = field(default_factory=list)
    default_item: Optional[str] = None  # Item name to select by default
    # Optional DAX table expression backing this parameter (for Power BI-like authoring and schema inference).
    dax: Optional[str] = None


@dataclass(frozen=True)
class WhatIfParameter:
    """What-If Parameter (Power BI parity).
    
    A numeric slider parameter used in measure calculations.
    The current value can be referenced in measures via WHATIFVALUE("name").
    """
    name: str
    min_value: float
    max_value: float
    step: float
    default_value: float
    format: Optional[str] = None


# Back-compat alias for legacy code referencing the old option shape.
@dataclass(frozen=True)
class FieldParameterOption:
    """Legacy shape - deprecated, use FieldParameterItem instead."""
    key: str
    label: str
    expr: Expr
    sort: Optional[int] = None


@dataclass(frozen=True)
class CalculationItem:
    name: str
    expression: str
    format_string: Optional[str] = None

    # Back-compat: older callsites/tests used CalcItem.key.
    @property
    def key(self) -> str:  # pragma: no cover
        return self.name


@dataclass(frozen=True)
class CalcItem:
    """Legacy Calculation Item shape (v0).

    New code should use CalculationItem (name/expression).
    Loader supports reading this legacy YAML shape for backward compatibility.
    """

    key: str
    label: str
    template: str


@dataclass(frozen=True)
class CalculationGroup:
    name: str
    precedence: int = 0
    items: List[CalculationItem] = field(default_factory=list)


@dataclass(frozen=True)
class SecurityRlsRule:
    table: str
    filter: str


@dataclass(frozen=True)
class SecurityOls:
    # Object-level security (visibility). Names are compared case-insensitively.
    tables: List[str] = field(default_factory=list)
    measures: List[str] = field(default_factory=list)
    # Mapping: table -> hidden column names
    columns: Dict[str, List[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class SecurityRole:
    name: str
    rls: List[SecurityRlsRule] = field(default_factory=list)
    ols: SecurityOls = field(default_factory=SecurityOls)


@dataclass(frozen=True)
class HierarchyLevel:
    """A single level in a hierarchy (maps to a column in the hierarchy's table)."""
    column: str       # Column name in the table
    name: str         # Display name (defaults to column name if not provided)


@dataclass(frozen=True)
class Hierarchy:
    """An explicit hierarchy definition (Phase 4.1).

    A hierarchy is a named, ordered list of levels (columns from a single table)
    that defines a natural drill path. E.g., Year → Month → Date.
    """
    name: str
    table: str
    levels: List[HierarchyLevel] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticModel:
    tables: List[Table]
    relationships: List[Relationship]
    measures: List[MeasureDefinition]
    field_parameters: Dict[str, FieldParameter] = field(default_factory=dict)
    calculation_groups: Dict[str, CalculationGroup] = field(default_factory=dict)
    what_if_parameters: Dict[str, WhatIfParameter] = field(default_factory=dict)
    # Optional security config (Phase 1.3).
    security_roles: Dict[str, SecurityRole] = field(default_factory=dict)
    default_role: Optional[str] = None
    # Hierarchies (Phase 4.1).
    hierarchies: Dict[str, Hierarchy] = field(default_factory=dict)


@dataclass(frozen=True)
class PageDefinition:
    id: str
    title: str
    order: Optional[int] = None
    page_type: Optional[str] = None
    placeholder_containers: List[str] = field(default_factory=list)
    drillthrough: bool = False
    drillthrough_columns: List[Dict[str, str]] = field(default_factory=list)
    hidden: bool = False


@dataclass(frozen=True)
class VisualDefinition:
    id: str
    title: str
    type: str
    spec: VisualQuerySpec
    # Pages (Power BI-style). Defaults to "page1" for backward compatibility.
    page_id: str = "page1"
    param_values: Dict[str, str] = field(default_factory=dict)
    calc_groups: Dict[str, str] = field(default_factory=dict)
    # Optional canvas/runtime fields (v1): persisted in reports/visuals/<id>.json.
    layout: Optional[Dict[str, float]] = None
    encodings: Dict[str, Any] = field(default_factory=dict)
    advanced_plotly_patch: Optional[Dict[str, Any]] = None
