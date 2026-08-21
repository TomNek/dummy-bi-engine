from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, MutableMapping, Optional

from .sql_utils import quote_ident, unwrap_outer_parentheses


@dataclass(frozen=True)
class TableSource:
    """Represents a logical table's SQL source.

    - If sql is None/empty, the table resolves to its quoted logical name.
    - If sql is a SELECT/WITH/subquery, it is wrapped and aliased to the logical name.

    This module is intentionally pure (no compilation, no project semantics).
    Runtime/project orchestration is responsible for populating TABLE_SOURCES.
    """

    sql: str


# Logical table name (uppercased) -> TableSource
_TABLE_SOURCES: MutableMapping[str, TableSource] = {}


def clear_table_sources() -> None:
    _TABLE_SOURCES.clear()


def set_table_sources(sources: Mapping[str, str | TableSource]) -> None:
    """Replace the current table source mapping.

    Keys are treated case-insensitively.
    Values may be:
    - str: the raw SQL/table source
    - TableSource
    """

    _TABLE_SOURCES.clear()
    for k, v in dict(sources).items():
        if k is None:
            continue
        name = str(k).strip()
        if not name:
            continue
        if isinstance(v, TableSource):
            sql = str(v.sql or "")
        else:
            sql = str(v or "")
        sql = sql.strip()
        if not sql:
            continue
        _TABLE_SOURCES[name.upper()] = TableSource(sql=sql)


def resolve_table_source_sql(table_name: str) -> str:
    """Resolve a logical table name to a FROM/JOIN-safe SQL source.

    - Unknown tables fall back to quote_ident(table_name)
    - SELECT/WITH/subqueries are wrapped and aliased to the logical table name
    """

    name = str(table_name or "").strip()
    if not name:
        return "(SELECT NULL WHERE FALSE)"

    src = _TABLE_SOURCES.get(name.upper())
    if src is None:
        return quote_ident(name)

    s = (src.sql or "").strip()
    if not s:
        return quote_ident(name)

    upper = s.lstrip().upper()
    if s.startswith("(") or upper.startswith("SELECT") or upper.startswith("WITH"):
        inner = unwrap_outer_parentheses(s)
        return f"({inner}) AS {quote_ident(name)}"

    # Already a FROM-safe source (e.g., a physical identifier or view name).
    return s


def resolve_table_source_raw_sql(table_name: str) -> str:
    """Resolve a logical table name to its *raw* SQL source.

    - Unknown tables fall back to quote_ident(table_name)
    - Calculated tables return the raw stored SQL (often SELECT/WITH)

    Callers that need to apply a different alias (e.g., `AS t`) should use this
    and then wrap/alias using sql_utils.as_from_source or equivalent.
    """

    name = str(table_name or "").strip()
    if not name:
        return "(SELECT NULL WHERE FALSE)"

    src = _TABLE_SOURCES.get(name.upper())
    if src is None:
        return quote_ident(name)

    s = (src.sql or "").strip()
    if not s:
        return quote_ident(name)
    return s
