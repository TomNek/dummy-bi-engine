"""Canonical capability allowlists for the small public Open Core MVP."""

from __future__ import annotations

import os


OPEN_CORE_PROFILE = "open-core-mvp"
PROFILE_ENV_VAR = "DAX_PRODUCT_PROFILE"

OPEN_CORE_DATA_CONNECTIONS = frozenset(
    {
        "csv",
        "parquet",
        "json",
        "folder",
        "excel",
        "text",
        "blob",
        "duckdb",
        "sqlite",
        "postgres",
        "mysql",
        "http",
        "s3",
        "azure_blob",
        "cloudflare_r2",
        "delta",
        "iceberg",
    }
)
OPEN_CORE_VISUAL_TYPES = frozenset(
    {
        "bar",
        "column",
        "line",
        "scatter",
        "area",
        "pie",
        "combo",
        "histogram",
        "box",
        "violin",
        "strip",
        "ecdf",
        "funnel",
        "funnel_area",
        "density_contour",
        "density_heatmap",
        "treemap",
        "sunburst",
        "icicle",
        "scatter_polar",
        "line_polar",
        "bar_polar",
        "bubble",
        "bubble_3d",
        "scatter_3d",
        "line_3d",
        "candlestick",
        "ohlc",
        "waterfall",
        "gauge",
        "sankey",
    }
)


def is_open_core_mvp(profile: str | None = None) -> bool:
    value = profile if profile is not None else os.environ.get(PROFILE_ENV_VAR, "")
    return str(value).strip().lower() == OPEN_CORE_PROFILE
