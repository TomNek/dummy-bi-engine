"""SSRS-style Tablix layout IR.

This module defines the TablixPlan layout abstraction that represents
an SSRS-style tablix grid with:
- Row groups (hierarchical)
- Column groups (multi-level headers)
- Header bands (custom row/column header extensions)
- Body cells
- Subtotal bands
- Grand total bands
- Expand/collapse metadata
- Static measure columns (row-scope measures outside pivot body)

CRITICAL: This is a LAYOUT model, not a query model.
All values come from MatrixResult - no recomputation allowed.

Non-goals:
- No value recomputation
- No filter invention
- No key path changes
- No pagination/page breaks
- No conditional formatting
- No business logic (MTD/YTD/FY)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
import uuid


# =============================================================================
# Enterprise Tablix Imports (measure blocks, header bands, cell rules)
# =============================================================================

try:
    from dax_engine.planner.tablix_enterprise import (
        MeasureScope,
        ResolvedMeasure,
        resolve_unified_measures,
        measures_for_column_block,
        measures_for_row_block,
        RowHeaderBandColumn,
        ColHeaderBandRow,
        ColumnMeasureBlock,
        RowMeasureBlock,
        CellFormattingStyle,
        CellFormattingRule,
    )
    _HAS_ENTERPRISE_TABLIX = True
except ImportError:
    _HAS_ENTERPRISE_TABLIX = False

    # ---- Minimal stubs so community builds can still load/render ----
    class MeasureScope:  # type: ignore[no-redef]
        def __init__(self, **kw: Any) -> None:
            pass

    class ResolvedMeasure:  # type: ignore[no-redef]
        def __init__(self, **kw: Any) -> None:
            pass

    def resolve_unified_measures(*a: Any, **kw: Any) -> list:  # type: ignore[no-redef]
        return []

    def measures_for_column_block(*a: Any, **kw: Any) -> list:  # type: ignore[no-redef]
        return []

    def measures_for_row_block(*a: Any, **kw: Any) -> list:  # type: ignore[no-redef]
        return []

    class RowHeaderBandColumn:  # type: ignore[no-redef]
        @classmethod
        def from_dict(cls, data: Any) -> "RowHeaderBandColumn":
            return cls()
        def to_dict(self) -> dict:
            return {}

    class ColHeaderBandRow:  # type: ignore[no-redef]
        @classmethod
        def from_dict(cls, data: Any) -> "ColHeaderBandRow":
            return cls()
        def to_dict(self) -> dict:
            return {}

    class ColumnMeasureBlock:  # type: ignore[no-redef]
        id: Optional[str] = None
        measure_id: str = ""
        measure_mode: str = "explicit"
        placement: str = "right"
        column_fields: list = []  # noqa: RUF012
        applies_to: list = []  # noqa: RUF012
        is_grouped: bool = False

        @classmethod
        def from_dict(cls, data: Any) -> "ColumnMeasureBlock":
            return cls()
        def to_dict(self) -> dict:
            return {}
        @classmethod
        def from_static_measure_column(cls, smc: "StaticMeasureColumn") -> "ColumnMeasureBlock":
            return cls()

    class RowMeasureBlock:  # type: ignore[no-redef]
        id: Optional[str] = None
        measure_id: str = ""
        measure_mode: str = "explicit"
        placement: str = "bottom"
        row_fields: list = []  # noqa: RUF012

        @classmethod
        def from_dict(cls, data: Any) -> "RowMeasureBlock":
            return cls()
        def to_dict(self) -> dict:
            return {}

    class CellFormattingStyle:  # type: ignore[no-redef]
        @classmethod
        def from_dict(cls, data: Any) -> "CellFormattingStyle":
            return cls()
        def to_dict(self) -> dict:
            return {}

    class CellFormattingRule:  # type: ignore[no-redef]
        @classmethod
        def from_dict(cls, data: Any) -> "CellFormattingRule":
            return cls()
        def to_dict(self) -> dict:
            return {}
        def matches_cell(self, *a: Any, **kw: Any) -> bool:
            return False


# Keep legacy stub reference so enterprise module can import StaticMeasureColumn
# without circular dependency -- the actual class is defined below.


# =============================================================================
# Unified Measure Resolution -- REMOVED (now in tablix_enterprise.py)
# StaticMeasureColumn kept here for backwards compat (community).
# =============================================================================
# Static Measure Column Definition (Legacy - Kept for Backwards Compatibility)
# =============================================================================


@dataclass
class StaticMeasureColumn:
    """Definition of a static (non-pivoted) measure column.
    
    DEPRECATED: Use ColumnMeasureBlock instead. This class is kept for
    backwards compatibility only. Old configs with staticMeasureColumns
    will be auto-converted to column_measure_blocks on load.
    
    Static measure columns are evaluated per row context only, NOT pivoted
    by column groups. They render as regular tablix body columns and can
    appear to the left or right of the pivoted matrix body.
    
    Examples:
    - KPI columns next to row headers
    - Revenue | Cost | Margin % columns (before pivoted year data)
    - Variance columns (after pivoted data)
    
    This is a LAYOUT concern only - values come from existing MatrixResult.
    
    Row Applicability (SSRS parity):
    - Static columns can be configured to appear only on specific row types
    - Supported row types: leaf, subtotal, group, grand_total
    - Default: ["leaf"] (backward compatible)
    - If a row type is not in applies_to, the cell is structurally absent (not empty)
    """
    # Measure identifier (must exist in values)
    measure_id: str
    
    # Display label (optional, defaults to measure name)
    label: Optional[str] = None
    
    # Placement relative to pivot body
    placement: Literal["left", "right"] = "right"
    
    # Column width (optional)
    width: Optional[int] = None
    
    # Row types where this column appears (SSRS parity)
    # Supported values: "leaf", "subtotal", "group", "grand_total"
    # Default: ["leaf"] - column appears only on leaf (detail) rows
    applies_to: List[str] = field(default_factory=lambda: ["leaf"])
    
    # Valid row type values
    VALID_ROW_TYPES = frozenset(["leaf", "subtotal", "group", "grand_total"])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        d: Dict[str, Any] = {
            "measureId": self.measure_id,
            "placement": self.placement,
        }
        if self.label is not None:
            d["label"] = self.label
        if self.width is not None:
            d["width"] = self.width
        # Only include appliesTo if not the "all row types" default (backward compat)
        all_row_types = ["leaf", "group", "subtotal", "grand_total"]
        if sorted(self.applies_to) != sorted(all_row_types):
            d["appliesTo"] = self.applies_to
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StaticMeasureColumn":
        """Create from JSON dict."""
        # Parse applies_to
        # BACKWARD COMPATIBILITY: if appliesTo is not set (legacy columns), 
        # default to ALL row types (preserves pre-SSRS-parity behavior)
        applies_to_raw = data.get("appliesTo") or data.get("applies_to")
        if applies_to_raw is None:
            # Legacy columns show on all row types
            applies_to = ["leaf", "group", "subtotal", "grand_total"]
        elif isinstance(applies_to_raw, list):
            # Validate and filter to only valid row types
            applies_to = [rt for rt in applies_to_raw if rt in cls.VALID_ROW_TYPES]
            if not applies_to:
                applies_to = ["leaf", "group", "subtotal", "grand_total"]  # Fallback if all invalid
        else:
            applies_to = ["leaf", "group", "subtotal", "grand_total"]
        
        return cls(
            measure_id=data.get("measureId") or data.get("measure_id", ""),
            label=data.get("label"),
            placement=data.get("placement", "right"),
            width=data.get("width"),
            applies_to=applies_to,
        )


# =============================================================================
# ColumnMeasureBlock, RowMeasureBlock, CellFormattingStyle, CellFormattingRule
# -- REMOVED (now in tablix_enterprise.py, imported via try/except above)
# =============================================================================


# =============================================================================
# Tablix Properties (SSRS-style layout settings)
# =============================================================================


def _parse_level_dict(raw: Any) -> Dict[int, bool]:
    """Convert a JSON-style level dict (string keys) to Dict[int, bool].

    Accepts ``{"0": false, "1": true}`` (from JSON) or ``{0: False, 1: True}``
    (already parsed). Returns an empty dict for falsy / non-dict input.
    """
    if not raw or not isinstance(raw, dict):
        return {}
    return {int(k): bool(v) for k, v in raw.items()}


@dataclass
class TablixProperties:
    """SSRS-style layout properties for Tablix rendering.
    
    These properties control visual appearance and layout behavior without
    affecting query semantics or value computation.
    
    Defaults are chosen to reproduce the current UI output exactly.
    
    MEASURE BLOCKS:
    - column_measure_blocks: Column-oriented measure blocks (replaces static_measure_columns)
    - row_measure_blocks: Row-oriented measure blocks (new)
    
    For backwards compatibility, static_measure_columns is still supported on load
    and auto-converted to column_measure_blocks. On save, only column_measure_blocks
    is serialized (unless there are legacy columns that haven't been edited).
    """
    # Header repetition (SSRS: RepeatRowHeaders, RepeatColumnHeaders)
    # Currently maps to sticky header behavior
    repeat_row_headers: bool = True
    repeat_column_headers: bool = True
    
    # Gridlines style
    gridlines: Literal["none", "light", "full"] = "light"
    
    # Density (affects row height and padding)
    density: Literal["compact", "normal"] = "normal"
    
    # Row header width mode
    row_header_width_mode: Literal["auto", "fixed"] = "auto"

    # Power BI column width preview mode.  `grow_to_fit` is the historical
    # Dummy BI behavior: columns size from their defaults/imported widths and
    # the table fills the available visual width.
    column_width_mode: Literal["fit_to_content", "grow_to_fit", "fixed"] = "grow_to_fit"
    more_granular_column_widths: bool = False
    mobile_column_widths: Dict[str, float] = field(default_factory=dict)
    
    # Autofit controls: when enabled, columns/rows size to content; when disabled, use defaults
    autofit_columns: bool = True
    autofit_rows: bool = True
    
    # Snap columns to fit: when enabled, columns snap to fill container; when disabled, free resize
    snap_columns_to_fit: bool = True
    
    # Default pixel sizes (used when autofit is disabled)
    default_column_width: int = 100
    default_row_height: int = 32
    
    # Column header background color (from PBI import or user setting)
    column_header_back_color: Optional[str] = None
    
    # Initial column widths from PBI import (key: "Table.Field" → width in px)
    initial_column_widths: Dict[str, float] = field(default_factory=dict)
    
    # Subtotal visibility (hooks into existing subtotal option)
    show_subtotals: bool = True
    show_col_subtotals: bool = True
    
    # Per-level subtotal visibility (key = hierarchy level index, value = enabled)
    # When missing or empty, all levels follow show_subtotals. When present,
    # individual levels can be disabled even when show_subtotals is True.
    row_subtotal_levels: Dict[int, bool] = field(default_factory=dict)
    col_subtotal_levels: Dict[int, bool] = field(default_factory=dict)
    
    # Subtotal placement relative to children
    subtotal_placement: Literal["after_children", "before_children"] = "after_children"
    
    # Grand total visibility
    grand_total_visibility: Literal["both", "rows", "cols", "none"] = "both"
    
    # Suppress blank columns: when True, columns where ALL data values are
    # null/blank are removed from the rendered tablix (applies to both base
    # matrix columns and column-measure-block columns).
    suppress_blank_cols: bool = False
    
    # Static measure columns (LEGACY - kept for backwards compatibility)
    # Use column_measure_blocks instead
    static_measure_columns: List["StaticMeasureColumn"] = field(default_factory=list)
    
    # Column Measure Blocks (replaces static_measure_columns)
    # Each block can be simple (no grouping) or grouped (with column_fields)
    column_measure_blocks: List["ColumnMeasureBlock"] = field(default_factory=list)
    
    # Row Measure Blocks (new)
    # Each block can be simple (no grouping) or grouped (with row_fields)
    row_measure_blocks: List["RowMeasureBlock"] = field(default_factory=list)
    
    # Row header band columns (SSRS-style extra columns in row header region)
    row_header_bands: List["RowHeaderBandColumn"] = field(default_factory=list)
    
    # Column header band rows (SSRS-style extra rows in column header region)
    col_header_bands: List["ColHeaderBandRow"] = field(default_factory=list)
    
    # Cell formatting rules (declarative, match-based formatting)
    # Applied in order; later rules override earlier ones; cell overrides (designCells) beat rules
    cell_rules: List["CellFormattingRule"] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        d: Dict[str, Any] = {
            "repeatRowHeaders": self.repeat_row_headers,
            "repeatColumnHeaders": self.repeat_column_headers,
            "gridlines": self.gridlines,
            "density": self.density,
            "rowHeaderWidthMode": self.row_header_width_mode,
            "columnWidthMode": self.column_width_mode,
            "moreGranularColumnWidths": self.more_granular_column_widths,
            "mobileColumnWidths": self.mobile_column_widths if self.mobile_column_widths else {},
            "autofitColumns": self.autofit_columns,
            "autofitRows": self.autofit_rows,
            "snapColumnsToFit": self.snap_columns_to_fit,
            "defaultColumnWidth": self.default_column_width,
            "defaultRowHeight": self.default_row_height,
            "columnHeaderBackColor": self.column_header_back_color,
            "initialColumnWidths": self.initial_column_widths if self.initial_column_widths else {},
            "showSubtotals": self.show_subtotals,
            "showColSubtotals": self.show_col_subtotals,
            "rowSubtotalLevels": {str(k): v for k, v in self.row_subtotal_levels.items()} if self.row_subtotal_levels else {},
            "colSubtotalLevels": {str(k): v for k, v in self.col_subtotal_levels.items()} if self.col_subtotal_levels else {},
            "subtotalPlacement": self.subtotal_placement,
            "grandTotalVisibility": self.grand_total_visibility,
            "suppressBlankCols": self.suppress_blank_cols,
        }
        # Serialize column measure blocks (new format)
        if self.column_measure_blocks:
            d["columnMeasureBlocks"] = [cmb.to_dict() for cmb in self.column_measure_blocks]
        # Also include legacy static_measure_columns for backwards compat
        # (only if no column_measure_blocks and we have legacy columns)
        elif self.static_measure_columns:
            d["staticMeasureColumns"] = [smc.to_dict() for smc in self.static_measure_columns]
        # Serialize row measure blocks
        if self.row_measure_blocks:
            d["rowMeasureBlocks"] = [rmb.to_dict() for rmb in self.row_measure_blocks]
        if self.row_header_bands:
            d["rowHeaderBands"] = [rhb.to_dict() for rhb in self.row_header_bands]
        if self.col_header_bands:
            d["colHeaderBands"] = [chb.to_dict() for chb in self.col_header_bands]
        if self.cell_rules:
            d["cellRules"] = [rule.to_dict() for rule in self.cell_rules]
        return d
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TablixProperties":
        """Create from JSON dict with defaults for missing fields.
        
        Accepts both camelCase (JSON/JS) and snake_case (Python) keys.
        
        BACKWARDS COMPATIBILITY:
        - If staticMeasureColumns is present but columnMeasureBlocks is not,
          auto-convert to column_measure_blocks
        """
        if not data:
            return cls()
        
        # Helper to get value from snake_case or camelCase key.
        # snake_case is treated as canonical when both exist.
        def get_val(camel: str, snake: str, default: Any) -> Any:
            if snake in data:
                return data[snake]
            if camel in data:
                return data[camel]
            return default

        def normalize_column_width_mode(raw: Any, autofit: bool, snap: bool) -> str:
            text = str(raw or "").strip().lower()
            compact = "".join(ch for ch in text if ch.isalpha())
            if "fixed" in compact:
                return "fixed"
            if "grow" in compact or "snap" in compact:
                return "grow_to_fit"
            if "fit" in compact or "auto" in compact:
                return "fit_to_content"
            if autofit is False:
                return "fixed"
            if snap is not False:
                return "grow_to_fit"
            return "fit_to_content"

        def parse_positive_float(raw: Any) -> Optional[float]:
            if isinstance(raw, (int, float)):
                value = float(raw)
            elif isinstance(raw, str):
                try:
                    value = float(raw.rstrip("Dd"))
                except ValueError:
                    return None
            else:
                return None
            return value if value > 0 else None

        def get_merged_level_dict(camel: str, snake: str) -> Dict[Any, Any]:
            camel_raw = data.get(camel)
            snake_raw = data.get(snake)
            camel_dict = camel_raw if isinstance(camel_raw, dict) else {}
            snake_dict = snake_raw if isinstance(snake_raw, dict) else {}
            if camel in data and snake in data:
                merged = dict(camel_dict)
                merged.update(snake_dict)
                return merged
            if snake in data:
                return snake_dict
            if camel in data:
                return camel_dict
            return {}
        
        # Parse column measure blocks (new format)
        col_blocks_raw = get_val("columnMeasureBlocks", "column_measure_blocks", [])
        column_measure_blocks = [ColumnMeasureBlock.from_dict(cmb) for cmb in (col_blocks_raw or [])]
        
        # Parse legacy static measure columns for backwards compatibility
        static_cols_raw = get_val("staticMeasureColumns", "static_measure_columns", [])
        static_cols = [StaticMeasureColumn.from_dict(sc) for sc in (static_cols_raw or [])]
        
        # AUTO-CONVERT: If we have legacy columns but no new blocks, convert them
        if static_cols and not column_measure_blocks:
            column_measure_blocks = [
                ColumnMeasureBlock.from_static_measure_column(smc)
                for smc in static_cols
            ]
            # Clear static_cols after conversion (we now use column_measure_blocks)
            static_cols = []
        
        # Parse row measure blocks (new format)
        row_blocks_raw = get_val("rowMeasureBlocks", "row_measure_blocks", [])
        row_measure_blocks = [RowMeasureBlock.from_dict(rmb) for rmb in (row_blocks_raw or [])]
        
        # Parse row header band columns
        # Skip user-defined bands with 'spans' property (rendered client-side)
        row_header_bands_raw = get_val("rowHeaderBands", "row_header_bands", [])
        row_header_bands = [
            RowHeaderBandColumn.from_dict(rhb) 
            for rhb in (row_header_bands_raw or [])
            if not (isinstance(rhb, dict) and rhb.get("spans"))
        ]
        
        # Parse column header band rows
        # Skip user-defined bands with 'spans' property (rendered client-side)
        col_header_bands_raw = get_val("colHeaderBands", "col_header_bands", [])
        col_header_bands_prop = [
            ColHeaderBandRow.from_dict(chb) 
            for chb in (col_header_bands_raw or [])
            if not (isinstance(chb, dict) and chb.get("spans"))
        ]
        
        # Parse cell formatting rules
        cell_rules_raw = get_val("cellRules", "cell_rules", [])
        cell_rules = [CellFormattingRule.from_dict(rule) for rule in (cell_rules_raw or [])]
        
        autofit_columns = get_val("autofitColumns", "autofit_columns", True)
        snap_columns_to_fit = get_val("snapColumnsToFit", "snap_columns_to_fit", True)
        column_width_mode = normalize_column_width_mode(
            get_val("columnWidthMode", "column_width_mode", None),
            bool(autofit_columns),
            bool(snap_columns_to_fit),
        )

        return cls(
            repeat_row_headers=get_val("repeatRowHeaders", "repeat_row_headers", True),
            repeat_column_headers=get_val("repeatColumnHeaders", "repeat_column_headers", True),
            gridlines=get_val("gridlines", "gridlines", "light"),
            density=get_val("density", "density", "normal"),
            row_header_width_mode=get_val("rowHeaderWidthMode", "row_header_width_mode", "auto"),
            column_width_mode=column_width_mode,
            more_granular_column_widths=bool(get_val("moreGranularColumnWidths", "more_granular_column_widths", False)),
            mobile_column_widths={
                str(k): parsed
                for k, v in (get_val("mobileColumnWidths", "mobile_column_widths", {}) or {}).items()
                for parsed in [parse_positive_float(v)]
                if parsed is not None
            },
            autofit_columns=autofit_columns,
            autofit_rows=get_val("autofitRows", "autofit_rows", True),
            snap_columns_to_fit=snap_columns_to_fit,
            default_column_width=get_val("defaultColumnWidth", "default_column_width", 100),
            default_row_height=get_val("defaultRowHeight", "default_row_height", 32),
            column_header_back_color=get_val("columnHeaderBackColor", "column_header_back_color", None),
            initial_column_widths={
                str(k): parsed
                for k, v in (get_val("initialColumnWidths", "initial_column_widths", {}) or {}).items()
                for parsed in [parse_positive_float(v)]
                if parsed is not None
            },
            show_subtotals=get_val("showSubtotals", "show_subtotals", True),
            show_col_subtotals=get_val("showColSubtotals", "show_col_subtotals", True),
            row_subtotal_levels=_parse_level_dict(get_merged_level_dict("rowSubtotalLevels", "row_subtotal_levels")),
            col_subtotal_levels=_parse_level_dict(get_merged_level_dict("colSubtotalLevels", "col_subtotal_levels")),
            subtotal_placement=get_val("subtotalPlacement", "subtotal_placement", "after_children"),
            grand_total_visibility=get_val("grandTotalVisibility", "grand_total_visibility", "both"),
            suppress_blank_cols=get_val("suppressBlankCols", "suppress_blank_cols", False),
            static_measure_columns=static_cols,
            column_measure_blocks=column_measure_blocks,
            row_measure_blocks=row_measure_blocks,
            row_header_bands=row_header_bands,
            col_header_bands=col_header_bands_prop,
            cell_rules=cell_rules,
        )


# =============================================================================
# Tablix Cell Roles
# =============================================================================


class CellRole(str, Enum):
    """Semantic role of a tablix cell.
    
    Each cell must know exactly what it represents.
    """
    CORNER = "corner"              # Top-left corner region
    ROW_HEADER = "row_header"      # Row axis header label
    ROW_GROUP = "row_group"        # Row group header (expandable)
    COL_HEADER = "col_header"      # Column axis header label
    COL_GROUP = "col_group"        # Column group header
    DETAIL = "detail"              # Data cell (leaf row Ã— leaf column)
    SUBTOTAL = "subtotal"          # Subtotal cell (row or column)
    GRAND_TOTAL = "grand_total"    # Grand total cell
    ROW_HEADER_BAND = "row_header_band"  # Row header band cell (extra column)
    COL_HEADER_BAND = "col_header_band"  # Column header band cell (extra row)
    ROW_BLOCK = "row_block"        # Row measure block cell (extra row)


# =============================================================================
# Tablix Cells
# =============================================================================


@dataclass
class TablixCell:
    """A single cell in the tablix grid.
    
    Each cell knows:
    - Its semantic role
    - Its row/col position in the grid
    - Its span (for merged cells)
    - Its semantic path (row path + col path)
    - Whether it's interactive
    - Whether it toggles expansion
    - Its display value
    """
    # Grid position (0-indexed, row-major)
    row: int
    col: int
    
    # Semantic role
    role: CellRole
    
    # Span for merged cells (default 1Ã—1)
    row_span: int = 1
    col_span: int = 1
    
    # Semantic paths (for interaction/binding)
    row_path: Tuple[str, ...] = field(default_factory=tuple)  # e.g., ("Bikes", "Mountain")
    col_path: Tuple[str, ...] = field(default_factory=tuple)  # e.g., ("2023-01-20",)
    
    # Keys (for backend lookup)
    row_key: Optional[str] = None  # e.g., "Bikes__Mountain"
    col_key: Optional[str] = None  # e.g., "2023-01-20"
    
    # Display content
    value: Any = None
    formatted: Optional[str] = None
    label: Optional[str] = None
    
    # Hierarchy level (for row headers)
    level: int = 0
    indent: int = 0
    
    # Expand/collapse metadata (for row group headers only)
    is_expandable: bool = False
    is_expanded: bool = False
    
    # Semantic flags
    is_subtotal: bool = False
    is_grand_total: bool = False
    is_interactive: bool = True
    
    # Measure info (for value cells)
    measure_name: Optional[str] = None
    format_string: Optional[str] = None

    # Row block metadata (optional)
    row_block_index: Optional[int] = None
    
    # Column block metadata (optional, for overlap region cells)
    col_block_index: Optional[int] = None
    
    # Bar spec (for IBCS bars-in-cells)
    bar_spec: Optional[Dict[str, Any]] = None

    # Conditional formatting (PBI: fontColor, backColor, icon, dataBars)
    cond_fmt: Optional[Dict[str, Any]] = None
    
    # Breaker flag (for blank mode blocks)
    # Breaker cells are transparent with no borders, used as visual separators
    is_breaker: bool = False
    
    # Rotate flag (for row header band columns): render text vertically
    rotate: bool = False

    # Base-mode block flag: True for CMB/RMB cells in "base" or "base_calc" mode.
    # These blocks replicate base matrix measures without adding extra columns/rows,
    # so they should be treated as grand-total-equivalent in coloring.
    is_base_block: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        d: Dict[str, Any] = {
            "row": self.row,
            "col": self.col,
            "role": self.role.value,
        }
        if self.row_span != 1:
            d["rowSpan"] = self.row_span
        if self.col_span != 1:
            d["colSpan"] = self.col_span
        if self.row_path:
            d["rowPath"] = list(self.row_path)
        if self.col_path:
            d["colPath"] = list(self.col_path)
        if self.row_key is not None:
            d["rowKey"] = self.row_key
        if self.col_key is not None:
            d["colKey"] = self.col_key
        if self.value is not None:
            d["value"] = self.value
        if self.formatted is not None:
            d["formatted"] = self.formatted
        if self.label is not None:
            d["label"] = self.label
        # Always serialize level (even 0) so the frontend can distinguish
        # level-0 rows from rows with no level info at all.
        d["level"] = self.level
        if self.indent != 0:
            d["indent"] = self.indent
        if self.is_expandable:
            d["isExpandable"] = True
        if self.is_expanded:
            d["isExpanded"] = True
        if self.is_subtotal:
            d["isSubtotal"] = True
        if self.is_grand_total:
            d["isGrandTotal"] = True
        if not self.is_interactive:
            d["isInteractive"] = False
        if self.measure_name is not None:
            d["measureName"] = self.measure_name
        if self.format_string is not None:
            d["formatString"] = self.format_string
        if self.row_block_index is not None:
            d["rowBlockIndex"] = self.row_block_index
        if self.col_block_index is not None:
            d["colBlockIndex"] = self.col_block_index
        if self.bar_spec is not None:
            d["barSpec"] = self.bar_spec
        if self.cond_fmt is not None:
            d["condFmt"] = self.cond_fmt
        if self.is_breaker:
            d["isBreaker"] = True
        if self.rotate:
            d["rotate"] = True
        if self.is_base_block:
            d["isBaseBlock"] = True
        return d


# =============================================================================


@dataclass
class TablixRegion:
    """A rectangular region in the tablix grid.
    
    Regions define the semantic boundaries of the grid.
    """
    # Grid boundaries (0-indexed, inclusive)
    start_row: int
    end_row: int
    start_col: int
    end_col: int
    
    # Region type
    region_type: Literal["corner", "col_headers", "row_headers", "body"]
    
    def width(self) -> int:
        return self.end_col - self.start_col + 1
    
    def height(self) -> int:
        return self.end_row - self.start_row + 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "startRow": self.start_row,
            "endRow": self.end_row,
            "startCol": self.start_col,
            "endCol": self.end_col,
            "type": self.region_type,
        }


# =============================================================================
# Tablix Row/Column Definitions
# =============================================================================


@dataclass
class TablixRowDef:
    """Definition of a row in the tablix grid."""
    index: int
    key: Optional[str] = None
    level: int = 0
    is_subtotal: bool = False
    is_grand_total: bool = False
    is_header_row: bool = False  # True for column header rows
    is_header_band_row: bool = False  # True for column header band rows
    is_row_block: bool = False  # True for row measure block rows
    measure_name: Optional[str] = None  # Measure name for row block rows
    
    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"index": self.index}
        if self.key is not None:
            d["key"] = self.key
        if self.level != 0:
            d["level"] = self.level
        if self.is_subtotal:
            d["isSubtotal"] = True
        if self.is_grand_total:
            d["isGrandTotal"] = True
        if self.is_header_row:
            d["isHeaderRow"] = True
        if self.is_header_band_row:
            d["isHeaderBandRow"] = True
        if self.is_row_block:
            d["isRowBlock"] = True
        if self.measure_name is not None:
            d["measureName"] = self.measure_name
        return d


@dataclass
class TablixColDef:
    """Definition of a column in the tablix grid."""
    index: int
    key: Optional[str] = None
    level: int = 0
    measure_name: Optional[str] = None
    is_subtotal: bool = False
    is_grand_total: bool = False
    is_row_header_col: bool = False  # True for row header columns
    is_header_band_col: bool = False  # True for row header band columns
    is_static_measure: bool = False  # True for static (non-pivoted) measure columns
    static_placement: Optional[Literal["left", "right"]] = None  # Placement of static column
    col_block_index: Optional[int] = None  # Block index for column measure blocks
    is_breaker: bool = False  # True for blank/breaker columns (transparent separator)
    
    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"index": self.index}
        if self.key is not None:
            d["key"] = self.key
        if self.level != 0:
            d["level"] = self.level
        if self.measure_name is not None:
            d["measureName"] = self.measure_name
        if self.is_subtotal:
            d["isSubtotal"] = True
        if self.is_grand_total:
            d["isGrandTotal"] = True
        if self.is_row_header_col:
            d["isRowHeaderCol"] = True
        if self.is_header_band_col:
            d["isHeaderBandCol"] = True
        if self.is_static_measure:
            d["isStaticMeasure"] = True
        if self.static_placement is not None:
            d["staticPlacement"] = self.static_placement
        if self.col_block_index is not None:
            d["colBlockIndex"] = self.col_block_index
        if self.is_breaker:
            d["isBreaker"] = True
        return d


# =============================================================================
# Tablix Plan (Main Structure)
# =============================================================================


@dataclass
class TablixPlan:
    """SSRS-style Tablix layout plan.
    
    This is the single source of truth for tablix rendering.
    
    Structure:
    - Grid: row-major list of rows, each row is a list of cells
    - Regions: corner, col_headers, row_headers, body, static_left, static_right
    - Row definitions: metadata per row
    - Column definitions: metadata per column
    - Interaction metadata: for click handling
    
    Static measure columns:
    - Non-pivoted measure columns that render outside the pivot body
    - Can appear to left or right of pivoted region
    - Values bound by rowKey only (no column group keys)
    
    Invariants:
    - Grid is rectangular (all rows same length)
    - Cells are positioned by (row, col) indices
    - Merged cells have span > 1, spanned-over positions are None
    - All values come from MatrixResult (no recomputation)
    
    Header bands:
    - Row header band columns: extra columns in row header region
    - Column header band rows: extra rows in column header region
    """
    # Grid dimensions
    num_rows: int = 0
    num_cols: int = 0
    
    # Header dimensions
    num_col_header_rows: int = 0  # Number of rows for column headers
    num_row_header_cols: int = 1  # Number of columns for row headers (usually 1)
    
    # Static measure column counts
    num_static_left_cols: int = 0   # Number of static columns on left
    num_static_right_cols: int = 0  # Number of static columns on right
    
    # Header band counts
    num_row_header_band_cols: int = 0  # Number of extra row header band columns
    num_col_header_band_rows: int = 0  # Number of extra column header band rows
    
    # The grid: cells[row][col], None for spanned-over positions
    cells: List[List[Optional[TablixCell]]] = field(default_factory=list)
    
    # Regions
    corner: Optional[TablixRegion] = None
    col_headers: Optional[TablixRegion] = None
    row_headers: Optional[TablixRegion] = None
    body: Optional[TablixRegion] = None
    static_left: Optional[TablixRegion] = None   # Left static measure region
    static_right: Optional[TablixRegion] = None  # Right static measure region
    row_header_bands: Optional[TablixRegion] = None   # Row header band region
    col_header_bands: Optional[TablixRegion] = None   # Column header band region
    
    # Row and column definitions
    row_defs: List[TablixRowDef] = field(default_factory=list)
    col_defs: List[TablixColDef] = field(default_factory=list)
    
    # SSRS-style layout properties
    properties: Optional[TablixProperties] = None
    
    # Interaction metadata (from MatrixResult._interaction)
    interaction: Optional[Dict[str, Any]] = None
    
    # Debug info
    debug: Optional[Dict[str, Any]] = None
    
    def get_cell(self, row: int, col: int) -> Optional[TablixCell]:
        """Get cell at position, handling spans."""
        if row < 0 or row >= len(self.cells):
            return None
        if col < 0 or col >= len(self.cells[row]):
            return None
        return self.cells[row][col]
    
    def iter_cells(self) -> List[TablixCell]:
        """Iterate over all non-None cells."""
        result = []
        for row in self.cells:
            for cell in row:
                if cell is not None:
                    result.append(cell)
        return result
    
    def iter_region(self, region: TablixRegion) -> List[TablixCell]:
        """Iterate over cells in a region."""
        result = []
        for r in range(region.start_row, region.end_row + 1):
            for c in range(region.start_col, region.end_col + 1):
                cell = self.get_cell(r, c)
                if cell is not None:
                    result.append(cell)
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict for the renderer."""
        # Build sparse cell list (only non-None cells)
        cells_list = []
        for row_idx, row in enumerate(self.cells):
            for col_idx, cell in enumerate(row):
                if cell is not None:
                    cells_list.append(cell.to_dict())
        
        d: Dict[str, Any] = {
            "numRows": self.num_rows,
            "numCols": self.num_cols,
            "numColHeaderRows": self.num_col_header_rows,
            "numRowHeaderCols": self.num_row_header_cols,
            "numStaticLeftCols": self.num_static_left_cols,
            "numStaticRightCols": self.num_static_right_cols,
            "numRowHeaderBandCols": self.num_row_header_band_cols,
            "numColHeaderBandRows": self.num_col_header_band_rows,
            "cells": cells_list,
        }
        
        if self.corner:
            d["corner"] = self.corner.to_dict()
        if self.col_headers:
            d["colHeaders"] = self.col_headers.to_dict()
        if self.row_headers:
            d["rowHeaders"] = self.row_headers.to_dict()
        if self.body:
            d["body"] = self.body.to_dict()
        if self.static_left:
            d["staticLeft"] = self.static_left.to_dict()
        if self.static_right:
            d["staticRight"] = self.static_right.to_dict()
        if self.row_header_bands:
            d["rowHeaderBands"] = self.row_header_bands.to_dict()
        if self.col_header_bands:
            d["colHeaderBands"] = self.col_header_bands.to_dict()
        
        if self.row_defs:
            d["rowDefs"] = [rd.to_dict() for rd in self.row_defs]
        if self.col_defs:
            d["colDefs"] = [cd.to_dict() for cd in self.col_defs]
        
        # Include layout properties (always include for frontend consistency)
        props = self.properties or TablixProperties()
        d["properties"] = props.to_dict()
        
        if self.interaction:
            d["_interaction"] = self.interaction
        if self.debug:
            d["debug"] = self.debug
        
        return d
