"""Matrix → Tablix compiler.

This module compiles MatrixResult into TablixPlan.

The compiler transforms the backend MatrixResult structure into an
SSRS-style tablix grid layout. This is a LAYOUT transformation only:
- No value recomputation
- No filter invention
- No key path changes
- Uses existing MatrixResult row paths, column paths, and keys

The TablixPlan is the single source of truth for rendering.

Column Measure Blocks (replaces static measure columns):
- Non-pivoted measure columns that render outside the pivot body
- Can appear to left ("left") or right ("right") of pivoted region
- Values bound by rowKey only (no column group keys)
- Configured via TablixProperties.column_measure_blocks
- Row applicability (applies_to): controls which row types show the column
- Grouped blocks (with column_fields): expand into one-axis mini-matrix

Row Measure Blocks (new):
- Non-pivoted measure rows that render outside the pivot body
- Can appear at "top" or "bottom" relative to main body
- Grouped blocks (with row_fields): expand into one-axis mini-matrix

OVERLAP REGION:
- Overlap cells (row-block rows × column-block columns) use overlap query values.
- If row-block measure ≠ column-block measure, overlap values are blanked.
- Column-block applies_to is enforced by row type for overlap rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from dax_engine.planner.tablix import (
    CellRole,
    ColHeaderBandRow,
    ColumnMeasureBlock,
    RowHeaderBandColumn,
    RowMeasureBlock,
    StaticMeasureColumn,
    TablixCell,
    TablixColDef,
    TablixPlan,
    TablixProperties,
    TablixRegion,
    TablixRowDef,
)



# Enterprise compiler helpers (block layout, band levels, overlap).
# Community builds fall back to no-op stubs.
try:
    from dax_engine.planner.tablix_compiler_enterprise import (
        BlockColumnLayout,
        BlockRowLayout,
        _compute_band_display_levels,
        _static_col_applies_to_row,
        _col_block_applies_to_row,
        _should_blank_intersection,
    )
    _HAS_ENTERPRISE_COMPILER = True
except ImportError:
    _HAS_ENTERPRISE_COMPILER = False

    class BlockColumnLayout:  # type: ignore[no-redef]
        """Stub -- enterprise not available."""
        pass

    class BlockRowLayout:  # type: ignore[no-redef]
        """Stub -- enterprise not available."""
        pass

    def _compute_band_display_levels(bands):  # type: ignore[no-redef]
        return {}, 0

    def _static_col_applies_to_row(smc, row_type):  # type: ignore[no-redef]
        return False

    def _col_block_applies_to_row(block, row_type):  # type: ignore[no-redef]
        return False

    def _should_blank_intersection(row_block, col_block, base_measure_name=None):  # type: ignore[no-redef]
        return True


def _get_row_type(
    is_grand_total: bool,
    is_subtotal: bool,
    is_expandable: bool,
) -> str:
    """Determine the row type for static column applicability.
    
    Row types (SSRS parity):
    - grand_total: Grand total row
    - subtotal: Subtotal row (group aggregates)
    - group: Group header row (expandable parent)
    - leaf: Detail/leaf row (no children, not a total)
    
    Returns:
        Row type string: "grand_total", "subtotal", "group", or "leaf"
    """
    if is_grand_total:
        return "grand_total"
    elif is_subtotal:
        return "subtotal"
    elif is_expandable:
        return "group"
    else:
        return "leaf"




def _suppress_blank_cols(
    col_leaf_keys: List[str],
    col_header_bands: List[List[Dict[str, Any]]],
    values: List[Dict[str, Any]],
    row_order: List[str],
) -> Tuple[List[str], List[List[Dict[str, Any]]]]:
    """Remove leaf columns where ALL values are null/blank.

    Returns updated (col_leaf_keys, col_header_bands).
    Header band cells whose keys are entirely removed are dropped and parent
    spans are decremented accordingly.

    Grand-total columns and subtotal columns are never suppressed.
    """
    # Build set of col_keys that have at least one non-null value
    non_blank_keys: set = set()
    for measure_col in values:
        cells_map = measure_col.get("cells") or {}
        for row_key in row_order:
            row_cells = cells_map.get(row_key)
            if not row_cells:
                continue
            for col_key in col_leaf_keys:
                if col_key in non_blank_keys:
                    continue  # already proven non-blank
                cell = row_cells.get(col_key)
                if cell and cell.get("value") is not None:
                    non_blank_keys.add(col_key)

    # Never suppress special columns (grand total, subtotal)
    for col_key in col_leaf_keys:
        if col_key == "__col_grand_total__" or col_key.endswith("__subtotal"):
            non_blank_keys.add(col_key)

    # Determine which leaf keys to keep
    suppressed_keys: set = set()
    filtered_leaf_keys: List[str] = []
    for col_key in col_leaf_keys:
        if col_key in non_blank_keys:
            filtered_leaf_keys.append(col_key)
        else:
            suppressed_keys.add(col_key)

    if not suppressed_keys:
        # Nothing to suppress
        return col_leaf_keys, col_header_bands

    # --- Adjust col_header_bands ---
    # Each band level has cells with `key` and `colSpan`.
    # A header cell at level N covers a contiguous range of leaf keys.
    # We need to reduce spans when leaves under a header are removed,
    # and drop the header entirely if all its leaves are gone.
    #
    # Strategy: for each header cell, count how many of its descendant
    # leaf keys survived.  The cell's key is a prefix of its descendant
    # leaf keys (or equal for bottom-level cells).
    filtered_leaf_set = set(filtered_leaf_keys)

    new_header_bands: List[List[Dict[str, Any]]] = []
    for band in col_header_bands:
        new_band: List[Dict[str, Any]] = []
        for cell_data in band:
            cell_key = cell_data.get("key") or ""
            old_span = cell_data.get("colSpan") or 1

            # Count surviving leaves under this header cell.
            # A leaf key belongs to this header if its key starts with
            # the header key + joiner, or equals the header key exactly
            # (for bottom-level cells that are also leaves).
            surviving = 0
            for lk in filtered_leaf_keys:
                if lk == cell_key or lk.startswith(cell_key + "__"):
                    surviving += 1

            if surviving == 0:
                # All descendant leaves suppressed — drop this header
                continue

            # Update span to match surviving descendants
            updated = dict(cell_data)
            updated["colSpan"] = surviving
            new_band.append(updated)
        new_header_bands.append(new_band)

    return filtered_leaf_keys, new_header_bands


def compile_matrix_to_tablix(
    matrix_result: Dict[str, Any],
    *,
    tablix_properties: Optional[Dict[str, Any]] = None,
    block_results: Optional[Dict[str, Dict[str, Any]]] = None,
    debug: bool = False,
) -> TablixPlan:
    """Compile MatrixResult dict into TablixPlan.
    
    Args:
        matrix_result: The MatrixResult.to_dict() output from matrix planner
        tablix_properties: Optional SSRS-style layout properties dict
        block_results: Optional dict of block sub-query results, keyed by block identifier.
            Used for grouped blocks (column_fields or row_fields present).
            Format: {"col_block_0": MatrixResult.to_dict(), "row_block_0": ...}
        debug: Include debug info in output
    
    Returns:
        TablixPlan ready for rendering
    
    Responsibilities:
    - Build full tablix grid (row-major)
    - Multi-level column header bands
    - Multi-level row header bands (single column for now)
    - Corner region
    - Body region
    - Preserve existing expand/collapse behavior
    - Preserve subtotal rules (OFF by default, only visible when expanded)
    - Preserve grand total behavior (distinct band, not a subtotal)
    - Expand grouped blocks into mini-matrix regions
    
    Strict rules:
    - Do NOT recalculate values
    - Do NOT invent filters
    - Do NOT change key paths
    - Use existing MatrixResult data only
    """
    # Parse tablix properties (defaults if not provided)
    props = TablixProperties.from_dict(tablix_properties)
    
    # Initialize block_results if not provided
    if block_results is None:
        block_results = {}
    
    # Extract MatrixResult fields
    row_tree = matrix_result.get("rowTree") or []
    row_order_raw = matrix_result.get("rowOrder") or []
    col_header_bands_raw = matrix_result.get("colHeaderBands") or []
    col_leaf_keys_raw = matrix_result.get("colLeafKeys") or []
    values = matrix_result.get("values") or []
    interaction = matrix_result.get("_interaction")
    
    # Build row node lookup
    row_node_map: Dict[str, Dict[str, Any]] = {}
    for node in row_tree:
        key = node.get("key") or ""
        row_node_map[key] = node

    def _level_disabled(level_raw: Any, levels_map: Dict[int, bool], use_parent_level: bool) -> bool:
        if not levels_map:
            return False
        level: Optional[int] = None
        if isinstance(level_raw, int):
            level = level_raw
        elif isinstance(level_raw, str):
            try:
                level = int(level_raw)
            except ValueError:
                level = None
        if level is None:
            return False

        candidate_levels: List[int] = [level]
        if use_parent_level and level > 0:
            candidate_levels.append(level - 1)
        for lvl in candidate_levels:
            if lvl in levels_map and not levels_map[lvl]:
                return True
        return False

    def _hide_row_subtotal_for_level(level_raw: Any) -> bool:
        # Row subtotal nodes carry their parent group's own level (e.g., Year subtotal=0,
        # Month subtotal=1). Row-level toggles must therefore match exact levels only.
        # Using parent-level fallback here incorrectly hides child subtotals when a parent
        # subtotal level is disabled.
        return _level_disabled(level_raw, props.row_subtotal_levels, use_parent_level=False)
    
    # =========================================================================
    # Filter rows based on TablixProperties
    # =========================================================================
    row_order: List[str] = []
    for row_key in row_order_raw:
        node = row_node_map.get(row_key) or {}
        is_subtotal = node.get("isSubtotal") or False
        is_grand_total = node.get("isGrandTotal") or False
        
        # Filter subtotals based on show_subtotals property
        if is_subtotal and not props.show_subtotals:
            continue
        
        # Per-level row subtotal filtering
        if is_subtotal and _hide_row_subtotal_for_level(node.get("level")):
            continue
        
        # Filter grand totals based on grand_total_visibility property
        # For rows, we hide if visibility is "cols" or "none"
        if is_grand_total:
            if props.grand_total_visibility in ("cols", "none"):
                continue
        
        row_order.append(row_key)
    
    # =========================================================================
    # Filter column headers based on TablixProperties
    # =========================================================================
    # For column grand totals, hide if visibility is "rows" or "none"
    hide_col_grand_total = props.grand_total_visibility in ("rows", "none")
    
    def _hide_col_subtotal_for_level(level_raw: Any) -> bool:
        return _level_disabled(level_raw, props.col_subtotal_levels, use_parent_level=True)

    col_header_bands: List[List[Dict[str, Any]]] = []
    for band in col_header_bands_raw:
        filtered_band: List[Dict[str, Any]] = []
        for cell_data in band:
            is_gt = cell_data.get("isGrandTotal") or False
            is_st = cell_data.get("isSubtotal") or False
            
            # Filter column subtotals
            if is_st and not props.show_col_subtotals:
                continue
            
            # Per-level column subtotal filtering
            if is_st and _hide_col_subtotal_for_level(cell_data.get("level")):
                continue
            
            # Filter column grand totals
            if is_gt and hide_col_grand_total:
                continue
            
            filtered_band.append(cell_data)
        col_header_bands.append(filtered_band)
    
    # Filter column leaf keys (for grand total columns)
    # Build lookup from leaf key -> subtotal metadata so per-level subtotal
    # filtering also applies to leaf columns (not only header label cells).
    subtotal_meta_by_col_key: Dict[str, Dict[str, Any]] = {}
    for band_idx, band in enumerate(col_header_bands_raw):
        for cell_data in band:
            key = cell_data.get("key")
            if not key:
                continue
            if not (cell_data.get("isSubtotal") or False):
                continue
            if key not in subtotal_meta_by_col_key:
                subtotal_meta_by_col_key[key] = {
                    "level": cell_data.get("level", band_idx),
                }

    col_leaf_keys: List[str] = []
    for col_key in col_leaf_keys_raw:
        # Check if this is a grand total column
        is_col_gt = col_key == "__col_grand_total__"
        is_col_subtotal = col_key in subtotal_meta_by_col_key
        
        # Filter column grand totals
        if is_col_gt and hide_col_grand_total:
            continue
        # Filter column subtotals and per-level subtotal columns
        if is_col_subtotal and not props.show_col_subtotals:
            continue
        if is_col_subtotal and _hide_col_subtotal_for_level(subtotal_meta_by_col_key[col_key].get("level")):
            continue
        
        col_leaf_keys.append(col_key)
    
    # =========================================================================
    # Suppress blank columns (base matrix)
    # =========================================================================
    # When suppressBlankCols is enabled, remove leaf columns where ALL data
    # values across ALL measures and ALL rows are null/blank.
    # This also adjusts col_header_bands (spans / removal of empty groups).
    if props.suppress_blank_cols and col_leaf_keys and values:
        col_leaf_keys, col_header_bands = _suppress_blank_cols(
            col_leaf_keys, col_header_bands, values, row_order,
        )
    
    # =========================================================================
    # Column Measure Blocks Setup (replaces static_measure_columns)
    # =========================================================================
    
    # Build measure lookup by name/id for block value binding
    # Values can be either:
    #   - {"type": "MeasureRef", "name": "Total Sales"} (direct MeasureRef)
    #   - {"measure": {"name": "Total Sales", ...}, ...} (wrapped format)
    measure_by_id: Dict[str, Dict[str, Any]] = {}
    for measure_col in (values or []):
        # Try direct MeasureRef format first
        if measure_col.get("type") == "MeasureRef" and measure_col.get("name"):
            measure_name = measure_col["name"]
        else:
            # Fall back to wrapped format
            measure_info = measure_col.get("measure") or {}
            measure_name = measure_info.get("name") or "Value"
        measure_by_id[measure_name] = measure_col
    
    # Use column_measure_blocks if available, otherwise fall back to static_measure_columns
    # This provides backwards compatibility
    if props.column_measure_blocks:
        col_blocks_to_use = props.column_measure_blocks
    else:
        # Convert legacy static_measure_columns to column_measure_blocks
        col_blocks_to_use = [
            ColumnMeasureBlock.from_static_measure_column(smc)
            for smc in props.static_measure_columns
        ]
    
    # Build BlockColumnLayout objects for each block
    # Each layout tracks the expanded columns and cell data for that block
    block_left_layouts: List[BlockColumnLayout] = []
    block_right_layouts: List[BlockColumnLayout] = []
    
    for block_idx, block in enumerate(col_blocks_to_use):
        block_key = f"col_block_{block_idx}"
        block_result = block_results.get(block_key)
        
        # Handle blank mode: emit a single blank column with no cells
        if block.measure_mode == "blank":
            layout = BlockColumnLayout(
                block=block,
                block_idx=block_idx,
                block_id=block.id or "",
                leaf_keys=["__blank__"],
                header_bands=[],
                cells={},  # No cells - all values are blank
                format_string=None,
            )
            if block.placement == "left":
                block_left_layouts.append(layout)
            else:
                block_right_layouts.append(layout)
            continue  # Skip all other processing for blank mode
        
        # Determine format string from main matrix or block result
        measure_col_main = measure_by_id.get(block.measure_id)
        if measure_col_main:
            measure_info_main = measure_col_main.get("measure") or {}
            format_string = measure_info_main.get("formatString")
        else:
            format_string = None
        
        # For grouped blocks with results, extract the mini-matrix structure
        if block.is_grouped and block_result:
            leaf_keys = block_result.get("colLeafKeys") or ["__all__"]
            header_bands = block_result.get("colHeaderBands") or []

            block_show_subtotals = props.show_col_subtotals
            if block.show_subtotals is not None:
                block_show_subtotals = bool(block.show_subtotals)

            def _hide_col_subtotal_for_block_level(level_raw: Any) -> bool:
                if _hide_col_subtotal_for_level(level_raw):
                    return True
                return _level_disabled(level_raw, block.subtotal_levels, use_parent_level=True)

            # Apply the same subtotal/grand-total visibility rules to grouped blocks
            # as the main matrix column axis.
            if header_bands:
                filtered_bands: List[List[Dict[str, Any]]] = []
                for band in header_bands:
                    filtered_band: List[Dict[str, Any]] = []
                    for cell in band:
                        cell_is_gt = cell.get("isGrandTotal") or False
                        cell_is_st = cell.get("isSubtotal") or False

                        if cell_is_gt and hide_col_grand_total:
                            continue
                        if cell_is_st and not block_show_subtotals:
                            continue
                        if cell_is_st and _hide_col_subtotal_for_block_level(cell.get("level")):
                            continue

                        filtered_band.append(cell)
                    filtered_bands.append(filtered_band)
                header_bands = filtered_bands

            subtotal_meta_by_col_key_block: Dict[str, Dict[str, Any]] = {}
            for band_idx, band in enumerate(block_result.get("colHeaderBands") or []):
                for cell_data in band:
                    key = cell_data.get("key")
                    if not key:
                        continue
                    if not (cell_data.get("isSubtotal") or False):
                        continue
                    if key not in subtotal_meta_by_col_key_block:
                        subtotal_meta_by_col_key_block[key] = {
                            "level": cell_data.get("level", band_idx),
                        }

            filtered_leaf_keys: List[str] = []
            for leaf_key in leaf_keys:
                is_col_gt = leaf_key == "__col_grand_total__"
                is_col_subtotal = (leaf_key in subtotal_meta_by_col_key_block) or str(leaf_key).endswith("__subtotal")

                if is_col_gt and hide_col_grand_total:
                    continue
                if is_col_subtotal and not block_show_subtotals:
                    continue
                level_hint = subtotal_meta_by_col_key_block.get(leaf_key, {}).get("level")
                if is_col_subtotal and _hide_col_subtotal_for_block_level(level_hint):
                    continue

                filtered_leaf_keys.append(leaf_key)
            leaf_keys = filtered_leaf_keys

            if hide_col_grand_total:
                leaf_keys = [k for k in leaf_keys if k != "__col_grand_total__"]
                if header_bands:
                    filtered_bands: List[List[Dict[str, Any]]] = []
                    for band in header_bands:
                        filtered_band = [
                            cell for cell in band
                            if not (cell.get("isGrandTotal") or False)
                        ]
                        filtered_bands.append(filtered_band)
                    header_bands = filtered_bands
            # Extract cell data from block result values
            # Block result may have multiple measures (unified resolution)
            # Find the block's primary measure based on measure_mode:
            # - explicit mode: use block.measure_id
            # - base/base_calc mode: use first main matrix measure in block result
            block_values = block_result.get("values") or []
            cells_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
            measure_data = None
            
            if block.measure_mode in ("base", "base_calc"):
                # Base mode: find first main matrix measure in block result
                # This ensures main matrix rows get matrix measure values
                main_measure_names = list(measure_by_id.keys())
                for mv in block_values:
                    mv_name = (mv.get("measure") or {}).get("name")
                    if mv_name in main_measure_names:
                        measure_data = mv
                        break
            else:
                # Explicit mode: find measure matching block.measure_id
                for mv in block_values:
                    mv_name = (mv.get("measure") or {}).get("name")
                    if mv_name == block.measure_id:
                        measure_data = mv
                        break
            
            if measure_data is None and block_values:
                # Fallback to first measure if primary not found
                measure_data = block_values[0]
            if measure_data:
                measure_cells = measure_data.get("cells") or {}
                for row_key, col_cells in measure_cells.items():
                    if row_key not in cells_data:
                        cells_data[row_key] = {}
                    for col_key, cell_val in col_cells.items():
                        cells_data[row_key][col_key] = cell_val
                # Also get format from block result if available
                block_format = (measure_data.get("measure") or {}).get("formatString")
                if block_format:
                    format_string = block_format
        elif block_result:
            # Simple block with sub-query result
            # For base/base_calc mode: expand to multiple columns (one per main matrix measure)
            # For explicit mode: single column keyed by "__all__"
            
            if block.measure_mode in ("base", "base_calc") and measure_by_id:
                # Base/base_calc mode: create multiple columns from block result
                # The block result has all main matrix measures with calc group applied (for base_calc)
                main_measure_names = list(measure_by_id.keys())
                leaf_keys = [f"__base_{m}__" for m in main_measure_names]
                header_bands = []
                cells_data = {}
                block_values = block_result.get("values") or []
                
                # Build a map of measure name -> measure data from block result
                measure_data_by_name = {}
                for mv in block_values:
                    mv_name = (mv.get("measure") or {}).get("name")
                    if mv_name:
                        measure_data_by_name[mv_name] = mv
                
                # Collect cells from each main matrix measure in block result
                for measure_name in main_measure_names:
                    measure_data = measure_data_by_name.get(measure_name)
                    if not measure_data:
                        continue
                    measure_cells = measure_data.get("cells") or {}
                    for row_key, col_cells in measure_cells.items():
                        if row_key not in cells_data:
                            cells_data[row_key] = {}
                        # Use col_grand_total or all for the row total value
                        cell_val = col_cells.get("__col_grand_total__") or col_cells.get("__all__") or {}
                        cells_data[row_key][f"__base_{measure_name}__"] = cell_val
                
                # Get format from first measure
                if main_measure_names and main_measure_names[0] in measure_data_by_name:
                    first_measure = measure_data_by_name[main_measure_names[0]]
                    measure_info = first_measure.get("measure") or {}
                    format_string = measure_info.get("formatString")
            else:
                # Explicit mode: single column with data from block result
                leaf_keys = ["__all__"]
                header_bands = []
                cells_data = {}
                block_values = block_result.get("values") or []
                # Find the block's primary measure
                measure_data = None
                for mv in block_values:
                    mv_name = (mv.get("measure") or {}).get("name")
                    if mv_name == block.measure_id:
                        measure_data = mv
                        break
                if measure_data is None and block_values:
                    # Fallback to first measure if primary not found
                    measure_data = block_values[0]
                if measure_data:
                    measure_cells = measure_data.get("cells") or {}
                    for row_key, col_cells in measure_cells.items():
                        if row_key not in cells_data:
                            cells_data[row_key] = {}
                        # For simple blocks, use "__all__" or the only column key
                        cell_val = col_cells.get("__all__") or col_cells.get("__col_grand_total__") or {}
                        # If neither exists, try to get the first available value
                        if not cell_val and col_cells:
                            cell_val = next(iter(col_cells.values()), {})
                        cells_data[row_key]["__all__"] = cell_val
                    # Also get format from block result if available
                    block_format = (measure_data.get("measure") or {}).get("formatString")
                    if block_format:
                        format_string = block_format
        else:
            # Simple block - no block_result from server
            # For base/base_calc mode: expand to one column per main matrix measure
            # For explicit mode: single column with block.measure_id
            
            if block.measure_mode in ("base", "base_calc") and measure_by_id:
                # Base mode simple block: create multiple columns, one per main matrix measure
                # Each "column" is keyed by measure name for identification
                main_measure_names = list(measure_by_id.keys())
                leaf_keys = [f"__base_{m}__" for m in main_measure_names]
                header_bands = []
                cells_data = {}
                
                # Collect cells from each main matrix measure
                for measure_name in main_measure_names:
                    measure_col = measure_by_id.get(measure_name)
                    if not measure_col:
                        continue
                    main_cells = measure_col.get("cells") or {}
                    for row_key, col_cells in main_cells.items():
                        if row_key not in cells_data:
                            cells_data[row_key] = {}
                        # Use col_grand_total or all for the row total value
                        cell_val = col_cells.get("__col_grand_total__") or col_cells.get("__all__") or {}
                        cells_data[row_key][f"__base_{measure_name}__"] = cell_val
                
                # Get format from first measure
                if main_measure_names:
                    first_measure = measure_by_id.get(main_measure_names[0])
                    if first_measure:
                        measure_info = first_measure.get("measure") or {}
                        format_string = measure_info.get("formatString")
            else:
                # Explicit mode: single column with data from main matrix
                # Skip if measure doesn't exist in main matrix (non-existent measure)
                if not measure_col_main:
                    continue  # Ignore block with non-existent measure and no block_result
                    
                leaf_keys = ["__all__"]
                header_bands = []
                cells_data = {}
                # For simple blocks, cells come from main matrix measure_by_id at render time
                # We populate cells_data from the main matrix here
                main_cells = measure_col_main.get("cells") or {}
                for row_key, col_cells in main_cells.items():
                    if row_key not in cells_data:
                        cells_data[row_key] = {}
                    # Simple blocks use row total (col_grand_total or all)
                    cell_val = col_cells.get("__col_grand_total__") or col_cells.get("__all__") or {}
                    cells_data[row_key]["__all__"] = cell_val
        
        layout = BlockColumnLayout(
            block=block,
            block_idx=block_idx,
            block_id=block.id or "",
            leaf_keys=leaf_keys,
            header_bands=header_bands,
            cells=cells_data,
            format_string=format_string,
        )
        
        if block.placement == "left":
            block_left_layouts.append(layout)
        else:
            block_right_layouts.append(layout)
    
    # =========================================================================
    # Suppress blank columns in CMB block layouts
    # =========================================================================
    if props.suppress_blank_cols:
        for layout in block_left_layouts + block_right_layouts:
            if not layout.is_grouped or len(layout.leaf_keys) <= 1:
                continue
            # Build pseudo-values list compatible with _suppress_blank_cols
            # layout.cells is {row_key: {col_key: cell_val}}
            pseudo_values = [{"cells": {
                rk: {ck: cv for ck, cv in col_cells.items()}
                for rk, col_cells in layout.cells.items()
            }}]
            new_keys, new_bands = _suppress_blank_cols(
                layout.leaf_keys, layout.header_bands, pseudo_values, row_order,
            )
            layout.leaf_keys = new_keys
            layout.header_bands = new_bands
    
    # Calculate actual column counts (accounting for grouped block expansion)
    num_static_left = sum(layout.num_cols for layout in block_left_layouts)
    num_static_right = sum(layout.num_cols for layout in block_right_layouts)
    
    # =========================================================================
    # Row Measure Blocks Setup (additional body rows at top/bottom)
    # =========================================================================
    
    row_blocks_to_use = props.row_measure_blocks or []
    
    # Build BlockRowLayout objects for each row block
    block_top_layouts: List[BlockRowLayout] = []
    block_bottom_layouts: List[BlockRowLayout] = []

    def _validate_row_block_result(block_idx: int, block_measure_id: str, block_result: Dict[str, Any]) -> None:
        """Ensure row block result contains the expected measure (among others).
        
        With unified measure resolution, block results may contain multiple measures.
        We just need to verify the block's primary measure is present.
        """
        block_values = block_result.get("values") or []
        found = False
        for v in block_values:
            measure_name = (v.get("measure") or {}).get("name")
            if measure_name == block_measure_id:
                found = True
                break
        if not found and block_values:
            # Only warn if there are values but the expected one is missing
            available = [((v.get("measure") or {}).get("name") or "?") for v in block_values]
            raise ValueError(
                f"Row block {block_idx} measure '{block_measure_id}' not found. Available: {available}"
            )
    
    for block_idx, block in enumerate(row_blocks_to_use):
        block_key = f"row_block_{block_idx}"
        block_result = block_results.get(block_key)
        
        # Handle blank mode: emit a single blank row with no cells
        if block.measure_mode == "blank":
            layout = BlockRowLayout(
                block=block,
                block_idx=block_idx,
                block_id=block.id or "",
                leaf_keys=["__blank__"],
                row_tree=[],
                row_order=["__blank__"],
                cells={},  # No cells - all values are blank
                format_string=None,
            )
            if block.placement == "top":
                block_top_layouts.append(layout)
            else:
                block_bottom_layouts.append(layout)
            continue  # Skip all other processing for blank mode
        
        # Determine format string from main matrix or block result
        measure_col_main = measure_by_id.get(block.measure_id)
        if measure_col_main:
            measure_info_main = measure_col_main.get("measure") or {}
            format_string = measure_info_main.get("formatString")
        else:
            format_string = None
        
        # For grouped blocks with results, extract the mini-matrix structure
        if block.is_grouped and block_result:
            _validate_row_block_result(block_idx, block.measure_id, block_result)
            # Grouped row block: rows come from block's row axis
            row_tree = block_result.get("rowTree") or []
            row_order_block = block_result.get("rowOrder") or []
            leaf_keys = row_order_block if row_order_block else ["__all__"]
            
            # Extract cell data from block result values
            # For row blocks, we need cells keyed by (row_key -> col_key)
            # Block result may have multiple measures (unified resolution)
            # Find the block's primary measure based on measure_mode:
            # - explicit mode: use block.measure_id
            # - base/base_calc mode: use first main matrix measure in block result
            block_values = block_result.get("values") or []
            cells_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
            measure_data = None
            
            if block.measure_mode in ("base", "base_calc"):
                # Base mode: find first main matrix measure in block result
                # This ensures row block gets matrix measure values, not other block measures
                main_measure_names = list(measure_by_id.keys())
                for mv in block_values:
                    mv_name = (mv.get("measure") or {}).get("name")
                    if mv_name in main_measure_names:
                        measure_data = mv
                        break
            else:
                # Explicit mode: find measure matching block.measure_id
                for mv in block_values:
                    mv_name = (mv.get("measure") or {}).get("name")
                    if mv_name == block.measure_id:
                        measure_data = mv
                        break
            
            if measure_data is None and block_values:
                # Fallback to first measure if primary not found
                measure_data = block_values[0]
            if measure_data:
                measure_cells = measure_data.get("cells") or {}
                for row_key, col_cells in measure_cells.items():
                    if row_key not in cells_data:
                        cells_data[row_key] = {}
                    for col_key, cell_val in col_cells.items():
                        cells_data[row_key][col_key] = cell_val
                # Also get format from block result if available
                block_format = (measure_data.get("measure") or {}).get("formatString")
                if block_format:
                    format_string = block_format
        elif block_result:
            _validate_row_block_result(block_idx, block.measure_id, block_result)
            # Simple row block with sub-query result (measure NOT in main values)
            # Uses "__all__" or "__grand_total__" as the single row key
            # Block result may have multiple measures (unified resolution)
            row_tree = []
            row_order_block = ["__all__"]
            leaf_keys = ["__all__"]
            cells_data = {}
            block_values = block_result.get("values") or []
            # Find the block's primary measure
            measure_data = None
            for mv in block_values:
                mv_name = (mv.get("measure") or {}).get("name")
                if mv_name == block.measure_id:
                    measure_data = mv
                    break
            if measure_data is None and block_values:
                # Fallback to first measure if primary not found
                measure_data = block_values[0]
            if measure_data:
                measure_cells = measure_data.get("cells") or {}
                # For simple row blocks, extract the grand total row or first available
                for row_key, col_cells in measure_cells.items():
                    if row_key not in cells_data:
                        cells_data[row_key] = {}
                    for col_key, cell_val in col_cells.items():
                        cells_data[row_key][col_key] = cell_val
                # If we got grand total, use that as the row
                if "__grand_total__" in measure_cells:
                    row_order_block = ["__grand_total__"]
                    leaf_keys = ["__grand_total__"]
                elif measure_cells:
                    # Use first available row
                    first_key = next(iter(measure_cells.keys()))
                    row_order_block = [first_key]
                    leaf_keys = [first_key]
                # Also get format from block result if available
                block_format = (measure_data.get("measure") or {}).get("formatString")
                if block_format:
                    format_string = block_format
        else:
            # No block result returned
            # For grouped blocks, this is an error: do not silently fall back.
            if block.is_grouped:
                row_tree = [
                    {
                        "key": "__row_block_error__",
                        "label": f"Row block '{block.measure_id}' missing data",
                        "level": 0,
                    }
                ]
                row_order_block = ["__row_block_error__"]
                leaf_keys = ["__row_block_error__"]
                cells_data = {}
            elif block.measure_mode in ("base", "base_calc") and measure_by_id:
                # Base mode simple row block: one row using main matrix grand total values
                # Each column corresponds to a main matrix measure
                main_measure_names = list(measure_by_id.keys())
                row_tree = []
                row_order_block = ["__all__"]
                leaf_keys = ["__all__"]
                cells_data = {}
                
                # Collect grand total cells from each main matrix measure
                gt_cells: Dict[str, Dict[str, Any]] = {}
                for measure_name in main_measure_names:
                    measure_col = measure_by_id.get(measure_name)
                    if not measure_col:
                        continue
                    main_cells = measure_col.get("cells") or {}
                    # Get the grand total row from main matrix for this measure
                    gt_row = main_cells.get("__grand_total__") or {}
                    # Merge column cells into gt_cells
                    for col_key, cell_val in gt_row.items():
                        if col_key not in gt_cells:
                            gt_cells[col_key] = cell_val
                cells_data["__all__"] = gt_cells
                
                # Get format from first measure
                if main_measure_names:
                    first_measure = measure_by_id.get(main_measure_names[0])
                    if first_measure:
                        measure_info = first_measure.get("measure") or {}
                        format_string = measure_info.get("formatString")
            else:
                # Explicit mode: Simple block - single row with data from main matrix
                # Skip if measure doesn't exist in main matrix (non-existent measure)
                if not measure_col_main:
                    continue  # Ignore block with non-existent measure and no block_result
            
                row_tree = []
                row_order_block = ["__all__"]
                leaf_keys = ["__all__"]
                cells_data = {}
                # For simple row blocks, cells come from main matrix - use row grand total
                main_cells = measure_col_main.get("cells") or {}
                # Get the grand total row from main matrix
                gt_cells = main_cells.get("__grand_total__") or {}
                cells_data["__all__"] = gt_cells
        
        # Extract overlap cells from pairwise overlap queries per (row_block, col_block) pair
        # Each column block gets its own overlap keyspace to avoid key collision
        # Keys are now ID-based: row_block_{row_block_id}_col_block_{col_block_id}_overlap
        row_block_id = block.id or ""
        overlap_cells_by_col_block: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
        
        # Robust regex for overlap keys: handles IDs containing hyphens or underscores
        # Pattern: row_block_{row_id}_col_block_{col_id}_overlap
        # Uses non-greedy match for both row_id and col_id for symmetric, future-proof parsing
        overlap_key_pattern = re.compile(
            r"^row_block_(?P<row_id>.+?)_col_block_(?P<col_id>.+?)_overlap$"
        )
        
        # Look for pairwise overlap results matching this row block's ID
        for result_key, overlap_result in block_results.items():
            match = overlap_key_pattern.match(result_key)
            if not match:
                continue
            parsed_row_id = match.group("row_id")
            if parsed_row_id != row_block_id:
                continue
            col_block_id = match.group("col_id")
            
            overlap_values = overlap_result.get("values") or []
            # Find the block's primary measure in overlap result
            # For base/base_calc mode: use first main matrix measure
            # For explicit mode: use block.measure_id
            overlap_measure_data = None
            if block.measure_mode in ("base", "base_calc"):
                # Base mode: find first main matrix measure in overlap result
                main_measure_names = list(measure_by_id.keys())
                for mv in overlap_values:
                    mv_name = (mv.get("measure") or {}).get("name")
                    if mv_name in main_measure_names:
                        overlap_measure_data = mv
                        break
            else:
                # Explicit mode: find measure matching block.measure_id
                for mv in overlap_values:
                    mv_name = (mv.get("measure") or {}).get("name")
                    if mv_name == block.measure_id:
                        overlap_measure_data = mv
                        break
            if overlap_measure_data is None and overlap_values:
                overlap_measure_data = overlap_values[0]
            if overlap_measure_data:
                col_overlap_cells: Dict[str, Dict[str, Dict[str, Any]]] = {}
                overlap_measure_cells = overlap_measure_data.get("cells") or {}
                for row_key, col_cells in overlap_measure_cells.items():
                    if row_key not in col_overlap_cells:
                        col_overlap_cells[row_key] = {}
                    for col_key, cell_val in col_cells.items():
                        col_overlap_cells[row_key][col_key] = cell_val
                overlap_cells_by_col_block[col_block_id] = col_overlap_cells
        
        layout = BlockRowLayout(
            block=block,
            block_idx=block_idx,
            block_id=row_block_id,
            leaf_keys=leaf_keys,
            row_tree=row_tree,
            row_order=row_order_block,
            cells=cells_data,
            overlap_cells_by_col_block=overlap_cells_by_col_block,
            format_string=format_string,
        )
        
        if block.placement == "top":
            block_top_layouts.append(layout)
        else:
            block_bottom_layouts.append(layout)
    
    # Calculate row block row counts
    num_top_block_rows = sum(layout.num_rows for layout in block_top_layouts)
    num_bottom_block_rows = sum(layout.num_rows for layout in block_bottom_layouts)
    
    # =========================================================================
    # Header Bands Setup
    # =========================================================================
    row_header_band_cols = props.row_header_bands or []
    col_header_band_rows = props.col_header_bands or []
    
    # Group bands by display_level so that bands sharing the same level
    # occupy a single grid row (for col bands) or grid column (for row bands).
    _col_band_level_map, num_col_header_band_rows = _compute_band_display_levels(col_header_band_rows)
    _row_band_level_map, num_row_header_band_cols = _compute_band_display_levels(row_header_band_cols)
    
    # =========================================================================
    # Calculate grid dimensions
    # =========================================================================
    # Main matrix header depth (before considering blocks)
    main_header_rows_base = len(col_header_bands)
    if not col_header_bands:
        main_header_rows_base = 1  # At least one header row for measure names
    
    # Global header rows: max of main matrix and all block header depths
    num_col_header_rows = main_header_rows_base
    max_block_header_rows = 0
    for layout in block_left_layouts + block_right_layouts:
        if layout.is_grouped and layout.header_bands:
            max_block_header_rows = max(max_block_header_rows, len(layout.header_bands))
    if max_block_header_rows > num_col_header_rows:
        num_col_header_rows = max_block_header_rows
    
    # Padding: how many blank rows above main matrix headers
    # (main matrix headers start lower when blocks have deeper headers)
    main_header_pad = num_col_header_rows - main_header_rows_base
    
    # Add measure name row if multiple measures
    num_measures = len(values) if values else 1
    has_measure_row = num_measures > 1 and col_header_bands
    if has_measure_row:
        num_col_header_rows += 1
    
    # Add column header band rows (extra rows above column headers)
    total_col_header_rows = num_col_header_band_rows + num_col_header_rows
    
    num_row_header_cols = 1  # Single column for row labels (with indentation)
    
    num_data_rows = len(row_order)
    num_leaf_cols = len(col_leaf_keys) if col_leaf_keys else 1
    num_pivot_cols = num_leaf_cols * num_measures  # Pivoted body columns
    
    # Total columns: row headers + row header bands + static left + pivot body + static right
    num_cols = num_row_header_cols + num_row_header_band_cols + num_static_left + num_pivot_cols + num_static_right
    
    # Total rows: header rows + top blocks + main body + bottom blocks
    num_rows = total_col_header_rows + num_top_block_rows + num_data_rows + num_bottom_block_rows
    
    # Column index offsets (band columns are to the LEFT of row headers)
    row_header_band_start_col = 0
    row_header_start_col = num_row_header_band_cols
    static_left_start_col = num_row_header_band_cols + num_row_header_cols
    pivot_body_start_col = num_row_header_band_cols + num_row_header_cols + num_static_left
    static_right_start_col = num_row_header_band_cols + num_row_header_cols + num_static_left + num_pivot_cols
    
    # Row index offsets (accounting for col header band rows AND row blocks)
    col_header_band_start_row = 0
    col_header_start_row = num_col_header_band_rows
    
    # Top row blocks start immediately after header rows
    top_block_start_row = total_col_header_rows
    
    # Main body starts after headers + top blocks
    data_start_row = total_col_header_rows + num_top_block_rows
    
    # Bottom row blocks start after main body
    bottom_block_start_row = data_start_row + num_data_rows
    
    # Set start_row for each block layout
    row_offset = top_block_start_row
    for layout in block_top_layouts:
        layout.start_row = row_offset
        row_offset += layout.num_rows
    
    row_offset = bottom_block_start_row
    for layout in block_bottom_layouts:
        layout.start_row = row_offset
        row_offset += layout.num_rows
    
    # Initialize grid with None
    cells: List[List[Optional[TablixCell]]] = [
        [None for _ in range(num_cols)]
        for _ in range(num_rows)
    ]
    
    # Key joiner from interaction metadata
    joiner = "__"
    if interaction and isinstance(interaction, dict):
        joiner = interaction.get("key_joiner") or "__"
    
    # Helper to split key into path parts
    def key_to_path(key: str) -> Tuple[str, ...]:
        if not key:
            return ()
        if key == "__grand_total__" or key == "__col_grand_total__" or key == "__all__":
            return ()
        # Remove subtotal suffix if present
        k = key
        if k.endswith("__subtotal"):
            k = k[:-10]  # len("__subtotal") = 10
        parts = k.split(joiner)
        return tuple(p for p in parts if p)
    
    # =========================================================================
    # Corner region (spans row header cols × all header rows)
    # =========================================================================
    corner_cell = TablixCell(
        row=0,
        col=row_header_start_col,
        role=CellRole.CORNER,
        row_span=total_col_header_rows,
        col_span=num_row_header_cols,
        is_interactive=False,
    )
    cells[0][row_header_start_col] = corner_cell
    
    # =========================================================================
    # Pre-compute start_col for column block layouts.
    # Needed here because the col header band section below uses
    # layout.start_col to determine the band span, but the actual
    # column header placement loop runs later.
    # =========================================================================
    _pre_offset = static_left_start_col
    for layout in block_left_layouts:
        layout.start_col = _pre_offset
        _pre_offset += layout.num_cols
    _pre_offset = static_right_start_col
    for layout in block_right_layouts:
        layout.start_col = _pre_offset
        _pre_offset += layout.num_cols

    # =========================================================================
    # Column Header Band Rows (extra rows above column headers)
    # These span from row header bands through static right
    # =========================================================================
    _col_band_corners_written: Set[int] = set()
    for band_idx, band_row in enumerate(col_header_band_rows):
        _band_grid_row = _col_band_level_map[band_idx]
        # Corner extension for band row (only once per grid row)
        if num_row_header_band_cols > 0 and _band_grid_row not in _col_band_corners_written:
            _col_band_corners_written.add(_band_grid_row)
            # Band corner spans row header band columns
            band_corner = TablixCell(
                row=_band_grid_row,
                col=row_header_band_start_col,
                role=CellRole.COL_HEADER_BAND,
                col_span=num_row_header_band_cols,
                label="",
                is_interactive=False,
            )
            cells[_band_grid_row][row_header_band_start_col] = band_corner
        
        # Determine if this band spans across CMBs
        span_blocks = getattr(band_row, 'span_blocks', None)
        span_all = getattr(band_row, 'span_scope', 'main') == 'all'
        
        if span_blocks is not None:
            # Selective span: main pivot + only the specified block IDs
            # Build a contiguous span from left blocks, pivot, and right blocks
            # that includes only those blocks whose IDs are in span_blocks
            span_blocks_set = set(span_blocks)  # for O(1) lookup
            
            def _cmb_layout_matches(layout: "BlockColumnLayout") -> bool:
                """Check if a CMB layout matches any span_blocks entry."""
                if layout.block_id in span_blocks_set:
                    return True
                # Fallback: frontend stores "blk-{idx}" when block has no persisted id
                return f"blk-{layout.block_idx}" in span_blocks_set
            
            # Also check if base matrix is included
            include_base = "__base__" in span_blocks_set or len(span_blocks_set) == 0
            
            # Initialize span boundaries.
            # When base is included, seed with the pivot columns;
            # when base is NOT included, use sentinel values so only
            # matching block layouts contribute to the range.
            if include_base:
                span_start = pivot_body_start_col
                span_end = pivot_body_start_col + num_pivot_cols
            else:
                span_start = num_cols   # will be reduced by min()
                span_end = 0            # will be increased by max()
            
            # Check which left blocks are included
            for layout in block_left_layouts:
                if _cmb_layout_matches(layout):
                    span_start = min(span_start, layout.start_col)
                    span_end = max(span_end, layout.start_col + layout.num_cols)
            
            # Check which right blocks are included
            for layout in block_right_layouts:
                if _cmb_layout_matches(layout):
                    span_start = min(span_start, layout.start_col)
                    span_end = max(span_end, layout.start_col + layout.num_cols)
            
            total_span = max(1, span_end - span_start)
            
            # Emit empty cells for left blocks NOT included that precede span_start
            col_offset_left = static_left_start_col
            for layout in block_left_layouts:
                if not _cmb_layout_matches(layout):
                    is_block_breaker = layout.block.measure_mode == "blank"
                    for _ in range(layout.num_cols):
                        if col_offset_left < span_start:
                            cells[_band_grid_row][col_offset_left] = TablixCell(
                                row=_band_grid_row, col=col_offset_left,
                                role=CellRole.COL_HEADER_BAND,
                                label="", is_interactive=False,
                                is_breaker=is_block_breaker,
                            )
                        col_offset_left += 1
                else:
                    col_offset_left += layout.num_cols
            
            # One big cell from span_start to span_end
            band_cell = TablixCell(
                row=_band_grid_row,
                col=span_start,
                role=CellRole.COL_HEADER_BAND,
                col_span=total_span,
                label=band_row.label if band_row.band_type == "label" else "",
                is_interactive=False,
            )
            cells[_band_grid_row][span_start] = band_cell

            # Emit empty cells for right blocks NOT included that follow span_end
            col_offset_right = static_right_start_col
            for layout in block_right_layouts:
                if not _cmb_layout_matches(layout):
                    is_block_breaker = layout.block.measure_mode == "blank"
                    for _ in range(layout.num_cols):
                        if col_offset_right >= span_end:
                            cells[_band_grid_row][col_offset_right] = TablixCell(
                                row=_band_grid_row, col=col_offset_right,
                                role=CellRole.COL_HEADER_BAND,
                                label="", is_interactive=False,
                                is_breaker=is_block_breaker,
                            )
                        col_offset_right += 1
                else:
                    col_offset_right += layout.num_cols
        
        elif span_all and (num_static_left + num_pivot_cols + num_static_right) > 0:
            # Span across static left + pivot body + static right as one cell
            total_span = num_static_left + num_pivot_cols + num_static_right
            if total_span < 1:
                total_span = 1
            band_cell = TablixCell(
                row=_band_grid_row,
                col=static_left_start_col,
                role=CellRole.COL_HEADER_BAND,
                col_span=total_span,
                label=band_row.label if band_row.band_type == "label" else "",
                is_interactive=False,
            )
            cells[_band_grid_row][static_left_start_col] = band_cell
        else:
            # Original behavior: separate cells for left CMB, pivot, right CMB
            
            # Static left headers for band row (one cell per block column)
            col_offset_left = static_left_start_col
            for layout in block_left_layouts:
                is_block_breaker = layout.block.measure_mode == "blank"
                for _ in range(layout.num_cols):
                    static_band_cell = TablixCell(
                        row=_band_grid_row,
                        col=col_offset_left,
                        role=CellRole.COL_HEADER_BAND,
                        label="",
                        is_interactive=False,
                        is_breaker=is_block_breaker,
                    )
                    cells[_band_grid_row][col_offset_left] = static_band_cell
                    col_offset_left += 1
            
            # Main band content spanning pivot body
            pivot_span = num_pivot_cols if num_pivot_cols > 0 else 1
            if band_row.band_type == "label":
                band_cell = TablixCell(
                    row=_band_grid_row,
                    col=pivot_body_start_col,
                    role=CellRole.COL_HEADER_BAND,
                    col_span=pivot_span,
                    label=band_row.label,
                    is_interactive=False,
                )
                cells[_band_grid_row][pivot_body_start_col] = band_cell
            else:
                band_cell = TablixCell(
                    row=_band_grid_row,
                    col=pivot_body_start_col,
                    role=CellRole.COL_HEADER_BAND,
                    col_span=pivot_span,
                    label=band_row.label,
                    is_interactive=False,
                )
                cells[_band_grid_row][pivot_body_start_col] = band_cell
            
            # Static right headers for band row (one cell per block column)
            col_offset_right = static_right_start_col
            for layout in block_right_layouts:
                is_block_breaker = layout.block.measure_mode == "blank"
                for _ in range(layout.num_cols):
                    static_band_cell = TablixCell(
                        row=_band_grid_row,
                        col=col_offset_right,
                        role=CellRole.COL_HEADER_BAND,
                        label="",
                        is_interactive=False,
                        is_breaker=is_block_breaker,
                    )
                    cells[_band_grid_row][col_offset_right] = static_band_cell
                    col_offset_right += 1
    
    # =========================================================================
    # Row Header Band Column Headers (in header region, below band rows)
    # =========================================================================
    for band_idx, band_col in enumerate(row_header_band_cols):
        col_idx = row_header_band_start_col + _row_band_level_map[band_idx]
        # Header cell spanning from col_header_start_row to end of header region
        # Label is always empty here — the actual band label appears in the
        # merged body cell, not the corner/header region.
        header_span = num_col_header_rows
        header_cell = TablixCell(
            row=col_header_start_row,
            col=col_idx,
            role=CellRole.ROW_HEADER_BAND,
            row_span=header_span,
            label="",
            is_interactive=False,
        )
        cells[col_header_start_row][col_idx] = header_cell
    
    # =========================================================================
    # Static Left Column Headers (in header region)
    # For grouped blocks: multiple columns with header bands from block result
    # For simple blocks: single column with measure name (or multiple for base mode)
    # =========================================================================
    col_offset = static_left_start_col
    for layout in block_left_layouts:
        block = layout.block
        is_cmb_breaker = block.measure_mode == "blank"
        # For base mode, block.measure_id may be empty - use first leaf key to determine measure
        primary_measure_id = block.measure_id
        if not primary_measure_id and layout.leaf_keys:
            first_key = layout.leaf_keys[0]
            if first_key.startswith("__base_") and first_key.endswith("__"):
                primary_measure_id = first_key[7:-2]  # Extract measure name
        measure_col = measure_by_id.get(primary_measure_id)
        measure_info = measure_col.get("measure") or {} if measure_col else {}
        base_label = block.label or measure_info.get("name") or primary_measure_id
        
        if layout.is_grouped and layout.header_bands:
            # Grouped block with header bands: render multi-row headers
            # The block's header bands need to be rendered above the leaf level
            num_block_header_rows = len(layout.header_bands)
            
            # Track actual positions per band for correct column offsetting
            _block_band_positions: List[List[Tuple[int, int, int]]] = []

            for band_idx, band in enumerate(layout.header_bands):
                header_row = col_header_start_row + band_idx
                leaf_col_offset = col_offset

                # For deeper bands, skip columns occupied by cells from
                # earlier bands whose rowSpan extends into this row.
                block_occupied: Set[int] = set()
                if band_idx > 0:
                    for prev_bi, prev_pos in enumerate(_block_band_positions):
                        for pos_col, pos_cs, pos_rs in prev_pos:
                            if prev_bi + pos_rs > band_idx:
                                for c in range(pos_col, pos_col + pos_cs):
                                    block_occupied.add(c)

                cur_positions: List[Tuple[int, int, int]] = []

                for cell_data in band:
                    cell_label = cell_data.get("label") or ""
                    cell_col_span = cell_data.get("colSpan") or 1
                    cell_row_span = cell_data.get("rowSpan") or 1
                    # Extract expand/collapse metadata for block column headers
                    cell_key = cell_data.get("key") or ""
                    is_expandable = cell_data.get("isExpandable") or False
                    is_expanded = cell_data.get("isExpanded") or False
                    is_gt = cell_data.get("isGrandTotal") or False
                    is_st = cell_data.get("isSubtotal") or False

                    # Skip occupied columns between cells
                    if block_occupied:
                        while leaf_col_offset in block_occupied:
                            leaf_col_offset += 1
                    
                    header_cell = TablixCell(
                        row=header_row,
                        col=leaf_col_offset,
                        role=CellRole.COL_HEADER,
                        col_span=cell_col_span,
                        row_span=cell_row_span,
                        col_key=cell_key,
                        col_path=key_to_path(cell_key),
                        label="" if is_cmb_breaker else cell_label,
                        level=band_idx,
                        measure_name=block.measure_id,
                        format_string=layout.format_string,
                        is_interactive=False,
                        col_block_index=layout.block_idx,
                        is_expandable=is_expandable,
                        is_expanded=is_expanded,
                        is_grand_total=is_gt,
                        is_subtotal=is_st,
                        is_breaker=is_cmb_breaker,
                    )
                    cells[header_row][leaf_col_offset] = header_cell
                    cur_positions.append((leaf_col_offset, cell_col_span, cell_row_span))
                    leaf_col_offset += cell_col_span

                _block_band_positions.append(cur_positions)
            
            # If there are more header rows than block bands, add block label row
            if num_block_header_rows < num_col_header_rows:
                # Add measure label cells for each leaf column
                label_row = col_header_start_row + num_block_header_rows
                for leaf_idx, leaf_key in enumerate(layout.leaf_keys):
                    header_cell = TablixCell(
                        row=label_row,
                        col=col_offset + leaf_idx,
                        role=CellRole.COL_HEADER,
                        row_span=num_col_header_rows - num_block_header_rows,
                        label="" if is_cmb_breaker else (base_label if leaf_idx == 0 else ""),
                        measure_name=block.measure_id,
                        col_key=leaf_key,
                        format_string=layout.format_string,
                        is_interactive=False,
                        col_block_index=layout.block_idx,
                        is_breaker=is_cmb_breaker,
                    )
                    cells[label_row][col_offset + leaf_idx] = header_cell
        else:
            # Simple block: header cells for each leaf column
            # For base mode: each leaf is a different measure, show measure name as label
            # For explicit mode: single leaf with block's measure name
            for leaf_idx, leaf_key in enumerate(layout.leaf_keys):
                # Extract label from leaf_key for base mode columns
                if leaf_key.startswith("__base_") and leaf_key.endswith("__"):
                    # Base mode: extract measure name from key like "__base_Total Sales__"
                    measure_name_from_key = leaf_key[7:-2]  # Remove "__base_" prefix and "__" suffix
                    leaf_label = measure_name_from_key
                    leaf_measure_name = measure_name_from_key
                else:
                    # Explicit mode: use block's measure
                    leaf_label = base_label if leaf_idx == 0 else ""
                    leaf_measure_name = block.measure_id
                
                header_cell = TablixCell(
                    row=col_header_start_row,
                    col=col_offset + leaf_idx,
                    role=CellRole.COL_HEADER,
                    row_span=num_col_header_rows,
                    label="" if is_cmb_breaker else leaf_label,
                    measure_name=leaf_measure_name,
                    col_key=leaf_key,
                    format_string=layout.format_string,
                    is_interactive=False,
                    col_block_index=layout.block_idx,
                    is_breaker=is_cmb_breaker,
                )
                cells[col_header_start_row][col_offset + leaf_idx] = header_cell
        
        # Update layout's start_col for body cell generation
        layout.start_col = col_offset
        col_offset += layout.num_cols
    
    # =========================================================================
    # Column header bands (for pivoted region) - offset by col_header_band_rows
    # Apply main_header_pad to push main matrix headers down when blocks are deeper
    # =========================================================================
    
    # First, add explicit blank padding cells in main region above its headers
    if main_header_pad > 0:
        for pad_row in range(main_header_pad):
            row_idx = col_header_start_row + pad_row
            for col_idx in range(pivot_body_start_col, pivot_body_start_col + num_pivot_cols):
                pad_cell = TablixCell(
                    row=row_idx,
                    col=col_idx,
                    role=CellRole.COL_HEADER,
                    label="",  # Explicit blank
                    is_interactive=False,
                )
                cells[row_idx][col_idx] = pad_cell
    
    if col_header_bands:
        # Track actual column positions per band so that deeper bands
        # can skip over columns occupied by multi-row-spanning cells
        # (e.g. collapsed parents that span all header rows).
        _band_cell_positions: List[List[Tuple[int, int, int]]] = []

        for band_idx, band in enumerate(col_header_bands):
            row_idx = col_header_start_row + main_header_pad + band_idx  # Offset by band rows + padding
            col_offset = pivot_body_start_col  # Start after row headers + row header bands + static left

            # For bands beyond the first, build a set of columns that
            # are already occupied by cells from earlier bands whose
            # rowSpan extends into this row.
            occupied_cols: Set[int] = set()
            if band_idx > 0:
                for prev_bi, prev_positions in enumerate(_band_cell_positions):
                    for pos_col, pos_cs, pos_rs in prev_positions:
                        if prev_bi + pos_rs > band_idx:
                            for c in range(pos_col, pos_col + pos_cs):
                                occupied_cols.add(c)

            current_positions: List[Tuple[int, int, int]] = []

            for cell_data in band:
                cell_key = cell_data.get("key") or ""
                cell_label = cell_data.get("label") or ""
                cell_col_span = (cell_data.get("colSpan") or 1) * num_measures
                cell_row_span = cell_data.get("rowSpan") or 1
                is_gt = cell_data.get("isGrandTotal") or False
                is_st = cell_data.get("isSubtotal") or False
                # Preserve expand/collapse metadata from MatrixResult
                is_expandable = cell_data.get("isExpandable") or False
                is_expanded = cell_data.get("isExpanded") or False
                
                col_path = key_to_path(cell_key)

                # Skip columns occupied by multi-row cells from earlier bands
                if occupied_cols:
                    while col_offset in occupied_cols:
                        col_offset += 1
                
                cell = TablixCell(
                    row=row_idx,
                    col=col_offset,
                    role=CellRole.COL_GROUP if not is_gt else CellRole.GRAND_TOTAL,
                    row_span=cell_row_span,
                    col_span=cell_col_span,
                    col_key=cell_key,
                    col_path=col_path,
                    label=cell_label,
                    level=band_idx,
                    is_subtotal=is_st,
                    is_grand_total=is_gt,
                    is_expandable=is_expandable,
                    is_expanded=is_expanded,
                )
                cells[row_idx][col_offset] = cell
                
                current_positions.append((col_offset, cell_col_span, cell_row_span))
                col_offset += cell_col_span

            _band_cell_positions.append(current_positions)
        
        # Measure name row (if multiple measures)
        if has_measure_row:
            measure_row_idx = col_header_start_row + main_header_pad + len(col_header_bands)  # Offset by band rows + padding
            col_offset = pivot_body_start_col
            
            for col_key in (col_leaf_keys or ["__all__"]):
                for measure_col in values:
                    measure_info = measure_col.get("measure") or {}
                    measure_name = measure_info.get("name") or "Value"
                    format_string = measure_info.get("formatString")
                    
                    col_path = key_to_path(col_key)
                    
                    cell = TablixCell(
                        row=measure_row_idx,
                        col=col_offset,
                        role=CellRole.COL_HEADER,
                        col_key=col_key,
                        col_path=col_path,
                        label=measure_name,
                        measure_name=measure_name,
                        format_string=format_string,
                    )
                    cells[measure_row_idx][col_offset] = cell
                    col_offset += 1
    else:
        # Simple single-row header with measure names only (for pivoted region)
        # Apply main_header_pad to push headers down when blocks are deeper
        col_offset = pivot_body_start_col
        header_row = col_header_start_row + main_header_pad  # Offset by band rows + padding
        for measure_col in (values or [{"measure": {"name": "Value"}}]):
            measure_info = measure_col.get("measure") or {}
            measure_name = measure_info.get("name") or "Value"
            format_string = measure_info.get("formatString")
            
            cell = TablixCell(
                row=header_row,
                col=col_offset,
                role=CellRole.COL_HEADER,
                col_key="__all__",
                label=measure_name,
                measure_name=measure_name,
                format_string=format_string,
            )
            cells[header_row][col_offset] = cell
            col_offset += 1
    
    # =========================================================================
    # Static Right Column Headers (in header region)
    # For grouped blocks: multiple columns with header bands from block result
    # For simple blocks: single column with measure name (or multiple for base mode)
    # =========================================================================
    col_offset = static_right_start_col
    for layout in block_right_layouts:
        block = layout.block
        is_cmb_breaker = block.measure_mode == "blank"
        # For base mode, block.measure_id may be empty - use first leaf key to determine measure
        primary_measure_id = block.measure_id
        if not primary_measure_id and layout.leaf_keys:
            first_key = layout.leaf_keys[0]
            if first_key.startswith("__base_") and first_key.endswith("__"):
                primary_measure_id = first_key[7:-2]  # Extract measure name
        measure_col = measure_by_id.get(primary_measure_id)
        measure_info = measure_col.get("measure") or {} if measure_col else {}
        base_label = block.label or measure_info.get("name") or primary_measure_id
        
        if layout.is_grouped and layout.header_bands:
            # Grouped block with header bands: render multi-row headers
            num_block_header_rows = len(layout.header_bands)
            
            # Track actual positions per band for correct column offsetting
            _rblock_band_positions: List[List[Tuple[int, int, int]]] = []

            for band_idx, band in enumerate(layout.header_bands):
                header_row = col_header_start_row + band_idx
                leaf_col_offset = col_offset

                # For deeper bands, skip columns occupied by cells from
                # earlier bands whose rowSpan extends into this row.
                rblock_occupied: Set[int] = set()
                if band_idx > 0:
                    for prev_bi, prev_pos in enumerate(_rblock_band_positions):
                        for pos_col, pos_cs, pos_rs in prev_pos:
                            if prev_bi + pos_rs > band_idx:
                                for c in range(pos_col, pos_col + pos_cs):
                                    rblock_occupied.add(c)

                rcur_positions: List[Tuple[int, int, int]] = []

                for cell_data in band:
                    cell_label = cell_data.get("label") or ""
                    cell_col_span = cell_data.get("colSpan") or 1
                    cell_row_span = cell_data.get("rowSpan") or 1
                    # Extract expand/collapse metadata for column measure block headers
                    cell_key = cell_data.get("key") or ""
                    is_expandable = cell_data.get("isExpandable") or False
                    is_expanded = cell_data.get("isExpanded") or False
                    is_gt = cell_data.get("isGrandTotal") or False
                    is_st = cell_data.get("isSubtotal") or False

                    # Skip occupied columns between cells
                    if rblock_occupied:
                        while leaf_col_offset in rblock_occupied:
                            leaf_col_offset += 1
                    
                    header_cell = TablixCell(
                        row=header_row,
                        col=leaf_col_offset,
                        role=CellRole.COL_HEADER,
                        col_span=cell_col_span,
                        row_span=cell_row_span,
                        col_key=cell_key,
                        col_path=key_to_path(cell_key),
                        label="" if is_cmb_breaker else cell_label,
                        level=band_idx,
                        measure_name=block.measure_id,
                        format_string=layout.format_string,
                        is_interactive=False,
                        col_block_index=layout.block_idx,
                        is_expandable=is_expandable,
                        is_expanded=is_expanded,
                        is_grand_total=is_gt,
                        is_subtotal=is_st,
                        is_breaker=is_cmb_breaker,
                    )
                    cells[header_row][leaf_col_offset] = header_cell
                    rcur_positions.append((leaf_col_offset, cell_col_span, cell_row_span))
                    leaf_col_offset += cell_col_span

                _rblock_band_positions.append(rcur_positions)
            
            # Add measure label row if needed
            if num_block_header_rows < num_col_header_rows:
                label_row = col_header_start_row + num_block_header_rows
                for leaf_idx, leaf_key in enumerate(layout.leaf_keys):
                    header_cell = TablixCell(
                        row=label_row,
                        col=col_offset + leaf_idx,
                        role=CellRole.COL_HEADER,
                        row_span=num_col_header_rows - num_block_header_rows,
                        label="" if is_cmb_breaker else (base_label if leaf_idx == 0 else ""),
                        measure_name=block.measure_id,
                        col_key=leaf_key,
                        format_string=layout.format_string,
                        is_interactive=False,
                        col_block_index=layout.block_idx,
                        is_breaker=is_cmb_breaker,
                    )
                    cells[label_row][col_offset + leaf_idx] = header_cell
        else:
            # Simple block: header cells for each leaf column
            # For base mode: each leaf is a different measure, show measure name as label
            # For explicit mode: single leaf with block's measure name
            for leaf_idx, leaf_key in enumerate(layout.leaf_keys):
                # Extract label from leaf_key for base mode columns
                if leaf_key.startswith("__base_") and leaf_key.endswith("__"):
                    # Base mode: extract measure name from key like "__base_Total Sales__"
                    measure_name_from_key = leaf_key[7:-2]  # Remove "__base_" prefix and "__" suffix
                    leaf_label = measure_name_from_key
                    leaf_measure_name = measure_name_from_key
                else:
                    # Explicit mode: use block's measure
                    leaf_label = base_label if leaf_idx == 0 else ""
                    leaf_measure_name = block.measure_id
                
                header_cell = TablixCell(
                    row=col_header_start_row,
                    col=col_offset + leaf_idx,
                    role=CellRole.COL_HEADER,
                    row_span=num_col_header_rows,
                    label="" if is_cmb_breaker else leaf_label,
                    measure_name=leaf_measure_name,
                    col_key=leaf_key,
                    format_string=layout.format_string,
                    is_interactive=False,
                    col_block_index=layout.block_idx,
                    is_breaker=is_cmb_breaker,
                )
                cells[col_header_start_row][col_offset + leaf_idx] = header_cell
        
        # Update layout's start_col for body cell generation
        layout.start_col = col_offset
        col_offset += layout.num_cols
    
    # =========================================================================
    # Pre-compute merged row header band columns
    # Merge=True (default): emit one cell spanning base matrix body rows
    # + optionally RMB rows when span_blocks includes them
    # =========================================================================
    merged_band_indices = set()
    num_body_rows = len(row_order)
    
    # Build a lookup from block_id to BlockRowLayout for span_blocks resolution
    # Register both the actual block_id (UUID) AND the frontend fallback
    # key "blk-{idx}" so span_blocks from either convention can match.
    _rmb_layout_by_id: Dict[str, "BlockRowLayout"] = {}
    for layout in block_top_layouts + block_bottom_layouts:
        if layout.block_id:
            _rmb_layout_by_id[layout.block_id] = layout
        # Fallback: frontend uses "blk-{idx}" when blocks lack a persisted id
        _rmb_layout_by_id[f"blk-{layout.block_idx}"] = layout
    
    # Pre-compute row types for each body row (used by merged band appliesTo)
    _body_row_types: List[str] = []
    for _ri, _rk in enumerate(row_order):
        _rn = row_node_map.get(_rk) or {}
        _is_gt = _rn.get("isGrandTotal") or False
        _is_st = _rn.get("isSubtotal") or False
        _is_exp = _rn.get("isExpandable") or False
        _body_row_types.append(_get_row_type(_is_gt, _is_st, _is_exp))

    for band_idx, band_col in enumerate(row_header_band_cols):
        if getattr(band_col, 'merge', True) and band_col.band_type == "label" and num_body_rows > 0:
            merged_band_indices.add(band_idx)
            col_idx = row_header_band_start_col + _row_band_level_map[band_idx]
            
            # Compute total row span: body rows + selected RMB rows
            span_blocks = getattr(band_col, 'span_blocks', None)
            span_all = getattr(band_col, 'span_scope', 'main') == 'all'
            include_base = True  # default: base matrix is included
            
            # When span_blocks is set, check if "base" is explicitly included
            if span_blocks is not None:
                include_base = "__base__" in span_blocks
            
            # Collect actual spanned block layout positions.
            # This is needed to compute merge_start/end from real layout
            # positions rather than aggregate row counts (which don't account
            # for block ordering when only a subset of blocks is spanned).
            spanned_top_layouts: List["BlockRowLayout"] = []
            spanned_bottom_layouts: List["BlockRowLayout"] = []
            if span_all:
                spanned_top_layouts = list(block_top_layouts)
                spanned_bottom_layouts = list(block_bottom_layouts)
            elif span_blocks is not None:
                for bid in span_blocks:
                    if bid == "__base__":
                        continue
                    rmb_layout = _rmb_layout_by_id.get(bid)
                    if rmb_layout:
                        if rmb_layout.block.placement == "top":
                            spanned_top_layouts.append(rmb_layout)
                        else:
                            spanned_bottom_layouts.append(rmb_layout)
            
            extra_top_rows = sum(l.num_rows for l in spanned_top_layouts)
            extra_bottom_rows = sum(l.num_rows for l in spanned_bottom_layouts)
            
            # Compute merge start/end from actual layout positions.
            # A merged cell must be contiguous in the grid.
            #
            # Region boundaries:
            #   top blocks:    [top_block_start_row .. data_start_row)
            #   base body:     [data_start_row .. data_start_row + num_body_rows)
            #   bottom blocks: [bottom_block_start_row .. bottom_block_start_row + num_bottom_block_rows)
            #
            # When specific span_blocks are named, compute start/end from the
            # actual block start_row positions (not the aggregate boundaries)
            # so that spanning e.g. only "blk-1" of two bottom blocks starts
            # at blk-1's actual start_row rather than the bottom_block_start_row.
            
            if include_base:
                # Base is included — start from base body
                region_start = data_start_row
                region_end = data_start_row + num_body_rows
                # Extend to top blocks
                if spanned_top_layouts:
                    top_min = min(l.start_row for l in spanned_top_layouts)
                    region_start = min(region_start, top_min)
                # Extend to bottom blocks
                if spanned_bottom_layouts:
                    bottom_max = max(l.start_row + l.num_rows for l in spanned_bottom_layouts)
                    region_end = max(region_end, bottom_max)
                merge_start = region_start
                total_span = region_end - region_start
            elif extra_top_rows > 0 and extra_bottom_rows > 0:
                # Both top and bottom blocks but no base — include base for
                # grid contiguity (a merged cell must be contiguous)
                top_min = min(l.start_row for l in spanned_top_layouts)
                bottom_max = max(l.start_row + l.num_rows for l in spanned_bottom_layouts)
                merge_start = top_min
                total_span = bottom_max - top_min
            elif extra_bottom_rows > 0:
                # Bottom blocks only — start at the first spanned block's
                # actual position (not bottom_block_start_row which is the
                # start of ALL bottom blocks)
                bottom_min = min(l.start_row for l in spanned_bottom_layouts)
                bottom_max = max(l.start_row + l.num_rows for l in spanned_bottom_layouts)
                merge_start = bottom_min
                total_span = bottom_max - bottom_min
            elif extra_top_rows > 0:
                # Top blocks only
                top_min = min(l.start_row for l in spanned_top_layouts)
                top_max = max(l.start_row + l.num_rows for l in spanned_top_layouts)
                merge_start = top_min
                total_span = top_max - top_min
            else:
                # No blocks, no base — nothing to span
                merge_start = data_start_row
                total_span = 0
            
            if total_span > 0:
                merged_cell = TablixCell(
                    row=merge_start,
                    col=col_idx,
                    role=CellRole.ROW_HEADER_BAND,
                    row_span=total_span,
                    label=band_col.label,
                    is_interactive=False,
                    rotate=getattr(band_col, 'rotate', False),
                )
                cells[merge_start][col_idx] = merged_cell
    
    # =========================================================================
    # Row headers and body cells
    # =========================================================================

    def _is_grouped_subtotal_leaf(layout: BlockColumnLayout, leaf_key: str) -> bool:
        if not layout.is_grouped:
            return False
        if str(leaf_key).endswith("__subtotal"):
            return True
        for band in (layout.header_bands or []):
            for cell_data in band:
                if (cell_data.get("key") == leaf_key) and (cell_data.get("isSubtotal") or False):
                    return True
        return False

    def _resolve_grouped_block_cell_data(
        row_cells: Dict[str, Dict[str, Any]],
        leaf_key: str,
        col_is_gt: bool,
        col_is_st: bool,
    ) -> Dict[str, Any]:
        """Resolve grouped block cell value with safe fallbacks for GT/subtotal keys."""
        cell_data = row_cells.get(leaf_key) or {}
        if cell_data:
            return cell_data

        if col_is_gt:
            return row_cells.get("__col_grand_total__") or row_cells.get("__all__") or {}

        if col_is_st:
            leaf_key_s = str(leaf_key)
            if not leaf_key_s.endswith("__subtotal"):
                by_suffix = row_cells.get(f"{leaf_key_s}__subtotal") or {}
                if by_suffix:
                    return by_suffix
            if leaf_key_s.endswith("__subtotal"):
                parent_key = leaf_key_s[: -len("__subtotal")]
                if parent_key.endswith(joiner):
                    parent_key = parent_key[: -len(joiner)]
                by_parent = row_cells.get(parent_key) or {}
                if by_parent:
                    return by_parent
                child_prefix = f"{parent_key}{joiner}" if parent_key else ""
                child_values: List[float] = []
                for key, child_cell in row_cells.items():
                    key_s = str(key)
                    if not key_s.startswith(child_prefix):
                        continue
                    if key_s == leaf_key_s or key_s.endswith("__subtotal"):
                        continue
                    v = (child_cell or {}).get("value")
                    if isinstance(v, (int, float)):
                        child_values.append(float(v))
                if child_values:
                    subtotal_value = float(sum(child_values))
                    if all(float(v).is_integer() for v in child_values):
                        subtotal_value = int(subtotal_value)
                    return {
                        "value": subtotal_value,
                        "formatted": f"{float(subtotal_value):,.2f}",
                    }
            return row_cells.get("__all__") or {}

        return {}

    for data_row_idx, row_key in enumerate(row_order):
        grid_row_idx = data_start_row + data_row_idx  # Offset by header rows
        node = row_node_map.get(row_key) or {}
        
        node_label = node.get("label") or row_key
        node_level = node.get("level") or 0
        node_indent = node.get("indent") or 0
        node_is_expandable = node.get("isExpandable") or False
        node_is_expanded = node.get("isExpanded") or False
        node_is_subtotal = node.get("isSubtotal") or False
        node_is_grand_total = node.get("isGrandTotal") or False
        
        row_path = key_to_path(row_key)
        
        # Determine row header role
        if node_is_grand_total:
            row_role = CellRole.GRAND_TOTAL
        elif node_is_subtotal:
            row_role = CellRole.SUBTOTAL
        elif node_is_expandable:
            row_role = CellRole.ROW_GROUP
        else:
            row_role = CellRole.ROW_HEADER
        
        # Determine row type for band column applicability
        row_type = _get_row_type(node_is_grand_total, node_is_subtotal, node_is_expandable)
        
        # Row header cell
        row_hdr_cell = TablixCell(
            row=grid_row_idx,
            col=row_header_start_col,
            role=row_role,
            row_key=row_key,
            row_path=row_path,
            label=node_label,
            level=node_level,
            indent=node_indent,
            is_expandable=node_is_expandable,
            is_expanded=node_is_expanded,
            is_subtotal=node_is_subtotal,
            is_grand_total=node_is_grand_total,
        )
        cells[grid_row_idx][row_header_start_col] = row_hdr_cell
        
        # Row Header Band Column Body Cells
        for band_idx, band_col in enumerate(row_header_band_cols):
            # Skip merged bands (already emitted as single spanning cell)
            if band_idx in merged_band_indices:
                continue
            
            col_idx = row_header_band_start_col + _row_band_level_map[band_idx]
            
            # Check if this band column applies to this row type
            if row_type not in band_col.applies_to:
                continue
            
            # Determine content based on band type
            if band_col.band_type == "label":
                band_value = band_col.label
            elif band_col.band_type == "row_attribute":
                # Show part of row path based on path_level
                path_level = band_col.path_level if band_col.path_level is not None else -1
                if row_path and len(row_path) > 0:
                    if path_level < 0:
                        # Negative index from end
                        idx = len(row_path) + path_level
                        band_value = row_path[idx] if 0 <= idx < len(row_path) else ""
                    else:
                        band_value = row_path[path_level] if path_level < len(row_path) else ""
                else:
                    band_value = ""
            elif band_col.band_type == "measure" and band_col.measure_id:
                # Get measure value for row (same as static column logic)
                measure_col = measure_by_id.get(band_col.measure_id)
                if measure_col:
                    row_cells = measure_col.get("cells") or {}
                    col_cells = row_cells.get(row_key) or {}
                    cell_data = col_cells.get("__col_grand_total__") or col_cells.get("__all__") or {}
                    band_value = cell_data.get("formatted") or cell_data.get("value") or ""
                else:
                    band_value = ""
            else:
                band_value = ""
            
            band_cell = TablixCell(
                row=grid_row_idx,
                col=col_idx,
                role=CellRole.ROW_HEADER_BAND,
                row_key=row_key,
                row_path=row_path,
                label=str(band_value) if band_value else "",
                level=node_level,
                is_subtotal=node_is_subtotal,
                is_grand_total=node_is_grand_total,
                is_interactive=False,
                rotate=getattr(band_col, 'rotate', False),
            )
            cells[grid_row_idx][col_idx] = band_cell
        
        # Static Left Column Body Cells (from column measure blocks)
        # For grouped blocks: multiple cells from block result
        # For simple blocks: single cell from main matrix
        for layout in block_left_layouts:
            block = layout.block
            is_cmb_breaker = block.measure_mode == "blank"
            
            # Check if this block applies to this row type
            if not _col_block_applies_to_row(block, row_type):
                # Cell is structurally absent (not just empty) - leave as None
                continue
            
            # Determine base cell role from row status
            if node_is_grand_total:
                base_cell_role = CellRole.GRAND_TOTAL
            elif node_is_subtotal:
                base_cell_role = CellRole.SUBTOTAL
            else:
                base_cell_role = CellRole.DETAIL
            
            # Generate cells for each leaf column in this block
            for leaf_idx, leaf_key in enumerate(layout.leaf_keys):
                col_idx = layout.start_col + leaf_idx
                
                # Detect column-level grand total / subtotal within this CMB block
                col_is_gt = (leaf_key == "__col_grand_total__") if layout.is_grouped else False
                col_is_st = _is_grouped_subtotal_leaf(layout, leaf_key)
                
                # Final cell role: promote to GT/subtotal if column is GT/subtotal
                if col_is_gt or node_is_grand_total:
                    cell_role = CellRole.GRAND_TOTAL
                elif col_is_st or node_is_subtotal:
                    cell_role = CellRole.SUBTOTAL
                else:
                    cell_role = base_cell_role
                
                # Determine measure name for this leaf
                # For base mode: extract from key like "__base_Total Sales__"
                # For explicit mode: use block.measure_id
                if leaf_key.startswith("__base_") and leaf_key.endswith("__"):
                    leaf_measure_name = leaf_key[7:-2]  # Remove prefix and suffix
                else:
                    leaf_measure_name = block.measure_id
                
                # Get cell data from block layout (already populated from block_results or main matrix)
                # For subtotal rows, try both the full subtotal key and the parent key
                # The block subquery may not have the __subtotal suffix on its keys
                # For expanded parent rows, try the subtotal key as fallback
                parent_key = None
                row_cells = layout.cells.get(row_key)
                if not row_cells and row_key.endswith('__subtotal'):
                    # Try parent key (without __subtotal suffix)
                    parent_key = row_key[:-len('__subtotal')]
                    if parent_key.endswith(joiner):
                        parent_key = parent_key[: -len(joiner)]
                    row_cells = layout.cells.get(parent_key)
                if not row_cells and not row_key.endswith('__subtotal') and row_key != "__grand_total__":
                    # For expanded parent rows, try the subtotal key
                    subtotal_key = f"{row_key}__subtotal"
                    row_cells = layout.cells.get(subtotal_key)
                row_cells = row_cells or {}
                cell_data = _resolve_grouped_block_cell_data(row_cells, leaf_key, col_is_gt, col_is_st) if layout.is_grouped else (row_cells.get(leaf_key) or {})
                # FIX: For grouped blocks, a missing column value means no data
                # for that row×column combination. Do NOT fall back to
                # __col_grand_total__ which would incorrectly show the row total
                # in every column.
                if not cell_data and row_cells and not layout.is_grouped:
                    cell_data = row_cells.get("__col_grand_total__") or row_cells.get("__all__") or {}
                if not cell_data and measure_by_id and not layout.is_grouped:
                    measure_col_main = measure_by_id.get(leaf_measure_name) or measure_by_id.get(block.measure_id)
                    if measure_col_main:
                        main_cells = measure_col_main.get("cells") or {}
                        main_row_cells = main_cells.get(row_key)
                        if main_row_cells is None and parent_key:
                            main_row_cells = main_cells.get(parent_key)
                        if main_row_cells is None and row_key != "__grand_total__":
                            main_row_cells = main_cells.get(f"{row_key}__subtotal")
                        if main_row_cells:
                            cell_data = main_row_cells.get("__col_grand_total__") or main_row_cells.get("__all__") or {}
                
                value = cell_data.get("value")
                formatted = cell_data.get("formatted")
                bar_spec = cell_data.get("barSpec")
                cond_fmt = cell_data.get("condFmt")
                
                # For simple (non-grouped) blocks, col_key is None (static column bound by row only)
                # For grouped blocks, col_key is the leaf key from the block's axis
                effective_col_key = leaf_key if layout.is_grouped else None
                
                static_cell = TablixCell(
                    row=grid_row_idx,
                    col=col_idx,
                    role=cell_role,
                    row_key=row_key,
                    col_key=effective_col_key,
                    row_path=row_path,
                    value=None if is_cmb_breaker else value,
                    formatted="" if is_cmb_breaker else formatted,
                    measure_name=leaf_measure_name,
                    format_string=layout.format_string,
                    bar_spec=None if is_cmb_breaker else bar_spec,
                    cond_fmt=None if is_cmb_breaker else cond_fmt,
                    is_subtotal=node_is_subtotal or col_is_st,
                    is_grand_total=node_is_grand_total or col_is_gt,
                    col_block_index=layout.block_idx,
                    is_breaker=is_cmb_breaker,
                )
                cells[grid_row_idx][col_idx] = static_cell
        
        # Pivoted Body cells (values)
        col_offset = pivot_body_start_col
        for col_key in (col_leaf_keys or ["__all__"]):
            col_path = key_to_path(col_key)
            col_is_gt = col_key == "__col_grand_total__"
            
            for measure_col in (values or [{"measure": {"name": "Value"}, "cells": {}}]):
                measure_info = measure_col.get("measure") or {}
                measure_name = measure_info.get("name") or "Value"
                format_string = measure_info.get("formatString")
                
                # Get cell value from MatrixResult
                row_cells = measure_col.get("cells") or {}
                col_cells = row_cells.get(row_key) or {}
                cell_data = col_cells.get(col_key) or {}
                
                value = cell_data.get("value")
                formatted = cell_data.get("formatted")
                bar_spec = cell_data.get("barSpec")
                cond_fmt = cell_data.get("condFmt")
                
                # Determine cell role
                if node_is_grand_total or col_is_gt:
                    cell_role = CellRole.GRAND_TOTAL
                elif node_is_subtotal:
                    cell_role = CellRole.SUBTOTAL
                else:
                    cell_role = CellRole.DETAIL
                
                body_cell = TablixCell(
                    row=grid_row_idx,
                    col=col_offset,
                    role=cell_role,
                    row_key=row_key,
                    col_key=col_key,
                    row_path=row_path,
                    col_path=col_path,
                    value=value,
                    formatted=formatted,
                    measure_name=measure_name,
                    format_string=format_string,
                    bar_spec=bar_spec,
                    cond_fmt=cond_fmt,
                    is_subtotal=node_is_subtotal,
                    is_grand_total=node_is_grand_total or col_is_gt,
                )
                cells[grid_row_idx][col_offset] = body_cell
                col_offset += 1
        
        # Static Right Column Body Cells (from column measure blocks)
        # For grouped blocks: multiple cells from block result
        # For simple blocks: single cell from main matrix
        for layout in block_right_layouts:
            block = layout.block
            is_cmb_breaker = block.measure_mode == "blank"
            
            # Check if this block applies to this row type
            if not _col_block_applies_to_row(block, row_type):
                # Cell is structurally absent (not just empty) - leave as None
                continue
            
            # Determine base cell role from row status
            if node_is_grand_total:
                base_cell_role = CellRole.GRAND_TOTAL
            elif node_is_subtotal:
                base_cell_role = CellRole.SUBTOTAL
            else:
                base_cell_role = CellRole.DETAIL
            
            # Generate cells for each leaf column in this block
            for leaf_idx, leaf_key in enumerate(layout.leaf_keys):
                col_idx = layout.start_col + leaf_idx
                
                # Detect column-level grand total / subtotal within this CMB block
                col_is_gt = (leaf_key == "__col_grand_total__") if layout.is_grouped else False
                col_is_st = _is_grouped_subtotal_leaf(layout, leaf_key)
                
                # Final cell role: promote to GT/subtotal if column is GT/subtotal
                if col_is_gt or node_is_grand_total:
                    cell_role = CellRole.GRAND_TOTAL
                elif col_is_st or node_is_subtotal:
                    cell_role = CellRole.SUBTOTAL
                else:
                    cell_role = base_cell_role
                
                # Determine measure name for this leaf
                # For base mode: extract from key like "__base_Total Sales__"
                # For explicit mode: use block.measure_id
                if leaf_key.startswith("__base_") and leaf_key.endswith("__"):
                    leaf_measure_name = leaf_key[7:-2]  # Remove prefix and suffix
                else:
                    leaf_measure_name = block.measure_id
                
                # Get cell data from block layout
                # For subtotal rows, try both the full subtotal key and the parent key
                # The block subquery may not have the __subtotal suffix on its keys
                # For expanded parent rows, try the subtotal key as fallback
                row_cells = layout.cells.get(row_key)
                parent_key = None
                if not row_cells and row_key.endswith('__subtotal'):
                    # Try parent key (without __subtotal suffix)
                    parent_key = row_key[:-len('__subtotal')]
                    if parent_key.endswith(joiner):
                        parent_key = parent_key[: -len(joiner)]
                    row_cells = layout.cells.get(parent_key)
                if not row_cells and not row_key.endswith('__subtotal') and row_key != "__grand_total__":
                    # For expanded parent rows, try the subtotal key
                    subtotal_key = f"{row_key}__subtotal"
                    row_cells = layout.cells.get(subtotal_key)
                row_cells = row_cells or {}
                cell_data = _resolve_grouped_block_cell_data(row_cells, leaf_key, col_is_gt, col_is_st) if layout.is_grouped else (row_cells.get(leaf_key) or {})
                # FIX: For grouped blocks, a missing column value means no data
                # for that row×column combination. Do NOT fall back to
                # __col_grand_total__ which would incorrectly show the row total
                # in every column.
                if not cell_data and row_cells and not layout.is_grouped:
                    cell_data = row_cells.get("__col_grand_total__") or row_cells.get("__all__") or {}
                if not cell_data and measure_by_id and not layout.is_grouped:
                    measure_col_main = measure_by_id.get(leaf_measure_name) or measure_by_id.get(block.measure_id)
                    if measure_col_main:
                        main_cells = measure_col_main.get("cells") or {}
                        main_row_cells = main_cells.get(row_key)
                        if main_row_cells is None and parent_key:
                            main_row_cells = main_cells.get(parent_key)
                        if main_row_cells is None and row_key != "__grand_total__":
                            main_row_cells = main_cells.get(f"{row_key}__subtotal")
                        if main_row_cells:
                            cell_data = main_row_cells.get("__col_grand_total__") or main_row_cells.get("__all__") or {}
                
                value = cell_data.get("value")
                formatted = cell_data.get("formatted")
                bar_spec = cell_data.get("barSpec")
                cond_fmt = cell_data.get("condFmt")
                
                # For simple (non-grouped) blocks, col_key is None (static column bound by row only)
                # For grouped blocks, col_key is the leaf key from the block's axis
                effective_col_key = leaf_key if layout.is_grouped else None
                
                static_cell = TablixCell(
                    row=grid_row_idx,
                    col=col_idx,
                    role=cell_role,
                    row_key=row_key,
                    col_key=effective_col_key,
                    row_path=row_path,
                    value=None if is_cmb_breaker else value,
                    formatted="" if is_cmb_breaker else formatted,
                    measure_name=leaf_measure_name,
                    format_string=layout.format_string,
                    bar_spec=None if is_cmb_breaker else bar_spec,
                    cond_fmt=None if is_cmb_breaker else cond_fmt,
                    is_subtotal=node_is_subtotal or col_is_st,
                    is_grand_total=node_is_grand_total or col_is_gt,
                    col_block_index=layout.block_idx,
                    is_breaker=is_cmb_breaker,
                )
                cells[grid_row_idx][col_idx] = static_cell
    
    # =========================================================================
    # Row Measure Block Body Rows (Top and Bottom)
    # Render block rows aligned to main matrix column axis
    # =========================================================================

    def _row_block_visible_row_keys(layout: BlockRowLayout) -> List[str]:
        """Return visible row keys for a row block based on its toggles."""
        block = layout.block
        row_order = layout.row_order if layout.row_order else (layout.leaf_keys or ["__all__"])
        node_map = {n.get("key"): n for n in (layout.row_tree or []) if isinstance(n, dict)}

        visible: List[str] = []
        for key in row_order:
            node = node_map.get(key)

            is_gt = key == "__grand_total__" or (node and node.get("isGrandTotal"))
            if is_gt:
                if block.show_gt:
                    visible.append(key)
                continue

            if node and node.get("isSubtotal"):
                if not block.show_sub:
                    continue
                if _level_disabled(node.get("level"), block.subtotal_levels, use_parent_level=False):
                    continue
                visible.append(key)
                continue

            if node:
                children = node.get("childrenKeys") or []
                is_leaf = len(children) == 0
                if is_leaf:
                    if block.show_leaf:
                        visible.append(key)
                else:
                    if block.show_grp:
                        visible.append(key)
            else:
                # No node metadata: treat as leaf
                if block.show_leaf:
                    visible.append(key)

        if not visible:
            return ["__row_block_empty__"]

        return visible
    
    def _render_row_block(layout: BlockRowLayout, cells: List[List[Optional[TablixCell]]]) -> None:
        """Render cells for a row measure block."""
        block = layout.block
        block_row_order = _row_block_visible_row_keys(layout)

        def _resolve_overlap_row_cells(
            overlap_cells: Dict[str, Dict[str, Dict[str, Any]]],
            row_key: str,
        ) -> Dict[str, Dict[str, Any]]:
            row_cells = overlap_cells.get(row_key)
            parent_key = None
            if not row_cells and row_key.endswith('__subtotal'):
                parent_key = row_key[:-len('__subtotal')]
                if parent_key.endswith(joiner):
                    parent_key = parent_key[: -len(joiner)]
                row_cells = overlap_cells.get(parent_key)
            if not row_cells and not row_key.endswith('__subtotal') and row_key != "__grand_total__":
                subtotal_key = f"{row_key}__subtotal"
                row_cells = overlap_cells.get(subtotal_key)
            return row_cells or {}
        
        # Breaker flag for blank mode blocks (transparent, no borders)
        is_breaker = block.measure_mode == "blank"
        
        for local_row_idx, block_row_key in enumerate(block_row_order):
            grid_row_idx = layout.start_row + local_row_idx

            if block_row_key == "__row_block_empty__":
                row_label = "Row block hidden (no row types selected)"
                row_level = 0
                row_indent = 0
                is_gt = False
                is_sub = False
                is_expandable = False
                is_expanded = False
            else:
                is_gt = False
                is_sub = False
                is_expandable = False
                is_expanded = False
                row_level = 0
                row_indent = 0
            
                # Row header cell for this block row
                if layout.is_grouped and layout.row_tree:
                    # Find the node for this row key
                    block_node = next(
                        (n for n in layout.row_tree if n.get("key") == block_row_key),
                        {}
                    )
                    row_label = block_node.get("label") or block_row_key
                    is_gt = block_node.get("isGrandTotal") or False
                    is_sub = block_node.get("isSubtotal") or False
                    is_expandable = block_node.get("isExpandable") or bool(block_node.get("childrenKeys"))
                    is_expanded = block_node.get("isExpanded") or False
                    row_level = block_node.get("level") or 0
                    row_indent = block_node.get("indent") or 0
                else:
                    # Simple block - use block label, fallback to measure_id, or "Grand Total" for base mode
                    if block.label:
                        row_label = block.label
                    elif block.measure_id:
                        row_label = block.measure_id
                    elif block.measure_mode in ("base", "base_calc"):
                        row_label = "Grand Total"
                    else:
                        row_label = "Block"
                    # For simple base mode blocks, treat as grand total row type
                    # (affects styling/applicability checks)
                    # Explicit mode simple blocks are NOT grand totals - they're just single-row blocks
                    is_gt = block.measure_mode in ("base", "base_calc")
            
            row_type = _get_row_type(is_gt, is_sub, is_expandable)

            # Row header - always use ROW_BLOCK role for row blocks
            row_hdr_cell = TablixCell(
                row=grid_row_idx,
                col=row_header_start_col,
                role=CellRole.ROW_BLOCK,
                row_key=block_row_key,
                row_path=key_to_path(block_row_key),
                label=row_label if not is_breaker else "",
                level=row_level,
                indent=row_indent,
                is_expandable=is_expandable,
                is_expanded=is_expanded,
                is_subtotal=is_sub,
                measure_name=block.measure_id,
                is_grand_total=is_gt,
                is_interactive=False,
                row_block_index=layout.block_idx,
                is_breaker=is_breaker,
            )
            cells[grid_row_idx][row_header_start_col] = row_hdr_cell
            
            # Row header band columns (empty for block rows, skip if merged band covers this row)
            for band_idx, _band_col in enumerate(row_header_band_cols):
                if band_idx in merged_band_indices:
                    continue  # merged band cell already spans this row
                col_idx = row_header_band_start_col + _row_band_level_map[band_idx]
                band_cell = TablixCell(
                    row=grid_row_idx,
                    col=col_idx,
                    role=CellRole.ROW_BLOCK,
                    row_key=block_row_key,
                    row_path=key_to_path(block_row_key),
                    label="",
                    is_interactive=False,
                    is_subtotal=is_sub,
                    is_grand_total=is_gt,
                    row_block_index=layout.block_idx,
                    is_breaker=is_breaker,
                )
                cells[grid_row_idx][col_idx] = band_cell
            
            # Static left column cells (for row blocks - look up from OVERLAP result)
            # These are the overlap region: row block rows × column block columns
            # Uses layout.overlap_cells_by_col_block which is keyed per column block ID
            for col_layout in block_left_layouts:
                if not _col_block_applies_to_row(col_layout.block, row_type):
                    continue
                # Get overlap cells for this specific column block (keyed by block_id)
                col_block_overlap = layout.overlap_cells_by_col_block.get(col_layout.block_id) or {}
                for leaf_idx, leaf_key in enumerate(col_layout.leaf_keys):
                    if hide_col_grand_total and leaf_key == "__col_grand_total__":
                        continue
                    col_idx = col_layout.start_col + leaf_idx
                    
                    # Detect column-level grand total / subtotal within this CMB block
                    col_is_gt = (leaf_key == "__col_grand_total__") if col_layout.is_grouped else False
                    col_is_st = _is_grouped_subtotal_leaf(col_layout, leaf_key)
                    
                    # Look up cell data from OVERLAP result (pairwise query per block pair)
                    # For base mode simple blocks: leaf_key is __base_X__ but overlap uses __all__
                    row_cells = _resolve_overlap_row_cells(col_block_overlap, block_row_key)
                    
                    # Determine the lookup key for overlap cells
                    # Base mode simple blocks have __base_X__ keys but overlap query uses __all__
                    if leaf_key.startswith("__base_") and leaf_key.endswith("__"):
                        overlap_lookup_key = "__all__"
                    else:
                        overlap_lookup_key = leaf_key
                    
                    cell_data = row_cells.get(overlap_lookup_key) or {}
                    if not cell_data and col_layout.is_grouped:
                        cell_data = _resolve_grouped_block_cell_data(row_cells, leaf_key, col_is_gt, col_is_st)
                    value = cell_data.get("value")
                    formatted = cell_data.get("formatted")
                    bar_spec = cell_data.get("barSpec")
                    cond_fmt = cell_data.get("condFmt")
                    
                    # Intersection rule: blank if row block measure differs from column block measure
                    # This keeps the overlap region clean when blocks have different measures
                    if _should_blank_intersection(block, col_layout.block):
                        value = None
                        formatted = ""
                        bar_spec = None
                        cond_fmt = None
                        value = None
                        formatted = ""
                        bar_spec = None
                    
                    block_cell = TablixCell(
                        row=grid_row_idx,
                        col=col_idx,
                        role=CellRole.ROW_BLOCK,
                        row_key=block_row_key,
                        col_key=leaf_key,
                        row_path=key_to_path(block_row_key),
                        col_path=key_to_path(leaf_key),
                        value=value,
                        formatted=formatted,
                        measure_name=block.measure_id,  # Use row block's measure
                        format_string=layout.format_string,
                        bar_spec=bar_spec,
                        cond_fmt=cond_fmt,
                        is_subtotal=is_sub or col_is_st,
                        is_grand_total=is_gt or col_is_gt,
                        is_interactive=False,
                        row_block_index=layout.block_idx,
                        col_block_index=col_layout.block_idx,  # Mark as overlap cell
                        is_breaker=is_breaker,
                    )
                    cells[grid_row_idx][col_idx] = block_cell
            
            # Pivot body cells for this block row (aligned to main column axis)
            col_offset = pivot_body_start_col
            for col_key in (col_leaf_keys or ["__all__"]):
                col_path = key_to_path(col_key)
                col_is_gt = col_key == "__col_grand_total__"
                
                # For row blocks, we only have one measure per block
                # Get cell from block's cells data
                row_cells = layout.cells.get(block_row_key) or {}
                cell_data = row_cells.get(col_key) or {}
                
                value = cell_data.get("value")
                formatted = cell_data.get("formatted")
                bar_spec = cell_data.get("barSpec")
                cond_fmt = cell_data.get("condFmt")
                
                # Row block cells always use ROW_BLOCK role
                body_cell = TablixCell(
                    row=grid_row_idx,
                    col=col_offset,
                    role=CellRole.ROW_BLOCK,
                    row_key=block_row_key,
                    col_key=col_key,
                    row_path=key_to_path(block_row_key),
                    col_path=col_path,
                    value=value if not is_breaker else None,
                    formatted=formatted if not is_breaker else "",
                    measure_name=block.measure_id,
                    format_string=layout.format_string,
                    bar_spec=bar_spec if not is_breaker else None,
                    cond_fmt=cond_fmt if not is_breaker else None,
                    is_subtotal=is_sub,
                    is_grand_total=is_gt or col_is_gt,
                    row_block_index=layout.block_idx,
                    is_breaker=is_breaker,
                )
                cells[grid_row_idx][col_offset] = body_cell
                col_offset += 1
                
                # If multiple measures in main matrix, skip remaining pivot cols for row blocks
                # Row blocks only have their single measure
            
            # Adjust col_offset to skip any additional measure columns in pivot body
            # since row blocks don't repeat across multiple measures
            if num_measures > 1:
                # We already placed one cell per col_key, but pivot body has num_measures per col_key
                # Need to place empty cells for the remaining measure slots
                for col_key in (col_leaf_keys or ["__all__"]):
                    for extra_m in range(1, num_measures):
                        # Calculate the column index for this extra measure slot
                        base_col = pivot_body_start_col + (col_leaf_keys or ["__all__"]).index(col_key) * num_measures
                        extra_col = base_col + extra_m
                        # Place empty cell
                        empty_cell = TablixCell(
                            row=grid_row_idx,
                            col=extra_col,
                            role=CellRole.ROW_BLOCK,
                            row_key=block_row_key,
                            col_key=col_key,
                            label="",  # Empty for non-block measures
                            is_interactive=False,
                            is_subtotal=is_sub,
                            is_grand_total=is_gt,
                            row_block_index=layout.block_idx,
                            is_breaker=is_breaker,
                        )
                        cells[grid_row_idx][extra_col] = empty_cell
            
            # Static right column cells (for row blocks - look up from OVERLAP result)
            # These are the overlap region: row block rows × column block columns
            # Uses layout.overlap_cells_by_col_block which is keyed per column block ID
            for col_layout in block_right_layouts:
                if not _col_block_applies_to_row(col_layout.block, row_type):
                    continue
                # Get overlap cells for this specific column block (keyed by block_id)
                col_block_overlap = layout.overlap_cells_by_col_block.get(col_layout.block_id) or {}
                for leaf_idx, leaf_key in enumerate(col_layout.leaf_keys):
                    if hide_col_grand_total and leaf_key == "__col_grand_total__":
                        continue
                    col_idx = col_layout.start_col + leaf_idx
                    
                    # Detect column-level grand total / subtotal within this CMB block
                    col_is_gt = (leaf_key == "__col_grand_total__") if col_layout.is_grouped else False
                    col_is_st = _is_grouped_subtotal_leaf(col_layout, leaf_key)
                    
                    # Look up cell data from OVERLAP result (pairwise query per block pair)
                    # For base mode simple blocks: leaf_key is __base_X__ but overlap uses __all__
                    row_cells = _resolve_overlap_row_cells(col_block_overlap, block_row_key)
                    
                    # Determine the lookup key for overlap cells
                    # Base mode simple blocks have __base_X__ keys but overlap query uses __all__
                    if leaf_key.startswith("__base_") and leaf_key.endswith("__"):
                        overlap_lookup_key = "__all__"
                    else:
                        overlap_lookup_key = leaf_key
                    
                    cell_data = row_cells.get(overlap_lookup_key) or {}
                    if not cell_data and col_layout.is_grouped:
                        cell_data = _resolve_grouped_block_cell_data(row_cells, leaf_key, col_is_gt, col_is_st)
                    value = cell_data.get("value")
                    formatted = cell_data.get("formatted")
                    bar_spec = cell_data.get("barSpec")
                    cond_fmt = cell_data.get("condFmt")
                    
                    # Intersection rule: blank if row block measure differs from column block measure
                    if _should_blank_intersection(block, col_layout.block):
                        value = None
                        formatted = ""
                        bar_spec = None
                        cond_fmt = None
                        value = None
                        formatted = ""
                        bar_spec = None
                    
                    block_cell = TablixCell(
                        row=grid_row_idx,
                        col=col_idx,
                        role=CellRole.ROW_BLOCK,
                        row_key=block_row_key,
                        col_key=leaf_key,
                        row_path=key_to_path(block_row_key),
                        col_path=key_to_path(leaf_key),
                        value=value,
                        formatted=formatted,
                        measure_name=block.measure_id,
                        format_string=layout.format_string,
                        bar_spec=bar_spec,
                        cond_fmt=cond_fmt,
                        is_subtotal=is_sub or col_is_st,
                        is_grand_total=is_gt or col_is_gt,
                        is_interactive=False,
                        row_block_index=layout.block_idx,
                        col_block_index=col_layout.block_idx,
                        is_breaker=is_breaker,
                    )
                    cells[grid_row_idx][col_idx] = block_cell
    
    # Render top row blocks
    for layout in block_top_layouts:
        _render_row_block(layout, cells)
    
    # Render bottom row blocks
    for layout in block_bottom_layouts:
        _render_row_block(layout, cells)
    
    # =========================================================================
    # Build regions
    # =========================================================================
    
    # Corner region spans: all header rows (incl band rows) x row header columns (excl band cols)
    corner_region = TablixRegion(
        start_row=0,
        end_row=total_col_header_rows - 1,
        start_col=row_header_start_col,
        end_col=row_header_start_col + num_row_header_cols - 1,
        region_type="corner",
    )
    
    # Column header bands region (if any) - rows 0..num_col_header_band_rows-1
    col_header_bands_region: Optional[TablixRegion] = None
    if num_col_header_band_rows > 0:
        col_header_bands_region = TablixRegion(
            start_row=0,
            end_row=num_col_header_band_rows - 1,
            start_col=pivot_body_start_col,
            end_col=num_cols - 1,
            region_type="col_header_bands",
        )
    
    # Row header bands region (if any) - column indices for band columns
    row_header_bands_region: Optional[TablixRegion] = None
    if num_row_header_band_cols > 0:
        row_header_bands_region = TablixRegion(
            start_row=data_start_row,
            end_row=num_rows - 1,
            start_col=row_header_band_start_col,
            end_col=row_header_band_start_col + num_row_header_band_cols - 1,
            region_type="row_header_bands",
        )
    
    col_headers_region = TablixRegion(
        start_row=col_header_start_row,
        end_row=total_col_header_rows - 1,
        start_col=pivot_body_start_col,
        end_col=num_cols - 1,
        region_type="col_headers",
    ) if num_cols > num_row_header_cols else None
    
    row_headers_region = TablixRegion(
        start_row=data_start_row,
        end_row=num_rows - 1,
        start_col=row_header_start_col,
        end_col=row_header_start_col + num_row_header_cols - 1,
        region_type="row_headers",
    ) if num_rows > total_col_header_rows else None
    
    # Body region: covers static left + pivot + static right
    body_region = TablixRegion(
        start_row=data_start_row,
        end_row=num_rows - 1,
        start_col=static_left_start_col,
        end_col=num_cols - 1,
        region_type="body",
    ) if num_rows > total_col_header_rows and num_cols > num_row_header_cols else None
    
    # Static left region (if any)
    static_left_region: Optional[TablixRegion] = None
    if num_static_left > 0 and num_data_rows > 0:
        static_left_region = TablixRegion(
            start_row=data_start_row,
            end_row=num_rows - 1,
            start_col=static_left_start_col,
            end_col=static_left_start_col + num_static_left - 1,
            region_type="body",  # Part of body semantically
        )
    
    # Static right region (if any)
    static_right_region: Optional[TablixRegion] = None
    if num_static_right > 0 and num_data_rows > 0:
        static_right_region = TablixRegion(
            start_row=data_start_row,
            end_row=num_rows - 1,
            start_col=static_right_start_col,
            end_col=static_right_start_col + num_static_right - 1,
            region_type="body",  # Part of body semantically
        )
    
    # =========================================================================
    # Build row definitions
    # =========================================================================
    row_defs: List[TablixRowDef] = []
    
    # Column header band rows
    for i in range(num_col_header_band_rows):
        row_defs.append(TablixRowDef(
            index=i,
            is_header_row=True,
            is_header_band_row=True,
        ))
    
    # Column header rows (including measure row)
    for i in range(num_col_header_rows):
        row_defs.append(TablixRowDef(
            index=col_header_start_row + i,
            is_header_row=True,
        ))
    
    # Data rows
    for data_row_idx, row_key in enumerate(row_order):
        node = row_node_map.get(row_key) or {}
        row_defs.append(TablixRowDef(
            index=data_start_row + data_row_idx,
            key=row_key,
            level=node.get("level") or 0,
            is_subtotal=node.get("isSubtotal") or False,
            is_grand_total=node.get("isGrandTotal") or False,
        ))
    
    # Top row block rows
    for layout in block_top_layouts:
        block_row_order = layout.row_order if layout.row_order else ["__all__"]
        for local_idx, block_row_key in enumerate(block_row_order):
            is_gt = block_row_key in ("__grand_total__", "__all__")
            row_defs.append(TablixRowDef(
                index=layout.start_row + local_idx,
                key=block_row_key,
                is_row_block=True,
                measure_name=layout.block.measure_id,
                is_grand_total=is_gt,
            ))
    
    # Bottom row block rows
    for layout in block_bottom_layouts:
        block_row_order = layout.row_order if layout.row_order else ["__all__"]
        for local_idx, block_row_key in enumerate(block_row_order):
            is_gt = block_row_key in ("__grand_total__", "__all__")
            row_defs.append(TablixRowDef(
                index=layout.start_row + local_idx,
                key=block_row_key,
                is_row_block=True,
                measure_name=layout.block.measure_id,
                is_grand_total=is_gt,
            ))
    
    # =========================================================================
    # Build column definitions
    # =========================================================================
    col_defs: List[TablixColDef] = []
    
    # Row header band columns (leftmost, before row headers)
    # Deduplicate: bands sharing a display_level map to the same grid column.
    _row_band_cols_emitted: Set[int] = set()
    for idx, band_col in enumerate(row_header_band_cols):
        grid_col = _row_band_level_map[idx]
        if grid_col in _row_band_cols_emitted:
            continue
        _row_band_cols_emitted.add(grid_col)
        col_defs.append(TablixColDef(
            index=row_header_band_start_col + grid_col,
            is_row_header_col=True,
            is_header_band_col=True,
            measure_name=band_col.measure_id if band_col.band_type == "measure" else None,
        ))
    
    # Row header column (after band columns)
    col_defs.append(TablixColDef(
        index=row_header_start_col,
        is_row_header_col=True,
    ))
    
    # Static left columns (from column measure blocks - may be expanded for grouped blocks)
    for layout in block_left_layouts:
        is_cmb_breaker = layout.block.measure_mode == "blank"
        for leaf_idx, leaf_key in enumerate(layout.leaf_keys):
            col_defs.append(TablixColDef(
                index=layout.start_col + leaf_idx,
                key=leaf_key,
                measure_name=layout.block.measure_id,
                is_static_measure=True,
                static_placement="left",
                col_block_index=layout.block_idx,
                is_breaker=is_cmb_breaker,
            ))
    
    # Pivoted value columns
    col_offset = pivot_body_start_col
    for col_key in (col_leaf_keys or ["__all__"]):
        col_is_gt = col_key == "__col_grand_total__"
        col_is_st = col_key in subtotal_meta_by_col_key
        for measure_col in (values or [{"measure": {"name": "Value"}}]):
            measure_info = measure_col.get("measure") or {}
            measure_name = measure_info.get("name") or "Value"
            
            col_defs.append(TablixColDef(
                index=col_offset,
                key=col_key,
                measure_name=measure_name,
                is_grand_total=col_is_gt,
                is_subtotal=col_is_st,
            ))
            col_offset += 1
    
    # Static right columns (from column measure blocks - may be expanded for grouped blocks)
    for layout in block_right_layouts:
        is_cmb_breaker = layout.block.measure_mode == "blank"
        for leaf_idx, leaf_key in enumerate(layout.leaf_keys):
            col_defs.append(TablixColDef(
                index=layout.start_col + leaf_idx,
                key=leaf_key,
                measure_name=layout.block.measure_id,
                is_static_measure=True,
                static_placement="right",
                col_block_index=layout.block_idx,
                is_breaker=is_cmb_breaker,
            ))
    
    # =========================================================================
    # Gap-fill row header band columns
    # =========================================================================
    # Merged band cells may not cover all body+block rows, leaving NULL gaps
    # that render as white unstyled <td> elements.  Fill them with empty
    # ROW_HEADER_BAND cells so the band background is continuous.
    if num_row_header_band_cols > 0 and row_header_band_cols:
        _band_grid_cols = sorted(set(_row_band_level_map.values()))
        _body_row_start = top_block_start_row          # first body-region row
        _body_row_end = num_rows                       # one past last row
        for _gc in _band_grid_cols:
            _ci = row_header_band_start_col + _gc
            # Build set of rows already covered (directly or via rowSpan)
            _covered: set = set()
            for _r in range(_body_row_start, _body_row_end):
                _c = cells[_r][_ci]
                if _c is not None:
                    _span = _c.row_span if _c.row_span else 1
                    for _sr in range(_r, _r + _span):
                        _covered.add(_sr)
            # Fill uncovered positions
            for _r in range(_body_row_start, _body_row_end):
                if _r not in _covered:
                    cells[_r][_ci] = TablixCell(
                        row=_r,
                        col=_ci,
                        role=CellRole.ROW_HEADER_BAND,
                        label="",
                        is_interactive=False,
                    )

    # =========================================================================
    # Build final TablixPlan
    # =========================================================================

    # Post-process: mark cells from non-grouped blocks so the frontend
    # can color them as grand-total-equivalent (no extra columns/rows added).
    # A block is "base" when it has no grouping fields (is_grouped == False),
    # meaning the measure is evaluated without additional row/column context.
    _base_col_block_indices: set = set()
    for layout in block_left_layouts + block_right_layouts:
        if not layout.block.is_grouped:
            _base_col_block_indices.add(layout.block_idx)
    _base_row_block_indices: set = set()
    for idx_rb, rb in enumerate(row_blocks_to_use):
        if not rb.is_grouped:
            _base_row_block_indices.add(idx_rb)
    if _base_col_block_indices or _base_row_block_indices:
        for row in cells:
            for cell in row:
                if cell is None:
                    continue
                if cell.col_block_index is not None and cell.col_block_index in _base_col_block_indices:
                    cell.is_base_block = True
                elif cell.row_block_index is not None and cell.row_block_index in _base_row_block_indices:
                    cell.is_base_block = True

    plan = TablixPlan(
        num_rows=num_rows,
        num_cols=num_cols,
        num_col_header_rows=total_col_header_rows,
        num_row_header_cols=num_row_header_cols,
        num_col_header_band_rows=num_col_header_band_rows,
        num_row_header_band_cols=num_row_header_band_cols,
        num_static_left_cols=num_static_left,
        num_static_right_cols=num_static_right,
        cells=cells,
        corner=corner_region,
        col_headers=col_headers_region,
        row_headers=row_headers_region,
        body=body_region,
        static_left=static_left_region,
        static_right=static_right_region,
        col_header_bands=col_header_bands_region,
        row_header_bands=row_header_bands_region,
        row_defs=row_defs,
        col_defs=col_defs,
        properties=props,
        interaction=interaction,
        debug={"source": "matrix_to_tablix"} if debug else None,
    )
    
    return plan
