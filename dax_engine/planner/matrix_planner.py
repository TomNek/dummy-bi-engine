"""Matrix query planner.

Implements SSRS/Tablix-style matrix semantics:
- Row hierarchies with indentation and expand/collapse
- Column groups with multi-row header bands
- Totals computed by re-evaluating measures in modified filter context
- Integration with calculation groups, field parameters, and what-if parameters

Non-goals for v1:
- No Excel-style pivot builder
- No conditional formatting
- No per-cell styling
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, Union

from dax_engine.context import Context
from dax_engine.ir import (
    ColumnRef,
    DaxFunction,
    Expr,
    Literal as LiteralExpr,
    MeasureRef,
    ParamRef,
    ScalarExpr,
    TableRef,
)


# =============================================================================
# Matrix Spec (Input Contract)
# =============================================================================


@dataclass(frozen=True)
class AxisItem:
    """An item on a matrix axis (row or column).
    
    Supports:
    - ColumnRef: direct column binding
    - hierarchy_ref: reference to a hierarchy definition
    - calc_group_ref: calculation group (for columns typically)
    - field_param_ref: field parameter (dynamic axis switching)
    """
    type: str  # 'column' | 'hierarchy' | 'calc_group' | 'field_param'
    # For type='column':
    table: Optional[str] = None
    column: Optional[str] = None
    # For type='hierarchy':
    hierarchy_name: Optional[str] = None
    # For type='calc_group':
    calc_group_name: Optional[str] = None
    # For type='field_param':
    field_param_name: Optional[str] = None
    
    def to_column_ref(self) -> Optional[ColumnRef]:
        """Convert to ColumnRef if this is a column type."""
        if self.type == 'column' and self.table and self.column:
            return ColumnRef(table=self.table, column=self.column)
        return None


@dataclass(frozen=True)
class MatrixSortSpec:
    """Sort specification for an axis level."""
    level: int
    direction: Literal['ASC', 'DESC'] = 'ASC'
    by_measure: Optional[str] = None  # Sort by measure value instead of label


@dataclass(frozen=True)
class ExpandedPath:
    """Represents an expanded path in the hierarchy."""
    axis: Literal['rows', 'cols']
    path: Tuple[str, ...]  # Tuple of keys representing the path


@dataclass
class MatrixSpec:
    """Input specification for a matrix visual.
    
    This is the contract the UI sends to request matrix data.
    """
    visual_id: str
    page_id: str
    
    # Axis definitions
    rows: List[AxisItem] = field(default_factory=list)
    cols: List[AxisItem] = field(default_factory=list)
    values: List[MeasureRef] = field(default_factory=list)
    
    # Totals configuration
    show_row_subtotals: bool = False
    show_row_grand_total: bool = True
    show_col_subtotals: bool = False
    show_col_grand_total: bool = True
    subtotal_placement: str = 'after_children'  # 'before_children' or 'after_children'
    
    # Expansion state
    expanded_paths: List[ExpandedPath] = field(default_factory=list)
    expand_all_rows: bool = False  # If True, expand ALL row hierarchies to lowest level
    expand_all_cols: bool = False  # If True, expand ALL column hierarchies to lowest level
    expand_all_cmb: bool = False   # If True, expand ALL column measure block hierarchies
    expand_all_rmb: bool = False   # If True, expand ALL row measure block hierarchies
    
    # CMB/RMB incremental expansion depth (-1 = not set, 0+ = expand to that depth)
    # When set, this takes precedence over expand_all_cmb/expand_all_rmb
    cmb_expand_depth: int = -1  # -1 = use expand_all_cmb, 0 = collapsed, 1+ = expand to depth
    rmb_expand_depth: int = -1  # -1 = use expand_all_rmb, 0 = collapsed, 1+ = expand to depth
    
    # Drill state (Power BI style)
    # drill_row_level: 0 = show all levels (expand mode), 1+ = start from that level
    # drill_row_mode: 'expand' = normal hierarchy, 'drill' = show only that level, 'flat' = flatten
    drill_row_level: int = 0
    drill_col_level: int = 0
    drill_row_mode: str = 'expand'  # 'expand' | 'drill' | 'flat'
    drill_col_mode: str = 'expand'
    
    # Drill filters (from "Drill Down" action - filters to specific parent value's children)
    # Each filter is a dict with {column: str, value: Any, level: int}
    drill_row_filters: List[Dict[str, Any]] = field(default_factory=list)
    drill_col_filters: List[Dict[str, Any]] = field(default_factory=list)
    
    # Sorting
    row_sort: List[MatrixSortSpec] = field(default_factory=list)
    col_sort: List[MatrixSortSpec] = field(default_factory=list)
    
    # Limits
    max_rows: Optional[int] = None
    max_cols: Optional[int] = None

    # Unresolved ParamRef names in the values encoding.
    # Resolved to MeasureRef at query time when param_values + model are available.
    _value_param_refs: List[str] = field(default_factory=list)


# =============================================================================
# Matrix Result (Output Contract)
# =============================================================================


@dataclass
class RowNode:
    """A node in the row hierarchy tree."""
    key: str
    label: str
    level: int
    parent_key: Optional[str] = None
    is_subtotal: bool = False
    is_grand_total: bool = False
    children_keys: List[str] = field(default_factory=list)
    indent: int = 0
    is_expandable: bool = False
    is_expanded: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'label': self.label,
            'level': self.level,
            'parentKey': self.parent_key,
            'isSubtotal': self.is_subtotal,
            'isGrandTotal': self.is_grand_total,
            'childrenKeys': self.children_keys,
            'indent': self.indent,
            'isExpandable': self.is_expandable,
            'isExpanded': self.is_expanded,
        }


@dataclass
class ColHeaderCell:
    """A cell in the column header band."""
    key: str
    label: str
    level: int
    col_span: int = 1
    row_span: int = 1
    is_subtotal: bool = False
    is_grand_total: bool = False
    is_expandable: bool = False
    is_expanded: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'label': self.label,
            'level': self.level,
            'colSpan': self.col_span,
            'rowSpan': self.row_span,
            'isSubtotal': self.is_subtotal,
            'isGrandTotal': self.is_grand_total,
            'isExpandable': self.is_expandable,
            'isExpanded': self.is_expanded,
        }


@dataclass
class CellValue:
    """A single cell value in the matrix."""
    value: Any
    formatted: Optional[str] = None
    bar_spec: Optional[Dict[str, Any]] = None  # For IBCS bars-in-cells
    cond_fmt: Optional[Dict[str, Any]] = None  # Conditional formatting (PBI)
    
    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {'value': self.value}
        if self.formatted is not None:
            d['formatted'] = self.formatted
        if self.bar_spec is not None:
            d['barSpec'] = self.bar_spec
        if self.cond_fmt is not None:
            d['condFmt'] = self.cond_fmt
        return d


@dataclass
class MeasureColumn:
    """A measure column with its values."""
    measure: Dict[str, Any]  # {name, formatString?}
    cells: Dict[str, Dict[str, CellValue]]  # rowKey -> colLeafKey -> CellValue
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'measure': self.measure,
            'cells': {
                rk: {ck: cv.to_dict() for ck, cv in col_cells.items()}
                for rk, col_cells in self.cells.items()
            }
        }


@dataclass
class MatrixResult:
    """Output result from matrix query planning and execution.
    
    This is the contract returned to the UI for rendering.
    """
    # Row hierarchy
    row_tree: List[RowNode] = field(default_factory=list)
    row_order: List[str] = field(default_factory=list)  # Ordered list of visible row keys
    
    # Column header bands (multi-row headers)
    col_header_bands: List[List[ColHeaderCell]] = field(default_factory=list)
    col_leaf_keys: List[str] = field(default_factory=list)  # Ordered leaf column keys
    
    # Values
    values: List[MeasureColumn] = field(default_factory=list)
    
    # Truncation flags (set when safety caps are applied)
    rows_truncated: bool = False
    cols_truncated: bool = False
    max_rows_applied: Optional[int] = None
    max_cols_applied: Optional[int] = None
    
    # Debug info
    debug: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            'rowTree': [n.to_dict() for n in self.row_tree],
            'rowOrder': self.row_order,
            'colHeaderBands': [[c.to_dict() for c in band] for band in self.col_header_bands],
            'colLeafKeys': self.col_leaf_keys,
            'values': [v.to_dict() for v in self.values],
        }
        # Include truncation info when caps were applied
        if self.rows_truncated or self.cols_truncated:
            d['truncated'] = {
                'rows': self.rows_truncated,
                'cols': self.cols_truncated,
                'max_rows': self.max_rows_applied,
                'max_cols': self.max_cols_applied,
            }
        if self.debug is not None:
            d['debug'] = self.debug
        return d


# =============================================================================
# Matrix Query Planning
# =============================================================================


def _resolve_axis_items_to_columns(
    items: List[AxisItem],
    model: Any,
    param_values: Optional[Mapping[str, str]] = None,
) -> List[ColumnRef]:
    """Resolve axis items to concrete ColumnRefs.
    
    Handles field parameter resolution and hierarchy expansion.
    """
    resolved: List[ColumnRef] = []
    
    for item in items:
        # Normalize type to handle both 'column' and 'ColumnRef' from payload
        item_type_norm = item.type.lower() if item.type else ''
        is_column_type = item_type_norm in ('column', 'columnref')
        
        if is_column_type:
            col_ref = item.to_column_ref()
            if col_ref is None and item.table and item.column:
                # Fallback: create ColumnRef directly if to_column_ref() fails due to type mismatch
                col_ref = ColumnRef(table=item.table, column=item.column)
            if col_ref:
                resolved.append(col_ref)
        elif item.type == 'field_param' and item.field_param_name:
            # Resolve field parameter to selected column
            fp_map = getattr(model, 'field_parameters', None) or {}
            fp = None
            for k, v in fp_map.items():
                if isinstance(k, str) and k.upper() == item.field_param_name.upper():
                    fp = v
                    break
            if fp is not None:
                # Get current selection from param_values
                selected = None
                if param_values:
                    selected = param_values.get(item.field_param_name.upper())
                    if selected is None:
                        selected = param_values.get(item.field_param_name)
                
                # Fall back to first item in field parameter
                if selected is None:
                    fp_items = getattr(fp, 'items', []) or []
                    if fp_items:
                        first_item = fp_items[0]
                        ref = getattr(first_item, 'ref', None)
                        if ref and hasattr(ref, 'table') and hasattr(ref, 'column'):
                            resolved.append(ColumnRef(table=ref.table, column=ref.column))
                else:
                    # Find the selected item
                    fp_items = getattr(fp, 'items', []) or []
                    for fp_item in fp_items:
                        if getattr(fp_item, 'name', '') == selected:
                            ref = getattr(fp_item, 'ref', None)
                            if ref and hasattr(ref, 'table') and hasattr(ref, 'column'):
                                resolved.append(ColumnRef(table=ref.table, column=ref.column))
                            elif ref and hasattr(ref, 'name'):
                                # MeasureRef - not valid for row axis
                                pass
                            break
        elif item.type == 'hierarchy' and item.hierarchy_name:
            # Expand hierarchy to its level columns
            h_map = getattr(model, 'hierarchies', None) or {}
            hierarchy = None
            for k, v in h_map.items():
                if isinstance(k, str) and k.upper() == item.hierarchy_name.upper():
                    hierarchy = v
                    break
            if hierarchy is not None:
                for level in hierarchy.levels:
                    resolved.append(ColumnRef(table=hierarchy.table, column=level.column))
        elif item.type == 'calc_group' and item.calc_group_name:
            # Calculation groups on axis - use virtual table
            cg_name = item.calc_group_name
            resolved.append(ColumnRef(table=f"CalcGroup_{cg_name}", column=cg_name))
    
    return resolved


def _apply_drill_to_axis(
    columns: List[ColumnRef],
    drill_level: int,
    drill_mode: str,
) -> List[ColumnRef]:
    """Apply drill state to filter/slice axis columns.
    
    Power BI drill modes:
    - 'expand': Normal hierarchical view. Show all levels from level 0 to len(columns)-1.
                This is the default mode with expand/collapse.
    - 'drill': Show ONLY the specified level. Hide all parent levels.
               E.g., drill_level=1 shows only the 2nd column (e.g., Quarter without Year).
    - 'flat': Show only the specified level as a flat list (no hierarchy).
              Similar to 'drill' but conceptually indicates flattening.
    
    Args:
        columns: The resolved ColumnRef list for this axis
        drill_level: The level to drill to (0 = top level)
        drill_mode: 'expand' | 'drill' | 'flat'
    
    Returns:
        Modified list of ColumnRefs based on drill state.
    """
    if not columns:
        return columns
    
    # Clamp drill_level to valid range
    max_level = len(columns) - 1
    drill_level = max(0, min(drill_level, max_level))
    
    if drill_mode == 'expand':
        # Normal mode: show all levels (expand/collapse determines visibility)
        return columns
    elif drill_mode == 'drill':
        # Drill mode: show only the single level at drill_level (hide parents)
        # E.g., if columns = [Year, Quarter, Month] and drill_level = 1,
        # return just [Quarter] so we see quarters without year grouping
        return [columns[drill_level]]
    elif drill_mode == 'flat':
        # Flat mode: same as drill for now (show single level)
        # Future enhancement could aggregate differently
        return [columns[drill_level]]
    else:
        # Unknown mode - fallback to expand
        return columns


def _build_row_tree(
    rows: List[Dict[str, Any]],
    axis_columns: List[ColumnRef],
    show_subtotals: bool,
    show_grand_total: bool,
    expanded_paths: List[Tuple[str, ...]],
    subtotal_placement: str = 'after_children',
    expand_all: bool = False,
) -> Tuple[List[RowNode], List[str]]:
    """Build the row hierarchy tree from query results.
    
    Args:
        subtotal_placement: 'before_children' or 'after_children' (default)
        expand_all: If True, expand all nodes to lowest level (ignore expanded_paths)
    
    Returns (row_tree, row_order) where row_order is the display order of row keys.
    """
    if not axis_columns:
        # No row grouping - single grand total row
        if show_grand_total:
            node = RowNode(
                key='__grand_total__',
                label='Grand Total',
                level=0,
                is_grand_total=True,
                indent=0,
            )
            return [node], ['__grand_total__']
        return [], []
    
    # Normalize expanded paths: if a deep path is expanded, all prefixes must be treated as expanded
    expanded_set = {tuple(p) for p in expanded_paths if p}
    expanded_prefixes: set[Tuple[str, ...]] = set()
    for p in expanded_set:
        for i in range(1, len(p) + 1):
            expanded_prefixes.add(p[:i])

    # Group rows by hierarchy levels
    nodes: Dict[str, RowNode] = {}
    row_order: List[str] = []
    
    # Track unique values at each level
    level_values: List[Dict[str, List[Dict[str, Any]]]] = [dict() for _ in axis_columns]
    
    for row in rows:
        path_parts: List[str] = []
        for i, col in enumerate(axis_columns):
            col_key = f"{col.table}.{col.column}"
            val = row.get(col.column) or row.get(col_key) or row.get(col.column.replace('"', ''))
            if val is None:
                val = "(Blank)"
            path_parts.append(str(val))
            
            # Create node for this level
            node_key = '__'.join(path_parts)
            
            if node_key not in nodes:
                parent_key = '__'.join(path_parts[:-1]) if len(path_parts) > 1 else None
                # Provisional expandable state; finalized after we discover children.
                is_expandable = i < len(axis_columns) - 1
                # Expand if: expand_all is True, OR path is in expanded_paths, OR single-level axis
                is_expanded = expand_all or tuple(path_parts) in expanded_prefixes or len(axis_columns) == 1
                
                node = RowNode(
                    key=node_key,
                    label=str(val),
                    level=i,
                    parent_key=parent_key,
                    indent=i,
                    is_expandable=is_expandable,
                    is_expanded=is_expanded,
                )
                nodes[node_key] = node
                
                # Add to parent's children
                if parent_key and parent_key in nodes:
                    if node_key not in nodes[parent_key].children_keys:
                        nodes[parent_key].children_keys.append(node_key)

    # Finalize expandability based on discovered children
    for n in nodes.values():
        if n.level < (len(axis_columns) - 1):
            n.is_expandable = bool(n.children_keys)
        else:
            n.is_expandable = False
    
    # Helper to create subtotal node
    def _ensure_subtotal_node(key: str, node: RowNode) -> str:
        subtotal_key = f"{key}__subtotal"
        if subtotal_key not in nodes:
            subtotal = RowNode(
                key=subtotal_key,
                label=f"{node.label} Total",
                level=node.level,
                parent_key=key,
                is_subtotal=True,
                indent=node.indent,
            )
            nodes[subtotal_key] = subtotal
        return subtotal_key
    
    # Build display order (respecting expansion state)
    def add_node_and_children(key: str) -> None:
        if key not in nodes:
            return
        node = nodes[key]
        row_order.append(key)

        # Add children when expanded, independent of subtotal config.
        if node.is_expanded and node.children_keys:
            # Subtotals BEFORE children if placement is 'before_children'
            if show_subtotals and node.is_expandable and subtotal_placement == 'before_children':
                subtotal_key = _ensure_subtotal_node(key, node)
                row_order.append(subtotal_key)
            
            for child_key in node.children_keys:
                add_node_and_children(child_key)

            # Subtotals AFTER children if placement is 'after_children' (default SSRS/Power BI semantics)
            if show_subtotals and node.is_expandable and subtotal_placement == 'after_children':
                subtotal_key = _ensure_subtotal_node(key, node)
                row_order.append(subtotal_key)
    
    # Start from root level nodes
    root_keys = sorted([k for k, n in nodes.items() if n.level == 0 and not n.is_subtotal])
    for root_key in root_keys:
        add_node_and_children(root_key)
    
    # Add grand total
    if show_grand_total:
        gt_key = '__grand_total__'
        gt_node = RowNode(
            key=gt_key,
            label='Grand Total',
            level=0,
            is_grand_total=True,
            indent=0,
        )
        nodes[gt_key] = gt_node
        row_order.append(gt_key)
    
    return list(nodes.values()), row_order


def _build_col_header_bands(
    col_columns: List[ColumnRef],
    unique_col_values: List[List[str]],
    show_subtotals: bool,
    show_grand_total: bool,
    expanded_col_paths: Optional[List[Tuple[str, ...]]] = None,
    expand_all: bool = False,
) -> Tuple[List[List[ColHeaderCell]], List[str]]:
    """Build column header bands (multi-row headers) and leaf keys.
    
    Args:
        col_columns: List of column references defining the column hierarchy.
        unique_col_values: Unique values at each hierarchy level.
        show_subtotals: Whether to show subtotal columns.
        show_grand_total: Whether to show grand total column.
        expanded_col_paths: List of expanded column paths (tuples). A column is
            expanded if its path is in this list. When None or empty, only the
            first level is shown (all collapsed). For single-level columns,
            all are expanded by default.
        expand_all: If True, expand all columns to lowest level (ignore expanded_col_paths).
    
    Returns (header_bands, leaf_keys).
    
    Column expansion semantics (mirrors row expansion):
    - Only expanded paths show their children.
    - A collapsed parent shows as a single column with is_expandable=True.
    - Leaf columns have is_expandable=False.
    - Subtotals can be shown after expanded groups (when show_subtotals=True).
    """
    if not col_columns:
        # No column grouping - one column per measure
        return [], ['__all__']
    
    num_levels = len(col_columns)
    
    # Normalize expanded paths: if a deep path is expanded, all prefixes must be treated as expanded
    expanded_set: set[Tuple[str, ...]] = set()
    expanded_prefixes: set[Tuple[str, ...]] = set()
    if expanded_col_paths:
        expanded_set = {tuple(p) for p in expanded_col_paths if p}
        for p in expanded_set:
            for i in range(1, len(p) + 1):
                expanded_prefixes.add(p[:i])
    
    # For single-level column axes, all columns are automatically "expanded" (no collapse possible)
    single_level = num_levels == 1
    
    # Build the visible column paths based on expansion state
    # Start from unique values at level 0 and expand only where allowed
    visible_paths: List[Tuple[str, ...]] = []
    leaf_keys: List[str] = []
    # Track which paths are subtotals (for header cell styling)
    subtotal_paths: set[Tuple[str, ...]] = set()
    
    def build_visible_paths(level: int, parent_path: Tuple[str, ...]) -> None:
        """Recursively build visible paths based on expansion state."""
        if level >= num_levels:
            # Reached leaf level - add to visible paths
            visible_paths.append(parent_path)
            leaf_keys.append('__'.join(parent_path) if parent_path else '__all__')
            return
        
        values = unique_col_values[level] if level < len(unique_col_values) else []
        
        for val in values:
            path = parent_path + (val,)
            is_leaf_level = level == num_levels - 1
            # Expand if: expand_all is True, OR path is in expanded_paths, OR single-level axis
            is_expanded = expand_all or tuple(path) in expanded_prefixes or single_level
            
            if is_leaf_level:
                # Leaf level: always add
                visible_paths.append(path)
                leaf_keys.append('__'.join(path))
            elif is_expanded:
                # Expanded: recurse to children
                build_visible_paths(level + 1, path)
                # After children, add subtotal column for this expanded parent if enabled
                if show_subtotals:
                    subtotal_path = path + ('__subtotal',)
                    visible_paths.append(subtotal_path)
                    subtotal_key = '__'.join(path) + '__subtotal'
                    leaf_keys.append(subtotal_key)
                    subtotal_paths.add(subtotal_path)
            else:
                # Collapsed: show as leaf (don't recurse)
                visible_paths.append(path)
                leaf_keys.append('__'.join(path))
    
    build_visible_paths(0, ())
    
    # Determine the maximum depth reached for visible paths
    max_visible_depth = max((len(p) for p in visible_paths), default=0)
    
    # Build header bands from visible paths
    # Each band row corresponds to a hierarchy level
    bands: List[List[ColHeaderCell]] = [[] for _ in range(max_visible_depth)]
    
    for level in range(max_visible_depth):
        current_group: Optional[str] = None
        current_cell: Optional[ColHeaderCell] = None
        col_span = 0
        
        for path in visible_paths:
            # Check if this is a subtotal path
            is_subtotal_path = path in subtotal_paths
            
            if level < len(path):
                val = path[level]
                
                # For subtotal paths, build the group_key without '__subtotal' suffix at value positions
                if is_subtotal_path and val == '__subtotal':
                    # This is the subtotal marker level - create subtotal cell
                    # The parent group_key is the path before '__subtotal'
                    parent_key = '__'.join(path[:-1])
                    subtotal_key = parent_key + '__subtotal'
                    
                    if subtotal_key != current_group:
                        # Flush previous cell
                        if current_cell is not None:
                            current_cell.col_span = col_span
                            bands[level].append(current_cell)
                        
                        # Subtotal cell spans from current level to max depth
                        row_span = max_visible_depth - level
                        
                        current_cell = ColHeaderCell(
                            key=subtotal_key,
                            label='Total',
                            level=level,
                            row_span=row_span,
                            is_subtotal=True,
                        )
                        current_group = subtotal_key
                        col_span = 1
                    else:
                        col_span += 1
                else:
                    group_key = '__'.join(path[:level + 1])
                    
                    if group_key != current_group:
                        # Flush previous cell
                        if current_cell is not None:
                            current_cell.col_span = col_span
                            bands[level].append(current_cell)
                        
                        # Determine expandability and expansion state
                        path_tuple = tuple(path[:level + 1])
                        is_at_data_leaf_level = level == num_levels - 1
                        is_at_visible_leaf = len(path) == level + 1 or (len(path) == level + 2 and path[-1] == '__subtotal')
                        
                        # Expanded if: (expand_all OR path is in expanded prefixes) AND has visible children
                        is_expanded = (expand_all or path_tuple in expanded_prefixes) and not is_at_visible_leaf
                        
                        # Expandable if: not at the deepest data level AND not single level AND
                        # either at visible leaf (can expand) OR already expanded (can collapse)
                        is_expandable = (not is_at_data_leaf_level) and not single_level and (is_at_visible_leaf or is_expanded)
                        
                        # Row span: if this is a collapsed column, it should span down to the body
                        row_span = max_visible_depth - level if is_at_visible_leaf else 1
                        
                        current_cell = ColHeaderCell(
                            key=group_key,
                            label=val,
                            level=level,
                            row_span=row_span,
                            is_expandable=is_expandable,
                            is_expanded=is_expanded,
                        )
                        current_group = group_key
                        col_span = 1
                    else:
                        col_span += 1
        
        # Add last cell
        if current_cell is not None:
            current_cell.col_span = col_span
            bands[level].append(current_cell)
    
    # Remove empty bands (can happen if all columns collapse to level 0)
    bands = [b for b in bands if b]
    
    # Add grand total column
    if show_grand_total:
        num_band_rows = len(bands) if bands else 1
        if bands:
            bands[0].append(ColHeaderCell(
                key='__col_grand_total__',
                label='Total',
                level=0,
                col_span=1,
                row_span=num_band_rows,
                is_grand_total=True,
            ))
        else:
            bands = [[ColHeaderCell(
                key='__col_grand_total__',
                label='Total',
                level=0,
                col_span=1,
                row_span=1,
                is_grand_total=True,
            )]]
        leaf_keys.append('__col_grand_total__')
    
    return bands, leaf_keys


def _format_value(value: Any, format_string: Optional[str]) -> str:
    """Format a numeric value using DAX-style format string."""
    if value is None:
        return ""
    
    if format_string is None:
        if isinstance(value, float):
            # Default: 2 decimal places for floats
            return f"{value:,.2f}"
        return str(value)
    
    fs = format_string.strip().upper()
    
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    
    # Common format patterns
    if fs == '0%' or fs == 'PERCENT':
        return f"{v * 100:.0f}%"
    if fs == '0.0%':
        return f"{v * 100:.1f}%"
    if fs == '0.00%':
        return f"{v * 100:.2f}%"
    if fs.startswith('$') or fs == 'CURRENCY':
        return f"${v:,.2f}"
    if fs == '#,##0':
        return f"{v:,.0f}"
    if fs == '#,##0.00':
        return f"{v:,.2f}"
    if fs == '0' or fs == 'INTEGER':
        return f"{v:.0f}"
    if fs == '0.0':
        return f"{v:.1f}"
    if fs == '0.00':
        return f"{v:.2f}"
    
    # Default formatting
    if isinstance(value, float):
        return f"{v:,.2f}"
    return str(value)


def _compute_bar_spec(
    value: Any,
    min_val: float,
    max_val: float,
    is_negative_bad: bool = True,
) -> Optional[Dict[str, Any]]:
    """Compute IBCS-style bar specification for a cell value."""
    if value is None:
        return None
    
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    
    if max_val == min_val:
        return None
    
    # Normalize to 0-100 scale
    range_val = max_val - min_val
    pct = ((v - min_val) / range_val) * 100 if range_val != 0 else 50
    
    # Determine direction and color
    is_negative = v < 0
    color = '#cc0000' if is_negative and is_negative_bad else '#333333'
    
    return {
        'width': min(100, max(0, abs(pct))),
        'direction': 'left' if is_negative else 'right',
        'color': color,
    }


def plan_matrix_query(
    spec: MatrixSpec,
    model: Any,
    ctx: Context,
    param_values: Optional[Mapping[str, str]] = None,
    calc_groups: Optional[Mapping[str, str]] = None,
    what_if_values: Optional[Mapping[str, float]] = None,
    include_bars: bool = False,
    debug: bool = False,
) -> Tuple[str, MatrixResult]:
    """Plan and generate SQL for a matrix query.
    
    Strategy:
    1) Resolve axis items to concrete columns
    2) Build grouping sets for all required aggregation levels
    3) Execute single query with GROUPING SETS or UNION ALL
    4) Post-process results into MatrixResult structure
    
    Returns (sql, MatrixResult).
    """
    from dax_engine.planner.visual_planner import resolve_facade_column_refs, resolve_params, resolve_what_if_params
    from dax_project import get_measure
    
    # Resolve row and column axes
    row_columns_full = _resolve_axis_items_to_columns(spec.rows, model, param_values)
    col_columns_full = _resolve_axis_items_to_columns(spec.cols, model, param_values)
    
    # Keep original full columns for drill filter lookup (filters apply to parent levels)
    # These are used to find the table name for drill filters at a given level
    
    # Apply drill state to axis items (Power BI style)
    # drill mode: 'expand' = normal hierarchy (all levels), 
    #             'drill' = show only one level (hide parents),
    #             'flat' = flatten to single level (no hierarchy)
    row_columns = _apply_drill_to_axis(row_columns_full, spec.drill_row_level, spec.drill_row_mode)
    col_columns = _apply_drill_to_axis(col_columns_full, spec.drill_col_level, spec.drill_col_mode)
    
    # When drill filters are present, skip the levels that have been drilled through.
    # E.g., if we have a filter at level 0, we should show levels 1+ (the children).
    # The drill filter acts as a WHERE clause AND skips parent groupings.
    if spec.drill_row_filters:
        max_filter_level = max(df.get("level", 0) for df in spec.drill_row_filters)
        # Skip levels 0 through max_filter_level, show max_filter_level+1 onwards
        start_level = max_filter_level + 1
        if start_level < len(row_columns):
            row_columns = row_columns[start_level:]
        else:
            # All levels drilled through - show empty or just measures
            row_columns = []
    
    if spec.drill_col_filters:
        max_filter_level = max(df.get("level", 0) for df in spec.drill_col_filters)
        start_level = max_filter_level + 1
        if start_level < len(col_columns):
            col_columns = col_columns[start_level:]
        else:
            col_columns = []
    
    # Collect all dimensions for grouping
    all_dims = row_columns + col_columns
    
    # Build SQL query
    # Use SUMMARIZECOLUMNS-style approach with grouping sets for totals
    
    if not all_dims and not spec.values:
        # Empty matrix
        return "SELECT 1 WHERE FALSE", MatrixResult()
    
    # Build dimension column list
    dim_cols: List[str] = []
    dim_aliases: Dict[str, str] = {}
    
    for col in all_dims:
        alias = f"{col.table}__{col.column}".replace('"', '').replace("'", "")
        dim_cols.append(f'"{col.table}"."{col.column}" AS "{alias}"')
        dim_aliases[f"{col.table}.{col.column}"] = alias
    
    # Build measure aggregations
    measure_cols: List[str] = []
    measure_aliases: Dict[str, str] = {}
    measure_formats: Dict[str, Optional[str]] = {}
    
    for m in spec.values:
        # Get measure definition
        measure_def = get_measure(model, m.name)
        if measure_def is None:
            continue
        
        alias = f"m__{m.name}".replace(' ', '_').replace('"', '')
        
        # Get format string
        fmt = getattr(measure_def, 'format', None) or getattr(measure_def, 'format_string', None)
        measure_formats[m.name] = fmt
        
        # For now, use placeholder - actual measure compilation happens in execution
        measure_cols.append(f"NULL AS \"{alias}\"")
        measure_aliases[m.name] = alias
    
    # Build FROM clause
    # Collect unique tables from dimensions AND drill filters
    # (drill filters may reference parent columns that aren't in the SELECT)
    tables: set[str] = set()
    for col in all_dims:
        tables.add(col.table)
    
    # Add tables from drill filter columns (these may be filtered out by drill_level)
    for col in row_columns_full:
        tables.add(col.table)
    for col in col_columns_full:
        tables.add(col.table)
    
    if not tables:
        # No dimensions - single row with measures only
        from_clause = "(SELECT 1) AS __dummy"
    else:
        # Join tables (simplified - assumes relationships are defined)
        from_clause = ', '.join(f'"{t}"' for t in sorted(tables))
    
    # Build GROUP BY clause
    group_by_cols: List[str] = []
    for col in all_dims:
        alias = dim_aliases.get(f"{col.table}.{col.column}")
        if alias:
            group_by_cols.append(f'"{alias}"')
    
    # Build basic SQL structure
    select_parts = dim_cols + measure_cols if measure_cols else dim_cols
    if not select_parts:
        select_parts = ['1 AS __dummy']
    
    sql = f"""
SELECT {', '.join(select_parts)}
FROM {from_clause}
"""
    
    # Build WHERE clause for drill filters (from "Drill Down" action)
    # These filter to show only children of the drilled value
    where_conditions: List[str] = []
    
    for df in spec.drill_row_filters:
        col_name = df.get("column", "")
        value = df.get("value")
        if col_name and value is not None:
            # Parse column name (could be "Sales[Category]" or just "Category")
            if "[" in col_name and "]" in col_name:
                # Extract table and column from "Table[Column]" format
                table_part = col_name.split("[")[0]
                col_part = col_name.split("[")[1].rstrip("]")
            else:
                # Assume it's a column name; find the table from original row_columns_full
                col_part = col_name
                table_part = ""
                # Find table from the resolved row columns at this level
                level = df.get("level", 0)
                if level < len(row_columns_full):
                    table_part = row_columns_full[level].table
            
            if table_part and col_part:
                # Escape value for SQL (simple string escape)
                if isinstance(value, str):
                    safe_value = value.replace("'", "''")
                    where_conditions.append(f'"{table_part}"."{col_part}" = \'{safe_value}\'')
                else:
                    where_conditions.append(f'"{table_part}"."{col_part}" = {value}')
    
    for df in spec.drill_col_filters:
        col_name = df.get("column", "")
        value = df.get("value")
        if col_name and value is not None:
            if "[" in col_name and "]" in col_name:
                table_part = col_name.split("[")[0]
                col_part = col_name.split("[")[1].rstrip("]")
            else:
                col_part = col_name
                table_part = ""
                level = df.get("level", 0)
                if level < len(col_columns_full):
                    table_part = col_columns_full[level].table
            
            if table_part and col_part:
                if isinstance(value, str):
                    safe_value = value.replace("'", "''")
                    where_conditions.append(f'"{table_part}"."{col_part}" = \'{safe_value}\'')
                else:
                    where_conditions.append(f'"{table_part}"."{col_part}" = {value}')
    
    if where_conditions:
        sql += f"\nWHERE {' AND '.join(where_conditions)}"
    
    if group_by_cols:
        sql += f"\nGROUP BY {', '.join(group_by_cols)}"
    
    # Apply limits
    if spec.max_rows:
        sql += f"\nLIMIT {spec.max_rows}"
    
    # Build result structure (placeholder - actual data comes from execution)
    result = MatrixResult(debug={'sql': sql} if debug else None)
    
    return sql.strip(), result


def _execute_totals_query(
    connection: Any,
    row_columns: List[ColumnRef],
    col_columns: List[ColumnRef],
    measure_name: str,
    measure_alias: str,
    row_level: Optional[int],  # None = grand total, 0 = first level subtotal, etc.
    col_level: Optional[int],  # None = column grand total
    base_tables: str,
) -> List[Dict[str, Any]]:
    """Execute a query for a specific totals level.
    
    This re-evaluates measures in the appropriate filter context for totals.
    
    Args:
        row_level: The row hierarchy level to group by (None = no row grouping = grand total)
        col_level: The column hierarchy level to group by (None = no column grouping)
    """
    # Build SELECT columns for this aggregation level
    select_cols: List[str] = []
    group_cols: List[str] = []
    
    # Include row columns up to row_level
    if row_level is not None:
        for i, col in enumerate(row_columns):
            if i <= row_level:
                alias = f"{col.table}__{col.column}".replace('"', '')
                select_cols.append(f'"{col.table}"."{col.column}" AS "{alias}"')
                group_cols.append(f'"{col.table}"."{col.column}"')
    
    # Include col columns up to col_level
    if col_level is not None:
        for i, col in enumerate(col_columns):
            if i <= col_level:
                alias = f"{col.table}__{col.column}".replace('"', '')
                select_cols.append(f'"{col.table}"."{col.column}" AS "{alias}"')
                group_cols.append(f'"{col.table}"."{col.column}"')
    
    # Add measure placeholder
    select_cols.append(f"NULL AS \"{measure_alias}\"")
    
    if not select_cols:
        select_cols = ['1 AS __dummy']
    
    sql = f"SELECT {', '.join(select_cols)} FROM {base_tables}"
    if group_cols:
        sql += f" GROUP BY {', '.join(group_cols)}"
    
    try:
        cur = connection.execute(sql)
        cols = [d[0] for d in (cur.description or [])]
        raw_rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in raw_rows]
    except Exception:
        return []


def execute_matrix_query(
    spec: MatrixSpec,
    sql: str,
    connection: Any,
    model: Any,
    row_columns: List[ColumnRef],
    col_columns: List[ColumnRef],
    ctx: Context,
    param_values: Optional[Mapping[str, str]] = None,
    calc_groups: Optional[Mapping[str, str]] = None,
    what_if_values: Optional[Mapping[str, float]] = None,
    include_bars: bool = False,
    debug_rows_target: Optional[int] = None,
    conditional_formatting_rules: Optional[List[Dict[str, Any]]] = None,
) -> MatrixResult:
    """Execute a matrix query and build the result structure.
    
    Totals Semantics (Power BI-like):
    - Subtotals and grand totals are computed by RE-EVALUATING the measure
      in the total context, NOT by summing visible cells.
    - This ensures correct results for non-additive measures like averages.
    
    Implementation:
    - Execute the main query for leaf cells
    - Execute additional queries for each totals level needed
    - Each totals query re-runs the measure expression in the appropriate filter context
    """
    import dax_compiler
    from dax_engine.planner.visual_planner import resolve_facade_column_refs, resolve_params, resolve_what_if_params
    from dax_project import get_measure
    
    expanded_paths = [tuple(ep.path) for ep in spec.expanded_paths if ep.axis == 'rows']
    col_expanded_paths = [tuple(ep.path) for ep in spec.expanded_paths if ep.axis == 'cols']
    
    # Execute main query for leaf cells
    try:
        cur = connection.execute(sql)
        cols = [d[0] for d in (cur.description or [])]
        raw_rows = cur.fetchall()
    except Exception as e:
        return MatrixResult(debug={'error': str(e)})
    
    # Track raw row count before debug inflation (for truncation detection)
    raw_row_count = len(raw_rows)
    rows = [dict(zip(cols, r)) for r in raw_rows]

    # Deterministic row inflation for UI tests (debug-only; values semantics unchanged).
    # This duplicates leaf rows and appends a suffix to the deepest row-axis column value
    # to ensure unique row keys.
    if debug_rows_target is not None and debug_rows_target > 0 and row_columns and rows:
        import itertools

        def _get_dim_value(row: Dict[str, Any], col: ColumnRef) -> Any:
            for key in [col.column, f"{col.table}.{col.column}", f"{col.table}__{col.column}"]:
                if key in row:
                    return row[key]
            return row.get(col.column)

        def _set_dim_value(row: Dict[str, Any], col: ColumnRef, value: Any) -> None:
            # Prefer setting both raw and qualified keys when present to keep downstream lookup stable.
            keys = [col.column, f"{col.table}.{col.column}", f"{col.table}__{col.column}"]
            found = False
            for k in keys:
                if k in row:
                    row[k] = value
                    found = True
            if not found:
                row[col.column] = value

        def _row_key(row: Dict[str, Any]) -> str:
            parts: List[str] = []
            for col in row_columns:
                v = _get_dim_value(row, col)
                parts.append(str(v) if v is not None else "(Blank)")
            return "__".join(parts) if parts else "__grand_total__"

        # Use unique keys count as the inflation driver.
        existing_keys = {_row_key(r) for r in rows}
        if len(existing_keys) < debug_rows_target:
            base_rows = list(rows)
            deepest = row_columns[-1]
            i = 1
            for base in itertools.cycle(base_rows):
                if len(existing_keys) >= debug_rows_target:
                    break
                dup = dict(base)
                orig = _get_dim_value(dup, deepest)
                orig_s = str(orig) if orig is not None else "(Blank)"
                new_val = f"{orig_s}__dup_{i}"
                _set_dim_value(dup, deepest, new_val)
                k = _row_key(dup)
                if k in existing_keys:
                    i += 1
                    continue
                rows.append(dup)
                existing_keys.add(k)
                i += 1
    
    # Build row tree
    row_tree, row_order = _build_row_tree(
        rows=rows,
        axis_columns=row_columns,
        show_subtotals=spec.show_row_subtotals,
        show_grand_total=spec.show_row_grand_total,
        expanded_paths=expanded_paths,
        subtotal_placement=spec.subtotal_placement,
        expand_all=spec.expand_all_rows,
    )
    
    # Get unique column values at each level
    unique_col_values: List[List[str]] = []
    cols_truncated = False
    for col in col_columns:
        values: set[str] = set()
        for row in rows:
            for key in [col.column, f"{col.table}.{col.column}", f"{col.table}__{col.column}"]:
                if key in row:
                    val = row[key]
                    if val is not None:
                        values.add(str(val))
                    break
        sorted_vals = sorted(values)
        # Enforce max_cols cap: truncate unique column members at each level
        if spec.max_cols and len(sorted_vals) > spec.max_cols:
            sorted_vals = sorted_vals[:spec.max_cols]
            cols_truncated = True
        unique_col_values.append(sorted_vals)
    
    # Build column header bands
    col_header_bands, col_leaf_keys = _build_col_header_bands(
        col_columns=col_columns,
        unique_col_values=unique_col_values,
        show_subtotals=spec.show_col_subtotals,
        show_grand_total=spec.show_col_grand_total,
        expanded_col_paths=col_expanded_paths,
        expand_all=spec.expand_all_cols,
    )
    
    # Build value columns with totals
    measure_columns: List[MeasureColumn] = []
    
    for m in spec.values:
        measure_def = get_measure(model, m.name)
        fmt = (getattr(measure_def, 'format', None) or getattr(measure_def, 'format_string', None)) if measure_def else None
        
        cells: Dict[str, Dict[str, CellValue]] = {}
        all_values: List[float] = []
        
        # Step 1: Map leaf rows to cells
        for row in rows:
            # Build row key
            row_parts: List[str] = []
            for col in row_columns:
                for key in [col.column, f"{col.table}.{col.column}", f"{col.table}__{col.column}"]:
                    if key in row:
                        val = row[key]
                        row_parts.append(str(val) if val is not None else "(Blank)")
                        break
            row_key = '__'.join(row_parts) if row_parts else '__grand_total__'
            
            # Build col key
            col_parts: List[str] = []
            for col in col_columns:
                for key in [col.column, f"{col.table}.{col.column}", f"{col.table}__{col.column}"]:
                    if key in row:
                        val = row[key]
                        col_parts.append(str(val) if val is not None else "(Blank)")
                        break
            col_key = '__'.join(col_parts) if col_parts else '__all__'
            
            # Get measure value
            m_alias = f"m__{m.name}".replace(' ', '_').replace('"', '')
            value = row.get(m_alias) or row.get(m.name)
            
            if value is not None:
                try:
                    all_values.append(float(value))
                except (TypeError, ValueError):
                    pass
            
            formatted = _format_value(value, fmt)
            
            if row_key not in cells:
                cells[row_key] = {}
            
            cells[row_key][col_key] = CellValue(
                value=value,
                formatted=formatted,
            )
        
        # Step 2: Compute totals by re-evaluating the measure
        # This is the critical part for non-additive measures
        totals_rows = _compute_totals_rows(
            connection=connection,
            spec=spec,
            measure=m,
            measure_def=measure_def,
            row_columns=row_columns,
            col_columns=col_columns,
            unique_col_values=unique_col_values,
            col_leaf_keys=col_leaf_keys,
            row_tree=row_tree,
            ctx=ctx,
            model=model,
            calc_groups=calc_groups,
        )
        
        # Step 3: Add totals to cells
        for total_row in totals_rows:
            row_key = total_row['row_key']
            col_key = total_row['col_key']
            value = total_row['value']
            
            formatted = _format_value(value, fmt)
            
            if value is not None:
                try:
                    all_values.append(float(value))
                except (TypeError, ValueError):
                    pass
            
            if row_key not in cells:
                cells[row_key] = {}
            
            cells[row_key][col_key] = CellValue(
                value=value,
                formatted=formatted,
            )
        
        # Step 4: Aggregate values for collapsed parent columns.
        # When a column is collapsed (e.g., Year "2023" collapsed, but Month/Date levels exist),
        # the query still produces full col_keys like "2023__1__2023-01-15".
        # We need to aggregate these into the visible collapsed parent col_key ("2023").
        # IMPORTANT: This must run BEFORE row aggregation so that leaf rows have
        # collapsed column values available for parent row aggregation.
        _aggregate_parent_col_values(
            cells=cells,
            col_columns=col_columns,
            col_leaf_keys=col_leaf_keys,
            fmt=fmt,
        )
        
        # Step 5: Aggregate values for column subtotals.
        # When a column hierarchy is expanded and subtotals are enabled, we have
        # subtotal columns like '2023__1__subtotal' that need aggregated values
        # from their descendant leaf columns (e.g., '2023__1__2023-01-05', '2023__1__2023-01-10').
        _aggregate_col_subtotal_values(
            cells=cells,
            col_leaf_keys=col_leaf_keys,
            fmt=fmt,
        )
        
        # Step 6: Aggregate values for visible parent rows that are not expanded.
        # When a hierarchy is collapsed, the parent row key is in row_order but
        # leaf-level cells are keyed by full paths (e.g., "Accessories__Contoso").
        # We need to aggregate leaf values to populate the parent row's cells.
        # NOTE: Runs after column aggregation so leaf rows have collapsed column values.
        _aggregate_parent_row_values(
            cells=cells,
            row_tree=row_tree,
            row_order=row_order,
            col_leaf_keys=col_leaf_keys,
            fmt=fmt,
        )
        
        # Step 7: Aggregate values for row subtotals.
        # When a row hierarchy is expanded and subtotals are enabled, we have
        # subtotal rows like 'Bikes__subtotal' that need aggregated values
        # from their descendant leaf rows.
        _aggregate_row_subtotal_values(
            cells=cells,
            row_tree=row_tree,
            row_order=row_order,
            col_leaf_keys=col_leaf_keys,
            fmt=fmt,
        )
        
        # Step 8: Copy subtotal values to expanded parent row headers.
        # When a row is expanded (showing children), Power BI shows the aggregated
        # value on the parent row header. We copy values from the subtotal row
        # (e.g., 'Bikes__subtotal') to the parent row (e.g., 'Bikes').
        _copy_subtotal_to_expanded_parents(
            cells=cells,
            row_order=row_order,
            col_leaf_keys=col_leaf_keys,
        )
        
        # Add bar specs if requested
        if include_bars and all_values:
            min_val = min(all_values)
            max_val = max(all_values)
            
            for row_key, col_cells in cells.items():
                for col_key, cell in col_cells.items():
                    cell.bar_spec = _compute_bar_spec(cell.value, min_val, max_val)
        
        measure_columns.append(MeasureColumn(
            measure={'name': m.name, 'formatString': fmt},
            cells=cells,
        ))
    
    # ---- Apply conditional formatting (PBI data bars, gradients, icons) ----
    if conditional_formatting_rules:
        from dax_engine.planner.matrix_conditional_formatting import ConditionalFormattingEngine
        cond_engine = ConditionalFormattingEngine(conditional_formatting_rules)
        if cond_engine.has_rules:
            # 1) Collect per-measure statistics
            for mc in measure_columns:
                mname = mc.measure.get('name', '')
                vals = []
                for row_cells in mc.cells.values():
                    for cell in row_cells.values():
                        if cell.value is not None and isinstance(cell.value, (int, float)):
                            vals.append(cell.value)
                cond_engine.collect_stats(mname, vals)

            # 2) Apply per-cell
            for mc in measure_columns:
                mname = mc.measure.get('name', '')
                for row_key, col_cells in mc.cells.items():
                    for col_key, cell in col_cells.items():
                        cf = cond_engine.apply(mname, cell.value)
                        if not cf.is_empty():
                            d = cf.to_dict()
                            # If dataBars rule produces a bar_spec, override the generic one
                            if cf.bar_spec is not None:
                                cell.bar_spec = cf.bar_spec
                                del d['barSpec']
                            if d:
                                cell.cond_fmt = d

    # Detect row truncation: if max_rows was set and we got exactly that many raw rows,
    # the result was likely truncated by the SQL LIMIT clause.
    rows_truncated = bool(spec.max_rows and raw_row_count >= spec.max_rows)
    
    # Hard safety ceiling: max_cells prevents N×M explosion
    # (applied after col truncation, before returning)
    max_cells = getattr(spec, '_max_cells', None)
    if max_cells and col_leaf_keys and row_order:
        total_cells = len(row_order) * len(col_leaf_keys) * max(len(measure_columns), 1)
        if total_cells > max_cells:
            # Trim rows to fit within the cell budget
            max_safe_rows = max(1, max_cells // (max(len(col_leaf_keys), 1) * max(len(measure_columns), 1)))
            if len(row_order) > max_safe_rows:
                row_order = row_order[:max_safe_rows]
                rows_truncated = True
    
    return MatrixResult(
        row_tree=row_tree,
        row_order=row_order,
        col_header_bands=col_header_bands,
        col_leaf_keys=col_leaf_keys,
        values=measure_columns,
        rows_truncated=rows_truncated,
        cols_truncated=cols_truncated,
        max_rows_applied=spec.max_rows if rows_truncated else None,
        max_cols_applied=spec.max_cols if cols_truncated else None,
    )


def _aggregate_parent_row_values(
    cells: Dict[str, Dict[str, CellValue]],
    row_tree: List[RowNode],
    row_order: List[str],
    col_leaf_keys: List[str],
    fmt: Optional[str],
) -> None:
    """Aggregate leaf values into parent rows when hierarchy is collapsed.
    
    When a parent row (e.g., "Accessories") is visible in row_order but its
    children are not (collapsed state), the parent row needs aggregated values
    for each column. This function sums up leaf values to populate parent cells.
    
    Modifies `cells` in-place.
    """
    # Build lookup: row_key -> RowNode
    node_by_key: Dict[str, RowNode] = {}
    for node in row_tree:
        node_by_key[node.key] = node
    
    # For each visible row in row_order, check if it's a parent that needs aggregation
    visible_set = set(row_order)
    
    for row_key in row_order:
        node = node_by_key.get(row_key)
        if not node:
            continue
        
        # Skip subtotals, grand totals, and leaf rows (already have values)
        if node.is_subtotal or node.is_grand_total:
            continue
        
        # Skip if children are visible (expanded) - no aggregation needed
        if node.children_keys and any(ck in visible_set for ck in node.children_keys):
            continue
        
        # If this parent already has cells for all col_leaf_keys, skip
        existing_cols = set(cells.get(row_key, {}).keys())
        missing_cols = [ck for ck in col_leaf_keys if ck not in existing_cols]
        if not missing_cols:
            continue
        
        # This is a collapsed parent. Aggregate values from descendant leaves.
        # Find all descendant leaf keys (recursively).
        descendant_leaf_keys = _collect_descendant_leaf_keys(node, node_by_key)
        
        if not descendant_leaf_keys:
            continue
        
        # Ensure the parent has a cells dict
        if row_key not in cells:
            cells[row_key] = {}
        
        # For each missing column key, aggregate values from descendants
        for col_key in missing_cols:
            total_value: Optional[float] = None
            
            for leaf_key in descendant_leaf_keys:
                leaf_cells = cells.get(leaf_key, {})
                leaf_cell = leaf_cells.get(col_key)
                if leaf_cell and leaf_cell.value is not None:
                    try:
                        v = float(leaf_cell.value)
                        if total_value is None:
                            total_value = v
                        else:
                            total_value += v
                    except (TypeError, ValueError):
                        pass
            
            # Store aggregated value
            cells[row_key][col_key] = CellValue(
                value=total_value,
                formatted=_format_value(total_value, fmt),
            )


def _aggregate_parent_col_values(
    cells: Dict[str, Dict[str, CellValue]],
    col_columns: List[ColumnRef],
    col_leaf_keys: List[str],
    fmt: Optional[str],
) -> None:
    """Aggregate leaf column values into collapsed parent columns.
    
    When a column hierarchy is collapsed at some level (e.g., Year "2023" is collapsed
    but the data has Year/Month/Date levels), the query produces full col_keys like
    "2023__1__2023-01-15". We need to aggregate these into the visible collapsed parent
    col_key ("2023") for each row.
    
    Modifies `cells` in-place.
    """
    num_col_levels = len(col_columns)
    if num_col_levels <= 1:
        # Single-level column axis - no aggregation needed
        return
    
    # Build a mapping: collapsed_prefix -> all full col_keys that start with that prefix
    # A col_leaf_key is "collapsed" if it has fewer levels than num_col_levels
    # e.g., col_leaf_keys = ['2023', '__col_grand_total__'] but full keys are '2023__1__...'
    
    collapsed_to_full: Dict[str, List[str]] = {}
    col_leaf_set = set(col_leaf_keys)
    
    # Collect all actual col_keys present in cells
    all_actual_col_keys: set[str] = set()
    for row_key, col_cells in cells.items():
        all_actual_col_keys.update(col_cells.keys())
    
    # For each visible col_leaf_key, check if it's collapsed
    for leaf_key in col_leaf_keys:
        if leaf_key in ('__all__', '__col_grand_total__'):
            continue  # Skip special keys
        
        leaf_parts = leaf_key.split('__')
        leaf_depth = len(leaf_parts)
        
        if leaf_depth < num_col_levels:
            # This is a collapsed parent column
            prefix = leaf_key + '__'
            matching_full_keys = [k for k in all_actual_col_keys 
                                  if k.startswith(prefix) or k == leaf_key]
            if matching_full_keys:
                collapsed_to_full[leaf_key] = matching_full_keys
    
    if not collapsed_to_full:
        # No collapsed columns with expandable children
        return
    
    # For each row, aggregate full col_keys into collapsed parent col_keys
    for row_key, col_cells in cells.items():
        for collapsed_key, full_keys in collapsed_to_full.items():
            # Skip if already has a value
            if collapsed_key in col_cells and col_cells[collapsed_key].value is not None:
                continue
            
            # Sum values from full col_keys
            total_value: Optional[float] = None
            for full_key in full_keys:
                cell = col_cells.get(full_key)
                if cell and cell.value is not None:
                    try:
                        v = float(cell.value)
                        if total_value is None:
                            total_value = v
                        else:
                            total_value += v
                    except (TypeError, ValueError):
                        pass
            
            if total_value is not None:
                # Store aggregated value
                col_cells[collapsed_key] = CellValue(
                    value=total_value,
                    formatted=_format_value(total_value, fmt),
                )


def _collect_descendant_leaf_keys(node: RowNode, node_by_key: Dict[str, RowNode]) -> List[str]:
    """Recursively collect all leaf descendant keys for a node."""
    if not node.children_keys:
        # This is a leaf node
        return [node.key]
    
    leaves: List[str] = []
    for child_key in node.children_keys:
        child_node = node_by_key.get(child_key)
        if child_node:
            leaves.extend(_collect_descendant_leaf_keys(child_node, node_by_key))
    return leaves


def _aggregate_col_subtotal_values(
    cells: Dict[str, Dict[str, CellValue]],
    col_leaf_keys: List[str],
    fmt: Optional[str],
) -> None:
    """Aggregate descendant column values into subtotal columns.
    
    When a column subtotal exists (e.g., '2023__subtotal' for Year 2023's total),
    we need to sum its VISIBLE sibling columns (those in col_leaf_keys that share
    the same parent prefix).
    
    IMPORTANT: We must only aggregate from VISIBLE columns (col_leaf_keys), not
    from all columns in cells. This prevents double-counting when a collapsed
    parent column (e.g., '2023__1') already contains aggregated values from its
    deeper descendants (e.g., '2023__1__2023-01-05').
    
    Modifies `cells` in-place.
    """
    # Find subtotal keys and their corresponding prefixes
    subtotal_to_prefix: Dict[str, str] = {}
    
    for col_key in col_leaf_keys:
        if col_key.endswith('__subtotal'):
            # Subtotal key like '2023__subtotal' -> prefix '2023__'
            prefix = col_key.replace('__subtotal', '') + '__'
            subtotal_to_prefix[col_key] = prefix
    
    if not subtotal_to_prefix:
        return
    
    # For each subtotal key, find its sibling VISIBLE columns (from col_leaf_keys only)
    # This ensures we don't double-count collapsed parents and their hidden descendants
    col_leaf_set = set(col_leaf_keys)
    
    subtotal_to_descendants: Dict[str, List[str]] = {}
    for subtotal_key, prefix in subtotal_to_prefix.items():
        # Only include VISIBLE columns that:
        # 1. Start with the prefix (are descendants of the same parent)
        # 2. Are not subtotals themselves
        # 3. Are in col_leaf_keys (visible, not hidden deep leaves)
        descendants = [
            k for k in col_leaf_keys
            if k.startswith(prefix) and not k.endswith('__subtotal') and k != subtotal_key
        ]
        if descendants:
            subtotal_to_descendants[subtotal_key] = descendants
    
    # For each row, compute subtotal column values
    for row_key, col_cells in cells.items():
        for subtotal_key, descendants in subtotal_to_descendants.items():
            # Skip if already has a value (computed by totals)
            if subtotal_key in col_cells and col_cells[subtotal_key].value is not None:
                continue
            
            # Sum values from descendant columns
            total_value: Optional[float] = None
            for desc_key in descendants:
                cell = col_cells.get(desc_key)
                if cell and cell.value is not None:
                    try:
                        v = float(cell.value)
                        if total_value is None:
                            total_value = v
                        else:
                            total_value += v
                    except (TypeError, ValueError):
                        pass
            
            if total_value is not None:
                col_cells[subtotal_key] = CellValue(
                    value=total_value,
                    formatted=_format_value(total_value, fmt),
                )


def _aggregate_row_subtotal_values(
    cells: Dict[str, Dict[str, CellValue]],
    row_tree: List[RowNode],
    row_order: List[str],
    col_leaf_keys: List[str],
    fmt: Optional[str],
) -> None:
    """Aggregate descendant row values into subtotal rows.
    
    When a row subtotal exists (e.g., 'Bikes__subtotal' for Bikes category total),
    we need to sum all descendant leaf rows that are children of 'Bikes'.
    
    Modifies `cells` in-place.
    """
    # Build lookup: row_key -> RowNode
    node_by_key: Dict[str, RowNode] = {}
    for node in row_tree:
        node_by_key[node.key] = node
    
    # Find subtotal rows and their parent keys
    subtotal_to_parent: Dict[str, str] = {}
    for row_key in row_order:
        if row_key.endswith('__subtotal'):
            parent_key = row_key.replace('__subtotal', '')
            subtotal_to_parent[row_key] = parent_key
    
    if not subtotal_to_parent:
        return
    
    # For each subtotal row, find descendant leaf rows
    for subtotal_key, parent_key in subtotal_to_parent.items():
        parent_node = node_by_key.get(parent_key)
        if not parent_node:
            continue
        
        # Get all descendant leaf keys
        descendant_leaves = _collect_descendant_leaf_keys(parent_node, node_by_key)
        
        if not descendant_leaves:
            continue
        
        # Ensure subtotal row exists in cells
        if subtotal_key not in cells:
            cells[subtotal_key] = {}
        
        # For each visible column, aggregate values from descendant rows
        for col_key in col_leaf_keys:
            # Skip if already has a value
            if col_key in cells[subtotal_key] and cells[subtotal_key][col_key].value is not None:
                continue
            
            # Sum values from descendant rows
            total_value: Optional[float] = None
            for leaf_key in descendant_leaves:
                leaf_cells = cells.get(leaf_key, {})
                cell = leaf_cells.get(col_key)
                if cell and cell.value is not None:
                    try:
                        v = float(cell.value)
                        if total_value is None:
                            total_value = v
                        else:
                            total_value += v
                    except (TypeError, ValueError):
                        pass
            
            if total_value is not None:
                cells[subtotal_key][col_key] = CellValue(
                    value=total_value,
                    formatted=_format_value(total_value, fmt),
                )


def _copy_subtotal_to_expanded_parents(
    cells: Dict[str, Dict[str, CellValue]],
    row_order: List[str],
    col_leaf_keys: List[str],
) -> None:
    """Copy subtotal values to expanded parent row headers.
    
    When a row is expanded (showing children), the parent row header should
    display the aggregated value (same as the subtotal). This function copies
    values from subtotal rows (e.g., 'Bikes__subtotal') to their parent rows
    (e.g., 'Bikes') when the parent has no value but the subtotal does.
    
    This provides Power BI-like behavior where expanded group headers show
    the group's total value.
    
    Modifies `cells` in-place.
    """
    # Find subtotal rows and their corresponding parent rows
    subtotal_to_parent: Dict[str, str] = {}
    parent_set: set[str] = set()
    
    for row_key in row_order:
        if row_key.endswith('__subtotal'):
            parent_key = row_key.replace('__subtotal', '')
            subtotal_to_parent[row_key] = parent_key
            parent_set.add(parent_key)
    
    if not subtotal_to_parent:
        return
    
    # For each subtotal row, copy its values to the parent row (if parent exists and has no value)
    for subtotal_key, parent_key in subtotal_to_parent.items():
        # Skip if parent row is not in row_order (not visible)
        if parent_key not in row_order:
            continue
        
        subtotal_cells = cells.get(subtotal_key, {})
        if not subtotal_cells:
            continue
        
        # Ensure parent row exists in cells
        if parent_key not in cells:
            cells[parent_key] = {}
        
        parent_cells = cells[parent_key]
        
        # Copy values from subtotal to parent for each column
        for col_key in col_leaf_keys:
            # Skip if parent already has a value for this column
            if col_key in parent_cells and parent_cells[col_key].value is not None:
                continue
            
            # Copy from subtotal if it has a value
            subtotal_cell = subtotal_cells.get(col_key)
            if subtotal_cell and subtotal_cell.value is not None:
                parent_cells[col_key] = CellValue(
                    value=subtotal_cell.value,
                    formatted=subtotal_cell.formatted,
                )


def _compute_totals_rows(
    connection: Any,
    spec: MatrixSpec,
    measure: MeasureRef,
    measure_def: Any,
    row_columns: List[ColumnRef],
    col_columns: List[ColumnRef],
    unique_col_values: List[List[str]],
    col_leaf_keys: List[str],
    row_tree: List[RowNode],
    ctx: Context,
    model: Any,
    calc_groups: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Compute totals by re-evaluating the measure at each totals level.
    
    This ensures non-additive measures (like averages) are computed correctly.
    
    Args:
        col_leaf_keys: The actual visible column leaf keys (including subtotals).
    
    Returns list of dicts with: row_key, col_key, value
    """
    from dax_engine.planner.visual_planner import plan_visual_query, VisualQuerySpec
    import dax_compiler
    
    totals: List[Dict[str, Any]] = []
    
    # Determine which totals we need based on spec and row_tree
    need_row_grand_total = spec.show_row_grand_total
    need_col_grand_total = spec.show_col_grand_total and col_columns
    need_row_subtotals = spec.show_row_subtotals and len(row_columns) > 1
    
    # Use the passed col_leaf_keys which includes subtotals
    # Filter out grand total for normal column operations
    col_keys_for_totals = [k for k in col_leaf_keys if k != '__col_grand_total__']
    
    # 1. Row grand total (across all rows, for each column)
    if need_row_grand_total:
        for col_key in col_keys_for_totals:
            # Build filter context for this column
            col_filters = _col_key_to_filters(col_key, col_columns, unique_col_values)
            
            # Re-evaluate measure
            value = _evaluate_measure_with_filters(
                connection=connection,
                measure=measure,
                measure_def=measure_def,
                row_filters=[],  # No row filter = all rows
                col_filters=col_filters,
                model=model,
                ctx=ctx,
                calc_groups=calc_groups,
            )
            
            totals.append({
                'row_key': '__grand_total__',
                'col_key': col_key,
                'value': value,
            })
    
    # 2. Row subtotals (for hierarchical row groups)
    if need_row_subtotals:
        # Find subtotal nodes in row_tree
        subtotal_nodes = [n for n in row_tree if n.is_subtotal]
        
        for node in subtotal_nodes:
            # Parse the subtotal key to get the parent value(s)
            # Key pattern: "Level1Value__subtotal" or "Level1Value__Level2Value__subtotal"
            parts = node.key.replace('__subtotal', '').split('__')
            
            # Build row filters for this subtotal level
            row_filters: List[Tuple[ColumnRef, Any]] = []
            for i, part in enumerate(parts):
                if i < len(row_columns):
                    row_filters.append((row_columns[i], part))
            
            for col_key in col_keys_for_totals:
                col_filters = _col_key_to_filters(col_key, col_columns, unique_col_values)
                
                value = _evaluate_measure_with_filters(
                    connection=connection,
                    measure=measure,
                    measure_def=measure_def,
                    row_filters=row_filters,
                    col_filters=col_filters,
                    model=model,
                    ctx=ctx,
                    calc_groups=calc_groups,
                )
                
                totals.append({
                    'row_key': node.key,
                    'col_key': col_key,
                    'value': value,
                })
    
    # 3. Column grand totals (for each row, summed across all columns)
    if need_col_grand_total:
        # Get all leaf row keys (non-subtotal, non-grand-total)
        leaf_row_keys = [n.key for n in row_tree 
                       if not n.is_subtotal and not n.is_grand_total]
        
        for row_key in leaf_row_keys:
            # Parse row key to get filter values
            parts = row_key.split('__')
            row_filters: List[Tuple[ColumnRef, Any]] = []
            for i, part in enumerate(parts):
                if i < len(row_columns):
                    row_filters.append((row_columns[i], part))
            
            value = _evaluate_measure_with_filters(
                connection=connection,
                measure=measure,
                measure_def=measure_def,
                row_filters=row_filters,
                col_filters=[],  # No column filter = all columns
                model=model,
                ctx=ctx,
                calc_groups=calc_groups,
            )
            
            totals.append({
                'row_key': row_key,
                'col_key': '__col_grand_total__',
                'value': value,
            })
        
        # Add subtotal rows' column grand totals too
        if need_row_subtotals:
            subtotal_nodes = [n for n in row_tree if n.is_subtotal]
            for node in subtotal_nodes:
                parts = node.key.replace('__subtotal', '').split('__')
                row_filters = []
                for i, part in enumerate(parts):
                    if i < len(row_columns):
                        row_filters.append((row_columns[i], part))
                
                value = _evaluate_measure_with_filters(
                    connection=connection,
                    measure=measure,
                    measure_def=measure_def,
                    row_filters=row_filters,
                    col_filters=[],
                    model=model,
                    ctx=ctx,
                    calc_groups=calc_groups,
                )
                
                totals.append({
                    'row_key': node.key,
                    'col_key': '__col_grand_total__',
                    'value': value,
                })
        
        # 4. Bottom-right corner: row grand total × column grand total
        # This is the overall total across all rows AND all columns
        if need_row_grand_total:
            value = _evaluate_measure_with_filters(
                connection=connection,
                measure=measure,
                measure_def=measure_def,
                row_filters=[],  # No row filter = all rows
                col_filters=[],  # No column filter = all columns
                model=model,
                ctx=ctx,
                calc_groups=calc_groups,
            )
            
            totals.append({
                'row_key': '__grand_total__',
                'col_key': '__col_grand_total__',
                'value': value,
            })
    
    return totals


def _col_key_to_filters(
    col_key: str,
    col_columns: List[ColumnRef],
    unique_col_values: List[List[str]],
) -> List[Tuple[ColumnRef, Any]]:
    """Convert a column key to filter predicates.
    
    Handles special keys:
    - '__all__': No column filters
    - '__col_grand_total__': No column filters (grand total)
    - '....__subtotal': Subtotal for parent path (filters only on parent levels)
    """
    if col_key == '__all__' or col_key == '__col_grand_total__':
        return []
    
    # Handle subtotal keys: '2023__subtotal' means filter on Year=2023 only
    parts = col_key.split('__')
    if parts and parts[-1] == 'subtotal':
        parts = parts[:-1]  # Remove the 'subtotal' marker
    
    filters: List[Tuple[ColumnRef, Any]] = []
    
    for i, part in enumerate(parts):
        if i < len(col_columns):
            filters.append((col_columns[i], part))
    
    return filters


def _evaluate_measure_with_filters(
    connection: Any,
    measure: MeasureRef,
    measure_def: Any,
    row_filters: List[Tuple[ColumnRef, Any]],
    col_filters: List[Tuple[ColumnRef, Any]],
    model: Any,
    ctx: Context,
    calc_groups: Optional[Mapping[str, str]] = None,
) -> Any:
    """Evaluate a measure with the given filter context.
    
    This is the key function for correct totals semantics:
    it re-evaluates the measure expression using the REAL compiler path
    (via plan_card_query), not a mini-converter.
    """
    from dax_engine.planner.visual_planner import plan_card_query
    from dax_engine.ir import DaxBinaryOp, DaxFunction, Literal
    import dax_compiler
    
    # Ensure registry is loaded
    try:
        dax_compiler.load_default_mapping(register_verified_table_rewrites=True)
    except Exception:
        pass  # Already loaded or not available
    
    # Build filter expressions for plan_card_query
    filter_exprs: List[Expr] = []
    
    for col_ref, val in row_filters + col_filters:
        # "(Blank)" is the UI sentinel for NULL dimension values (from LEFT JOIN
        # mismatches).  Emit ISBLANK(col) → "col IS NULL" instead of "col = '(Blank)'".
        if val == "(Blank)":
            filter_expr = DaxFunction("ISBLANK", [col_ref])
        else:
            filter_expr = DaxBinaryOp("=", col_ref, Literal(val))
        filter_exprs.append(filter_expr)
    
    try:
        # Use the real compiler path via plan_card_query
        # This compiles the measure with filters into proper SQL
        _table_ir, sql = plan_card_query(
            measure=measure,
            filters=filter_exprs,
            model=model,
            calc_groups=calc_groups,  # Pass through for base_calc mode blocks
            param_values=None,
            what_if_values=None,
            ctx=ctx,
        )
        
        # Normalize and execute the compiled SQL
        sql = dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
        
        cur = connection.execute(sql)
        row = cur.fetchone()
        
        if row:
            # plan_card_query returns a table with a "Value" column
            # Get the first column value
            return row[0] if row else None
        return None
        
    except Exception as e:
        # Log error but don't fail the whole query
        import logging
        logging.getLogger(__name__).warning(f"Totals evaluation error for {measure.name}: {e}")
        return None


def _extract_tables_from_filters(
    filters: List[Tuple[ColumnRef, Any]],
    model: Any,
) -> List[str]:
    """Extract unique table names from filter column refs.
    
    NOTE: This function is no longer needed for totals evaluation
    (which now uses plan_card_query), but is kept for potential future use.
    """
    return list(set(col_ref.table for col_ref, _ in filters))


def _build_from_clause_with_joins(tables: List[str], model: Any) -> str:
    """Build a FROM clause with appropriate JOINs between tables.
    
    NOTE: This function is no longer needed for totals evaluation
    (which now uses plan_card_query), but is kept for potential future use.
    """
    if not tables:
        return "(SELECT 1) AS __dummy"
    
    if len(tables) == 1:
        return f'"{tables[0]}"'
    
    # Build JOINs based on model relationships
    relationships = getattr(model, 'relationships', [])
    
    # Start with first table
    from_clause = f'"{tables[0]}"'
    joined = {tables[0]}
    
    for table in tables[1:]:
        if table in joined:
            continue
        
        # Find relationship to join this table
        join_found = False
        for rel in relationships:
            from_t = getattr(rel, 'from_table', None)
            to_t = getattr(rel, 'to_table', None)
            from_c = getattr(rel, 'from_column', None)
            to_c = getattr(rel, 'to_column', None)
            
            if from_t == table and to_t in joined:
                from_clause += f' JOIN "{table}" ON "{table}"."{from_c}" = "{to_t}"."{to_c}"'
                joined.add(table)
                join_found = True
                break
            elif to_t == table and from_t in joined:
                from_clause += f' JOIN "{table}" ON "{from_t}"."{from_c}" = "{table}"."{to_c}"'
                joined.add(table)
                join_found = True
                break
        
        if not join_found:
            # Cross join as fallback (not ideal but prevents failure)
            from_clause += f', "{table}"'
            joined.add(table)
    
    return from_clause


def _convert_dax_measure_to_sql(dax_expr: str) -> str:
    """DEPRECATED: This mini-converter should not be used.
    
    Totals must be computed via the real compiler path (plan_card_query).
    This function is kept temporarily to catch any accidental usage.
    """
    raise RuntimeError(
        "DEPRECATED: _convert_dax_measure_to_sql should not be called. "
        "Totals must use the real compiler path via plan_card_query. "
        "If you see this error, there is a bug in the totals evaluation code."
    )


def matrix_spec_from_visual(visual: Mapping[str, Any]) -> MatrixSpec:
    """Create a MatrixSpec from a visual JSON definition."""
    encodings = visual.get('encodings') or {}
    
    # Parse rows axis
    rows: List[AxisItem] = []
    rows_enc = encodings.get('rows') or []
    if not isinstance(rows_enc, list):
        rows_enc = [rows_enc] if rows_enc else []
    
    for item in rows_enc:
        if isinstance(item, dict):
            item_type = item.get('type', 'column')
            if item_type == 'ColumnRef':
                rows.append(AxisItem(
                    type='column',
                    table=item.get('table'),
                    column=item.get('column'),
                ))
            elif item_type == 'ParamRef':
                rows.append(AxisItem(
                    type='field_param',
                    field_param_name=item.get('name'),
                ))
            elif item_type == 'HierarchyRef':
                rows.append(AxisItem(
                    type='hierarchy',
                    hierarchy_name=item.get('name'),
                ))
    
    # Parse cols axis
    cols: List[AxisItem] = []
    cols_enc = encodings.get('cols') or encodings.get('columns') or []
    if not isinstance(cols_enc, list):
        cols_enc = [cols_enc] if cols_enc else []
    
    for item in cols_enc:
        if isinstance(item, dict):
            item_type = item.get('type', 'column')
            if item_type == 'ColumnRef':
                cols.append(AxisItem(
                    type='column',
                    table=item.get('table'),
                    column=item.get('column'),
                ))
            elif item_type == 'ParamRef':
                cols.append(AxisItem(
                    type='field_param',
                    field_param_name=item.get('name'),
                ))
            elif item_type == 'HierarchyRef':
                cols.append(AxisItem(
                    type='hierarchy',
                    hierarchy_name=item.get('name'),
                ))
    
    # Parse values (measures) from encodings
    values: List[MeasureRef] = []
    values_enc = encodings.get('values') or []
    if not isinstance(values_enc, list):
        values_enc = [values_enc] if values_enc else []
    
    value_param_refs: List[str] = []
    seen_measures: set[str] = set()
    for item in values_enc:
        if isinstance(item, dict) and item.get('type') == 'MeasureRef':
            name = item.get('name', '')
            if name and name not in seen_measures:
                values.append(MeasureRef(name=name))
                seen_measures.add(name)
        elif isinstance(item, dict) and item.get('type') == 'ParamRef':
            pname = item.get('name', '')
            if pname:
                value_param_refs.append(pname)
    
    # NOTE: Row/column measure blocks are NOT added to main values.
    # Block measures are queried separately via block sub-queries in server.py.
    # Adding them here would cause "measure leakage" - block measures appearing
    # as columns in the main matrix headers.
    
    # Legacy support: static_measure_columns
    tablix = encodings.get('tablix') or {}
    for smc in (tablix.get('staticMeasureColumns') or []):
        if isinstance(smc, dict):
            measure_id = smc.get('measureId') or smc.get('measure_id')
            if measure_id and measure_id not in seen_measures:
                values.append(MeasureRef(name=measure_id))
                seen_measures.add(measure_id)
    
    # Parse options
    options = visual.get('options') or {}
    
    # Bridge tablix.showSubtotals → row/col subtotals.
    # TablixProperties.showSubtotals is a single boolean that controls both axes.
    # Default is True (matching TablixProperties.show_subtotals default).
    # Per-axis overrides in options take precedence.
    tablix_show_subtotals = tablix.get('showSubtotals', tablix.get('show_subtotals', None))
    if tablix_show_subtotals is None:
        # Match TablixProperties default: show_subtotals = True
        default_row_st = True
        default_col_st = True
    else:
        default_row_st = bool(tablix_show_subtotals)
        default_col_st = bool(tablix_show_subtotals)
    
    return MatrixSpec(
        visual_id=visual.get('id', ''),
        page_id=visual.get('page_id', ''),
        rows=rows,
        cols=cols,
        values=values,
        show_row_subtotals=options.get('showRowSubtotals', default_row_st),
        show_row_grand_total=options.get('showRowGrandTotal', True),
        show_col_subtotals=options.get('showColSubtotals', default_col_st),
        show_col_grand_total=options.get('showColGrandTotal', True),
        _value_param_refs=value_param_refs,
    )
