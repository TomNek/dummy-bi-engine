"""Small shared SQL-string helpers.

These utilities are intentionally tiny and dependency-light so that
`dax_engine.compiler`, `dax_engine.lowering_table`, and other lowering modules
can share stable helpers without circular imports.

No behavior changes: code here is moved verbatim from `dax_engine.compiler`.
"""

from __future__ import annotations

import re


def quote_ident(name: str) -> str:
    """Quote an identifier only when required.

    - Leaves simple identifiers unquoted to preserve existing SQL snapshots.
    - Uses DuckDB/SQL standard double-quote escaping.
    """

    s = str(name)
    if s.isidentifier():
        return s
    # If the caller already provided a quoted identifier, keep it.
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s
    return '"' + s.replace('"', '""') + '"'


def quote_alias(name: str) -> str:
    """Always quote a projection alias (DAX aliases often contain spaces)."""

    s = str(name)
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s
    return '"' + s.replace('"', '""') + '"'


def normalize_sql(sql: str) -> str:
    """Normalize SQL for stable tests.

    - Strip redundant whitespace
    """

    sql = re.sub(r"\s+", " ", sql)
    return sql.strip()


def unwrap_outer_parentheses(sql: str) -> str:
    s = sql.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        ok = True
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    ok = False
                    break
            if depth < 0:
                ok = False
                break
        if ok and depth == 0:
            s = s[1:-1].strip()
        else:
            break
    return s


def rewrite_qualifiers_to_alias(expr_sql: str, alias: str) -> str:
    """Best-effort portability helper.

    If we wrap a derived table as `(...) AS t`, any previously-qualified references
    like `Sales.Amount` won't be valid in the outer scope. This rewrites
    `<identifier>.` to `<alias>.`.
    """

    return re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\.", f"{alias}.", expr_sql)


def rewrite_table_qualifier_to_alias(expr_sql: str, table_name: str, alias: str) -> str:
    """Rewrite only the given table qualifier to an alias.

    Unlike rewrite_qualifiers_to_alias(), this targets a single qualifier so that
    expressions that reference multiple tables don't get clobbered.
    """

    t = str(table_name or "").strip()
    a = str(alias or "").strip()
    if not t or not a:
        return expr_sql

    q = quote_ident(t)
    if q.startswith('"'):
        pat = re.escape(q) + r"\."
    else:
        pat = r"\b" + re.escape(q) + r"\."
    return re.sub(pat, f"{a}.", expr_sql)


def _strip_trailing_alias(sql: str) -> str:
    """Strip a trailing ``AS <identifier>`` from an already-aliased derived table.

    Handles both quoted (``"Product"``) and unquoted (``Product``) identifiers.
    Only strips when the core expression is a parenthesised subquery so that bare
    ``TableName AS alias`` is left untouched.
    """

    m = re.match(
        r'^(\(.*\))\s+AS\s+("(?:[^"]|"")*"|\w+)\s*$',
        sql,
        re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else sql


def as_from_source(table_sql: str, alias: str = "t") -> str:
    """Return a FROM-safe source.

    Many SQL engines require an alias for derived tables. When `table_sql` is a
    subquery, return `(<subquery>) AS <alias>`. Otherwise return it unchanged.

    If the input is already aliased (e.g. ``(subquery) AS Product`` from
    ``resolve_table_source_sql``), the existing alias is stripped first so that
    the caller's requested alias takes precedence without double-wrapping.
    """

    s = _strip_trailing_alias(table_sql.strip())
    upper = s.lstrip().upper()
    if s.startswith("(") or upper.startswith("SELECT") or upper.startswith("WITH"):
        inner = unwrap_outer_parentheses(s)
        return f"({inner}) AS {alias}"
    # Bare table name — alias it so callers can rewrite qualifiers to the alias.
    return f"{s} AS {alias}"
