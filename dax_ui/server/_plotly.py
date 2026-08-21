"""Community helper module — extracted from dax_ui.server.__init__."""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Optional

from dax_ui.server._engine import _deep_merge

logger = logging.getLogger(__name__)


def _apply_alpha_to_color(color: str, alpha: float) -> str:
    """Convert a hex or named color to rgba with the given alpha (0-1)."""
    if not color:
        return f"rgba(0,0,0,{alpha:.2f})"
    c = color.strip()
    if c.startswith("rgba"):
        # Already rgba — replace alpha
        parts = c.replace("rgba(", "").rstrip(")").split(",")
        if len(parts) >= 3:
            return f"rgba({parts[0].strip()},{parts[1].strip()},{parts[2].strip()},{alpha:.2f})"
    if c.startswith("rgb("):
        parts = c.replace("rgb(", "").rstrip(")").split(",")
        if len(parts) >= 3:
            return f"rgba({parts[0].strip()},{parts[1].strip()},{parts[2].strip()},{alpha:.2f})"
    if c.startswith("#"):
        h = c.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) >= 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r},{g},{b},{alpha:.2f})"
    return f"rgba(0,0,0,{alpha:.2f})"


_POWERBI_SELECTOR_VALUE_RE = re.compile(r"=\s*['\"]?([^'\"\)]+)")


def _selector_format_rows(format_opts: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for key in ("datapoint_selectors", "selector_formatting", "visual_selector_objects", "documentation_properties"):
        value = format_opts.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, Mapping))
    return rows


def _extract_selector_value(selector: Any) -> str | None:
    if not isinstance(selector, str) or not selector.strip():
        return None
    match = _POWERBI_SELECTOR_VALUE_RE.search(selector)
    if match:
        return match.group(1).strip()
    return selector.strip()


def _selector_row_color(row: Mapping[str, Any]) -> str | None:
    prop = str(row.get("property") or row.get("PropertyName") or row.get("property_name") or "").lower()
    if prop not in {"fill", "color", "background", "backgroundcolor", "markercolor", "datacolor"}:
        return None
    value = row.get("value")
    if value is None:
        value = row.get("ExampleValue")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping):
        solid = value.get("solid")
        color = value.get("color")
        if color is None and isinstance(solid, Mapping):
            color = solid.get("color")
        if isinstance(color, str) and color.strip():
            return color.strip()
    return None


def _apply_powerbi_selector_point_colors(fig_dict: dict[str, Any], format_opts: Mapping[str, Any]) -> None:
    selector_colors: dict[str, str] = {}
    for row in _selector_format_rows(format_opts):
        color = _selector_row_color(row)
        selector = row.get("selector") or row.get("Selector")
        selector_value = _extract_selector_value(selector)
        if color and selector_value:
            selector_colors[str(selector_value)] = color
    if not selector_colors:
        return

    for trace in fig_dict.get("data", []):
        if not isinstance(trace, dict):
            continue
        candidates = trace.get("y") if str(trace.get("orientation", "")).lower() == "h" else trace.get("x")
        if not isinstance(candidates, list) or not candidates:
            continue
        marker = trace.setdefault("marker", {})
        if not isinstance(marker, dict):
            marker = {}
            trace["marker"] = marker
        existing = marker.get("color")
        if isinstance(existing, list):
            colors = list(existing)
        else:
            colors = [existing or None] * len(candidates)
        while len(colors) < len(candidates):
            colors.append(None)
        changed = False
        for index, candidate in enumerate(candidates):
            color = selector_colors.get(str(candidate))
            if color:
                colors[index] = color
                changed = True
        if changed:
            marker["color"] = colors[:len(candidates)]


_PLOTLY_COLOR_SEQUENCES: dict[str, list[str]] = {
    "Plotly": ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"],
    "D3": ["#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD", "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF"],
    "Pastel": ["#66C5CC", "#F6CF71", "#F89C74", "#DCB0F2", "#87C55F", "#9EB9F3", "#FE88B1", "#C9DB74", "#8BE0A4", "#B497E7"],
    "Bold": ["#7F3C8D", "#11A579", "#3969AC", "#F2B701", "#E73F74", "#80BA5A", "#E68310", "#008695", "#CF1C90", "#F97B72"],
    "Vivid": ["#E58606", "#5D69B1", "#52BCA3", "#99C945", "#CC61B0", "#24796C", "#DAA51B", "#2F8AC4", "#764E9F", "#ED645A"],
    "Safe": ["#88CCEE", "#CC6677", "#DDCC77", "#117733", "#332288", "#AA4499", "#44AA99", "#999933", "#882255", "#661100"],
}

_ALL_PLOTLY = [
    "bar", "column", "line", "scatter", "area", "pie", "combo",
    "histogram", "box", "violin", "strip", "ecdf",
    "funnel", "funnel_area",
    "density_contour", "density_heatmap",
    "treemap", "sunburst", "icicle",
    "scatter_polar", "line_polar", "bar_polar",
    "scatter_3d", "line_3d",
    "bubble", "bubble_3d",
    "candlestick", "ohlc", "waterfall", "gauge", "sankey",
]
_CARTESIAN = [
    "bar", "column", "line", "scatter", "area", "combo",
    "histogram", "box", "violin", "strip", "ecdf",
    "funnel", "density_contour", "density_heatmap",
    "bubble", "waterfall", "candlestick", "ohlc",
]

_FORMAT_SCHEMA: dict[str, dict[str, Any]] = {
    # ── Title ──────────────────────────────────────────────────
    "showTitle": {"type": "boolean", "default": True, "label": "Show title", "category": "title", "applies_to": _ALL_PLOTLY},
    "title": {"type": "string", "default": "", "label": "Title text", "category": "title", "applies_to": _ALL_PLOTLY},
    "titleFontSize": {"type": "number", "default": 16, "min": 8, "max": 48, "label": "Title font size", "category": "title", "applies_to": _ALL_PLOTLY},
    "titleFontColor": {"type": "color", "default": "", "label": "Title font color", "category": "title", "applies_to": _ALL_PLOTLY},

    # ── Legend ─────────────────────────────────────────────────
    "showLegend": {"type": "boolean", "default": True, "label": "Show legend", "category": "legend", "applies_to": _ALL_PLOTLY},
    "legendPosition": {"type": "select", "default": "right", "options": ["top", "bottom", "left", "right"], "label": "Legend position", "category": "legend", "applies_to": _ALL_PLOTLY},
    "legendFontSize": {"type": "number", "default": None, "min": 6, "max": 30, "label": "Legend font size", "category": "legend", "applies_to": _ALL_PLOTLY},
    "legendFontFamily": {"type": "text", "default": "", "label": "Legend font family", "category": "legend", "applies_to": _ALL_PLOTLY},
    "legendFontColor": {"type": "color", "default": "", "label": "Legend font color", "category": "legend", "applies_to": _ALL_PLOTLY},
    "legendTitleText": {"type": "string", "default": "", "label": "Legend title text", "category": "legend", "applies_to": _ALL_PLOTLY},
    "legendShowTitle": {"type": "boolean", "default": False, "label": "Show legend title", "category": "legend", "applies_to": _ALL_PLOTLY},

    # ── X Axis ─────────────────────────────────────────────────
    "xAxisLabel": {"type": "string", "default": "", "label": "X axis label", "category": "xAxis", "applies_to": _CARTESIAN},
    "yAxisLabel": {"type": "string", "default": "", "label": "Y axis label", "category": "yAxis", "applies_to": _CARTESIAN},
    "showXAxis": {"type": "boolean", "default": True, "label": "Show X axis", "category": "xAxis", "applies_to": _CARTESIAN},
    "showYAxis": {"type": "boolean", "default": True, "label": "Show Y axis", "category": "yAxis", "applies_to": _CARTESIAN},
    "showXAxisTitle": {"type": "boolean", "default": True, "label": "Show X axis label", "category": "xAxis", "applies_to": _CARTESIAN},
    "showYAxisTitle": {"type": "boolean", "default": True, "label": "Show Y axis label", "category": "yAxis", "applies_to": _CARTESIAN},
    "xAxisTickAngle": {"type": "number", "default": 0, "min": -90, "max": 90, "label": "X axis tick angle", "category": "xAxis", "applies_to": _CARTESIAN},
    "yAxisTickAngle": {"type": "number", "default": 0, "min": -90, "max": 90, "label": "Y axis tick angle", "category": "yAxis", "applies_to": _CARTESIAN},
    "showXAxisGridlines": {"type": "boolean", "default": True, "label": "Show X gridlines", "category": "xAxis", "applies_to": _CARTESIAN},
    "showYAxisGridlines": {"type": "boolean", "default": True, "label": "Show Y gridlines", "category": "yAxis", "applies_to": _CARTESIAN},
    "xAxisFontSize": {"type": "number", "default": None, "min": 6, "max": 30, "label": "X axis font size", "category": "xAxis", "applies_to": _CARTESIAN},
    "xAxisFontFamily": {"type": "text", "default": "", "label": "X axis font family", "category": "xAxis", "applies_to": _CARTESIAN},
    "xAxisFontColor": {"type": "color", "default": "", "label": "X axis font color", "category": "xAxis", "applies_to": _CARTESIAN},
    "xAxisGridlineColor": {"type": "color", "default": "", "label": "X axis gridline color", "category": "xAxis", "applies_to": _CARTESIAN},
    "yAxisFontSize": {"type": "number", "default": None, "min": 6, "max": 30, "label": "Y axis font size", "category": "yAxis", "applies_to": _CARTESIAN},
    "yAxisFontFamily": {"type": "text", "default": "", "label": "Y axis font family", "category": "yAxis", "applies_to": _CARTESIAN},
    "yAxisFontColor": {"type": "color", "default": "", "label": "Y axis font color", "category": "yAxis", "applies_to": _CARTESIAN},
    "yAxisGridlineColor": {"type": "color", "default": "", "label": "Y axis gridline color", "category": "yAxis", "applies_to": _CARTESIAN},
    "plotAreaTransparency": {"type": "number", "default": 0, "min": 0, "max": 100, "label": "Plot area transparency (%)", "category": "chartStyle", "applies_to": _ALL_PLOTLY},

    # ── Data Labels ────────────────────────────────────────────
    "showDataLabels": {"type": "boolean", "default": False, "label": "Show data labels", "category": "dataLabels", "applies_to": _ALL_PLOTLY},
    "dataLabelPosition": {"type": "select", "default": "auto", "options": ["inside", "outside", "auto", "top center", "bottom center", "top right", "top left", "middle right", "middle left"], "label": "Label position", "category": "dataLabels", "applies_to": _CARTESIAN},
    "dataLabelColor": {"type": "color", "default": "", "label": "Label color", "category": "dataLabels", "applies_to": _ALL_PLOTLY},
    "dataLabelFontSize": {"type": "number", "default": None, "min": 6, "max": 50, "label": "Label font size", "category": "dataLabels", "applies_to": _ALL_PLOTLY},
    "dataLabelFontFamily": {"type": "text", "default": "", "label": "Label font family", "category": "dataLabels", "applies_to": _ALL_PLOTLY},
    "dataLabelDisplayUnits": {"type": "select", "default": "auto", "options": ["auto", "none", "thousands", "millions", "billions", "trillions"], "label": "Display units", "category": "dataLabels", "applies_to": _ALL_PLOTLY},
    "dataLabelPrecision": {"type": "number", "default": None, "min": 0, "max": 10, "label": "Decimal places", "category": "dataLabels", "applies_to": _ALL_PLOTLY},
    "dataLabelShowBlankAs": {"type": "select", "default": "", "options": ["", "(Blank)", "0", "-"], "label": "Show blank as", "category": "dataLabels", "applies_to": _ALL_PLOTLY},
    "dataLabelTransparency": {"type": "number", "default": 0, "min": 0, "max": 100, "label": "Label transparency (%)", "category": "dataLabels", "applies_to": _ALL_PLOTLY},

    # ── Bar / Column style ─────────────────────────────────────
    "barMode": {"type": "select", "default": "group", "options": ["group", "stack", "relative"], "label": "Bar mode", "category": "chartStyle", "applies_to": ["bar", "column"]},
    "orientation": {"type": "select", "default": "v", "options": ["v", "h"], "label": "Orientation", "category": "chartStyle", "applies_to": ["bar", "column"]},
    "bargap": {"type": "number", "default": 0.2, "min": 0, "max": 1, "step": 0.05, "label": "Bar gap", "category": "chartStyle", "applies_to": ["bar", "column"]},
    "bargroupgap": {"type": "number", "default": 0.1, "min": 0, "max": 1, "step": 0.05, "label": "Bar group gap", "category": "chartStyle", "applies_to": ["bar", "column"]},
    "dataLabelAngle": {"type": "number", "default": 0, "min": -90, "max": 90, "label": "Data label angle", "category": "chartStyle", "applies_to": ["bar", "column"]},
    "seriesOrderSorted": {"type": "boolean", "default": False, "label": "Sort series", "category": "chartStyle", "applies_to": ["bar", "column"]},

    # ── Line / Area style ──────────────────────────────────────
    "lineShape": {"type": "select", "default": "linear", "options": ["linear", "spline", "hv", "vh", "hvh", "vhv"], "label": "Line shape", "category": "chartStyle", "applies_to": ["line", "area"]},
    "lineWidth": {"type": "number", "default": 2, "min": 1, "max": 8, "label": "Line width", "category": "chartStyle", "applies_to": ["line", "area"]},
    "showMarkers": {"type": "boolean", "default": True, "label": "Show markers", "category": "chartStyle", "applies_to": ["line", "area", "scatter"]},
    "lineDash": {"type": "select", "default": "solid", "options": ["solid", "dot", "dash", "dashdot", "longdash", "longdashdot"], "label": "Line dash", "category": "chartStyle", "applies_to": ["line", "area"]},
    "fillArea": {"type": "boolean", "default": False, "label": "Fill area below line", "category": "chartStyle", "applies_to": ["line"]},
    "seriesLabelsShow": {"type": "boolean", "default": False, "label": "Show series labels", "category": "chartStyle", "applies_to": ["line", "area"]},

    # ── Scatter style ──────────────────────────────────────────
    "markerSize": {"type": "number", "default": 8, "min": 2, "max": 30, "label": "Marker size", "category": "chartStyle", "applies_to": ["scatter"]},
    "markerOpacity": {"type": "number", "default": 1, "min": 0, "max": 1, "step": 0.05, "label": "Marker opacity", "category": "chartStyle", "applies_to": ["scatter"]},
    "markerSymbol": {"type": "select", "default": "circle", "options": ["circle", "square", "diamond", "cross", "x", "triangle-up", "triangle-down", "star", "hexagon", "pentagon"], "label": "Marker symbol", "category": "chartStyle", "applies_to": ["scatter"]},

    # ── Pie / Donut style ──────────────────────────────────────
    "pieHole": {"type": "number", "default": 0, "min": 0, "max": 0.8, "step": 0.05, "label": "Donut hole size", "category": "chartStyle", "applies_to": ["pie"]},
    "pieTextInfo": {"type": "select", "default": "percent", "options": ["percent", "value", "label", "label+percent", "label+value", "value+percent", "none"], "label": "Slice text", "category": "chartStyle", "applies_to": ["pie"]},
    "pieTextPosition": {"type": "select", "default": "auto", "options": ["auto", "inside", "outside", "none"], "label": "Text position", "category": "chartStyle", "applies_to": ["pie"]},
    "piePull": {"type": "number", "default": 0, "min": 0, "max": 0.2, "step": 0.01, "label": "Explode slices", "category": "chartStyle", "applies_to": ["pie"]},
    "pieStartAngle": {"type": "number", "default": 0, "min": 0, "max": 360, "label": "Start angle", "category": "chartStyle", "applies_to": ["pie"]},

    # ── Histogram style ────────────────────────────────────────
    "histNbins": {"type": "number", "default": 0, "min": 0, "max": 200, "label": "Number of bins (0=auto)", "category": "chartStyle", "applies_to": ["histogram"]},
    "histFunc": {"type": "select", "default": "count", "options": ["count", "sum", "avg", "min", "max"], "label": "Aggregation", "category": "chartStyle", "applies_to": ["histogram"]},
    "histNorm": {"type": "select", "default": "", "options": ["", "percent", "probability", "density", "probability density"], "label": "Normalization", "category": "chartStyle", "applies_to": ["histogram"]},
    "cumulative": {"type": "boolean", "default": False, "label": "Cumulative", "category": "chartStyle", "applies_to": ["histogram"]},

    # ── Box / Violin / Strip style ─────────────────────────────
    "boxPoints": {"type": "select", "default": "outliers", "options": ["all", "outliers", "suspectedoutliers", "false"], "label": "Show points", "category": "chartStyle", "applies_to": ["box"]},
    "boxMean": {"type": "select", "default": "", "options": ["", "true", "sd"], "label": "Show mean", "category": "chartStyle", "applies_to": ["box"]},
    "notched": {"type": "boolean", "default": False, "label": "Notched", "category": "chartStyle", "applies_to": ["box"]},
    "violinSide": {"type": "select", "default": "both", "options": ["both", "positive", "negative"], "label": "Violin side", "category": "chartStyle", "applies_to": ["violin"]},
    "violinPoints": {"type": "select", "default": "false", "options": ["all", "outliers", "false"], "label": "Show points", "category": "chartStyle", "applies_to": ["violin"]},
    "violinBox": {"type": "boolean", "default": False, "label": "Show box inside", "category": "chartStyle", "applies_to": ["violin"]},
    "stripJitter": {"type": "number", "default": 0.3, "min": 0, "max": 1, "step": 0.05, "label": "Jitter", "category": "chartStyle", "applies_to": ["strip"]},

    # ── Hierarchical style (treemap/sunburst/icicle) ───────────
    "maxDepth": {"type": "number", "default": -1, "min": -1, "max": 10, "label": "Max depth (-1=all)", "category": "chartStyle", "applies_to": ["treemap", "sunburst", "icicle"]},
    "hierTextInfo": {"type": "select", "default": "label+value", "options": ["label", "value", "label+value", "label+percent entry", "percent entry", "percent parent", "percent root", "none"], "label": "Text info", "category": "chartStyle", "applies_to": ["treemap", "sunburst", "icicle"]},
    "branchValues": {"type": "select", "default": "remainder", "options": ["remainder", "total"], "label": "Branch values", "category": "chartStyle", "applies_to": ["treemap", "sunburst", "icicle"]},

    # ── Polar style ────────────────────────────────────────────
    "polarAngularDirection": {"type": "select", "default": "clockwise", "options": ["clockwise", "counterclockwise"], "label": "Angular direction", "category": "chartStyle", "applies_to": ["scatter_polar", "line_polar", "bar_polar"]},
    "polarStartAngle": {"type": "number", "default": 90, "min": 0, "max": 360, "label": "Start angle", "category": "chartStyle", "applies_to": ["scatter_polar", "line_polar", "bar_polar"]},
    "polarFill": {"type": "select", "default": "", "options": ["", "toself", "tonext"], "label": "Fill mode", "category": "chartStyle", "applies_to": ["scatter_polar", "line_polar"]},

    # ── Financial style (candlestick/OHLC) ─────────────────────
    "financialIncreasingColor": {"type": "color", "default": "#26A69A", "label": "Increasing color", "category": "chartStyle", "applies_to": ["candlestick", "ohlc"]},
    "financialDecreasingColor": {"type": "color", "default": "#EF5350", "label": "Decreasing color", "category": "chartStyle", "applies_to": ["candlestick", "ohlc"]},

    # ── Gauge / Indicator style ────────────────────────────────
    "gaugeShape": {"type": "select", "default": "angular", "options": ["angular", "bullet"], "label": "Gauge shape", "category": "chartStyle", "applies_to": ["gauge"]},
    "gaugeAxisRangeMax": {"type": "number", "default": 0, "min": 0, "max": 1000000, "label": "Axis max (0=auto)", "category": "chartStyle", "applies_to": ["gauge"]},
    "gaugeBarColor": {"type": "color", "default": "", "label": "Bar color", "category": "chartStyle", "applies_to": ["gauge"]},
    "gaugeSteps": {"type": "boolean", "default": True, "label": "Show background steps", "category": "chartStyle", "applies_to": ["gauge"]},

    # ── Sankey style ───────────────────────────────────────────
    "sankeyNodeThickness": {"type": "number", "default": 20, "min": 5, "max": 50, "label": "Node thickness", "category": "chartStyle", "applies_to": ["sankey"]},
    "sankeyNodePadding": {"type": "number", "default": 10, "min": 2, "max": 50, "label": "Node padding", "category": "chartStyle", "applies_to": ["sankey"]},
    "sankeyOrientation": {"type": "select", "default": "h", "options": ["h", "v"], "label": "Orientation", "category": "chartStyle", "applies_to": ["sankey"]},

    # ── Waterfall style ────────────────────────────────────────
    "waterfallConnectorLine": {"type": "boolean", "default": True, "label": "Connector lines", "category": "chartStyle", "applies_to": ["waterfall"]},
    "waterfallIncreasingColor": {"type": "color", "default": "#26A69A", "label": "Increasing color", "category": "chartStyle", "applies_to": ["waterfall"]},
    "waterfallDecreasingColor": {"type": "color", "default": "#EF5350", "label": "Decreasing color", "category": "chartStyle", "applies_to": ["waterfall"]},
    "waterfallTotalColor": {"type": "color", "default": "#42A5F5", "label": "Total bar color", "category": "chartStyle", "applies_to": ["waterfall"]},

    # ── Global chart style ─────────────────────────────────────
    "hoverMode": {"type": "select", "default": "", "options": ["closest", "x", "y", "x unified", "y unified", "false"], "label": "Hover mode", "category": "chartStyle", "applies_to": _ALL_PLOTLY},
    "chartFontFamily": {"type": "select", "default": "", "options": ["Arial", "Helvetica", "Inter", "Segoe UI", "Courier New", "Georgia", "Times New Roman"], "label": "Chart font", "category": "chartStyle", "applies_to": _ALL_PLOTLY},
    "chartFontSize": {"type": "number", "default": 12, "min": 8, "max": 24, "label": "Chart font size", "category": "chartStyle", "applies_to": _ALL_PLOTLY},

    # ── Colors ─────────────────────────────────────────────────
    "colorSequence": {"type": "select", "default": "", "options": list(_PLOTLY_COLOR_SEQUENCES.keys()), "label": "Color palette", "category": "colors", "applies_to": _ALL_PLOTLY},
    "plotBgColor": {"type": "color", "default": "", "label": "Plot background", "category": "colors", "applies_to": _ALL_PLOTLY},
    "paperBgColor": {"type": "color", "default": "", "label": "Paper background", "category": "colors", "applies_to": _ALL_PLOTLY},

    # ── Trendlines ─────────────────────────────────────────────
    "trendline": {"type": "select", "default": "", "options": ["", "ols", "lowess", "expanding", "rolling", "ewm"], "label": "Trendline", "category": "analytics", "applies_to": ["scatter", "line", "area", "bar", "column"]},
    "trendlineScope": {"type": "select", "default": "trace", "options": ["trace", "overall"], "label": "Trendline scope", "category": "analytics", "applies_to": ["scatter", "line", "area", "bar", "column"]},

    # ── Log Axes ───────────────────────────────────────────────
    "logX": {"type": "boolean", "default": False, "label": "Log scale X", "category": "xAxis", "applies_to": _CARTESIAN},
    "logY": {"type": "boolean", "default": False, "label": "Log scale Y", "category": "yAxis", "applies_to": _CARTESIAN},

    # ── Marginal distributions ─────────────────────────────────
    "marginalX": {"type": "select", "default": "", "options": ["", "histogram", "rug", "box", "violin"], "label": "Marginal X", "category": "analytics", "applies_to": ["scatter", "histogram"]},
    "marginalY": {"type": "select", "default": "", "options": ["", "histogram", "rug", "box", "violin"], "label": "Marginal Y", "category": "analytics", "applies_to": ["scatter", "histogram"]},

    # ── Pattern / Hatching ─────────────────────────────────────
    "patternShape": {"type": "select", "default": "", "options": ["", "/", "\\", "x", "+", "-", "|", "."], "label": "Pattern shape", "category": "chartStyle", "applies_to": ["bar", "column", "histogram", "pie", "funnel"]},

    # ── WebGL Rendering ────────────────────────────────────────
    "renderMode": {"type": "select", "default": "svg", "options": ["svg", "webgl"], "label": "Render mode", "category": "chartStyle", "applies_to": ["scatter", "line", "scatter_3d"]},

    # ── Continuous Color Scale ─────────────────────────────────
    "colorContinuousScale": {"type": "select", "default": "", "options": ["", "Viridis", "Plasma", "Inferno", "Magma", "Cividis", "Blues", "Reds", "Greens", "YlOrRd", "RdBu", "Picnic", "Portland", "Jet", "Hot", "Blackbody", "Earth", "Electric", "Turbo", "IceFire"], "label": "Color scale", "category": "colors", "applies_to": ["density_heatmap", "density_contour", "scatter", "scatter_3d"]},

    # ── Range Slider / Range Selector ──────────────────────────
    "showRangeSlider": {"type": "boolean", "default": False, "label": "Range slider", "category": "xAxis", "applies_to": _CARTESIAN},
    "showRangeSelector": {"type": "boolean", "default": False, "label": "Range selector", "category": "xAxis", "applies_to": _CARTESIAN},

    # ── Error Bars ─────────────────────────────────────────────
    "errorBarsY": {"type": "boolean", "default": False, "label": "Show Y error bars", "category": "analytics", "applies_to": ["scatter", "bar", "column", "line"]},
    "errorBarsYValue": {"type": "number", "default": 10, "min": 0, "max": 100, "label": "Y error ±%", "category": "analytics", "applies_to": ["scatter", "bar", "column", "line"]},

    # ── LaTeX / MathJax ────────────────────────────────────────
    "latexEnabled": {"type": "boolean", "default": False, "label": "Enable LaTeX", "category": "chartStyle", "applies_to": _ALL_PLOTLY},

    # ── Combo / Multi-Layer style ─────────────────────────────
    "y2AxisLabel": {"type": "string", "default": "", "label": "Secondary Y label", "category": "yAxis", "applies_to": ["combo"]},
    "showY2AxisGridlines": {"type": "boolean", "default": False, "label": "Secondary Y gridlines", "category": "yAxis", "applies_to": ["combo"]},
    "comboBarMode": {"type": "select", "default": "group", "options": ["group", "stack", "relative"], "label": "Bar layer mode", "category": "chartStyle", "applies_to": ["combo"]},
    "comboBarGap": {"type": "number", "default": 0.2, "min": 0, "max": 1, "step": 0.05, "label": "Bar layer gap", "category": "chartStyle", "applies_to": ["combo"]},
    "comboColorscale": {"type": "select", "default": "", "options": ["", "Viridis", "Plasma", "Inferno", "Magma", "Cividis", "Blues", "Reds", "Greens", "YlOrRd", "RdBu", "Turbo", "IceFire", "Jet"], "label": "Layer color gradient", "category": "colors", "applies_to": ["combo"]},
    "smallMultiplesMaxColumns": {"type": "number", "default": 2, "min": 1, "max": 6, "label": "Trellis max columns", "category": "chartStyle", "applies_to": ["combo"]},

    # ── Axis tick formatting (G8) ──────────────────────────────
    "yAxisFormat": {"type": "select", "default": "", "options": ["", ",.0f", "$,.2f", "$,.0f", ",.0%", ",.1%", ".2f", ".3f", ".2s"], "label": "Y axis format", "category": "yAxis", "applies_to": _CARTESIAN},
    "y2AxisFormat": {"type": "select", "default": "", "options": ["", ",.0f", "$,.2f", "$,.0f", ",.0%", ",.1%", ".2f", ".3f", ".2s"], "label": "Secondary Y format", "category": "yAxis", "applies_to": ["combo"]},
    "xAxisFormat": {"type": "select", "default": "", "options": ["", ",.0f", "$,.2f", "$,.0f", ",.0%", ".2f", "%Y-%m-%d", "%b %Y", "%Y"], "label": "X axis format", "category": "xAxis", "applies_to": _CARTESIAN},

    # ── Reversed axes (G7) ─────────────────────────────────────
    "reverseY": {"type": "boolean", "default": False, "label": "Reverse Y axis", "category": "yAxis", "applies_to": _CARTESIAN},
    "reverseX": {"type": "boolean", "default": False, "label": "Reverse X axis", "category": "xAxis", "applies_to": _CARTESIAN},
    "reverseY2": {"type": "boolean", "default": False, "label": "Reverse secondary Y", "category": "yAxis", "applies_to": ["combo"]},

    # ── Axis range control (G6) ────────────────────────────────
    "yAxisMin": {"type": "number", "default": None, "label": "Y axis min", "category": "yAxis", "applies_to": _CARTESIAN},
    "yAxisMax": {"type": "number", "default": None, "label": "Y axis max", "category": "yAxis", "applies_to": _CARTESIAN},
    "y2AxisMin": {"type": "number", "default": None, "label": "Secondary Y min", "category": "yAxis", "applies_to": ["combo"]},
    "y2AxisMax": {"type": "number", "default": None, "label": "Secondary Y max", "category": "yAxis", "applies_to": ["combo"]},

    # ── Synchronized dual axes (G5) ────────────────────────────
    "syncAxes": {"type": "boolean", "default": False, "label": "Sync Y axes", "category": "yAxis", "applies_to": ["combo"]},

    # ── Reference lines (G1) ───────────────────────────────────
    # Stored as JSON array in visual format_options; applied post-build.
    # Each: {axis: "y"|"y2"|"x", type: "constant"|"average"|"median"|"min"|"max",
    #        value?: number, label?: string, lineColor?: string,
    #        lineDash?: string, lineWidth?: number}
    "referenceLines": {"type": "json", "default": [], "label": "Reference lines", "category": "analytics", "applies_to": _CARTESIAN},

    # ── Reference bands (G2) ───────────────────────────────────
    # Each: {axis: "y"|"y2"|"x", y0: number, y1: number,
    #        fillColor?: string, opacity?: number, label?: string}
    "referenceBands": {"type": "json", "default": [], "label": "Reference bands", "category": "analytics", "applies_to": _CARTESIAN},

    # ── Axis sort (G16) ────────────────────────────────────────
    "categorySort": {"type": "select", "default": "", "options": ["", "category ascending", "category descending", "total ascending", "total descending", "min ascending", "min descending", "max ascending", "max descending"], "label": "Category sort", "category": "xAxis", "applies_to": _CARTESIAN},

    # ── Mark borders (G17) ─────────────────────────────────────
    "barBorderColor": {"type": "color", "default": "", "label": "Bar border color", "category": "chartStyle", "applies_to": ["bar", "column", "combo"]},
    "barBorderWidth": {"type": "number", "default": 0, "min": 0, "max": 5, "step": 0.5, "label": "Bar border width", "category": "chartStyle", "applies_to": ["bar", "column", "combo"]},
    "xAxisType": {"type": "select", "default": "", "options": ["", "linear", "category", "date", "log"], "label": "X axis type", "category": "xAxis", "applies_to": _CARTESIAN},

    # ── Jitter (G11) ───────────────────────────────────────────
    "comboJitter": {"type": "number", "default": 0, "min": 0, "max": 0.4, "step": 0.05, "label": "Scatter jitter", "category": "chartStyle", "applies_to": ["combo"]},

    # ── Tooltip template (G12) ─────────────────────────────────
    "comboTooltipTemplate": {"type": "string", "default": "", "label": "Tooltip template", "category": "chartStyle", "applies_to": ["combo"]},

    # ── Point annotations (G10) ────────────────────────────────
    # Each: {x: value, y: value, text: string, arrowhead?: int,
    #        font?: {size?: int, color?: string}, ax?: int, ay?: int}
    "annotations": {"type": "json", "default": [], "label": "Point annotations", "category": "analytics", "applies_to": _CARTESIAN},

    # ── IBCS Card format options ───────────────────────────────
    "ibcsCardShowGraphic": {"type": "boolean", "default": False, "label": "Show SVG graphic", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsCardGraphicSourceType": {"type": "select", "default": "custom", "options": ["custom", "generated"], "label": "Graphic source", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsCardGraphicPosition": {"type": "select", "default": "bottom", "options": ["top", "right", "bottom", "left"], "label": "Graphic position", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsCardDiPosition": {"type": "select", "default": "bottom", "options": ["top", "right", "bottom", "left"], "label": "DI overlay position", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsCardShowEduSummary": {"type": "boolean", "default": True, "label": "Show EDU summary", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsCardEduPosition": {"type": "select", "default": "inline", "options": ["inline", "top", "right", "bottom", "left"], "label": "EDU summary position", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsCardShowSignals": {"type": "boolean", "default": True, "label": "Show signal chips", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsCardGraphicSvg": {"type": "string", "default": "", "label": "Graphic SVG (URL/inline)", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsCardGraphicGeneratedType": {"type": "select", "default": "ibcs_bar", "options": ["ibcs_bar", "ibcs_line", "ibcs_waterfall"], "label": "Graphic visual type", "category": "ibcsCard", "applies_to": ["ibcs_card"]},
    "ibcsFontSize": {"type": "number", "default": 16, "min": 6, "max": 50, "label": "Font size", "category": "ibcsCard", "applies_to": ["ibcs_card", "ibcs_bar", "ibcs_line", "ibcs_column", "ibcs_waterfall"]},
    "ibcsDataLabelFontSize": {"type": "number", "default": 16, "min": 6, "max": 50, "label": "Data label font size", "category": "ibcsCard", "applies_to": ["ibcs_card", "ibcs_bar", "ibcs_line", "ibcs_column", "ibcs_waterfall"]},
    "ibcsFontFamily": {"type": "select", "default": "", "options": ["Arial", "Helvetica", "Inter", "Segoe UI", "system-ui"], "label": "Font family", "category": "ibcsCard", "applies_to": ["ibcs_card", "ibcs_bar", "ibcs_line", "ibcs_column", "ibcs_waterfall"]},

    # ── Slicer format (promoted from PBIR slicer_config) ───────
    "slicerRowCount": {"type": "number", "default": 1, "min": 1, "max": 10, "label": "Row count", "category": "slicerLayout", "applies_to": ["slicer"]},
    "slicerColumnCount": {"type": "number", "default": 1, "min": 1, "max": 10, "label": "Column count", "category": "slicerLayout", "applies_to": ["slicer"]},
    "slicerStyle": {"type": "select", "default": "Cards", "options": ["Cards", "Flow"], "label": "Style", "category": "slicerLayout", "applies_to": ["slicer"]},
    "slicerTileShape": {"type": "select", "default": "rectangleRoundedByPixel", "options": ["rectangleRoundedByPixel", "rectangle", "oval"], "label": "Tile shape", "category": "slicerLayout", "applies_to": ["slicer"]},
    "slicerRoundedCurve": {"type": "number", "default": 15, "min": 0, "max": 50, "label": "Corner radius", "category": "slicerLayout", "applies_to": ["slicer"]},
    "slicerValueAlignment": {"type": "select", "default": "center", "options": ["left", "center", "right"], "label": "Value alignment", "category": "slicerValue", "applies_to": ["slicer"]},
    "slicerValueFontSize": {"type": "number", "default": 9, "min": 6, "max": 36, "label": "Value font size", "category": "slicerValue", "applies_to": ["slicer"]},
    "slicerOverflowStyle": {"type": "number", "default": 0, "min": 0, "max": 1, "label": "Overflow style", "category": "slicerOverflow", "applies_to": ["slicer"]},
    "slicerOverflowDirection": {"type": "number", "default": 0, "min": 0, "max": 1, "label": "Overflow direction", "category": "slicerOverflow", "applies_to": ["slicer"]},
    "slicerPaddingSelection": {"type": "select", "default": "Narrow", "options": ["None", "Narrow", "Medium", "Wide"], "label": "Padding", "category": "slicerPadding", "applies_to": ["slicer"]},
    "slicerFillCustomShow": {"type": "boolean", "default": False, "label": "Custom fill", "category": "slicerPadding", "applies_to": ["slicer"]},
    "slicerOrientation": {"type": "number", "default": 0, "min": 0, "max": 1, "label": "Orientation", "category": "slicerLayout", "applies_to": ["slicer"]},
    "slicerCustomizePadding": {"type": "boolean", "default": False, "label": "Customize padding", "category": "slicerPadding", "applies_to": ["slicer"]},
    "slicerRoundedCurveCustom": {"type": "boolean", "default": False, "label": "Custom corner radius", "category": "slicerLayout", "applies_to": ["slicer"]},
    "slicerPaddingTop": {"type": "number", "default": 0, "min": 0, "max": 50, "label": "Padding top", "category": "slicerPadding", "applies_to": ["slicer"]},
    "slicerPaddingBottom": {"type": "number", "default": 0, "min": 0, "max": 50, "label": "Padding bottom", "category": "slicerPadding", "applies_to": ["slicer"]},
    "slicerImageFit": {"type": "select", "default": "Normal", "options": ["Normal", "Fit", "Fill"], "label": "Image fit", "category": "slicerImage", "applies_to": ["slicer"]},
    "slicerImagePosition": {"type": "select", "default": "Behind", "options": ["Behind", "Front"], "label": "Image position", "category": "slicerImage", "applies_to": ["slicer"]},
    "slicerImagePadding": {"type": "number", "default": 0, "min": 0, "max": 50, "label": "Image padding", "category": "slicerImage", "applies_to": ["slicer"]},
    "slicerImageSaturation": {"type": "number", "default": 100, "min": 0, "max": 100, "label": "Image saturation", "category": "slicerImage", "applies_to": ["slicer"]},
    "slicerImageAsBackground": {"type": "boolean", "default": False, "label": "Set as background", "category": "slicerImage", "applies_to": ["slicer"]},
    "slicerImageIgnorePadding": {"type": "boolean", "default": False, "label": "Ignore padding", "category": "slicerImage", "applies_to": ["slicer"]},
    "matrixColumnFormatting": {"type": "object", "default": None, "label": "Column formatting (dataBars)", "category": "matrixData", "applies_to": ["matrix"]},
    "matrixColumnWidths": {"type": "object", "default": None, "label": "Column widths", "category": "matrixData", "applies_to": ["matrix"]},
    "matrixValuesFormatting": {"type": "object", "default": None, "label": "Values conditional formatting", "category": "matrixData", "applies_to": ["matrix"]},
    "matrixSubTotals": {"type": "object", "default": None, "label": "Subtotals config", "category": "matrixLayout", "applies_to": ["matrix"]},
    "matrixTotalFormatting": {"type": "object", "default": None, "label": "Total row formatting", "category": "matrixLayout", "applies_to": ["matrix"]},

    # ── Matrix format (promoted from chart_objects) ────────────
    "matrixLayout": {"type": "select", "default": "Tabular", "options": ["Tabular", "Compact", "Outline"], "label": "Layout", "category": "matrixLayout", "applies_to": ["matrix"]},
    "matrixSteppedIndentation": {"type": "number", "default": 10, "min": 0, "max": 40, "label": "Stepped indentation", "category": "matrixLayout", "applies_to": ["matrix"]},
    "matrixGridHorizontal": {"type": "boolean", "default": True, "label": "Horizontal gridlines", "category": "matrixLayout", "applies_to": ["matrix"]},
    "matrixAutoSizeColumns": {"type": "boolean", "default": True, "label": "Auto-size columns", "category": "matrixLayout", "applies_to": ["matrix"]},
    "matrixColumnHeaderBg": {"type": "color", "default": "", "label": "Header background", "category": "matrixHeaders", "applies_to": ["matrix"]},
    "matrixColumnHeaderWordWrap": {"type": "boolean", "default": True, "label": "Header word wrap", "category": "matrixHeaders", "applies_to": ["matrix"]},
    "matrixColumnHeaderOutline": {"type": "number", "default": 1, "min": 0, "max": 2, "label": "Header outline", "category": "matrixHeaders", "applies_to": ["matrix"]},

    # ── Card format (promoted from chart_objects) ──────────────
    "cardValueFontSize": {"type": "number", "default": 14, "min": 8, "max": 72, "label": "Value font size", "category": "cardValues", "applies_to": ["card"]},
    "cardCategoryLabelsShow": {"type": "boolean", "default": True, "label": "Show category labels", "category": "cardValues", "applies_to": ["card"]},
    "cardCategoryFontSize": {"type": "number", "default": 12, "min": 6, "max": 36, "label": "Category font size", "category": "cardValues", "applies_to": ["card"]},
    "cardCategoryColor": {"type": "color", "default": "", "label": "Category color", "category": "cardValues", "applies_to": ["card"]},
    "cardValueColor": {"type": "color", "default": "", "label": "Value color", "category": "cardValues", "applies_to": ["card"]},
    "cardBarColor": {"type": "color", "default": "", "label": "Accent bar color", "category": "cardBar", "applies_to": ["card"]},
    "cardBarWeight": {"type": "number", "default": 3, "min": 0, "max": 10, "label": "Accent bar weight", "category": "cardBar", "applies_to": ["card"]},

    # ── Shape outline (promoted from shape_properties) ─────────
    "shape_outline_show": {"type": "boolean", "default": True, "label": "Show outline", "category": "shapeOutline", "applies_to": ["shape"]},
    "shape_outline_color": {"type": "color", "default": "", "label": "Outline color", "category": "shapeOutline", "applies_to": ["shape"]},
    "shape_outline_weight": {"type": "number", "default": 1, "min": 0, "max": 10, "label": "Outline weight", "category": "shapeOutline", "applies_to": ["shape"]},

    # ── Chart extras (promoted from chart_objects) ─────────────
    "legendShowGradient": {"type": "boolean", "default": False, "label": "Show gradient", "category": "legend", "applies_to": _ALL_PLOTLY},
    "dataPointBorderShow": {"type": "boolean", "default": False, "label": "Data point border", "category": "dataLabels", "applies_to": _ALL_PLOTLY},
    "categoryAxisType": {"type": "select", "default": "", "options": ["", "linear", "categorical", "logarithmic"], "label": "Category axis type", "category": "xAxis", "applies_to": _CARTESIAN},
    "categoryAxisInnerPadding": {"type": "number", "default": 0, "min": 0, "max": 50, "label": "Category axis inner padding", "category": "xAxis", "applies_to": _CARTESIAN},
}

_LEGEND_POSITION_MAP: dict[str, dict[str, Any]] = {
    "top": {"orientation": "h", "y": 1.1, "x": 0.5, "xanchor": "center"},
    "bottom": {"orientation": "h", "y": -0.2, "x": 0.5, "xanchor": "center"},
    "left": {"x": -0.15, "y": 0.5},
    "right": {"x": 1.02, "y": 0.5},
}

def _format_options_to_plotly_patch(format_opts: Mapping[str, Any], visual_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Translate structured FormatOptions into a Plotly figure patch.

    Returns (layout_patch, trace_patch).
    - layout_patch is deep-merged into fig_dict["layout"]
    - trace_patch is applied to each trace in fig_dict["data"]
    """
    layout: dict[str, Any] = {}
    trace: dict[str, Any] = {}

    # Title
    show_title = format_opts.get("showTitle", True)
    if not show_title:
        layout["title"] = {"text": ""}
    else:
        title_text = format_opts.get("title")
        if title_text:
            layout.setdefault("title", {})["text"] = title_text
        title_font_size = format_opts.get("titleFontSize")
        if title_font_size is not None:
            layout.setdefault("title", {}).setdefault("font", {})["size"] = title_font_size
        title_font_color = format_opts.get("titleFontColor")
        if title_font_color:
            layout.setdefault("title", {}).setdefault("font", {})["color"] = title_font_color

    # Legend
    show_legend = format_opts.get("showLegend")
    if show_legend is not None:
        layout["showlegend"] = bool(show_legend)
    legend_pos = format_opts.get("legendPosition")
    if legend_pos and legend_pos in _LEGEND_POSITION_MAP:
        layout["legend"] = dict(_LEGEND_POSITION_MAP[legend_pos])

    # Legend font styling (from PBIR legend objects)
    legend_font_size = format_opts.get("legendFontSize")
    legend_font_family = format_opts.get("legendFontFamily")
    legend_font_color = format_opts.get("legendFontColor")
    if legend_font_size:
        layout.setdefault("legend", {}).setdefault("font", {})["size"] = int(legend_font_size)
    if legend_font_family:
        layout.setdefault("legend", {}).setdefault("font", {})["family"] = legend_font_family
    if legend_font_color:
        layout.setdefault("legend", {}).setdefault("font", {})["color"] = legend_font_color
    legend_title_text = format_opts.get("legendTitleText")
    legend_show_title = format_opts.get("legendShowTitle")
    if legend_show_title and legend_title_text:
        layout.setdefault("legend", {}).setdefault("title", {})["text"] = legend_title_text

    # X Axis
    show_x_axis = format_opts.get("showXAxis")
    if show_x_axis is not None and not show_x_axis:
        layout.setdefault("xaxis", {})["visible"] = False
    show_x_title = format_opts.get("showXAxisTitle")
    if show_x_title is not None and not show_x_title:
        layout.setdefault("xaxis", {}).setdefault("title", {})["text"] = ""
    x_label = format_opts.get("xAxisLabel")
    if x_label and (show_x_title is None or show_x_title):
        layout.setdefault("xaxis", {}).setdefault("title", {})["text"] = x_label
    elif x_label == "" and (show_x_title is None or show_x_title):
        # Explicitly cleared — remove axis title
        layout.setdefault("xaxis", {}).setdefault("title", {})["text"] = ""
    x_tick = format_opts.get("xAxisTickAngle")
    if x_tick is not None and x_tick != 0:
        layout.setdefault("xaxis", {})["tickangle"] = x_tick
    show_x_grid = format_opts.get("showXAxisGridlines")
    if show_x_grid is not None:
        layout.setdefault("xaxis", {})["showgrid"] = bool(show_x_grid)

    # X Axis font styling (from PBIR categoryAxis)
    x_font_size = format_opts.get("xAxisFontSize") or format_opts.get("categoryAxisFontSize")
    x_font_family = format_opts.get("xAxisFontFamily") or format_opts.get("categoryAxisFontFamily")
    x_font_color = format_opts.get("xAxisFontColor") or format_opts.get("categoryAxisFontColor")
    if x_font_size:
        layout.setdefault("xaxis", {}).setdefault("tickfont", {})["size"] = int(x_font_size)
    if x_font_family:
        layout.setdefault("xaxis", {}).setdefault("tickfont", {})["family"] = x_font_family
    if x_font_color:
        layout.setdefault("xaxis", {}).setdefault("tickfont", {})["color"] = x_font_color
    x_gridline_color = format_opts.get("xAxisGridlineColor")
    if x_gridline_color:
        layout.setdefault("xaxis", {})["gridcolor"] = x_gridline_color

    # Y Axis
    show_y_axis = format_opts.get("showYAxis")
    if show_y_axis is not None and not show_y_axis:
        layout.setdefault("yaxis", {})["visible"] = False
    show_y_title = format_opts.get("showYAxisTitle")
    if show_y_title is not None and not show_y_title:
        layout.setdefault("yaxis", {}).setdefault("title", {})["text"] = ""
    y_label = format_opts.get("yAxisLabel")
    if y_label and (show_y_title is None or show_y_title):
        layout.setdefault("yaxis", {}).setdefault("title", {})["text"] = y_label
    elif y_label == "" and (show_y_title is None or show_y_title):
        layout.setdefault("yaxis", {}).setdefault("title", {})["text"] = ""
    y_tick = format_opts.get("yAxisTickAngle")
    if y_tick is not None and y_tick != 0:
        layout.setdefault("yaxis", {})["tickangle"] = y_tick
    show_y_grid = format_opts.get("showYAxisGridlines")
    if show_y_grid is not None:
        layout.setdefault("yaxis", {})["showgrid"] = bool(show_y_grid)

    # Y Axis font styling (from PBIR valueAxis)
    y_font_size = format_opts.get("yAxisFontSize") or format_opts.get("valueAxisFontSize")
    y_font_family = format_opts.get("yAxisFontFamily") or format_opts.get("valueAxisFontFamily")
    y_font_color = format_opts.get("yAxisFontColor") or format_opts.get("valueAxisFontColor")
    if y_font_size:
        layout.setdefault("yaxis", {}).setdefault("tickfont", {})["size"] = int(y_font_size)
    if y_font_family:
        layout.setdefault("yaxis", {}).setdefault("tickfont", {})["family"] = y_font_family
    if y_font_color:
        layout.setdefault("yaxis", {}).setdefault("tickfont", {})["color"] = y_font_color
    y_gridline_color = format_opts.get("yAxisGridlineColor") or format_opts.get("valueAxisGridlineColor")
    if y_gridline_color:
        layout.setdefault("yaxis", {})["gridcolor"] = y_gridline_color

    # Secondary Y Axis (combo / dual axis)
    y2_label = format_opts.get("y2AxisLabel")
    if y2_label:
        layout.setdefault("yaxis2", {}).setdefault("title", {})["text"] = y2_label
    show_y2_grid = format_opts.get("showY2AxisGridlines")
    if show_y2_grid is not None:
        layout.setdefault("yaxis2", {})["showgrid"] = bool(show_y2_grid)

    # Legacy gridlines
    show_grid = format_opts.get("showGridlines")
    if show_grid is not None and show_x_grid is None and show_y_grid is None:
        layout.setdefault("xaxis", {})["showgrid"] = bool(show_grid)
        layout.setdefault("yaxis", {})["showgrid"] = bool(show_grid)

    # ── Axis tick formatting (G8) ────────────────────────────────
    y_axis_format = format_opts.get("yAxisFormat")
    if y_axis_format:
        layout.setdefault("yaxis", {})["tickformat"] = y_axis_format
    y2_axis_format = format_opts.get("y2AxisFormat")
    if y2_axis_format:
        layout.setdefault("yaxis2", {})["tickformat"] = y2_axis_format
    x_axis_format = format_opts.get("xAxisFormat")
    if x_axis_format:
        layout.setdefault("xaxis", {})["tickformat"] = x_axis_format

    # ── Reversed axes (G7) ───────────────────────────────────────
    if format_opts.get("reverseY"):
        layout.setdefault("yaxis", {})["autorange"] = "reversed"
    if format_opts.get("reverseX"):
        layout.setdefault("xaxis", {})["autorange"] = "reversed"
    if format_opts.get("reverseY2"):
        layout.setdefault("yaxis2", {})["autorange"] = "reversed"

    # ── Axis range control (G6) ──────────────────────────────────
    y_min = format_opts.get("yAxisMin")
    y_max = format_opts.get("yAxisMax")
    if y_min is not None or y_max is not None:
        ax = layout.setdefault("yaxis", {})
        existing = ax.get("range", [None, None])
        ax["range"] = [
            float(y_min) if y_min is not None else existing[0],
            float(y_max) if y_max is not None else existing[1],
        ]
    y2_min = format_opts.get("y2AxisMin")
    y2_max = format_opts.get("y2AxisMax")
    if y2_min is not None or y2_max is not None:
        ax2 = layout.setdefault("yaxis2", {})
        existing2 = ax2.get("range", [None, None])
        ax2["range"] = [
            float(y2_min) if y2_min is not None else existing2[0],
            float(y2_max) if y2_max is not None else existing2[1],
        ]

    # ── Synchronized dual axes (G5) ──────────────────────────────
    if format_opts.get("syncAxes") and visual_type == "combo":
        layout.setdefault("yaxis2", {})["matches"] = "y"

    # ── Mark borders (G17) ───────────────────────────────────────
    bar_border_color = format_opts.get("barBorderColor")
    bar_border_width = format_opts.get("barBorderWidth")
    if (bar_border_color or (bar_border_width is not None and bar_border_width > 0)):
        if visual_type in ("bar", "column", "combo"):
            ml = trace.setdefault("marker", {}).setdefault("line", {})
            if bar_border_color:
                ml["color"] = bar_border_color
            if bar_border_width is not None:
                ml["width"] = float(bar_border_width)

    # Data labels
    show_labels = format_opts.get("showDataLabels")
    if show_labels:
        _default_pos = "outside" if visual_type in ("bar", "column", "combo") else "auto"
        pos = format_opts.get("dataLabelPosition") or _default_pos
        trace["textposition"] = pos

        # --- Build texttemplate with precision support ---
        display_units = format_opts.get("dataLabelDisplayUnits", "auto")
        precision = format_opts.get("dataLabelPrecision")

        # Determine the value variable for texttemplate
        # Note: display units that require value division are handled in
        # _apply_format_patch_to_figure via customdata post-processing.
        value_var = "%{value}" if visual_type == "bar" else "%{y}"

        # Store display-unit markers so _apply_format_patch_to_figure can
        # post-process traces (divide values, update texttemplate).
        _DU_MAP = {
            "thousands": (1e3, "K"),
            "millions": (1e6, "M"),
            "billions": (1e9, "B"),
            "trillions": (1e12, "T"),
        }
        if display_units in _DU_MAP:
            divisor, suffix = _DU_MAP[display_units]
            trace["_dax_display_divisor"] = divisor
            trace["_dax_display_suffix"] = suffix

        # Build texttemplate with precision (display-unit division applied later)
        if precision is not None:
            prec = int(precision)
            trace["texttemplate"] = value_var.replace("}", f":,.{prec}f}}")
        else:
            trace["texttemplate"] = value_var

        # For line/scatter, mode must include "text" to show data labels
        if visual_type in ("line", "area", "scatter"):
            trace["_dax_show_text"] = True  # marker for mode composition below

        # Apply data-label font properties
        textfont: dict[str, Any] = dict(trace.get("textfont", {}))
        dl_color = format_opts.get("dataLabelColor")
        if dl_color:
            textfont["color"] = dl_color
        dl_font_size = format_opts.get("dataLabelFontSize")
        if dl_font_size is not None:
            textfont["size"] = int(dl_font_size)
        dl_font_family = format_opts.get("dataLabelFontFamily")
        if dl_font_family:
            textfont["family"] = dl_font_family
        # Apply transparency as opacity on the color
        dl_transparency = format_opts.get("dataLabelTransparency")
        if dl_transparency is not None and dl_transparency > 0:
            alpha = 1.0 - (float(dl_transparency) / 100.0)
            base_color = textfont.get("color", "#000000")
            textfont["color"] = _apply_alpha_to_color(base_color, alpha)
        if textfont:
            trace["textfont"] = textfont

    # Bar mode
    bar_mode = format_opts.get("barMode")
    if bar_mode and visual_type in ("bar", "column"):
        layout["barmode"] = bar_mode

    # Combo bar mode (applies barmode to combo charts with bar layers)
    combo_bar_mode = format_opts.get("comboBarMode")
    if combo_bar_mode and visual_type == "combo":
        layout["barmode"] = combo_bar_mode

    # Bar gap / group gap
    bargap = format_opts.get("bargap")
    if bargap is not None and visual_type in ("bar", "column"):
        layout["bargap"] = float(bargap)
    bargroupgap = format_opts.get("bargroupgap")
    if bargroupgap is not None and visual_type in ("bar", "column"):
        layout["bargroupgap"] = float(bargroupgap)

    # Combo bar gap
    combo_bar_gap = format_opts.get("comboBarGap")
    if combo_bar_gap is not None and visual_type == "combo":
        layout["bargap"] = float(combo_bar_gap)

    # Data label angle (bar/column)
    data_label_angle = format_opts.get("dataLabelAngle")
    if data_label_angle is not None and visual_type in ("bar", "column"):
        trace["textangle"] = int(data_label_angle)

    # Line shape
    line_shape = format_opts.get("lineShape")
    if line_shape and visual_type in ("line", "area"):
        trace.setdefault("line", {})["shape"] = line_shape

    # Line width
    line_width = format_opts.get("lineWidth")
    if line_width is not None and visual_type in ("line", "area"):
        trace.setdefault("line", {})["width"] = line_width

    # Line dash
    line_dash = format_opts.get("lineDash")
    if line_dash and line_dash != "solid" and visual_type in ("line", "area"):
        trace.setdefault("line", {})["dash"] = line_dash

    # Fill area below line
    fill_area = format_opts.get("fillArea")
    if fill_area and visual_type == "line":
        trace["fill"] = "tozeroy"

    # Show markers (line/area/scatter) — compose mode with text labels
    show_markers = format_opts.get("showMarkers")
    want_text = trace.pop("_dax_show_text", False)
    if visual_type in ("line", "area"):
        parts = ["lines"]
        if show_markers is None or show_markers:
            parts.append("markers")
        if want_text:
            parts.append("text")
        trace["mode"] = "+".join(parts)
    elif visual_type == "scatter":
        parts = ["markers"]
        if want_text:
            parts.append("text")
        trace["mode"] = "+".join(parts)

    # Marker size (scatter)
    marker_size = format_opts.get("markerSize")
    if marker_size is not None and visual_type == "scatter":
        trace.setdefault("marker", {})["size"] = marker_size

    # Marker opacity (scatter)
    marker_opacity = format_opts.get("markerOpacity")
    if marker_opacity is not None and visual_type == "scatter":
        trace.setdefault("marker", {})["opacity"] = float(marker_opacity)

    # Marker symbol (scatter)
    marker_symbol = format_opts.get("markerSymbol")
    if marker_symbol and marker_symbol != "circle" and visual_type == "scatter":
        trace.setdefault("marker", {})["symbol"] = marker_symbol

    # ── Pie / Donut options ──────────────────────────────────────
    if visual_type == "pie":
        pie_hole = format_opts.get("pieHole")
        if pie_hole is not None and float(pie_hole) > 0:
            trace["hole"] = float(pie_hole)
        pie_text_info = format_opts.get("pieTextInfo")
        if pie_text_info and pie_text_info != "percent":
            trace["textinfo"] = pie_text_info
        pie_text_pos = format_opts.get("pieTextPosition")
        if pie_text_pos and pie_text_pos != "auto":
            trace["textposition"] = pie_text_pos
        pie_pull = format_opts.get("piePull")
        if pie_pull is not None and float(pie_pull) > 0:
            trace["pull"] = float(pie_pull)
        pie_start_angle = format_opts.get("pieStartAngle")
        if pie_start_angle is not None and int(pie_start_angle) != 0:
            layout["pie"] = {"startangle": int(pie_start_angle)}
            # Plotly uses trace-level rotation for go.Pie; for px figures
            # we can set it at trace level directly too.
            trace["rotation"] = int(pie_start_angle)

    # ── Histogram options ────────────────────────────────────────
    if visual_type == "histogram":
        hist_nbins = format_opts.get("histNbins")
        if hist_nbins is not None and int(hist_nbins) > 0:
            trace["nbinsx"] = int(hist_nbins)
        hist_func = format_opts.get("histFunc")
        if hist_func and hist_func != "count":
            trace["histfunc"] = hist_func
        hist_norm = format_opts.get("histNorm")
        if hist_norm:
            trace["histnorm"] = hist_norm
        cumulative = format_opts.get("cumulative")
        if cumulative:
            trace["cumulative"] = {"enabled": True}

    # ── Box options ──────────────────────────────────────────────
    if visual_type == "box":
        box_points = format_opts.get("boxPoints")
        if box_points is not None:
            trace["boxpoints"] = False if box_points == "false" else box_points
        box_mean = format_opts.get("boxMean")
        if box_mean:
            if box_mean == "sd":
                trace["boxmean"] = "sd"
            elif box_mean == "true":
                trace["boxmean"] = True
        notched = format_opts.get("notched")
        if notched:
            trace["notched"] = True

    # ── Violin options ───────────────────────────────────────────
    if visual_type == "violin":
        violin_side = format_opts.get("violinSide")
        if violin_side and violin_side != "both":
            trace["side"] = violin_side
        violin_points = format_opts.get("violinPoints")
        if violin_points is not None:
            trace["points"] = False if violin_points == "false" else violin_points
        violin_box = format_opts.get("violinBox")
        if violin_box:
            trace["box"] = {"visible": True}

    # ── Strip options ────────────────────────────────────────────
    if visual_type == "strip":
        strip_jitter = format_opts.get("stripJitter")
        if strip_jitter is not None:
            trace["jitter"] = float(strip_jitter)

    # ── Hierarchical options (treemap/sunburst/icicle) ───────────
    if visual_type in ("treemap", "sunburst", "icicle"):
        max_depth = format_opts.get("maxDepth")
        if max_depth is not None and int(max_depth) > 0:
            trace["maxdepth"] = int(max_depth)
        hier_text_info = format_opts.get("hierTextInfo")
        if hier_text_info and hier_text_info != "label+value":
            trace["textinfo"] = hier_text_info
        branch_values = format_opts.get("branchValues")
        if branch_values and branch_values != "remainder":
            trace["branchvalues"] = branch_values

    # ── Polar options ────────────────────────────────────────────
    if visual_type in ("scatter_polar", "line_polar", "bar_polar"):
        polar_dir = format_opts.get("polarAngularDirection")
        if polar_dir and polar_dir != "clockwise":
            layout.setdefault("polar", {}).setdefault("angularaxis", {})["direction"] = polar_dir
        polar_start = format_opts.get("polarStartAngle")
        if polar_start is not None and int(polar_start) != 90:
            layout.setdefault("polar", {}).setdefault("angularaxis", {})["rotation"] = int(polar_start)
        polar_fill = format_opts.get("polarFill")
        if polar_fill:
            trace["fill"] = polar_fill

    # ── Financial options (candlestick/OHLC) ─────────────────────
    if visual_type in ("candlestick", "ohlc"):
        inc_color = format_opts.get("financialIncreasingColor")
        if inc_color:
            trace.setdefault("increasing", {})["line"] = {"color": inc_color}
            if visual_type == "candlestick":
                trace["increasing"]["fillcolor"] = inc_color
        dec_color = format_opts.get("financialDecreasingColor")
        if dec_color:
            trace.setdefault("decreasing", {})["line"] = {"color": dec_color}
            if visual_type == "candlestick":
                trace["decreasing"]["fillcolor"] = dec_color

    # ── Gauge / Indicator options ────────────────────────────────
    if visual_type == "gauge":
        gauge_shape = format_opts.get("gaugeShape")
        if gauge_shape and gauge_shape != "angular":
            trace.setdefault("gauge", {})["shape"] = gauge_shape
        gauge_max = format_opts.get("gaugeAxisRangeMax")
        if gauge_max is not None and float(gauge_max) > 0:
            trace.setdefault("gauge", {}).setdefault("axis", {})["range"] = [0, float(gauge_max)]
        gauge_bar_color = format_opts.get("gaugeBarColor")
        if gauge_bar_color:
            trace.setdefault("gauge", {}).setdefault("bar", {})["color"] = gauge_bar_color
        gauge_steps = format_opts.get("gaugeSteps")
        if gauge_steps is False:
            trace.setdefault("gauge", {})["steps"] = []

    # ── Sankey options ───────────────────────────────────────────
    if visual_type == "sankey":
        sankey_thickness = format_opts.get("sankeyNodeThickness")
        if sankey_thickness is not None and int(sankey_thickness) != 20:
            trace.setdefault("node", {})["thickness"] = int(sankey_thickness)
        sankey_padding = format_opts.get("sankeyNodePadding")
        if sankey_padding is not None and int(sankey_padding) != 10:
            trace.setdefault("node", {})["pad"] = int(sankey_padding)
        sankey_orient = format_opts.get("sankeyOrientation")
        if sankey_orient and sankey_orient != "h":
            trace["orientation"] = sankey_orient

    # ── Waterfall options ────────────────────────────────────────
    if visual_type == "waterfall":
        wf_connector = format_opts.get("waterfallConnectorLine")
        if wf_connector is False:
            trace["connector"] = {"line": {"width": 0}}
        wf_inc_color = format_opts.get("waterfallIncreasingColor")
        if wf_inc_color:
            trace.setdefault("increasing", {})["marker"] = {"color": wf_inc_color}
        wf_dec_color = format_opts.get("waterfallDecreasingColor")
        if wf_dec_color:
            trace.setdefault("decreasing", {})["marker"] = {"color": wf_dec_color}
        wf_total_color = format_opts.get("waterfallTotalColor")
        if wf_total_color:
            trace.setdefault("totals", {})["marker"] = {"color": wf_total_color}

    # ── Global chart style ───────────────────────────────────────
    hover_mode = format_opts.get("hoverMode")
    if hover_mode:
        if hover_mode == "false":
            layout["hovermode"] = False
        else:
            layout["hovermode"] = hover_mode

    chart_font_family = format_opts.get("chartFontFamily")
    if chart_font_family:
        layout.setdefault("font", {})["family"] = chart_font_family
    chart_font_size = format_opts.get("chartFontSize")
    if chart_font_size is not None and int(chart_font_size) != 12:
        layout.setdefault("font", {})["size"] = int(chart_font_size)

    # Color sequence
    color_seq = format_opts.get("colorSequence")
    if color_seq and color_seq in _PLOTLY_COLOR_SEQUENCES:
        layout["colorway"] = _PLOTLY_COLOR_SEQUENCES[color_seq]

    # Background colors
    plot_bg = format_opts.get("plotBgColor")
    if plot_bg:
        layout["plot_bgcolor"] = plot_bg
    paper_bg = format_opts.get("paperBgColor")
    if paper_bg:
        layout["paper_bgcolor"] = paper_bg

    # ── Log axes ─────────────────────────────────────────────────
    log_x = format_opts.get("logX")
    if log_x:
        layout.setdefault("xaxis", {})["type"] = "log"
    log_y = format_opts.get("logY")
    if log_y:
        layout.setdefault("yaxis", {})["type"] = "log"

    # ── X axis type override (linear/category/date/log) ──────────
    x_axis_type = format_opts.get("xAxisType")
    if x_axis_type:
        layout.setdefault("xaxis", {})["type"] = x_axis_type

    # ── Range slider ─────────────────────────────────────────────
    show_range_slider = format_opts.get("showRangeSlider")
    if show_range_slider:
        layout.setdefault("xaxis", {})["rangeslider"] = {"visible": True}

    # ── Range selector ───────────────────────────────────────────
    show_range_selector = format_opts.get("showRangeSelector")
    if show_range_selector:
        layout.setdefault("xaxis", {})["rangeselector"] = {
            "buttons": [
                {"count": 1, "label": "1M", "step": "month", "stepmode": "backward"},
                {"count": 3, "label": "3M", "step": "month", "stepmode": "backward"},
                {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
                {"count": 1, "label": "YTD", "step": "year", "stepmode": "todate"},
                {"count": 1, "label": "1Y", "step": "year", "stepmode": "backward"},
                {"step": "all", "label": "All"},
            ]
        }

    # ── Error bars ───────────────────────────────────────────────
    error_bars_y = format_opts.get("errorBarsY")
    if error_bars_y:
        pct = format_opts.get("errorBarsYValue", 10)
        trace["error_y"] = {"type": "percent", "value": float(pct), "visible": True}

    # ── LaTeX / MathJax ──────────────────────────────────────────
    latex_enabled = format_opts.get("latexEnabled")
    if latex_enabled:
        # Plotly supports LaTeX in title/axis labels when surrounded by $...$
        # This just ensures MathJax is available; the user writes $...$ in labels
        pass  # MathJax is auto-loaded by Plotly.js on the frontend

    return layout, trace


def _maybe_set_date_axis(fig_dict: dict[str, Any]) -> None:
    """G15 — Auto-detect date x-values and configure date axis formatting.

    Inspects x-values across all traces. If the majority look like date
    strings (ISO format, common date patterns), sets ``xaxis.type = "date"``
    and adds sensible defaults (range slider hint, dtick for sparse data).
    """
    import re

    _DATE_RE = re.compile(
        r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}"  # 2024-01-15 or 2024/1/5
        r"|^\d{1,2}[-/]\d{1,2}[-/]\d{4}"  # 01-15-2024
        r"|^\d{4}$"                        # 2024 (year only)
        r"|^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d"  # "January 2024"
    , re.IGNORECASE)

    # Collect sample x values from traces
    sample_x: list[str] = []
    for t in fig_dict.get("data", []):
        xs = t.get("x")
        if not xs:
            continue
        if not isinstance(xs, (list, tuple)):
            try:
                xs = list(xs)
            except Exception:
                continue
        if len(xs) > 0:
            for v in xs[:10]:
                if isinstance(v, str):
                    sample_x.append(v)
                elif hasattr(v, "isoformat"):
                    # Already a datetime-like object
                    sample_x.append("DATE_OBJECT")
            if len(sample_x) >= 10:
                break

    if not sample_x:
        return

    date_count = sum(1 for s in sample_x if s == "DATE_OBJECT" or _DATE_RE.match(s))
    if date_count / len(sample_x) >= 0.6:
        fig_dict.setdefault("layout", {}).setdefault("xaxis", {}).setdefault("type", "date")


def _apply_display_unit_post_processing(fig_dict: dict[str, Any]) -> None:
    """Post-process traces that have display-unit markers.

    For each trace with ``_dax_display_divisor``, divide the numeric values
    by the divisor, store them in ``customdata``, and rewrite
    ``texttemplate`` to reference ``%{customdata[0]:format}suffix``.
    The original y/values data is left untouched so axes and tooltips
    remain correct.
    """
    for t in fig_dict.get("data", []):
        divisor = t.pop("_dax_display_divisor", None)
        suffix = t.pop("_dax_display_suffix", "")
        if divisor is None:
            continue

        # Determine which data array to read (bar uses "values", others "y")
        trace_type = t.get("type", "")
        if trace_type in ("pie", "funnel"):
            raw = t.get("values", [])
        else:
            raw = t.get("y", [])

        if not raw:
            continue

        # Divide values and store in customdata
        divided: list[Any] = []
        for v in raw:
            if isinstance(v, (int, float)):
                divided.append(v / divisor)
            else:
                divided.append(v)

        # Merge into existing customdata (keep any prior columns)
        existing_cd = t.get("customdata")
        if existing_cd and isinstance(existing_cd, list) and len(existing_cd) > 0:
            # Append to each row
            new_cd = []
            for idx, row in enumerate(existing_cd):
                dv = divided[idx] if idx < len(divided) else None
                if isinstance(row, (list, tuple)):
                    new_cd.append(list(row) + [dv])
                else:
                    new_cd.append([row, dv])
            t["customdata"] = new_cd
            cd_idx = len(new_cd[0]) - 1 if new_cd else 1
        else:
            t["customdata"] = [[dv] for dv in divided]
            cd_idx = 0

        # Rewrite texttemplate: replace %{y:format} or %{value:format}
        # with %{customdata[N]:format}suffix
        tmpl = t.get("texttemplate", "")
        if tmpl:
            import re
            # Match %{y:...} or %{value:...} or bare %{y} / %{value}
            def _repl(m: re.Match) -> str:
                fmt_part = m.group(1) or ""
                return f"%{{customdata[{cd_idx}]{fmt_part}}}{suffix}"
            tmpl = re.sub(r"%\{(?:y|value)(:[^}]*)?\}", _repl, tmpl)
            t["texttemplate"] = tmpl


def _apply_format_patch_to_figure(fig_dict: dict[str, Any], format_opts: Mapping[str, Any], visual_type: str) -> dict[str, Any]:
    """Apply format options to a Plotly figure dict."""
    if not format_opts:
        # Still apply smart date axis even without explicit format options
        _maybe_set_date_axis(fig_dict)
        return fig_dict
    layout_patch, trace_patch = _format_options_to_plotly_patch(format_opts, visual_type)
    if layout_patch:
        fig_dict["layout"] = _deep_merge(fig_dict.get("layout", {}), layout_patch)
    if trace_patch and "data" in fig_dict:
        for i, t in enumerate(fig_dict["data"]):
            # Adjust textposition for scatter/scattergl traces — "outside" is
            # only valid for bar; scatter uses the 9-point grid (e.g. "top center").
            effective_patch = dict(trace_patch)
            if effective_patch.get("textposition") == "outside" and t.get("type") in ("scatter", "scattergl"):
                effective_patch["textposition"] = "top center"
            fig_dict["data"][i] = _deep_merge(t, effective_patch)

    # ── Display-unit post-processing (divide values → customdata) ──
    # If traces have _dax_display_divisor markers, we divide the actual
    # numeric values and rewrite texttemplate to use customdata + suffix.
    _apply_display_unit_post_processing(fig_dict)

    # ── Reference lines (G1) — post-figure shapes ───────────────
    ref_lines = format_opts.get("referenceLines") or format_opts.get("reference_lines") or format_opts.get("chart_reference_lines")
    if ref_lines and isinstance(ref_lines, list):
        shapes = fig_dict.setdefault("layout", {}).setdefault("shapes", [])
        annotations = fig_dict.setdefault("layout", {}).setdefault("annotations", [])
        for rl in ref_lines:
            if not isinstance(rl, dict):
                continue
            axis = rl.get("axis", "y")
            rl_type = rl.get("type", "constant")
            color = rl.get("lineColor", "red")
            dash = rl.get("lineDash", "dash")
            width = rl.get("lineWidth", 2)
            label_text = rl.get("label", "")

            # Determine value
            value = rl.get("value")
            if rl_type != "constant" and value is None:
                # Compute aggregate from trace data
                import numpy as np
                all_vals: list[float] = []
                for t in fig_dict.get("data", []):
                    vals = t.get("y", []) if axis in ("y", "y2") else t.get("x", [])
                    if vals:
                        all_vals.extend(v for v in vals if isinstance(v, (int, float)))
                if all_vals:
                    if rl_type == "average":
                        value = float(np.mean(all_vals))
                    elif rl_type == "median":
                        value = float(np.median(all_vals))
                    elif rl_type == "min":
                        value = float(np.min(all_vals))
                    elif rl_type == "max":
                        value = float(np.max(all_vals))

            if value is not None:
                is_horizontal = axis in ("y", "y2")
                yref = "y2" if axis == "y2" else "y"
                xref = "x"
                if is_horizontal:
                    shapes.append({
                        "type": "line",
                        "xref": "paper", "yref": yref,
                        "x0": 0, "x1": 1,
                        "y0": value, "y1": value,
                        "line": {"color": color, "dash": dash, "width": width},
                    })
                else:
                    shapes.append({
                        "type": "line",
                        "xref": xref, "yref": "paper",
                        "x0": value, "x1": value,
                        "y0": 0, "y1": 1,
                        "line": {"color": color, "dash": dash, "width": width},
                    })
                if label_text:
                    annotations.append({
                        "xref": "paper" if is_horizontal else xref,
                        "yref": yref if is_horizontal else "paper",
                        "x": 1.0 if is_horizontal else value,
                        "y": value if is_horizontal else 1.0,
                        "text": label_text,
                        "showarrow": False,
                        "font": {"color": color, "size": 11},
                        "xanchor": "left" if is_horizontal else "center",
                        "yanchor": "bottom",
                    })

    # ── Reference bands (G2) — post-figure shapes ────────────────
    ref_bands = format_opts.get("referenceBands")
    if ref_bands and isinstance(ref_bands, list):
        shapes = fig_dict.setdefault("layout", {}).setdefault("shapes", [])
        annotations = fig_dict.setdefault("layout", {}).setdefault("annotations", [])
        for rb in ref_bands:
            if not isinstance(rb, dict):
                continue
            axis = rb.get("axis", "y")
            y0 = rb.get("y0")
            y1 = rb.get("y1")
            fill_color = rb.get("fillColor", "rgba(0,100,200,0.15)")
            opacity = rb.get("opacity", 0.2)
            label_text = rb.get("label", "")
            if y0 is not None and y1 is not None:
                is_horizontal = axis in ("y", "y2")
                yref = "y2" if axis == "y2" else "y"
                if is_horizontal:
                    shapes.append({
                        "type": "rect",
                        "xref": "paper", "yref": yref,
                        "x0": 0, "x1": 1,
                        "y0": float(y0), "y1": float(y1),
                        "fillcolor": fill_color,
                        "opacity": float(opacity),
                        "line": {"width": 0},
                    })
                else:
                    shapes.append({
                        "type": "rect",
                        "xref": "x", "yref": "paper",
                        "x0": float(y0), "x1": float(y1),
                        "y0": 0, "y1": 1,
                        "fillcolor": fill_color,
                        "opacity": float(opacity),
                        "line": {"width": 0},
                    })
                if label_text:
                    mid = (float(y0) + float(y1)) / 2
                    annotations.append({
                        "xref": "paper" if is_horizontal else "x",
                        "yref": yref if is_horizontal else "paper",
                        "x": 1.0 if is_horizontal else mid,
                        "y": mid if is_horizontal else 1.0,
                        "text": label_text,
                        "showarrow": False,
                        "font": {"size": 10, "color": "#555"},
                        "xanchor": "left" if is_horizontal else "center",
                        "yanchor": "middle",
                    })

    # ── Axis sort (G16) — post-figure categoryorder ──────────────
    cat_sort = format_opts.get("categorySort")
    if cat_sort and isinstance(cat_sort, str):
        sort_map = {
            "category ascending": "category ascending",
            "category descending": "category descending",
            "total ascending": "total ascending",
            "total descending": "total descending",
            "min ascending": "min ascending",
            "min descending": "min descending",
            "max ascending": "max ascending",
            "max descending": "max descending",
        }
        if cat_sort in sort_map:
            traces = fig_dict.get("data", []) if isinstance(fig_dict.get("data"), list) else []
            has_horizontal = any(
                isinstance(t, dict) and str(t.get("orientation", "")).lower() == "h"
                for t in traces
            )
            axis_key = "yaxis" if has_horizontal else "xaxis"
            fig_dict.setdefault("layout", {}).setdefault(axis_key, {})["categoryorder"] = sort_map[cat_sort]

    # ── Jitter on categorical scatter (G11) ──────────────────────
    jitter_amount = format_opts.get("comboJitter")
    if jitter_amount and float(jitter_amount) > 0:
        import numpy as np

        j = float(jitter_amount)
        # Detect categories from the first trace with string x values
        categories: list[str] | None = None
        for t in fig_dict.get("data", []):
            xs = t.get("x")
            if xs and len(xs) > 0 and isinstance(xs[0], str):
                categories = list(dict.fromkeys(xs))  # unique, order-preserving
                break

        if categories:
            cat_to_idx = {c: idx for idx, c in enumerate(categories)}
            rng = np.random.default_rng(42)  # deterministic seed for reproducibility
            for t in fig_dict.get("data", []):
                xs = t.get("x")
                if not xs or not isinstance(xs[0], str):
                    continue
                is_scatter_markers = (
                    t.get("type") == "scatter"
                    and "markers" in (t.get("mode") or "")
                    and "lines" not in (t.get("mode") or "")
                )
                if is_scatter_markers:
                    # Jitter: numeric category index + random offset
                    t["x"] = [
                        cat_to_idx.get(x, 0) + float(rng.uniform(-j, j))
                        for x in xs
                    ]
                else:
                    # Non-scatter traces: convert to numeric without jitter
                    t["x"] = [cat_to_idx.get(x, 0) for x in xs]

            fig_dict.setdefault("layout", {}).setdefault("xaxis", {}).update({
                "ticktext": categories,
                "tickvals": list(range(len(categories))),
                "tickmode": "array",
            })

    # ── Tooltip template (G12) ───────────────────────────────────
    tooltip_tpl = format_opts.get("comboTooltipTemplate")
    if tooltip_tpl and isinstance(tooltip_tpl, str) and tooltip_tpl.strip():
        for t in fig_dict.get("data", []):
            t["hovertemplate"] = tooltip_tpl.strip()

    # ── Point annotations (G10) ──────────────────────────────────
    user_annotations = format_opts.get("annotations")
    if user_annotations and isinstance(user_annotations, list):
        annotations = fig_dict.setdefault("layout", {}).setdefault("annotations", [])
        for ann in user_annotations:
            if not isinstance(ann, dict):
                continue
            x_val = ann.get("x")
            y_val = ann.get("y")
            text = ann.get("text", "")
            if x_val is None or y_val is None:
                continue
            plotly_ann: dict[str, Any] = {
                "x": x_val,
                "y": y_val,
                "text": str(text),
                "showarrow": ann.get("showarrow", True),
                "arrowhead": ann.get("arrowhead", 2),
            }
            ax = ann.get("ax")
            ay = ann.get("ay")
            if ax is not None:
                plotly_ann["ax"] = int(ax)
            if ay is not None:
                plotly_ann["ay"] = int(ay)
            font = ann.get("font")
            if font and isinstance(font, dict):
                plotly_ann["font"] = {}
                if "size" in font:
                    plotly_ann["font"]["size"] = int(font["size"])
                if "color" in font:
                    plotly_ann["font"]["color"] = str(font["color"])
            annotations.append(plotly_ann)

    # ── Smart date axis (G15) ────────────────────────────────────
    # Auto-detect date values in x-axis and configure date formatting.
    # Only applies when xAxisType is not explicitly set.
    if not format_opts.get("xAxisType"):
        _maybe_set_date_axis(fig_dict)

    # ── Color sequence: apply to individual traces ───────────────
    # Plotly Express assigns explicit marker.color to each trace,
    # which overrides layout.colorway. Apply colors directly.
    color_seq_name = format_opts.get("colorSequence")
    if color_seq_name and color_seq_name in _PLOTLY_COLOR_SEQUENCES:
        colors = _PLOTLY_COLOR_SEQUENCES[color_seq_name]
        for i, t in enumerate(fig_dict.get("data", [])):
            c = colors[i % len(colors)]
            if t.get("type") in ("bar", "histogram"):
                t.setdefault("marker", {})["color"] = c
            elif t.get("type") in ("scatter", "scattergl"):
                t.setdefault("marker", {})["color"] = c
                if t.get("line"):
                    t["line"]["color"] = c
                elif t.get("mode") and "lines" in t["mode"]:
                    t.setdefault("line", {})["color"] = c

    _apply_powerbi_selector_point_colors(fig_dict, format_opts)

    # ── Series order reversal (PBI seriesOrderReversed) ──────────
    if format_opts.get("seriesOrderSorted") and "data" in fig_dict:
        fig_dict["data"] = sorted(
            fig_dict["data"],
            key=lambda trace: str(trace.get("name") or trace.get("legendgroup") or "") if isinstance(trace, dict) else "",
        )

    # Reverse trace order so the first measure renders behind the last.
    if format_opts.get("seriesOrderReversed") and "data" in fig_dict:
        fig_dict["data"] = list(reversed(fig_dict["data"]))

    if format_opts.get("seriesLabelsShow") and visual_type in {"line", "area"} and "data" in fig_dict:
        annotations = fig_dict.setdefault("layout", {}).setdefault("annotations", [])
        for trace in fig_dict.get("data", []):
            if not isinstance(trace, dict):
                continue
            name = str(trace.get("name") or "").strip()
            xs = trace.get("x")
            ys = trace.get("y")
            if not name or not isinstance(xs, list) or not isinstance(ys, list) or not xs or not ys:
                continue
            for idx in range(min(len(xs), len(ys)) - 1, -1, -1):
                if xs[idx] is not None and ys[idx] is not None:
                    annotations.append(
                        {
                            "x": xs[idx],
                            "y": ys[idx],
                            "text": name,
                            "showarrow": False,
                            "xanchor": "left",
                            "yanchor": "middle",
                            "font": {"size": 10, "color": "#444"},
                        }
                    )
                    break

    # ── Overlay width scaling (PBI clusteredGapOverlapReverse) ───
    # When overlapping, make the "behind" trace wider and the "front"
    # trace narrower so the front bar sits centered over the back bar.
    if format_opts.get("barMode") == "overlay" and "data" in fig_dict:
        traces = fig_dict["data"]
        n = len(traces)
        if n >= 2:
            for i, t in enumerate(traces):
                if t.get("type") == "bar":
                    # Earlier traces (behind) are wider, later (front) narrower
                    # Scale from 1.0 (back) down to ~0.5 (front)
                    frac = i / (n - 1) if n > 1 else 0
                    t["width"] = None  # let Plotly auto-size
                    t["marker"] = t.get("marker", {})
                    t["marker"]["opacity"] = 1.0
                    # Use offset to center narrower bars
                    if format_opts.get("clusteredGapOverlapReverse"):
                        # Back trace: full width; front trace: ~60% width
                        scale = 1.0 - 0.4 * frac
                        t["width"] = scale  # relative width

    # ── Per-data-point color map (PBI dataPoint selectors) ───────
    # For hierarchical charts (treemap, sunburst, icicle), apply
    # per-label colors from the colorMap extracted from PBI dataPoint
    # objects with selectors.
    color_map = format_opts.get("colorMap")
    if color_map and isinstance(color_map, Mapping) and "data" in fig_dict:
        _HIERARCHICAL_TRACE_TYPES = {"treemap", "sunburst", "icicle"}
        for t in fig_dict["data"]:
            if t.get("type") in _HIERARCHICAL_TRACE_TYPES:
                labels = t.get("labels", [])
                if labels:
                    resolved_colors = []
                    for lbl in labels:
                        c = color_map.get(str(lbl))
                        if c:
                            resolved_colors.append(c)
                        else:
                            resolved_colors.append(None)
                    # Only apply if at least some colors matched
                    if any(c is not None for c in resolved_colors):
                        t.setdefault("marker", {})["colors"] = resolved_colors

    # ─────────────────────────────────────────────────────────────
    return fig_dict

_DEFAULT_VISUAL_INTERACTIONS: dict[str, Any] = {
    "affects_others": True,
    "is_affected": True,
    "mode": "filter",
}

def _normalize_visual_interactions(raw: Any) -> dict[str, Any]:
    if raw is None:
        return dict(_DEFAULT_VISUAL_INTERACTIONS)
    if not isinstance(raw, Mapping):
        raise ValueError("visual.interactions must be an object if provided")

    affects_others = raw.get("affects_others", _DEFAULT_VISUAL_INTERACTIONS["affects_others"])
    is_affected = raw.get("is_affected", _DEFAULT_VISUAL_INTERACTIONS["is_affected"])
    mode = raw.get("mode", _DEFAULT_VISUAL_INTERACTIONS["mode"])

    if not isinstance(affects_others, bool):
        raise ValueError("visual.interactions.affects_others must be a boolean")
    if not isinstance(is_affected, bool):
        raise ValueError("visual.interactions.is_affected must be a boolean")
    if not isinstance(mode, str) or not mode.strip():
        raise ValueError("visual.interactions.mode must be a non-empty string")
    mode_norm = mode.strip().lower()
    if mode_norm not in {"filter", "highlight"}:
        raise ValueError("visual.interactions.mode must be 'filter' or 'highlight'")

    result: dict[str, Any] = {
        "affects_others": affects_others,
        "is_affected": is_affected,
        "mode": mode_norm,
    }

    # Optional per-visual-pair interaction targets
    interaction_targets = raw.get("interaction_targets")
    if interaction_targets is not None:
        if not isinstance(interaction_targets, Mapping):
            raise ValueError("visual.interactions.interaction_targets must be an object if provided")
        validated: dict[str, str] = {}
        for target_id, target_mode in interaction_targets.items():
            if not isinstance(target_id, str) or not target_id.strip():
                raise ValueError("interaction_targets keys must be non-empty strings (visual IDs)")
            if not isinstance(target_mode, str) or target_mode.strip().lower() not in {"filter", "highlight", "none"}:
                raise ValueError(
                    f"interaction_targets[{target_id!r}] must be 'filter', 'highlight', or 'none'"
                )
            validated[target_id.strip()] = target_mode.strip().lower()
        if validated:
            result["interaction_targets"] = validated

    return result

