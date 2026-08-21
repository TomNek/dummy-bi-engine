"""Graph Objects renderer — go.* chart types that have no px.* equivalent.

This module is imported by dax_ui.server.__init__ and called via the
``renderer: graph_objects`` path in visual_types.yaml.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)


def _render_go_chart(
    *,
    go_type: str,
    df: Any,
    resolved_encodings: Mapping[str, Any],
    format_options: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Render a graph_objects chart and return a Plotly figure dict.

    The caller applies professional defaults and format patches after this returns.
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    # Helper to resolve slot to column name
    def _col(slot: str) -> Optional[str]:
        v = resolved_encodings.get(slot)
        if v is None:
            return None
        if isinstance(v, list):
            v = v[0]
        if isinstance(v, str):
            return v
        if isinstance(v, Mapping):
            return v.get("output_name") or v.get("column") or v.get("name")
        # Handle IR objects (ColumnRef, MeasureRef, etc.)
        if hasattr(v, "column"):
            return v.column
        if hasattr(v, "name"):
            return v.name
        return str(v)

    # Dispatch to type-specific builder
    builders = {
        "candlestick": _build_candlestick,
        "ohlc": _build_ohlc,
        "waterfall": _build_waterfall,
        "indicator": _build_indicator,
        "sankey": _build_sankey,
        "combo": _build_combo,
    }

    builder = builders.get(go_type)
    if builder is None:
        raise ValueError(f"Unknown go_type: {go_type!r}")

    fig = builder(df=df, col=_col, resolved_encodings=resolved_encodings, format_options=format_options)

    # Convert to dict
    try:
        fig_dict = json.loads(pio.to_json(fig, validate=False))
    except Exception:
        fig_dict = fig.to_dict()

    return fig_dict


def _build_candlestick(*, df: Any, col, resolved_encodings: Mapping[str, Any], format_options: Optional[Mapping[str, Any]] = None) -> Any:
    import plotly.graph_objects as go

    x_col = col("x")
    open_col = col("open")
    high_col = col("high")
    low_col = col("low")
    close_col = col("close")

    if not all([x_col, open_col, high_col, low_col, close_col]):
        raise ValueError("Candlestick requires x, open, high, low, close slots")

    fig = go.Figure(data=[go.Candlestick(
        x=df[x_col].tolist(),
        open=df[open_col].tolist(),
        high=df[high_col].tolist(),
        low=df[low_col].tolist(),
        close=df[close_col].tolist(),
    )])
    return fig


def _build_ohlc(*, df: Any, col, resolved_encodings: Mapping[str, Any], format_options: Optional[Mapping[str, Any]] = None) -> Any:
    import plotly.graph_objects as go

    x_col = col("x")
    open_col = col("open")
    high_col = col("high")
    low_col = col("low")
    close_col = col("close")

    if not all([x_col, open_col, high_col, low_col, close_col]):
        raise ValueError("OHLC requires x, open, high, low, close slots")

    fig = go.Figure(data=[go.Ohlc(
        x=df[x_col].tolist(),
        open=df[open_col].tolist(),
        high=df[high_col].tolist(),
        low=df[low_col].tolist(),
        close=df[close_col].tolist(),
    )])
    return fig


def _build_waterfall(*, df: Any, col, resolved_encodings: Mapping[str, Any], format_options: Optional[Mapping[str, Any]] = None) -> Any:
    import plotly.graph_objects as go

    x_col = col("x")
    y_col = col("y")
    measure_col = col("measure")

    if not x_col or not y_col:
        raise ValueError("Waterfall requires x and y slots")

    x_vals = df[x_col].tolist()
    y_vals = df[y_col].tolist()

    if measure_col and measure_col in df.columns:
        measures = df[measure_col].tolist()
    else:
        # Default: all "relative" except last which is "total"
        measures = ["relative"] * len(y_vals)
        if measures:
            measures[-1] = "total"

    fig = go.Figure(data=[go.Waterfall(
        x=x_vals,
        y=y_vals,
        measure=measures,
        connector={"line": {"color": "rgb(63, 63, 63)"}},
    )])
    return fig


def _build_indicator(*, df: Any, col, resolved_encodings: Mapping[str, Any], format_options: Optional[Mapping[str, Any]] = None) -> Any:
    import plotly.graph_objects as go

    value_col = col("value")
    ref_col = col("reference")

    if not value_col:
        raise ValueError("Indicator/Gauge requires a value slot")

    val = float(df[value_col].iloc[0]) if len(df) > 0 else 0

    indicator_kwargs: dict[str, Any] = {
        "mode": "gauge+number+delta",
        "value": val,
        "gauge": {"axis": {"range": [0, val * 1.5 if val > 0 else 100]}},
    }

    if ref_col and ref_col in df.columns and len(df) > 0:
        ref_val = float(df[ref_col].iloc[0])
        indicator_kwargs["delta"] = {"reference": ref_val}

    fig = go.Figure(data=[go.Indicator(**indicator_kwargs)])
    return fig


def _build_sankey(*, df: Any, col, resolved_encodings: Mapping[str, Any], format_options: Optional[Mapping[str, Any]] = None) -> Any:
    import plotly.graph_objects as go

    source_col = col("source")
    target_col = col("target")
    value_col = col("value")

    if not all([source_col, target_col, value_col]):
        raise ValueError("Sankey requires source, target, and value slots")

    # Build unique node labels and map to indices
    sources = df[source_col].tolist()
    targets = df[target_col].tolist()
    all_labels = list(dict.fromkeys(sources + targets))  # preserve order, dedupe
    label_to_idx = {label: i for i, label in enumerate(all_labels)}

    source_indices = [label_to_idx[s] for s in sources]
    target_indices = [label_to_idx[t] for t in targets]
    values = df[value_col].tolist()

    fig = go.Figure(data=[go.Sankey(
        node={"label": all_labels, "pad": 15, "thickness": 20},
        link={"source": source_indices, "target": target_indices, "value": values},
    )])
    return fig


# ── Layer-type → Plotly trace constructor mapping ─────────────────────
_LAYER_MARK_TYPES = {"bar", "line", "scatter", "area"}


def _layer_trace(
    *,
    layer_type: str,
    x_vals: list,
    y_vals: list,
    name: str,
    layer_format: dict,
    color_vals: list | None = None,
    size_vals: list | None = None,
    detail_data: list[tuple[str, list]] | None = None,
) -> Any:
    """Create a single Plotly trace for a combo layer.

    ``layer_format`` may contain per-layer format options matching the
    existing ``_FORMAT_SCHEMA`` keys (lineWidth, lineDash, lineShape,
    showMarkers, markerSize, markerSymbol, markerOpacity, barMode,
    opacity, colorscale).

    Color gradient support:
    - ``colorscale`` — Plotly continuous colorscale name (e.g. "Viridis")
      applied to marker colors (bar, scatter) or line marker colors.
    - When ``color_vals`` is provided AND ``colorscale`` is set, colors
      are mapped to the continuous scale.

    Size encoding (G9):
    - ``size_vals`` — list of numeric values mapped to marker size for
      scatter layers (bubble chart style).

    Detail shelf (G13):
    - ``detail_data`` — list of (column_name, values_list) tuples to
      include as customdata in the hovertemplate.
    """
    import plotly.graph_objects as go

    opacity = layer_format.get("opacity")
    colorscale = layer_format.get("colorscale")

    # Per-layer data labels (G4)
    show_data_labels = layer_format.get("showDataLabels", False)
    _default_label_pos = "outside" if layer_type in ("bar", "column") else "top center"
    data_label_pos = layer_format.get("dataLabelPosition") or _default_label_pos

    # Per-layer mark border (G17)
    border_color = layer_format.get("borderColor", "")
    border_width = layer_format.get("borderWidth", 0)

    def _apply_detail(kw: dict[str, Any]) -> None:
        """G13 — Enrich trace kwargs with detail shelf columns."""
        if not detail_data:
            return
        n = len(kw.get("y") or kw.get("x") or [])
        # Build customdata: list of lists, one per point
        # Each point gets [detail_col_0_val, detail_col_1_val, ...]
        custom = [[row_vals[j] for _, row_vals in detail_data] for j in range(n)]
        kw["customdata"] = custom
        # Build hovertemplate
        base = kw.get("hovertemplate", "%{x}<br>%{y}")
        detail_parts = [
            f"<br>{col_name}: %{{customdata[{i}]}}"
            for i, (col_name, _) in enumerate(detail_data)
        ]
        kw["hovertemplate"] = base + "".join(detail_parts) + "<extra></extra>"

    if layer_type == "bar":
        marker_kw_bar: dict[str, Any] = {}
        if colorscale:
            # Gradient bar coloring by Y value
            marker_kw_bar["color"] = y_vals
            marker_kw_bar["colorscale"] = colorscale
            marker_kw_bar["showscale"] = True
        if color_vals is not None and not colorscale:
            marker_kw_bar["color"] = color_vals
        if border_color or border_width:
            marker_kw_bar.setdefault("line", {})
            if border_color:
                marker_kw_bar["line"]["color"] = border_color
            if border_width:
                marker_kw_bar["line"]["width"] = float(border_width)
        bar_kw: dict[str, Any] = dict(
            x=x_vals,
            y=y_vals,
            name=name,
            opacity=opacity,
            marker=marker_kw_bar or None,
        )
        if show_data_labels:
            bar_kw["texttemplate"] = "%{y}"
            bar_kw["textposition"] = data_label_pos if data_label_pos else "auto"
        _apply_detail(bar_kw)
        return go.Bar(**bar_kw)

    if layer_type == "line":
        line_kw: dict[str, Any] = {}
        line_kw["width"] = layer_format.get("lineWidth", 2)
        dash = layer_format.get("lineDash")
        if dash:
            line_kw["dash"] = dash
        shape = layer_format.get("lineShape")
        if shape:
            line_kw["shape"] = shape
        show_markers = layer_format.get("showMarkers", True)
        mode_parts = ["lines"]
        if show_markers:
            mode_parts.append("markers")
        if show_data_labels:
            mode_parts.append("text")
        mode = "+".join(mode_parts)
        marker_kw: dict[str, Any] = {}
        if show_markers:
            marker_kw["size"] = layer_format.get("markerSize", 6)
            sym = layer_format.get("markerSymbol")
            if sym:
                marker_kw["symbol"] = sym
            if colorscale:
                marker_kw["color"] = y_vals
                marker_kw["colorscale"] = colorscale
                marker_kw["showscale"] = True
        scatter_kw: dict[str, Any] = dict(
            x=x_vals,
            y=y_vals,
            name=name,
            mode=mode,
            line=line_kw,
            marker=marker_kw or None,
            opacity=opacity,
        )
        if show_data_labels:
            scatter_kw["texttemplate"] = "%{y}"
            scatter_kw["textposition"] = data_label_pos if data_label_pos else "top center"
        _apply_detail(scatter_kw)
        return go.Scatter(**scatter_kw)

    if layer_type == "scatter":
        marker_kw2: dict[str, Any] = {}
        if size_vals is not None and len(size_vals) == len(y_vals):
            # G9 — Size encoding: map size column values to marker sizes
            import numpy as np
            raw = [float(v) if isinstance(v, (int, float)) else 0 for v in size_vals]
            min_s = layer_format.get("markerSizeMin", 4)
            max_s = layer_format.get("markerSizeMax", 40)
            arr = np.array(raw, dtype=float)
            range_val = arr.max() - arr.min()
            if range_val > 0:
                scaled = min_s + (arr - arr.min()) / range_val * (max_s - min_s)
                marker_kw2["size"] = scaled.tolist()
            else:
                marker_kw2["size"] = [float(min_s + max_s) / 2] * len(raw)
            marker_kw2["sizemode"] = "diameter"
        else:
            marker_kw2["size"] = layer_format.get("markerSize", 8)
        marker_kw2["opacity"] = layer_format.get("markerOpacity", 1.0)
        sym2 = layer_format.get("markerSymbol")
        if sym2:
            marker_kw2["symbol"] = sym2
        if colorscale:
            marker_kw2["color"] = color_vals if color_vals is not None else y_vals
            marker_kw2["colorscale"] = colorscale
            marker_kw2["showscale"] = True
        scatter_mode = "markers"
        if show_data_labels:
            scatter_mode = "markers+text"
        scatter_kw2: dict[str, Any] = dict(
            x=x_vals,
            y=y_vals,
            name=name,
            mode=scatter_mode,
            marker=marker_kw2,
            opacity=opacity,
        )
        if show_data_labels:
            scatter_kw2["texttemplate"] = "%{y}"
            scatter_kw2["textposition"] = data_label_pos if data_label_pos else "top center"
        _apply_detail(scatter_kw2)
        return go.Scatter(**scatter_kw2)

    if layer_type == "area":
        line_kw3: dict[str, Any] = {"width": layer_format.get("lineWidth", 2)}
        dash3 = layer_format.get("lineDash")
        if dash3:
            line_kw3["dash"] = dash3
        shape3 = layer_format.get("lineShape")
        if shape3:
            line_kw3["shape"] = shape3
        area_mode = "lines"
        if show_data_labels:
            area_mode = "lines+text"
        area_kw: dict[str, Any] = dict(
            x=x_vals,
            y=y_vals,
            name=name,
            mode=area_mode,
            fill="tozeroy",
            line=line_kw3,
            opacity=opacity,
        )
        if show_data_labels:
            area_kw["texttemplate"] = "%{y}"
            area_kw["textposition"] = data_label_pos if data_label_pos else "top center"
        _apply_detail(area_kw)
        return go.Scatter(**area_kw)

    raise ValueError(f"Unknown combo layer type: {layer_type!r}")


def _resolve_layer_y_col(layer: Mapping[str, Any]) -> str | None:
    """Extract the column name for a layer's ``y`` encoding."""
    y = layer.get("y")
    if y is None:
        return None
    if isinstance(y, str):
        return y
    if isinstance(y, Mapping):
        return y.get("output_name") or y.get("column") or y.get("name")
    if hasattr(y, "column"):
        return y.column
    if hasattr(y, "name"):
        return y.name
    return str(y)


def _resolve_layer_color_col(layer: Mapping[str, Any]) -> str | None:
    """Extract the column name for a layer's optional ``color`` encoding."""
    c = layer.get("color")
    if c is None:
        return None
    if isinstance(c, str):
        return c
    if isinstance(c, Mapping):
        return c.get("output_name") or c.get("column") or c.get("name")
    if hasattr(c, "column"):
        return c.column
    if hasattr(c, "name"):
        return c.name
    return str(c)


# ── Trend lines (G3) ────────────────────────────────────────
def _add_trendlines(fig: Any, format_options: Mapping[str, Any] | None) -> None:
    """Add OLS trend lines to each trace in the figure if enabled.

    Uses ``trendline`` format option (``ols``, ``lowess``).
    ``trendlineScope`` controls whether one line per trace or one for all data.
    """
    if not format_options:
        return
    trendline_type = format_options.get("trendline")
    if not trendline_type or trendline_type == "none":
        return

    import numpy as np
    import plotly.graph_objects as go

    scope = format_options.get("trendlineScope", "per_trace")

    if scope == "overall":
        # Aggregate all trace data into one trendline
        all_x: list[float] = []
        all_y: list[float] = []
        for t in fig.data:
            xd = t.get("x") if isinstance(t, dict) else getattr(t, "x", None)
            yd = t.get("y") if isinstance(t, dict) else getattr(t, "y", None)
            if xd is not None and yd is not None:
                for i, (xv, yv) in enumerate(zip(xd, yd)):
                    if isinstance(yv, (int, float)):
                        all_x.append(float(i))
                        all_y.append(float(yv))
        if len(all_x) >= 2:
            coeffs = np.polyfit(all_x, all_y, 1)
            trend_y = np.polyval(coeffs, all_x)
            # Use original categorical x values from first trace for labels
            first_x = fig.data[0].get("x") if isinstance(fig.data[0], dict) else getattr(fig.data[0], "x", None)
            x_labels = list(first_x) if first_x is not None else all_x
            fig.add_trace(go.Scatter(
                x=x_labels[:len(trend_y)],
                y=trend_y.tolist(),
                name="Trend (all)",
                mode="lines",
                line={"dash": "dot", "width": 2, "color": "#888"},
                showlegend=True,
            ))
        return

    # Per-trace trendlines
    traces_to_add = []
    for t in fig.data:
        xd = t.get("x") if isinstance(t, dict) else getattr(t, "x", None)
        yd = t.get("y") if isinstance(t, dict) else getattr(t, "y", None)
        t_name = t.get("name") if isinstance(t, dict) else getattr(t, "name", "")
        if xd is None or yd is None:
            continue
        nums_x: list[float] = []
        nums_y: list[float] = []
        for i, (xv, yv) in enumerate(zip(xd, yd)):
            if isinstance(yv, (int, float)):
                nums_x.append(float(i))
                nums_y.append(float(yv))
        if len(nums_x) < 2:
            continue
        coeffs = np.polyfit(nums_x, nums_y, 1)
        trend_y = np.polyval(coeffs, nums_x)
        x_labels = list(xd)
        traces_to_add.append(go.Scatter(
            x=x_labels[:len(trend_y)],
            y=trend_y.tolist(),
            name=f"Trend ({t_name})",
            mode="lines",
            line={"dash": "dot", "width": 2},
            showlegend=True,
        ))
    for tr in traces_to_add:
        fig.add_trace(tr)


# ── Measure pivot ────────────────────────────────────────────
_PIVOT_MARK_CYCLE = ["bar", "line", "scatter", "area"]


def _measure_pivot_to_layers(y_list: list) -> list[dict[str, Any]]:
    """Auto-create one layer per Y measure when multiple measures are dropped.

    Alternates mark types: bar → line → scatter → area → …
    The first two layers get primary/secondary Y; the rest stay on primary.
    """
    layers: list[dict[str, Any]] = []
    for i, y_item in enumerate(y_list):
        # Resolve column name
        if isinstance(y_item, str):
            y_name = y_item
        elif isinstance(y_item, Mapping):
            y_name = y_item.get("output_name") or y_item.get("column") or y_item.get("name") or str(y_item)
        elif hasattr(y_item, "column"):
            y_name = y_item.column
        elif hasattr(y_item, "name"):
            y_name = y_item.name
        else:
            y_name = str(y_item)

        mark = _PIVOT_MARK_CYCLE[i % len(_PIVOT_MARK_CYCLE)]
        secondary = (i == 1)  # second measure on secondary Y
        layers.append({
            "type": mark,
            "y": y_name,
            "secondary_y": secondary,
            "format": {},
        })
    return layers


def _build_combo(*, df: Any, col, resolved_encodings: Mapping[str, Any], format_options: Optional[Mapping[str, Any]] = None) -> Any:
    """Build a composable combo chart with N trace layers.

    Supports two modes:

    **Legacy mode** (backward-compat): ``encodings.y`` + optional ``encodings.y2``
    renders bar on primary + scatter(line) on secondary. This is auto-converted
    to the multi-layer format internally.

    **Multi-layer mode**: ``encodings.layers`` is an array of layer dicts::

        [
            {"type": "bar",     "y": <MeasureRef>, "secondary_y": false, "format": {...}},
            {"type": "line",    "y": <MeasureRef>, "secondary_y": true,  "format": {...}},
            {"type": "scatter", "y": <MeasureRef>, "secondary_y": false, "format": {...}},
        ]

    All layers share the same X-axis.

    **Trellis / small-multiples**: when ``facet_row``, ``facet_col``, or
    ``small_multiples`` encoding slots are set, the chart is split into
    a subplot grid — one combo panel per facet group.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    x_col_name = col("x")
    if not x_col_name:
        raise ValueError("Combo requires x slot")

    # ── Resolve layers ───────────────────────────────────────────
    raw_layers = resolved_encodings.get("layers")

    if raw_layers and isinstance(raw_layers, list) and len(raw_layers) > 0:
        # Multi-layer mode
        layers = raw_layers
    else:
        # Legacy mode — convert y/y2 to layers
        y_raw = resolved_encodings.get("y")

        # ── Measure pivot: when y is a list of 2+ columns, auto-create
        #    one layer per column (alternating bar/line types).
        if isinstance(y_raw, list) and len(y_raw) >= 2:
            layers = _measure_pivot_to_layers(y_raw)
        else:
            y_col = col("y")
            if not y_col:
                raise ValueError("Combo requires x and y slots")
            layers = [{"type": "bar", "y": y_col, "secondary_y": False, "format": {}}]

        y2_col = col("y2")
        if y2_col and y2_col in df.columns:
            layers.append({"type": "line", "y": y2_col, "secondary_y": True, "format": {}})

    # Determine if any layer needs secondary Y
    has_secondary = any(
        bool(lyr.get("secondary_y")) for lyr in layers
    )

    # ── Trellis / faceting ───────────────────────────────────────
    facet_row_col = col("facet_row")
    facet_col_col = col("facet_col")
    # small_multiples is a wrapping grid — distinct from facet_row/facet_col
    sm_col = col("small_multiples")
    sm_wrap: int | None = None
    if sm_col:
        if not facet_col_col:
            facet_col_col = sm_col
        # Determine wrap columns from format_options (0 = auto)
        sm_max = 0
        if format_options and isinstance(format_options, Mapping):
            sm_max = int(format_options.get("smallMultiplesMaxColumns", 0))
        if sm_max <= 0:
            import math
            n_unique = df[sm_col].nunique() if sm_col in df.columns else 1
            sm_wrap = max(1, math.ceil(math.sqrt(n_unique)))
        else:
            sm_wrap = max(1, min(8, sm_max))

    has_trellis = bool(facet_row_col or facet_col_col)

    if has_trellis:
        return _build_combo_trellis(
            df=df,
            x_col_name=x_col_name,
            layers=layers,
            has_secondary=has_secondary,
            color_col=col("color"),
            facet_row_col=facet_row_col,
            facet_col_col=facet_col_col,
            sm_wrap_cols=sm_wrap,
        )

    # ── Stacked mode: each layer in its own subplot row ──────────
    layout_mode = str(resolved_encodings.get("layout_mode", "overlay")).lower()
    if layout_mode == "stacked" and len(layers) > 1:
        return _build_combo_stacked(
            df=df,
            x_col_name=x_col_name,
            layers=layers,
            color_col=col("color"),
        )

    # ── Non-faceted combo (overlay — all layers share axes) ──────
    fig = make_subplots(specs=[[{"secondary_y": has_secondary}]])

    color_col = col("color")  # Visual-level color (applied to all layers that don't override)

    # G13 — Detail shelf columns
    detail_raw = resolved_encodings.get("detail")
    detail_cols: list[str] = []
    if detail_raw:
        if isinstance(detail_raw, list):
            for d in detail_raw:
                if isinstance(d, str):
                    dname = d
                elif isinstance(d, Mapping):
                    dname = d.get("output_name") or d.get("column") or d.get("name")
                elif hasattr(d, "column"):
                    dname = d.column
                elif hasattr(d, "name"):
                    dname = d.name
                else:
                    dname = str(d)
                if dname:
                    detail_cols.append(str(dname))
        elif isinstance(detail_raw, str):
            detail_cols.append(detail_raw)
        elif hasattr(detail_raw, "column"):
            detail_cols.append(detail_raw.column)

    _add_combo_layers(
        fig=fig,
        df=df,
        x_col_name=x_col_name,
        layers=layers,
        color_col=color_col,
        row=None,
        col_idx=None,
        detail_cols=detail_cols or None,
    )

    # ── Axis labels ──────────────────────────────────────────────
    _set_combo_axis_labels(fig, layers, x_col_name, has_secondary)

    # ── Trend lines (G3) ────────────────────────────────────────
    _add_trendlines(fig, format_options)

    return fig


def _build_combo_stacked(
    *,
    df: Any,
    x_col_name: str,
    layers: list,
    color_col: str | None,
) -> Any:
    """Build a vertically stacked combo chart — one subplot row per layer.

    Each layer gets its own Y-axis with independent scale.
    All subplots share the X-axis (only shown on the bottom panel).
    This is the Tableau-style "stacked measures" layout.
    """
    from plotly.subplots import make_subplots

    n = len(layers)

    # Build subplot titles from layer names
    subplot_titles: list[str] = []
    for layer in layers:
        name = str(layer.get("name") or _resolve_layer_y_col(layer) or "untitled")
        subplot_titles.append(name)

    fig = make_subplots(
        rows=n,
        cols=1,
        shared_xaxes=True,
        subplot_titles=subplot_titles,
        vertical_spacing=max(0.06, 0.15 / n),
    )

    x_vals = df[x_col_name].tolist()

    for i, layer in enumerate(layers, start=1):
        layer_type = str(layer.get("type", "bar")).lower()
        if layer_type not in _LAYER_MARK_TYPES:
            raise ValueError(
                f"Invalid combo layer type {layer_type!r}; "
                f"must be one of {sorted(_LAYER_MARK_TYPES)}"
            )

        y_col_name = _resolve_layer_y_col(layer)
        if not y_col_name:
            raise ValueError(f"Combo layer {i - 1} missing 'y' measure")
        if y_col_name not in df.columns:
            raise ValueError(
                f"Combo layer {i - 1} references column {y_col_name!r} "
                f"not present in query result"
            )

        layer_format = dict(layer.get("format") or {})
        layer_color = _resolve_layer_color_col(layer)
        effective_color = layer_color or color_col

        if effective_color and effective_color in df.columns:
            for group_val in df[effective_color].unique():
                mask = df[effective_color] == group_val
                trace = _layer_trace(
                    layer_type=layer_type,
                    x_vals=df.loc[mask, x_col_name].tolist(),
                    y_vals=df.loc[mask, y_col_name].tolist(),
                    name=f"{y_col_name} — {group_val}",
                    layer_format=layer_format,
                )
                fig.add_trace(trace, row=i, col=1)
        else:
            name = str(layer.get("name") or y_col_name)
            trace = _layer_trace(
                layer_type=layer_type,
                x_vals=x_vals,
                y_vals=df[y_col_name].tolist(),
                name=name,
                layer_format=layer_format,
            )
            fig.add_trace(trace, row=i, col=1)

        # Y-axis title for this panel
        fig.update_yaxes(title_text=str(y_col_name), row=i, col=1)

    # X-axis label only on the bottom subplot
    fig.update_xaxes(title_text=str(x_col_name), row=n, col=1)

    # Ensure enough top margin for the first subplot's annotation title
    fig.update_layout(margin=dict(t=30))

    # Make subplot titles more prominent
    for ann in fig.layout.annotations:
        ann.font = dict(size=13, weight="bold")

    return fig


def _build_combo_trellis(
    *,
    df: Any,
    x_col_name: str,
    layers: list,
    has_secondary: bool,
    color_col: str | None,
    facet_row_col: str | None,
    facet_col_col: str | None,
    sm_wrap_cols: int | None = None,
) -> Any:
    """Build a trellis / small-multiples combo chart.

    Splits the DataFrame by facet columns and renders each group as
    a separate combo subplot in a grid layout.

    When *sm_wrap_cols* is set (small-multiples mode), *facet_col_col* values
    are wrapped into a grid with at most *sm_wrap_cols* columns.
    """
    import math
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # Determine row/col groups
    row_groups = sorted(df[facet_row_col].unique().tolist()) if facet_row_col and facet_row_col in df.columns else [None]
    col_groups = sorted(df[facet_col_col].unique().tolist()) if facet_col_col and facet_col_col in df.columns else [None]

    # Small-multiples wrapping: flatten into wrapped grid rows
    if sm_wrap_cols and not facet_row_col and col_groups != [None]:
        # Wrap col_groups into rows of sm_wrap_cols
        all_values = col_groups
        n_total = len(all_values)
        n_cols = min(sm_wrap_cols, n_total)
        n_rows = math.ceil(n_total / n_cols)

        # Build a flat list of (row_idx, col_idx, value) cells
        grid_cells: list[tuple[int, int, Any]] = []
        for i, val in enumerate(all_values):
            r = i // n_cols
            c = i % n_cols
            grid_cells.append((r, c, val))
    else:
        n_rows = len(row_groups)
        n_cols = len(col_groups)
        grid_cells = None  # use legacy row_groups × col_groups

    # Build subplot titles
    subplot_titles: list[str] = []
    if grid_cells is not None:
        # Small-multiples wrapped grid
        for r in range(n_rows):
            for c in range(n_cols):
                # Find cell at this position
                val = next((v for (ri, ci, v) in grid_cells if ri == r and ci == c), None)
                subplot_titles.append(str(val) if val is not None else "")
    else:
        for rg in row_groups:
            for cg in col_groups:
                parts = []
                if rg is not None:
                    parts.append(str(rg))
                if cg is not None:
                    parts.append(str(cg))
                subplot_titles.append(" | ".join(parts) if parts else "")

    # Build specs: each cell may have secondary Y
    specs = [[{"secondary_y": has_secondary} for _ in range(n_cols)] for _ in range(n_rows)]

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        specs=specs,
        subplot_titles=subplot_titles,
    )

    show_legend_once: set[str] = set()

    if grid_cells is not None:
        # Small-multiples wrapped grid iteration
        for (ri, ci, val) in grid_cells:
            mask = df[facet_col_col] == val if facet_col_col else (df.index == df.index)
            cell_df = df.loc[mask]
            if cell_df.empty:
                continue
            _add_combo_layers(
                fig=fig,
                df=cell_df,
                x_col_name=x_col_name,
                layers=layers,
                color_col=color_col,
                row=ri + 1,  # 1-indexed
                col_idx=ci + 1,
                show_legend_once=show_legend_once,
            )
    else:
        for ri, rg in enumerate(row_groups, start=1):
            for ci, cg in enumerate(col_groups, start=1):
                # Filter DataFrame for this facet cell
                mask = df.index == df.index  # all True
                if rg is not None and facet_row_col:
                    mask = mask & (df[facet_row_col] == rg)
                if cg is not None and facet_col_col:
                    mask = mask & (df[facet_col_col] == cg)
                cell_df = df.loc[mask]

                if cell_df.empty:
                    continue

                _add_combo_layers(
                    fig=fig,
                    df=cell_df,
                    x_col_name=x_col_name,
                    layers=layers,
                    color_col=color_col,
                    row=ri,
                    col_idx=ci,
                    show_legend_once=show_legend_once,
                )

    # ── Axis labels (on first row/col only) ──────────────────────
    primary_layers = [l for l in layers if not l.get("secondary_y")]
    secondary_layers = [l for l in layers if l.get("secondary_y")]

    if primary_layers:
        p_name = _resolve_layer_y_col(primary_layers[0]) or ""
        fig.update_yaxes(title_text=p_name, row=1, col=1, secondary_y=False)
    if secondary_layers:
        s_name = _resolve_layer_y_col(secondary_layers[0]) or ""
        fig.update_yaxes(title_text=s_name, row=1, col=1, secondary_y=True)

    fig.update_xaxes(title_text=str(x_col_name), row=n_rows, col=1)

    # Ensure enough top margin for the trellis subplot annotation titles
    fig.update_layout(margin=dict(t=30))

    # Make subplot titles more prominent
    for ann in fig.layout.annotations:
        ann.font = dict(size=13, weight="bold")

    return fig


def _add_combo_layers(
    *,
    fig: Any,
    df: Any,
    x_col_name: str,
    layers: list,
    color_col: str | None,
    row: int | None,
    col_idx: int | None,
    show_legend_once: set | None = None,
    detail_cols: list[str] | None = None,
) -> None:
    """Add all combo layers to a figure (optionally targeting a specific subplot cell)."""
    add_kw: dict[str, Any] = {}
    if row is not None and col_idx is not None:
        add_kw["row"] = row
        add_kw["col"] = col_idx

    x_vals = df[x_col_name].tolist()

    # G13 — Resolve detail shelf columns (present in DataFrame)
    resolved_detail_cols = [
        c for c in (detail_cols or []) if c in df.columns
    ]

    for i, layer in enumerate(layers):
        layer_type = str(layer.get("type", "bar")).lower()
        if layer_type not in _LAYER_MARK_TYPES:
            raise ValueError(
                f"Invalid combo layer type {layer_type!r}; "
                f"must be one of {sorted(_LAYER_MARK_TYPES)}"
            )

        y_col_name = _resolve_layer_y_col(layer)
        if not y_col_name:
            raise ValueError(f"Combo layer {i} missing 'y' measure")
        if y_col_name not in df.columns:
            raise ValueError(
                f"Combo layer {i} references column {y_col_name!r} "
                f"not present in query result"
            )

        secondary_y = bool(layer.get("secondary_y", False))
        layer_format = dict(layer.get("format") or {})

        # Per-layer color overrides visual-level color
        layer_color = _resolve_layer_color_col(layer)
        effective_color = layer_color or color_col

        # G9 — Per-layer size encoding (bubble scatter)
        size_col = layer.get("size")
        if isinstance(size_col, dict):
            size_col = size_col.get("column") or size_col.get("field") or size_col.get("name")
        elif hasattr(size_col, "name"):
            # Handle IR objects (MeasureRef)
            size_col = size_col.name
        size_col = str(size_col) if size_col else None

        if effective_color and effective_color in df.columns:
            # Grouped traces: one trace per color group
            for group_val in df[effective_color].unique():
                mask = df[effective_color] == group_val
                name = f"{y_col_name} — {group_val}"
                size_data = df.loc[mask, size_col].tolist() if size_col and size_col in df.columns else None
                detail = [(c, df.loc[mask, c].tolist()) for c in resolved_detail_cols] if resolved_detail_cols else None
                trace = _layer_trace(
                    layer_type=layer_type,
                    x_vals=df.loc[mask, x_col_name].tolist(),
                    y_vals=df.loc[mask, y_col_name].tolist(),
                    name=name,
                    layer_format=layer_format,
                    size_vals=size_data,
                    detail_data=detail,
                )
                # De-dupe legend entries across facet cells
                if show_legend_once is not None:
                    if name in show_legend_once:
                        trace.showlegend = False
                    else:
                        show_legend_once.add(name)
                fig.add_trace(trace, secondary_y=secondary_y, **add_kw)
        else:
            name = str(layer.get("name") or y_col_name)
            size_data = df[size_col].tolist() if size_col and size_col in df.columns else None
            detail = [(c, df[c].tolist()) for c in resolved_detail_cols] if resolved_detail_cols else None
            trace = _layer_trace(
                layer_type=layer_type,
                x_vals=x_vals,
                y_vals=df[y_col_name].tolist(),
                name=name,
                layer_format=layer_format,
                size_vals=size_data,
                detail_data=detail,
            )
            if show_legend_once is not None:
                if name in show_legend_once:
                    trace.showlegend = False
                else:
                    show_legend_once.add(name)
            fig.add_trace(trace, secondary_y=secondary_y, **add_kw)


def _set_combo_axis_labels(
    fig: Any, layers: list, x_col_name: str, has_secondary: bool
) -> None:
    """Set axis labels for a non-faceted combo chart."""
    primary_layers = [l for l in layers if not l.get("secondary_y")]
    secondary_layers = [l for l in layers if l.get("secondary_y")]

    if primary_layers:
        p_name = _resolve_layer_y_col(primary_layers[0]) or ""
        fig.update_yaxes(title_text=p_name, secondary_y=False)
    if secondary_layers:
        s_name = _resolve_layer_y_col(secondary_layers[0]) or ""
        fig.update_yaxes(title_text=s_name, secondary_y=True)

    fig.update_xaxes(title_text=str(x_col_name))
    return fig
