"""TablixPlan v2 — Mixed Regions and Multi-Measure Layout.

Extends TablixPlan v1 with:
1. Mixed region support (independent column groups per region)
2. Multi-measure layout modes
3. Cross-tab style (measures as rows)

Backward compatible: "nested" mode produces identical output to v1.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from .tablix import (
    CellRole,
    TablixCell,
    TablixColDef,
    TablixPlan,
    TablixProperties,
    TablixRegion,
    TablixRowDef,
)
from .tablix_compiler import compile_matrix_to_tablix

# Valid layout modes
_VALID_LAYOUT_MODES = frozenset({"nested", "extra_columns", "cross_tab"})


# =============================================================================
# Mixed Region
# =============================================================================


@dataclass
class MixedRegion:
    """A region with its own independent column groups.

    Mixed regions allow different parts of the tablix to pivot on different
    column group fields.  For example, one region may pivot on ``[Year]``
    while a neighbouring region shows static KPI columns with no pivoting.
    """

    name: str
    region: TablixRegion
    column_groups: List[str] = field(default_factory=list)  # Column group field names
    measures: List[str] = field(default_factory=list)  # Measures rendered here
    is_static: bool = False  # True ⇒ no column pivoting

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "region": self.region.to_dict(),
            "columnGroups": self.column_groups,
            "measures": self.measures,
            "isStatic": self.is_static,
        }
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MixedRegion":
        region_raw = data.get("region") or {}
        region = TablixRegion(
            start_row=region_raw.get("startRow", 0),
            end_row=region_raw.get("endRow", 0),
            start_col=region_raw.get("startCol", 0),
            end_col=region_raw.get("endCol", 0),
            region_type=region_raw.get("type", "body"),
        )
        return cls(
            name=data.get("name", ""),
            region=region,
            column_groups=data.get("columnGroups") or data.get("column_groups") or [],
            measures=data.get("measures") or [],
            is_static=data.get("isStatic") or data.get("is_static", False),
        )


# =============================================================================
# Measure Layout
# =============================================================================


@dataclass
class MeasureLayout:
    """Defines how measures are arranged in the tablix.

    Modes
    -----
    nested (default, v1-compatible)
        Measures are nested under each column group value.
        Column headers:  Region1 | Region2 | …
        Under each:      Measure1 | Measure2
        Body cells:      row key × (column group value × measure)

    extra_columns
        The pivot body only has column group values (one column per value,
        no per-measure nesting).  Each measure gets its own column AFTER
        the pivot body.

    cross_tab
        Row headers include a *measure* dimension.  Column headers are
        column group values only (no measure nesting).  Each row = one
        measure × one row group value.
    """

    mode: Literal["nested", "extra_columns", "cross_tab"] = "nested"

    def to_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MeasureLayout":
        if not data:
            return cls()
        mode = data.get("mode", "nested")
        if mode not in _VALID_LAYOUT_MODES:
            raise ValueError(
                f"Invalid measure layout mode: {mode!r}. "
                f"Valid modes: {sorted(_VALID_LAYOUT_MODES)}"
            )
        return cls(mode=mode)  # type: ignore[arg-type]


# =============================================================================
# TablixPlan v2
# =============================================================================


@dataclass
class TablixPlanV2(TablixPlan):
    """Extended TablixPlan with mixed regions and multi-measure layout.

    Inherits all v1 fields and adds:
    - ``mixed_regions``:  independent column groups per region
    - ``measure_layout``: how measures are arranged
    """

    mixed_regions: List[MixedRegion] = field(default_factory=list)
    measure_layout: MeasureLayout = field(default_factory=MeasureLayout)

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    def get_region_by_name(self, name: str) -> Optional[MixedRegion]:
        """Return the first mixed region matching *name*, or ``None``."""
        for mr in self.mixed_regions:
            if mr.name == name:
                return mr
        return None

    def get_active_column_groups(self) -> List[str]:
        """Return unique column group field names across all mixed regions."""
        seen: set[str] = set()
        result: List[str] = []
        for mr in self.mixed_regions:
            for cg in mr.column_groups:
                if cg not in seen:
                    seen.add(cg)
                    result.append(cg)
        return result

    # --------------------------------------------------------------------- #
    # Serialization
    # --------------------------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Extend v1 ``to_dict`` with v2 fields."""
        d = super().to_dict()
        if self.mixed_regions:
            d["mixedRegions"] = [mr.to_dict() for mr in self.mixed_regions]
        d["measureLayout"] = self.measure_layout.to_dict()
        return d


# =============================================================================
# Conversion helpers
# =============================================================================


def convert_v1_to_v2(plan: TablixPlan) -> TablixPlanV2:
    """Convert a v1 TablixPlan to v2 (backward compatible).

    All v1 fields are preserved.  ``measure_layout`` defaults to ``nested``
    and ``mixed_regions`` is empty (single-region legacy mode).
    """
    v2 = TablixPlanV2(
        num_rows=plan.num_rows,
        num_cols=plan.num_cols,
        num_col_header_rows=plan.num_col_header_rows,
        num_row_header_cols=plan.num_row_header_cols,
        num_static_left_cols=plan.num_static_left_cols,
        num_static_right_cols=plan.num_static_right_cols,
        num_row_header_band_cols=plan.num_row_header_band_cols,
        num_col_header_band_rows=plan.num_col_header_band_rows,
        cells=plan.cells,
        corner=plan.corner,
        col_headers=plan.col_headers,
        row_headers=plan.row_headers,
        body=plan.body,
        static_left=plan.static_left,
        static_right=plan.static_right,
        row_header_bands=plan.row_header_bands,
        col_header_bands=plan.col_header_bands,
        row_defs=plan.row_defs,
        col_defs=plan.col_defs,
        properties=plan.properties,
        interaction=plan.interaction,
        debug=plan.debug,
        mixed_regions=[],
        measure_layout=MeasureLayout(mode="nested"),
    )
    return v2


# =============================================================================
# Internal: value lookup helpers
# =============================================================================


def _lookup_value(
    values: List[Dict[str, Any]],
    measure_name: str,
    row_key: str,
    col_key: str,
) -> Dict[str, Any]:
    """Find a cell dict from *values* for the given measure/row/col.

    Returns ``{"value": ..., "formatted": ...}`` or an empty-cell dict.
    """
    for v in values:
        m = v.get("measure") or {}
        if m.get("name") == measure_name:
            cells = v.get("cells") or {}
            row_cells = cells.get(row_key) or {}
            cell = row_cells.get(col_key)
            if cell is not None:
                return cell
    return {"value": None, "formatted": ""}


# =============================================================================
# Compiler — extra_columns mode
# =============================================================================


def _compile_extra_columns(
    matrix_result: Dict[str, Any],
    properties: Optional[Dict[str, Any]],
) -> TablixPlanV2:
    """Compile extra_columns layout.

    Pivot body shows one column per column-group leaf (no measure nesting).
    Measures become extra columns after the body.  If there are no column
    groups the result degenerates to a simple table.
    """
    props = TablixProperties.from_dict(properties)
    row_tree = matrix_result.get("rowTree") or []
    row_order = matrix_result.get("rowOrder") or []
    col_header_bands = matrix_result.get("colHeaderBands") or []
    col_leaf_keys = matrix_result.get("colLeafKeys") or []
    values = matrix_result.get("values") or []

    # Build row node lookup
    row_node_map: Dict[str, Dict[str, Any]] = {}
    for node in row_tree:
        row_node_map[node.get("key", "")] = node

    # Filter rows
    filtered_rows: List[str] = []
    for rk in row_order:
        node = row_node_map.get(rk, {})
        if node.get("isSubtotal") and not props.show_subtotals:
            continue
        # Per-level row subtotal filtering
        if node.get("isSubtotal") and props.row_subtotal_levels:
            node_level = node.get("level")
            if node_level is not None and node_level in props.row_subtotal_levels:
                if not props.row_subtotal_levels[node_level]:
                    continue
        if node.get("isGrandTotal") and props.grand_total_visibility in ("cols", "none"):
            continue
        filtered_rows.append(rk)

    # Determine measures
    measure_names: List[str] = []
    for v in values:
        m = (v.get("measure") or {}).get("name")
        if m:
            measure_names.append(m)

    # Determine if there's a real pivot (not just __all__)
    has_pivot = bool(col_leaf_keys) and col_leaf_keys != ["__all__"]

    # Pivot columns (no measure nesting)
    pivot_col_keys = col_leaf_keys if has_pivot else []

    # Grid dimensions
    num_row_header_cols = 1
    num_pivot_cols = len(pivot_col_keys)
    num_extra_measure_cols = len(measure_names)
    num_col_header_rows = 1 if (has_pivot or num_extra_measure_cols > 0) else 1
    num_data_rows = len(filtered_rows)

    # When no pivot, all measures are just columns (like a simple table)
    if not has_pivot:
        num_pivot_cols = 0
        # Header row + data rows
        total_cols = num_row_header_cols + num_extra_measure_cols
    else:
        total_cols = num_row_header_cols + num_pivot_cols + num_extra_measure_cols

    total_rows = num_col_header_rows + num_data_rows

    # Build grid
    cells: List[List[Optional[TablixCell]]] = [
        [None] * total_cols for _ in range(total_rows)
    ]
    row_defs: List[TablixRowDef] = []
    col_defs: List[TablixColDef] = []

    # ---- Column defs ----
    # Row header col
    col_defs.append(TablixColDef(index=0, is_row_header_col=True))
    ci = 1
    # Pivot columns
    for pk in pivot_col_keys:
        col_defs.append(TablixColDef(index=ci, key=pk))
        ci += 1
    # Extra measure columns
    for mn in measure_names:
        col_defs.append(TablixColDef(
            index=ci,
            measure_name=mn,
            is_static_measure=True,
            static_placement="right",
        ))
        ci += 1

    # ---- Header row (row 0) ----
    row_defs.append(TablixRowDef(index=0, is_header_row=True))
    # Corner
    cells[0][0] = TablixCell(row=0, col=0, role=CellRole.CORNER, label="")
    # Pivot col headers
    for j, pk in enumerate(pivot_col_keys):
        col_idx = num_row_header_cols + j
        is_gt = "__grand_total__" in pk or "__col_grand_total__" in pk
        cells[0][col_idx] = TablixCell(
            row=0,
            col=col_idx,
            role=CellRole.GRAND_TOTAL if is_gt else CellRole.COL_GROUP,
            label=pk,
            col_key=pk,
            is_grand_total=is_gt,
        )
    # Extra measure headers
    for j, mn in enumerate(measure_names):
        col_idx = num_row_header_cols + num_pivot_cols + j
        cells[0][col_idx] = TablixCell(
            row=0,
            col=col_idx,
            role=CellRole.COL_HEADER,
            label=mn,
            measure_name=mn,
        )

    # ---- Data rows ----
    for ri, rk in enumerate(filtered_rows):
        grid_row = num_col_header_rows + ri
        node = row_node_map.get(rk, {})
        is_subtotal = node.get("isSubtotal", False)
        is_gt = node.get("isGrandTotal", False)
        level = node.get("level", 0)
        label = node.get("label", rk)

        row_defs.append(TablixRowDef(
            index=grid_row,
            key=rk,
            level=level,
            is_subtotal=is_subtotal,
            is_grand_total=is_gt,
        ))

        # Row header cell
        if is_gt:
            role = CellRole.GRAND_TOTAL
        elif is_subtotal:
            role = CellRole.SUBTOTAL
        elif node.get("isExpandable"):
            role = CellRole.ROW_GROUP
        else:
            role = CellRole.ROW_HEADER

        cells[grid_row][0] = TablixCell(
            row=grid_row,
            col=0,
            role=role,
            label=label,
            row_key=rk,
            level=level,
            indent=node.get("indent", 0),
            is_expandable=node.get("isExpandable", False),
            is_expanded=node.get("isExpanded", False),
            is_subtotal=is_subtotal,
            is_grand_total=is_gt,
        )

        # Pivot body cells — use first measure for the single-column pivot cell
        first_measure = measure_names[0] if measure_names else None
        for j, pk in enumerate(pivot_col_keys):
            col_idx = num_row_header_cols + j
            is_col_gt = "__grand_total__" in pk or "__col_grand_total__" in pk
            cell_data = _lookup_value(values, first_measure or "", rk, pk)

            cell_role = CellRole.DETAIL
            if is_gt or is_col_gt:
                cell_role = CellRole.GRAND_TOTAL
            elif is_subtotal:
                cell_role = CellRole.SUBTOTAL

            cells[grid_row][col_idx] = TablixCell(
                row=grid_row,
                col=col_idx,
                role=cell_role,
                value=cell_data.get("value"),
                formatted=cell_data.get("formatted", ""),
                row_key=rk,
                col_key=pk,
                measure_name=first_measure,
                is_subtotal=is_subtotal,
                is_grand_total=is_gt or is_col_gt,
            )

        # Extra measure columns (row-scope values, col_key = "__all__")
        for j, mn in enumerate(measure_names):
            col_idx = num_row_header_cols + num_pivot_cols + j
            cell_data = _lookup_value(values, mn, rk, "__all__")

            cell_role = CellRole.DETAIL
            if is_gt:
                cell_role = CellRole.GRAND_TOTAL
            elif is_subtotal:
                cell_role = CellRole.SUBTOTAL

            cells[grid_row][col_idx] = TablixCell(
                row=grid_row,
                col=col_idx,
                role=cell_role,
                value=cell_data.get("value"),
                formatted=cell_data.get("formatted", ""),
                row_key=rk,
                col_key="__all__",
                measure_name=mn,
                is_subtotal=is_subtotal,
                is_grand_total=is_gt,
            )

    # Regions
    corner = TablixRegion(
        start_row=0,
        end_row=num_col_header_rows - 1,
        start_col=0,
        end_col=num_row_header_cols - 1,
        region_type="corner",
    )
    col_headers_region: Optional[TablixRegion] = None
    if total_cols > num_row_header_cols:
        col_headers_region = TablixRegion(
            start_row=0,
            end_row=num_col_header_rows - 1,
            start_col=num_row_header_cols,
            end_col=total_cols - 1,
            region_type="col_headers",
        )
    row_headers_region: Optional[TablixRegion] = None
    if num_data_rows > 0:
        row_headers_region = TablixRegion(
            start_row=num_col_header_rows,
            end_row=total_rows - 1,
            start_col=0,
            end_col=num_row_header_cols - 1,
            region_type="row_headers",
        )
    body_region: Optional[TablixRegion] = None
    if num_data_rows > 0 and total_cols > num_row_header_cols:
        body_region = TablixRegion(
            start_row=num_col_header_rows,
            end_row=total_rows - 1,
            start_col=num_row_header_cols,
            end_col=total_cols - 1,
            region_type="body",
        )

    plan = TablixPlanV2(
        num_rows=total_rows,
        num_cols=total_cols,
        num_col_header_rows=num_col_header_rows,
        num_row_header_cols=num_row_header_cols,
        cells=cells,
        corner=corner,
        col_headers=col_headers_region,
        row_headers=row_headers_region,
        body=body_region,
        row_defs=row_defs,
        col_defs=col_defs,
        properties=props,
        measure_layout=MeasureLayout(mode="extra_columns"),
    )
    return plan


# =============================================================================
# Compiler — cross_tab mode
# =============================================================================


def _compile_cross_tab(
    matrix_result: Dict[str, Any],
    properties: Optional[Dict[str, Any]],
) -> TablixPlanV2:
    """Compile cross_tab layout.

    Row headers include a *measure* dimension: each row is one
    (row-group-value × measure) combination.  Column headers are column
    group values only (no measure nesting).

    Subtotals in cross_tab mode aggregate across measures for each row key.
    """
    props = TablixProperties.from_dict(properties)
    row_tree = matrix_result.get("rowTree") or []
    row_order = matrix_result.get("rowOrder") or []
    col_leaf_keys = matrix_result.get("colLeafKeys") or []
    values = matrix_result.get("values") or []

    row_node_map: Dict[str, Dict[str, Any]] = {}
    for node in row_tree:
        row_node_map[node.get("key", "")] = node

    # Filter rows
    filtered_rows: List[str] = []
    for rk in row_order:
        node = row_node_map.get(rk, {})
        if node.get("isSubtotal") and not props.show_subtotals:
            continue
        # Per-level row subtotal filtering
        if node.get("isSubtotal") and props.row_subtotal_levels:
            node_level = node.get("level")
            if node_level is not None and node_level in props.row_subtotal_levels:
                if not props.row_subtotal_levels[node_level]:
                    continue
        if node.get("isGrandTotal") and props.grand_total_visibility in ("cols", "none"):
            continue
        filtered_rows.append(rk)

    measure_names: List[str] = []
    for v in values:
        m = (v.get("measure") or {}).get("name")
        if m:
            measure_names.append(m)

    if not measure_names:
        measure_names = ["Value"]

    has_pivot = bool(col_leaf_keys) and col_leaf_keys != ["__all__"]
    pivot_col_keys = col_leaf_keys if has_pivot else []

    # Grid dimensions
    # Row header: 2 cols (row key + measure name)  
    num_row_header_cols = 2
    num_pivot_cols = len(pivot_col_keys) if has_pivot else 1  # at least 1 value col
    num_col_header_rows = 1

    # Each row key × each measure = one row
    num_data_rows = len(filtered_rows) * len(measure_names)
    total_cols = num_row_header_cols + num_pivot_cols
    total_rows = num_col_header_rows + num_data_rows

    cells: List[List[Optional[TablixCell]]] = [
        [None] * total_cols for _ in range(total_rows)
    ]
    row_defs: List[TablixRowDef] = []
    col_defs: List[TablixColDef] = []

    # Column defs
    col_defs.append(TablixColDef(index=0, is_row_header_col=True))
    col_defs.append(TablixColDef(index=1, is_row_header_col=True))
    for j, pk in enumerate(pivot_col_keys):
        col_defs.append(TablixColDef(index=num_row_header_cols + j, key=pk))
    if not has_pivot:
        col_defs.append(TablixColDef(index=num_row_header_cols, key="__all__"))

    # Header row
    row_defs.append(TablixRowDef(index=0, is_header_row=True))
    cells[0][0] = TablixCell(row=0, col=0, role=CellRole.CORNER, label="")
    cells[0][1] = TablixCell(row=0, col=1, role=CellRole.CORNER, label="Measure")

    if has_pivot:
        for j, pk in enumerate(pivot_col_keys):
            ci = num_row_header_cols + j
            is_gt = "__grand_total__" in pk or "__col_grand_total__" in pk
            cells[0][ci] = TablixCell(
                row=0,
                col=ci,
                role=CellRole.GRAND_TOTAL if is_gt else CellRole.COL_GROUP,
                label=pk,
                col_key=pk,
                is_grand_total=is_gt,
            )
    else:
        cells[0][num_row_header_cols] = TablixCell(
            row=0,
            col=num_row_header_cols,
            role=CellRole.COL_HEADER,
            label="Value",
            col_key="__all__",
        )

    # Data rows: row_key × measure
    grid_row = num_col_header_rows
    for rk in filtered_rows:
        node = row_node_map.get(rk, {})
        is_subtotal = node.get("isSubtotal", False)
        is_gt = node.get("isGrandTotal", False)
        level = node.get("level", 0)
        label = node.get("label", rk)

        for mi, mn in enumerate(measure_names):
            row_defs.append(TablixRowDef(
                index=grid_row,
                key=rk,
                level=level,
                is_subtotal=is_subtotal,
                is_grand_total=is_gt,
                measure_name=mn,
            ))

            # Determine row header role
            if is_gt:
                rh_role = CellRole.GRAND_TOTAL
            elif is_subtotal:
                rh_role = CellRole.SUBTOTAL
            elif node.get("isExpandable"):
                rh_role = CellRole.ROW_GROUP
            else:
                rh_role = CellRole.ROW_HEADER

            # First row-header col: row key (span across measures for same key)
            if mi == 0:
                cells[grid_row][0] = TablixCell(
                    row=grid_row,
                    col=0,
                    role=rh_role,
                    label=label,
                    row_key=rk,
                    level=level,
                    indent=node.get("indent", 0),
                    is_expandable=node.get("isExpandable", False),
                    is_expanded=node.get("isExpanded", False),
                    is_subtotal=is_subtotal,
                    is_grand_total=is_gt,
                    row_span=len(measure_names),
                )
                # Mark spanned rows as None
                for sp in range(1, len(measure_names)):
                    cells[grid_row + sp][0] = None
            # else: already None (spanned)

            # Second row-header col: measure name
            cells[grid_row][1] = TablixCell(
                row=grid_row,
                col=1,
                role=CellRole.ROW_HEADER,
                label=mn,
                row_key=rk,
                measure_name=mn,
                is_subtotal=is_subtotal,
                is_grand_total=is_gt,
            )

            # Body cells
            if has_pivot:
                for j, pk in enumerate(pivot_col_keys):
                    ci = num_row_header_cols + j
                    cell_data = _lookup_value(values, mn, rk, pk)
                    is_col_gt = "__grand_total__" in pk or "__col_grand_total__" in pk

                    cell_role = CellRole.DETAIL
                    if is_gt or is_col_gt:
                        cell_role = CellRole.GRAND_TOTAL
                    elif is_subtotal:
                        cell_role = CellRole.SUBTOTAL

                    cells[grid_row][ci] = TablixCell(
                        row=grid_row,
                        col=ci,
                        role=cell_role,
                        value=cell_data.get("value"),
                        formatted=cell_data.get("formatted", ""),
                        row_key=rk,
                        col_key=pk,
                        measure_name=mn,
                        is_subtotal=is_subtotal,
                        is_grand_total=is_gt or is_col_gt,
                    )
            else:
                cell_data = _lookup_value(values, mn, rk, "__all__")

                cell_role = CellRole.DETAIL
                if is_gt:
                    cell_role = CellRole.GRAND_TOTAL
                elif is_subtotal:
                    cell_role = CellRole.SUBTOTAL

                cells[grid_row][num_row_header_cols] = TablixCell(
                    row=grid_row,
                    col=num_row_header_cols,
                    role=cell_role,
                    value=cell_data.get("value"),
                    formatted=cell_data.get("formatted", ""),
                    row_key=rk,
                    col_key="__all__",
                    measure_name=mn,
                    is_subtotal=is_subtotal,
                    is_grand_total=is_gt,
                )

            grid_row += 1

    # Regions
    corner = TablixRegion(
        start_row=0,
        end_row=num_col_header_rows - 1,
        start_col=0,
        end_col=num_row_header_cols - 1,
        region_type="corner",
    )
    col_headers_region = TablixRegion(
        start_row=0,
        end_row=num_col_header_rows - 1,
        start_col=num_row_header_cols,
        end_col=total_cols - 1,
        region_type="col_headers",
    ) if total_cols > num_row_header_cols else None
    row_headers_region = TablixRegion(
        start_row=num_col_header_rows,
        end_row=total_rows - 1,
        start_col=0,
        end_col=num_row_header_cols - 1,
        region_type="row_headers",
    ) if num_data_rows > 0 else None
    body_region = TablixRegion(
        start_row=num_col_header_rows,
        end_row=total_rows - 1,
        start_col=num_row_header_cols,
        end_col=total_cols - 1,
        region_type="body",
    ) if num_data_rows > 0 and total_cols > num_row_header_cols else None

    plan = TablixPlanV2(
        num_rows=total_rows,
        num_cols=total_cols,
        num_col_header_rows=num_col_header_rows,
        num_row_header_cols=num_row_header_cols,
        cells=cells,
        corner=corner,
        col_headers=col_headers_region,
        row_headers=row_headers_region,
        body=body_region,
        row_defs=row_defs,
        col_defs=col_defs,
        properties=props,
        measure_layout=MeasureLayout(mode="cross_tab"),
    )
    return plan


# =============================================================================
# Main compiler entry point
# =============================================================================


def compile_tablix_plan_v2(
    matrix_result: Dict[str, Any],
    properties: Optional[Dict[str, Any]] = None,
    measure_layout_mode: str = "nested",
    mixed_regions: Optional[List[Dict[str, Any]]] = None,
) -> TablixPlanV2:
    """Compile a TablixPlan v2 from a MatrixResult dict.

    Parameters
    ----------
    matrix_result : dict
        The ``MatrixResult.to_dict()`` output from the matrix planner.
    properties : dict, optional
        SSRS-style layout properties.
    measure_layout_mode : str
        ``"nested"`` (v1-compatible), ``"extra_columns"``, or ``"cross_tab"``.
    mixed_regions : list[dict], optional
        Independent region definitions.  Currently stored on the plan for
        downstream renderers but do not alter compilation flow.

    Returns
    -------
    TablixPlanV2
    """
    # Validate matrix_result shape
    if not isinstance(matrix_result, dict):
        raise ValueError(
            f"matrix_result must be a dict, got {type(matrix_result).__name__}"
        )
    _REQUIRED_MATRIX_KEYS = {"rowTree", "rowOrder", "colHeaderBands", "colLeafKeys", "values"}
    missing = _REQUIRED_MATRIX_KEYS - set(matrix_result.keys())
    if missing:
        raise ValueError(
            f"matrix_result is missing required keys: {sorted(missing)}. "
            f"Expected keys: {sorted(_REQUIRED_MATRIX_KEYS)}"
        )

    # Validate mode
    if measure_layout_mode not in _VALID_LAYOUT_MODES:
        raise ValueError(
            f"Invalid measure_layout_mode: {measure_layout_mode!r}. "
            f"Valid modes: {sorted(_VALID_LAYOUT_MODES)}"
        )

    # Dispatch by mode
    if measure_layout_mode == "nested":
        # Delegate to v1 and wrap
        v1_plan = compile_matrix_to_tablix(
            matrix_result,
            tablix_properties=properties,
        )
        v2_plan = convert_v1_to_v2(v1_plan)
    elif measure_layout_mode == "extra_columns":
        v2_plan = _compile_extra_columns(matrix_result, properties)
    elif measure_layout_mode == "cross_tab":
        v2_plan = _compile_cross_tab(matrix_result, properties)
    else:
        raise ValueError(f"Unsupported mode: {measure_layout_mode!r}")

    # Attach mixed regions if provided
    if mixed_regions:
        v2_plan.mixed_regions = [MixedRegion.from_dict(mr) for mr in mixed_regions]

    return v2_plan
