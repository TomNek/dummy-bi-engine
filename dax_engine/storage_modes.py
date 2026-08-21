"""Storage mode definitions and validation for the DAX-to-DuckDB semantic engine.

Three storage modes are supported (Phase 9):
- **Import**: Data is materialized into DuckDB tables. Queries read from local store.
  Refresh rebuilds from source.
- **DirectQuery**: Data is queried live from external sources via DuckDB views.
  No materialization; always current.
- **DirectLake**: Data is read from columnar lakehouse files (Iceberg/Parquet/Delta)
  via DuckDB views. Lightweight "framing" re-scans metadata without full copy.

Storage mode is a per-table semantic model property, not a runtime switch.
The compiler is unaware of storage modes — it sees the same logical table regardless.
Storage mode is an orchestration concern only.
"""

from __future__ import annotations

import enum
from typing import Any, Mapping, Optional


class StorageMode(enum.Enum):
    """Per-table storage mode."""

    IMPORT = "import"
    DIRECT_QUERY = "direct_query"
    DIRECT_LAKE = "direct_lake"


# Source types that support each storage mode.
_IMPORT_SOURCES = frozenset({
    "csv", "parquet", "json", "excel", "text", "blob",
    "duckdb", "sqlite", "postgres", "mysql",
    "http", "s3", "azure_blob", "cloudflare_r2",
    "delta", "iceberg",
})

_DIRECT_QUERY_SOURCES = frozenset({
    "duckdb", "sqlite", "postgres", "mysql",
    "http", "s3", "azure_blob", "cloudflare_r2",
})

_DIRECT_LAKE_SOURCES = frozenset({
    "iceberg", "parquet", "delta",
})


def parse_storage_mode(raw: Any) -> StorageMode:
    """Parse a storage mode value from YAML/JSON.

    Returns StorageMode.IMPORT if raw is None/empty (backward compatibility).
    Raises ValueError for invalid values.
    """
    if raw is None:
        return StorageMode.IMPORT

    if not isinstance(raw, str):
        raise ValueError(f"storage_mode must be a string, got {type(raw).__name__}")

    normalized = raw.strip().lower().replace("-", "_")
    if not normalized:
        return StorageMode.IMPORT

    # Support both "directquery" (no separator) and "direct_query" forms.
    aliases = {
        "import": StorageMode.IMPORT,
        "direct_query": StorageMode.DIRECT_QUERY,
        "directquery": StorageMode.DIRECT_QUERY,
        "direct_lake": StorageMode.DIRECT_LAKE,
        "directlake": StorageMode.DIRECT_LAKE,
    }
    mode = aliases.get(normalized)
    if mode is None:
        valid = ", ".join(sorted(aliases.keys()))
        raise ValueError(
            f"Invalid storage_mode: {raw!r}. Must be one of: {valid}"
        )
    return mode


def validate_storage_mode_source(
    storage_mode: StorageMode,
    source: Optional[Mapping[str, Any]],
    *,
    table_name: str = "<unknown>",
) -> None:
    """Validate that a table's storage mode is compatible with its source type.

    Rules:
    - Calculated tables (no source) must not have a storage mode set (caller handles).
    - Import: accepts any source type.
    - DirectQuery: requires a live-queryable source (DB/remote).
    - DirectLake: requires columnar lakehouse sources (Iceberg/Parquet/Delta).

    Raises ValueError on incompatible combinations.
    """
    if source is None:
        # Calculated tables — storage_mode is irrelevant; caller should not
        # set it. But if they do, we let it pass (no source to validate against).
        return

    src_type = str(source.get("type", "")).strip().lower()
    if not src_type:
        raise ValueError(
            f"Table {table_name!r}: source.type is required when source is specified"
        )

    if storage_mode == StorageMode.IMPORT:
        if src_type not in _IMPORT_SOURCES:
            raise ValueError(
                f"Table {table_name!r}: source type {src_type!r} is not supported for import mode. "
                f"Supported: {sorted(_IMPORT_SOURCES)}"
            )
    elif storage_mode == StorageMode.DIRECT_QUERY:
        if src_type not in _DIRECT_QUERY_SOURCES:
            raise ValueError(
                f"Table {table_name!r}: source type {src_type!r} is not supported for direct_query mode. "
                f"DirectQuery requires a live-queryable source. "
                f"Supported: {sorted(_DIRECT_QUERY_SOURCES)}"
            )
    elif storage_mode == StorageMode.DIRECT_LAKE:
        if src_type not in _DIRECT_LAKE_SOURCES:
            raise ValueError(
                f"Table {table_name!r}: source type {src_type!r} is not supported for direct_lake mode. "
                f"DirectLake requires columnar lakehouse sources. "
                f"Supported: {sorted(_DIRECT_LAKE_SOURCES)}"
            )


def infer_storage_mode(source: Optional[Mapping[str, Any]]) -> StorageMode:
    """Infer the most appropriate storage mode from a source definition.

    Used when a table has no explicit storage_mode set (backward compatibility).

    Heuristic:
    - No source → IMPORT (calculated tables are virtual anyway).
    - File sources (csv, parquet, json, excel, text, blob) → IMPORT.
    - DB sources (duckdb, sqlite, postgres, mysql) → DIRECT_QUERY.
    - Remote URL sources (http, s3, azure_blob, r2) → DIRECT_QUERY.
    - Lakehouse sources (iceberg, delta) → DIRECT_LAKE.
    - Parquet (local file) → IMPORT; Parquet (remote/directory) could be DIRECT_LAKE.
      For safety, default to IMPORT to match current behavior.
    """
    if source is None:
        return StorageMode.IMPORT

    src_type = str(source.get("type", "")).strip().lower()
    if not src_type:
        return StorageMode.IMPORT

    # Lakehouse columnar formats
    if src_type in ("iceberg", "delta"):
        return StorageMode.DIRECT_LAKE

    # DB sources (live queryable)
    if src_type in ("duckdb", "sqlite", "postgres", "mysql"):
        return StorageMode.DIRECT_QUERY

    # Remote URL sources (live queryable via DuckDB extensions)
    if src_type in ("http", "s3", "azure_blob", "cloudflare_r2"):
        return StorageMode.DIRECT_QUERY

    # File sources (need materialization)
    return StorageMode.IMPORT


def storage_mode_to_str(mode: StorageMode) -> str:
    """Serialize storage mode to its canonical string form for YAML/JSON."""
    return mode.value


def describe_storage_mode(mode: StorageMode) -> str:
    """Human-readable description for UI display."""
    descriptions = {
        StorageMode.IMPORT: "Import — data materialized into DuckDB, refreshed on demand",
        StorageMode.DIRECT_QUERY: "DirectQuery — queries execute live against external source",
        StorageMode.DIRECT_LAKE: "DirectLake — reads columnar files (Iceberg/Parquet) on demand",
    }
    return descriptions.get(mode, mode.value)
