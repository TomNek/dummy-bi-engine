"""
TMDL → Project YAML Converter
==============================
Converts a Power BI Tabular Model Definition Language (TMDL) folder
into the project's native YAML format.

Input:  A TMDL ``definition/`` folder (as exported by Power BI Desktop,
        Tabular Editor, or pbi-tools).

Output: A project directory with ``model/`` YAML files and (optionally)
        copied CSV data files.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml  # type: ignore

from .power_query import build_power_query_metadata


# ── Data-Type Mapping ──────────────────────────────────────────────────
_TMDL_TYPE_MAP: Dict[str, str] = {
    "int64": "INTEGER",
    "int32": "INTEGER",
    "double": "DOUBLE",
    "decimal": "DOUBLE",
    "string": "VARCHAR",
    "boolean": "BOOLEAN",
    "dateTime": "TIMESTAMP",
    "binary": "BLOB",
}


def _map_type(tmdl_type: Optional[str]) -> str:
    if not tmdl_type:
        return "VARCHAR"
    return _TMDL_TYPE_MAP.get(tmdl_type.strip(), "VARCHAR")


# ── Tiny Helpers ───────────────────────────────────────────────────────
def _unquote(name: str) -> str:
    """Remove surrounding single quotes from TMDL identifiers."""
    name = name.strip()
    if name.startswith("'") and name.endswith("'"):
        return name[1:-1]
    return name


def _strip_lineage(lines: List[str]) -> List[str]:
    """Drop annotation / lineageTag / extendedProperty blocks."""
    out: List[str] = []
    skip_block = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("lineageTag:") or stripped.startswith("annotation "):
            skip_block = False
            continue
        if stripped.startswith("extendedProperty "):
            skip_block = True
            continue
        if skip_block:
            if stripped and not stripped.startswith("\t"):
                skip_block = False
            else:
                continue
        out.append(ln)
    return out


# ── Parsed Intermediate Structures ────────────────────────────────────
@dataclass
class TmdlColumn:
    name: str
    data_type: Optional[str] = None
    format_string: Optional[str] = None
    expression: Optional[str] = None
    is_hidden: bool = False
    is_calculated: bool = False
    source_column: Optional[str] = None
    description: Optional[str] = None
    sort_by_column: Optional[str] = None
    display_folder: Optional[str] = None
    parameter_metadata_kind: Optional[int] = None  # 0 = what-if, 2 = field param


@dataclass
class TmdlMeasure:
    name: str
    expression: str
    format_string: Optional[str] = None
    is_hidden: bool = False
    description: Optional[str] = None
    display_folder: Optional[str] = None


@dataclass
class TmdlHierarchy:
    name: str
    levels: List[str] = field(default_factory=list)  # column names


@dataclass
class TmdlCalcItem:
    name: str
    expression: str


@dataclass
class TmdlCalcGroup:
    items: List[TmdlCalcItem] = field(default_factory=list)


@dataclass
class TmdlPartition:
    name: str
    mode: str = "import"
    kind: str = "m"  # "m" | "calculated"
    source: str = ""


@dataclass
class TmdlTable:
    name: str
    columns: List[TmdlColumn] = field(default_factory=list)
    measures: List[TmdlMeasure] = field(default_factory=list)
    hierarchies: List[TmdlHierarchy] = field(default_factory=list)
    partitions: List[TmdlPartition] = field(default_factory=list)
    calc_group: Optional[TmdlCalcGroup] = None
    is_hidden: bool = False


@dataclass
class TmdlRelationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    is_active: bool = True
    cross_filter: str = "single"
    cardinality: str = "many-to-one"  # TMDL default: fromColumn=many, toColumn=one


@dataclass
class TmdlRlsRule:
    table: str
    filter_expression: str


@dataclass
class TmdlRole:
    name: str
    permission: str = "read"
    rules: List[TmdlRlsRule] = field(default_factory=list)


@dataclass
class TmdlModel:
    tables: List[TmdlTable] = field(default_factory=list)
    relationships: List[TmdlRelationship] = field(default_factory=list)
    roles: List[TmdlRole] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
#  TMDL PARSING
# ══════════════════════════════════════════════════════════════════════

def _parse_table_tmdl(path: Path) -> TmdlTable:
    """Parse a single table .tmdl file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # ── Table name from first line ────────────────────────────────────
    first = lines[0].strip()
    m = re.match(r"^table\s+(.+)$", first)
    if not m:
        raise ValueError(f"Cannot parse table name from {path}: {first!r}")
    table_name = _unquote(m.group(1).strip())

    table = TmdlTable(name=table_name)

    # Detect hidden table
    if len(lines) > 1 and lines[1].strip() == "isHidden":
        table.is_hidden = True

    # ── State machine ─────────────────────────────────────────────────
    i = 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blanks / annotations / lineageTag
        if not stripped or stripped.startswith("lineageTag:") or stripped.startswith("annotation "):
            i += 1
            continue

        # ── calculationGroup ──
        if stripped == "calculationGroup":
            cg = TmdlCalcGroup()
            i += 1
            while i < len(lines):
                ln = lines[i].strip()
                if not ln or ln.startswith("lineageTag:") or ln.startswith("annotation "):
                    i += 1
                    continue
                cm = re.match(r"^calculationItem\s+(.+?)(?:\s*=\s*(.*))?$", ln)
                if cm:
                    ci_name = _unquote(cm.group(1).strip())
                    inline_expr = (cm.group(2) or "").strip()
                    expr_lines: List[str] = []
                    if inline_expr:
                        if inline_expr.startswith("```"):
                            # multi-line triple-backtick expression
                            i += 1
                            while i < len(lines):
                                el = lines[i]
                                if el.strip() == "```":
                                    i += 1
                                    break
                                expr_lines.append(el.strip())
                                i += 1
                        else:
                            expr_lines.append(inline_expr)
                            # check for continuation lines
                            i += 1
                            while i < len(lines):
                                nl = lines[i]
                                if nl.strip() and not nl.strip().startswith("calculationItem") and not nl.strip().startswith("column") and not nl.strip().startswith("measure") and _indent_level(nl) > _indent_level(line):
                                    expr_lines.append(nl.strip())
                                    i += 1
                                else:
                                    break
                            cg.items.append(TmdlCalcItem(name=ci_name, expression="\n".join(expr_lines).strip()))
                            continue
                    else:
                        # expression on next lines (skip blank lines)
                        calc_parent_indent = _indent_level(lines[i])
                        i += 1
                        while i < len(lines):
                            el = lines[i]
                            if not el.strip():
                                # skip blank lines inside expression block
                                i += 1
                                continue
                            if _indent_level(el) <= calc_parent_indent:
                                break
                            if el.strip().startswith("calculationItem") or el.strip().startswith("column") or el.strip().startswith("measure"):
                                break
                            expr_lines.append(el.strip())
                            i += 1
                    cg.items.append(TmdlCalcItem(name=ci_name, expression="\n".join(expr_lines).strip()))
                    continue
                # End of calc group section — a top-level element starts
                if not ln.startswith("\t") and not ln.startswith("  "):
                    break
                if ln.startswith("column ") or ln.startswith("measure ") or ln.startswith("partition ") or ln.startswith("hierarchy "):
                    break
                i += 1
            table.calc_group = cg
            continue

        # ── column ──
        col_m = (
            re.match(r"^\tcolumn\s+(.+?)(?:\s*=\s*(.*))?$", line)
            or re.match(r"^    column\s+(.+?)(?:\s*=\s*(.*))?$", line)
            or re.match(r"^\tcolumn\s+(.+?)(?:\s*=\s*(.*))?$", line)
        )
        if not col_m:
            col_m = re.match(r"^\s+column\s+(.+?)(?:\s*=\s*(.*))?$", line) if re.match(r"^\s+column\s", line) else None
        if col_m:
            col = _parse_column(lines, i, col_m.group(1).strip(), col_m.group(2))
            table.columns.append(col)
            i = _skip_block(lines, i + 1, _indent_level(line))
            continue

        # ── measure ──
        meas_m = re.match(r"^\s+measure\s+(.+?)(?:\s*=\s*(.*))?$", line)
        if meas_m:
            meas = _parse_measure(lines, i, meas_m.group(1).strip(), meas_m.group(2))
            table.measures.append(meas)
            i = _skip_block(lines, i + 1, _indent_level(line))
            continue

        # ── hierarchy ──
        hier_m = re.match(r"^\s+hierarchy\s+(.+?)$", line)
        if hier_m:
            hier = _parse_hierarchy(lines, i)
            table.hierarchies.append(hier)
            i = _skip_block(lines, i + 1, _indent_level(line))
            continue

        # ── partition ──
        part_m = re.match(r"^\s+partition\s+(.+?)\s*=\s*(\w+)$", line)
        if part_m:
            part = _parse_partition(lines, i, part_m.group(1).strip(), part_m.group(2).strip())
            table.partitions.append(part)
            i = _skip_block(lines, i + 1, _indent_level(line))
            continue

        i += 1

    return table


def _indent_level(line: str) -> int:
    """Count leading tabs (1 tab = 1 level) or 4-space groups."""
    tabs = len(line) - len(line.lstrip("\t"))
    if tabs > 0:
        return tabs
    spaces = len(line) - len(line.lstrip(" "))
    return spaces // 4


def _skip_block(lines: List[str], start: int, parent_indent: int) -> int:
    """Skip lines that belong to a block at deeper indent than *parent_indent*."""
    i = start
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if _indent_level(lines[i]) <= parent_indent:
            return i
        i += 1
    return i


def _parse_column(lines: List[str], start: int, raw_name: str, inline_expr: Optional[str] = None) -> TmdlColumn:
    """Parse a column declaration starting at *start*."""
    col = TmdlColumn(name=_unquote(raw_name))
    parent_indent = _indent_level(lines[start])

    expr_parts: List[str] = []
    ie = inline_expr.strip() if inline_expr is not None else ""
    if ie.startswith("```"):
        i = start + 1
        while i < len(lines):
            el = lines[i].strip()
            if el == "```":
                break
            expr_parts.append(el)
            i += 1
    elif ie:
        expr_parts.append(ie)
    elif inline_expr is not None:
        i = start + 1
        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped:
                i += 1
                continue
            if _indent_level(lines[i]) <= parent_indent:
                break
            if _is_column_property_line(stripped):
                break
            expr_parts.append(stripped)
            i += 1
    expression = "\n".join(expr_parts).strip()
    if expression:
        col.expression = expression
        col.is_calculated = True

    i = start + 1
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if _indent_level(lines[i]) <= parent_indent:
            break
        if stripped.startswith("dataType:"):
            col.data_type = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("formatString:"):
            col.format_string = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("sourceColumn:"):
            col.source_column = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("displayFolder:"):
            col.display_folder = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("sortByColumn:"):
            col.sort_by_column = _unquote(stripped.split(":", 1)[1].strip())
        elif stripped == "isHidden":
            col.is_hidden = True
        elif stripped.startswith("isNameInferred"):
            pass  # skip
        elif stripped.startswith("description:"):
            col.description = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("extendedProperty ParameterMetadata"):
            # Read the JSON block to extract "kind" value
            # The JSON may start on the same line (after =) or on the next lines
            json_lines: List[str] = []
            prop_indent = _indent_level(lines[i])
            i += 1
            while i < len(lines):
                pl = lines[i]
                if not pl.strip():
                    i += 1
                    continue
                if _indent_level(pl) <= prop_indent:
                    break
                json_lines.append(pl.strip())
                i += 1
            json_text = " ".join(json_lines)
            # Extract "kind": <number> from the JSON text
            kind_m = re.search(r'"kind"\s*:\s*(\d+)', json_text)
            if kind_m:
                col.parameter_metadata_kind = int(kind_m.group(1))
            else:
                # version-only (what-if, kind=0 implied)
                col.parameter_metadata_kind = 0
            continue  # already advanced i
        i += 1
    # If the column has an expression in sourceColumn (like [Value1]), it might
    # be part of a calculated table. We don't mark it as calc column here — that
    # depends on partition type.
    return col


def _is_column_property_line(stripped: str) -> bool:
    return (
        stripped.startswith("dataType:")
        or stripped.startswith("formatString:")
        or stripped.startswith("sourceColumn:")
        or stripped.startswith("displayFolder:")
        or stripped.startswith("sortByColumn:")
        or stripped.startswith("description:")
        or stripped.startswith("lineageTag:")
        or stripped.startswith("summarizeBy:")
        or stripped.startswith("annotation ")
        or stripped.startswith("extendedProperty ")
        or stripped.startswith("isNameInferred")
        or stripped == "isHidden"
    )


def _parse_measure(lines: List[str], start: int, raw_name: str, inline_expr: Optional[str]) -> TmdlMeasure:
    """Parse a measure declaration."""
    name = _unquote(raw_name)
    parent_indent = _indent_level(lines[start])

    # ── Collect expression ────────────────────────────────────────────
    expr_parts: List[str] = []
    ie = inline_expr.strip() if inline_expr else ""
    if ie.startswith("```"):
        # multi-line: read until closing ```
        i = start + 1
        while i < len(lines):
            el = lines[i].strip()
            if el == "```":
                i += 1
                break
            expr_parts.append(el)
            i += 1
    elif ie:
        # single-line expression provided inline after =
        expr_parts.append(ie)
    else:
        # expression on subsequent indented lines until a property line
        # (handles both inline_expr=None and inline_expr="" after = with newline)
        i = start + 1
        while i < len(lines):
            stripped = lines[i].strip()
            if _indent_level(lines[i]) <= parent_indent:
                break
            if stripped.startswith("formatString:") or stripped.startswith("lineageTag:") or stripped.startswith("annotation ") or stripped == "isHidden" or stripped.startswith("displayFolder:") or stripped.startswith("description:"):
                break
            expr_parts.append(stripped)
            i += 1

    expression = "\n".join(expr_parts).strip()

    # ── Collect properties ────────────────────────────────────────────
    fmt = None
    hidden = False
    desc: Optional[str] = None
    folder: Optional[str] = None
    i = start + 1
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if _indent_level(lines[i]) <= parent_indent:
            break
        if stripped.startswith("formatString:"):
            fmt = stripped.split(":", 1)[1].strip()
        elif stripped == "isHidden":
            hidden = True
        elif stripped.startswith("description:"):
            desc = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("displayFolder:"):
            folder = stripped.split(":", 1)[1].strip()
        i += 1

    return TmdlMeasure(
        name=name,
        expression=expression,
        format_string=fmt,
        is_hidden=hidden,
        description=desc,
        display_folder=folder,
    )


def _parse_hierarchy(lines: List[str], start: int) -> TmdlHierarchy:
    """Parse a hierarchy declaration."""
    line = lines[start].strip()
    m = re.match(r"^hierarchy\s+(.+)$", line)
    name = _unquote(m.group(1).strip()) if m else "Unknown"
    hier = TmdlHierarchy(name=name)

    parent_indent = _indent_level(lines[start])
    i = start + 1
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if _indent_level(lines[i]) <= parent_indent:
            break
        lm = re.match(r"^level\s+(.+)$", stripped)
        if lm:
            level_name = _unquote(lm.group(1).strip())
            # Look for column property inside the level block
            level_indent = _indent_level(lines[i])
            j = i + 1
            col_name = level_name  # default
            while j < len(lines):
                ls = lines[j].strip()
                if not ls:
                    j += 1
                    continue
                if _indent_level(lines[j]) <= level_indent:
                    break
                if ls.startswith("column:"):
                    col_name = _unquote(ls.split(":", 1)[1].strip())
                j += 1
            hier.levels.append(col_name)
        i += 1

    return hier


def _parse_partition(lines: List[str], start: int, raw_name: str, kind: str) -> TmdlPartition:
    """Parse a partition block."""
    part = TmdlPartition(name=_unquote(raw_name), kind=kind.lower())
    parent_indent = _indent_level(lines[start])
    source_lines: List[str] = []
    in_source = False
    i = start + 1
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            if in_source:
                source_lines.append("")
            i += 1
            continue
        if _indent_level(lines[i]) <= parent_indent:
            break
        if stripped.startswith("mode:"):
            part.mode = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("source") and "=" in stripped:
            in_source = True
            # Capture inline expression after "source ="
            inline_src = stripped.split("=", 1)[1].strip()
            if inline_src:
                source_lines.append(inline_src)
        elif in_source:
            source_lines.append(stripped)
        i += 1
    part.source = "\n".join(source_lines).strip()
    return part


# ── Relationships ─────────────────────────────────────────────────────

def _parse_relationships_tmdl(path: Path) -> List[TmdlRelationship]:
    """Parse the relationships.tmdl file."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    rels: List[TmdlRelationship] = []
    current: Dict[str, Any] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("lineageTag:") or stripped.startswith("annotation "):
            continue

        if stripped.startswith("relationship "):
            if current.get("from_table"):
                rels.append(_make_rel(current))
            current = {}
            continue

        if stripped.startswith("fromColumn:"):
            val = stripped.split(":", 1)[1].strip()
            if "." in val:
                t, c = val.split(".", 1)
                current["from_table"] = _unquote(t)
                current["from_column"] = _unquote(c)

        elif stripped.startswith("toColumn:"):
            val = stripped.split(":", 1)[1].strip()
            if "." in val:
                t, c = val.split(".", 1)
                current["to_table"] = _unquote(t)
                current["to_column"] = _unquote(c)

        elif stripped.startswith("crossFilteringBehavior:"):
            current["cross_filter"] = stripped.split(":", 1)[1].strip().lower()

        elif stripped.startswith("fromCardinality:"):
            raw_card = stripped.split(":", 1)[1].strip().lower()
            current["from_cardinality"] = raw_card  # "one" or "many"

        elif stripped.startswith("toCardinality:"):
            raw_card = stripped.split(":", 1)[1].strip().lower()
            current["to_cardinality"] = raw_card

        elif stripped.startswith("isActive:"):
            current["is_active"] = stripped.split(":", 1)[1].strip().lower() != "false"

    if current.get("from_table"):
        rels.append(_make_rel(current))

    return rels


def _make_rel(d: Dict[str, Any]) -> TmdlRelationship:
    # Resolve cardinality from TMDL fromCardinality/toCardinality fields.
    # TMDL default: fromColumn = many side, toColumn = one side → "many-to-one".
    # Explicit overrides: fromCardinality:one → one-to-one or one-to-many.
    from_card = d.get("from_cardinality", "many")  # TMDL default omits = many
    to_card = d.get("to_cardinality", "one")        # TMDL default omits = one
    cardinality = f"{from_card}-to-{to_card}"
    return TmdlRelationship(
        from_table=d.get("from_table", ""),
        from_column=d.get("from_column", ""),
        to_table=d.get("to_table", ""),
        to_column=d.get("to_column", ""),
        is_active=d.get("is_active", True),
        cross_filter=d.get("cross_filter", "single"),
        cardinality=cardinality,
    )





# ── Roles ─────────────────────────────────────────────────────────────

def _qualify_bare_columns(expr: str, table_name: str) -> str:
    """Qualify bare [Column] references with the table name.

    Power BI TMDL RLS filters use unqualified column references like
    ``[Region] = "France"`` because the table context is implicit.
    Our DAX parser requires fully qualified references:
    ``Region[Region] = "France"``.
    """
    # Match [ColName] that is NOT preceded by a table name (letter, digit, quote, ])
    # i.e., only match [Col] at word boundary, not Table[Col]
    return re.sub(
        r"(?<![A-Za-z0-9_'\]]) *\[",
        f"'{table_name}'[" if " " in table_name or not table_name.isidentifier() else f"{table_name}[",
        expr,
    )


def _parse_role_tmdl(path: Path) -> TmdlRole:
    """Parse a role .tmdl file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    first = lines[0].strip()
    m = re.match(r"^role\s+(.+)$", first)
    role_name = _unquote(m.group(1).strip()) if m else path.stem

    role = TmdlRole(name=role_name)

    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith("modelPermission:"):
            role.permission = stripped.split(":", 1)[1].strip()
        tp = re.match(r"^tablePermission\s+(.+?)\s*=\s*(.+)$", stripped)
        if tp:
            tbl = _unquote(tp.group(1).strip())
            expr = tp.group(2).strip()
            # Qualify bare [Column] refs with table name for our parser
            expr = _qualify_bare_columns(expr, tbl)
            # Normalize == to = (TMDL uses strict-equals, our parser uses =)
            expr = expr.replace("==", "=")
            role.rules.append(TmdlRlsRule(table=tbl, filter_expression=expr))

    return role


# ══════════════════════════════════════════════════════════════════════
#  FULL MODEL PARSE
# ══════════════════════════════════════════════════════════════════════

# ── Field Parameter / What-If Parameter Extraction ────────────────────

# Regex for NAMEOF('Table'[Column]) references in field parameter set literals
_NAMEOF_RE = re.compile(
    r"\(\s*\"([^\"]*)\"\s*,\s*NAMEOF\(\s*'([^']+)'\s*\[([^\]]+)\]\s*\)\s*,\s*(\d+)\s*(?:,\s*\"([^\"]*)\")?\s*\)",
    re.IGNORECASE,
)

# Regex for GENERATESERIES(min, max, step) in what-if parameter partitions
_GENERATESERIES_RE = re.compile(
    r"GENERATESERIES\s*\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
    re.IGNORECASE,
)

# Regex for SELECTEDVALUE('Table'[Column], default) in what-if measure expressions
_SELECTEDVALUE_RE = re.compile(
    r"SELECTEDVALUE\s*\(\s*'([^']+)'\s*\[([^\]]+)\]\s*(?:,\s*([^)]+?))?\s*\)",
    re.IGNORECASE,
)


def _is_field_parameter_table(table: TmdlTable) -> bool:
    """Check if a table is a field parameter table (ParameterMetadata kind=2)."""
    return any(
        col.parameter_metadata_kind == 2
        for col in table.columns
    )


def _is_what_if_parameter_table(table: TmdlTable) -> bool:
    """Check if a table is a what-if parameter table (ParameterMetadata kind=0 + GENERATESERIES)."""
    has_param_meta = any(
        col.parameter_metadata_kind is not None and col.parameter_metadata_kind != 2
        for col in table.columns
    )
    if not has_param_meta:
        return False
    # Must have a calculated partition with GENERATESERIES
    for part in table.partitions:
        if part.kind == "calculated" and _GENERATESERIES_RE.search(part.source):
            return True
    return False


def _extract_field_parameter(table: TmdlTable) -> Dict[str, Any]:
    """Extract field parameter items from a calculated partition with NAMEOF() refs.

    Returns a dict in the project YAML format:
        {
            "items": [
                {"name": "...", "ref": {"type": "ColumnRef", "table": "...", "column": "..."}, "sort": 0},
                ...
            ],
            "default_item": "..."
        }
    """
    items: List[Dict[str, Any]] = []

    # Find calculated partition source
    calc_source = ""
    for part in table.partitions:
        if part.kind == "calculated":
            calc_source = part.source
            break

    # Parse NAMEOF() references from the set literal
    for match in _NAMEOF_RE.finditer(calc_source):
        display_name = match.group(1)
        ref_table = match.group(2)
        ref_field = match.group(3)
        sort_order = int(match.group(4))
        hierarchy_group = match.group(5) if match.group(5) else None

        # Determine if reference is a column or measure by checking if the
        # referenced table has this as a measure (heuristic: field parameters
        # referencing measures typically have "Value" as display_name or
        # the display_name matches the measure name)
        # We'll default to ColumnRef and let the caller override if needed
        item: Dict[str, Any] = {
            "name": display_name,
            "ref": {
                "type": "ColumnRef",  # default; will be overridden for measures
                "table": ref_table,
                "column": ref_field,
            },
            "sort": sort_order,
        }
        if hierarchy_group:
            item["locale"] = hierarchy_group

        items.append(item)

    # Disambiguate duplicate display names by appending the hierarchy group
    from collections import Counter
    name_counts = Counter(it["name"] for it in items)
    if any(c > 1 for c in name_counts.values()):
        for it in items:
            if name_counts[it["name"]] > 1 and it.get("locale"):
                it["name"] = f"{it['name']} ({it['locale']})"

    # Default item is the first item (sort=0)
    default_item = items[0]["name"] if items else None

    result: Dict[str, Any] = {"items": items}
    if default_item:
        result["default_item"] = default_item

    return result


def _extract_what_if_parameter(table: TmdlTable) -> Optional[Dict[str, Any]]:
    """Extract what-if parameter config from a GENERATESERIES partition.

    Returns a dict in the project YAML format:
        {"min": 0.0, "max": 100.0, "step": 1.0, "default": 50.0, "format": "0%"}
    """
    # Find the GENERATESERIES partition
    for part in table.partitions:
        if part.kind != "calculated":
            continue
        gen_match = _GENERATESERIES_RE.search(part.source)
        if not gen_match:
            continue

        try:
            min_val = float(gen_match.group(1).strip())
            max_val = float(gen_match.group(2).strip())
            step_val = float(gen_match.group(3).strip())
        except (ValueError, TypeError):
            continue

        # Try to find the default value from the SELECTEDVALUE measure
        default_val = min_val  # fallback
        fmt = None
        for meas in table.measures:
            sv_match = _SELECTEDVALUE_RE.search(meas.expression)
            if sv_match:
                # Extract default from SELECTEDVALUE(..., default)
                if sv_match.group(3):
                    try:
                        default_val = float(sv_match.group(3).strip())
                    except (ValueError, TypeError):
                        pass
                # Use the measure's format string
                if meas.format_string:
                    fmt = meas.format_string
                break

        result: Dict[str, Any] = {
            "min": min_val,
            "max": max_val,
            "step": step_val,
            "default": default_val,
        }
        if fmt:
            result["format"] = fmt

        return result

    return None


def _is_measure_table(table: TmdlTable) -> bool:
    """Detect if a table is a 'measure table' — exists only to host measures.

    Heuristic: table has measures, no real data columns (only auto-generated
    RowNumber-* columns), and a trivial M partition (Table.FromRows / #table()).
    """
    if not table.measures:
        return False

    # Check columns: only auto-generated RowNumber columns count as "no real columns"
    real_columns = [
        col for col in table.columns
        if not col.name.startswith("RowNumber-")
        and not col.name.startswith("RowNumber ")
    ]
    if real_columns:
        return False

    # Check partitions: M partition with trivial expression (Table.FromRows or #table)
    for part in table.partitions:
        if part.kind == "m":
            src_lower = part.source.lower()
            if "table.fromrows" in src_lower or "#table" in src_lower:
                return True

    # Also match tables with no partitions at all (rare but possible)
    if not table.partitions:
        return True

    return False


def parse_tmdl_folder(definition_dir: str | Path) -> TmdlModel:
    """Parse an entire TMDL ``definition/`` folder into a :class:`TmdlModel`."""
    root = Path(definition_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"TMDL definition directory not found: {root}")

    model = TmdlModel()

    # Tables
    tables_dir = root / "tables"
    if tables_dir.is_dir():
        for tf in sorted(tables_dir.glob("*.tmdl")):
            try:
                tbl = _parse_table_tmdl(tf)
                model.tables.append(tbl)
            except Exception as exc:
                # Skip unparsable tables but warn
                print(f"[tmdl_converter] WARNING: skipped {tf.name}: {exc}")

    # Relationships
    rel_path = root / "relationships.tmdl"
    model.relationships = _parse_relationships_tmdl(rel_path)

    # Roles
    roles_dir = root / "roles"
    if roles_dir.is_dir():
        for rf in sorted(roles_dir.glob("*.tmdl")):
            try:
                model.roles.append(_parse_role_tmdl(rf))
            except Exception:
                pass

    return model


# ══════════════════════════════════════════════════════════════════════
#  DATA SOURCE EXTRACTION (generalized)
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ExtractedSource:
    """Result of parsing an M partition expression for data source info."""
    type: str          # "csv" | "parquet" | "json" | "excel" | "sql" | "odata" | "web" | "unknown"
    path: Optional[str] = None          # file path (for file-based sources)
    delimiter: str = ","                # CSV delimiter
    connection_string: Optional[str] = None  # for SQL/database sources
    url: Optional[str] = None           # for web/OData sources
    schema: Optional[str] = None        # for SQL sources
    table_name: Optional[str] = None    # for SQL/database table name
    raw_m_expression: Optional[str] = None  # the raw M expression for reference


# File.Contents("path/to/file.ext") — the universal file access pattern in M
_FILE_CONTENTS_RE = re.compile(
    r'File\.Contents\(\s*"([^"]+)"\s*\)',
    re.IGNORECASE,
)

# M document functions that indicate the file format:
#   Csv.Document(...)   → CSV
#   Excel.Workbook(...) → Excel
#   Json.Document(...)  → JSON
# If none of these appear, infer from file extension.
_M_FORMAT_PATTERNS: List[tuple[re.Pattern, str]] = [
    (re.compile(r'\bCsv\.Document\b', re.IGNORECASE), "csv"),
    (re.compile(r'\bExcel\.Workbook\b', re.IGNORECASE), "excel"),
    (re.compile(r'\bJson\.Document\b', re.IGNORECASE), "json"),
]

# Extension → source type mapping (fallback when no M function detected)
_EXT_TO_SOURCE: Dict[str, str] = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".json": "json",
    ".jsonl": "json",
    ".xlsx": "excel",
    ".xls": "excel",
    ".xlsm": "excel",
}

# Non-file M source patterns
_SQL_DATABASE_RE = re.compile(
    r'Sql\.Database\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
    re.IGNORECASE,
)
_SQL_TABLE_RE = re.compile(
    r'\[Schema\s*=\s*"([^"]+)"\s*,\s*Item\s*=\s*"([^"]+)"\s*\]',
    re.IGNORECASE,
)
_ODATA_RE = re.compile(
    r'OData\.Feed\(\s*"([^"]+)"\s*\)',
    re.IGNORECASE,
)
_WEB_CONTENTS_RE = re.compile(
    r'Web\.Contents\(\s*"([^"]+)"\s*\)',
    re.IGNORECASE,
)
_SHAREPOINT_RE = re.compile(
    r'SharePoint\.(?:Files|Tables)\(\s*"([^"]+)"\s*\)',
    re.IGNORECASE,
)

_TSV_DELIMITER_RE = re.compile(
    r'Delimiter\s*=\s*"[\t\\t]"',
    re.IGNORECASE,
)


def _extract_data_source(partition: TmdlPartition) -> Optional[ExtractedSource]:
    """Extract data source information from an M partition expression.

    Handles file-based sources (CSV, Parquet, JSON, Excel) via
    ``File.Contents(...)`` patterns, SQL database sources via
    ``Sql.Database(...)`` patterns, and web/OData sources.

    Returns ``None`` only if the partition has no recognizable source
    expression at all.
    """
    source_text = partition.source
    if not source_text.strip():
        return None

    # ── 1. File-based sources: File.Contents("path") ─────────────────
    file_match = _FILE_CONTENTS_RE.search(source_text)
    if file_match:
        file_path = file_match.group(1)
        ext = os.path.splitext(file_path)[1].lower()

        # Determine file type: prefer M function hints over extension
        source_type = None
        for pattern, stype in _M_FORMAT_PATTERNS:
            if pattern.search(source_text):
                source_type = stype
                break
        if source_type is None:
            source_type = _EXT_TO_SOURCE.get(ext, "unknown")

        result = ExtractedSource(
            type=source_type,
            path=file_path,
            raw_m_expression=source_text,
        )

        # Detect CSV delimiter (tab vs comma)
        if source_type == "csv" and _TSV_DELIMITER_RE.search(source_text):
            result.delimiter = "\t"

        return result

    # ── 2. SQL Database sources ───────────────────────────────────────
    sql_match = _SQL_DATABASE_RE.search(source_text)
    if sql_match:
        result = ExtractedSource(
            type="sql",
            connection_string=sql_match.group(1),
            raw_m_expression=source_text,
        )
        # Try to extract schema + table name
        tbl_match = _SQL_TABLE_RE.search(source_text)
        if tbl_match:
            result.schema = tbl_match.group(1)
            result.table_name = tbl_match.group(2)
        return result

    # ── 3. OData sources ─────────────────────────────────────────────
    odata_match = _ODATA_RE.search(source_text)
    if odata_match:
        return ExtractedSource(
            type="odata",
            url=odata_match.group(1),
            raw_m_expression=source_text,
        )

    # ── 4. Web.Contents sources ──────────────────────────────────────
    web_match = _WEB_CONTENTS_RE.search(source_text)
    if web_match:
        return ExtractedSource(
            type="web",
            url=web_match.group(1),
            raw_m_expression=source_text,
        )

    # ── 5. SharePoint sources ────────────────────────────────────────
    sp_match = _SHAREPOINT_RE.search(source_text)
    if sp_match:
        return ExtractedSource(
            type="sharepoint",
            url=sp_match.group(1),
            raw_m_expression=source_text,
        )

    # ── 6. Unknown but non-empty source ──────────────────────────────
    return ExtractedSource(
        type="unknown",
        raw_m_expression=source_text,
    )



# ══════════════════════════════════════════════════════════════════════
#  YAML GENERATION
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ConversionResult:
    """Result of a TMDL → project conversion."""
    project_path: str
    tables_created: List[str] = field(default_factory=list)
    measures_created: int = 0
    relationships_created: int = 0
    hierarchies_created: int = 0
    roles_created: int = 0
    calc_groups_created: int = 0
    data_files_copied: List[str] = field(default_factory=list)
    data_files_missing: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    skipped_tables: List[str] = field(default_factory=list)


# Tables we should skip (auto-generated date tables, translation tables, etc.)
_SKIP_TABLE_PATTERNS = [
    r"^DateTableTemplate_",
    r"^LocalDateTable_",
    r"^Translated ",
]


def _should_skip_table(name: str) -> bool:
    for pat in _SKIP_TABLE_PATTERNS:
        if re.match(pat, name, re.IGNORECASE):
            return True
    return False


def convert_tmdl_to_project(
    definition_dir: str | Path,
    output_dir: str | Path,
    *,
    copy_data: bool = True,
    project_name: Optional[str] = None,
    skip_hidden_tables: bool = False,
) -> ConversionResult:
    """
    Convert a TMDL definition folder to a project directory.

    Parameters
    ----------
    definition_dir : path
        Path to the TMDL ``definition/`` folder.
    output_dir : path
        Path where the project directory will be created.
    copy_data : bool
        If True, attempt to copy CSV data files referenced in M expressions.
    project_name : str | None
        Display name for the project (defaults to folder name).
    skip_hidden_tables : bool
        If True, skip tables marked as ``isHidden``.
    """
    definition_dir = Path(definition_dir)
    output_dir = Path(output_dir)
    result = ConversionResult(project_path=str(output_dir))

    # Parse the TMDL model
    model = parse_tmdl_folder(definition_dir)

    # Create output directory structure
    model_dir = output_dir / "model"
    tables_dir = model_dir / "tables"
    data_dir = output_dir / "data"
    reports_dir = output_dir / "reports"
    tables_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # ── Collect all measures, hierarchies, calc groups across tables ──
    all_measures: List[Dict[str, Any]] = []
    all_hierarchies: Dict[str, Any] = {}
    all_calc_groups: Dict[str, Any] = {}
    all_field_params: Dict[str, Any] = {}
    all_what_if_params: Dict[str, Any] = {}

    # Pre-scan: identify measure tables and collect measure names per table
    # so we can resolve ColumnRef vs MeasureRef in field parameter items
    measure_table_names: set[str] = set()
    all_measure_names: Dict[str, str] = {}  # measure_name -> table_name
    for tbl in model.tables:
        if _should_skip_table(tbl.name):
            continue
        if _is_measure_table(tbl):
            measure_table_names.add(tbl.name)
        for meas in tbl.measures:
            all_measure_names[meas.name] = tbl.name

    for tbl in model.tables:
        # Skip auto-generated tables
        if _should_skip_table(tbl.name):
            result.skipped_tables.append(tbl.name)
            continue

        # Skip hidden tables if requested
        if skip_hidden_tables and tbl.is_hidden:
            result.skipped_tables.append(tbl.name)
            continue

        # ── Field parameter tables → extract to field_parameters.yaml ─
        if _is_field_parameter_table(tbl):
            fp_data = _extract_field_parameter(tbl)
            # Resolve ColumnRef vs MeasureRef using collected measure names
            for item in fp_data.get("items", []):
                ref = item.get("ref", {})
                ref_field = ref.get("column", "")
                if ref_field in all_measure_names:
                    # MeasureRef uses {"type": "MeasureRef", "name": "..."}
                    item["ref"] = {"type": "MeasureRef", "name": ref_field}
            all_field_params[tbl.name] = fp_data
            result.skipped_tables.append(tbl.name)
            continue

        # ── What-if parameter tables → extract to what_if_parameters.yaml
        if _is_what_if_parameter_table(tbl):
            wi_data = _extract_what_if_parameter(tbl)
            if wi_data is not None:
                all_what_if_params[tbl.name] = wi_data
            result.skipped_tables.append(tbl.name)
            continue

        # Determine if this is a calculated table
        is_calc_table = False
        calc_expr = None
        extracted_source: Optional[ExtractedSource] = None
        power_query_partitions: List[Dict[str, Any]] = []

        for part in tbl.partitions:
            if part.kind == "calculated":
                is_calc_table = True
                calc_expr = part.source
                break
            elif part.kind == "m":
                if part.source.strip():
                    power_query_partitions.append(
                        build_power_query_metadata(
                            query_id=tbl.name,
                            raw_m=part.source,
                            table_name=tbl.name,
                            partition_name=part.name,
                            mode=part.mode,
                        )
                    )
                extracted_source = _extract_data_source(part)

        # ── Build table YAML ──────────────────────────────────────────
        table_yaml: Dict[str, Any] = {"name": tbl.name}

        # Columns
        cols_yaml: List[Dict[str, Any]] = []
        for col in tbl.columns:
            cy: Dict[str, Any] = {
                "name": col.name,
                "type": _map_type(col.data_type),
            }
            if col.expression:
                cy["expression"] = col.expression
                cy["is_calculated"] = True
            elif col.is_calculated:
                cy["is_calculated"] = True
            if col.is_hidden:
                cy["is_hidden"] = True
            if col.description:
                cy["description"] = col.description
            if col.display_folder:
                cy["folder"] = col.display_folder
            if col.format_string:
                cy["format"] = col.format_string
            if col.sort_by_column:
                cy["sort_by_column"] = col.sort_by_column
            cols_yaml.append(cy)

        table_yaml["columns"] = cols_yaml

        if power_query_partitions:
            table_yaml["power_query"] = power_query_partitions[0]
            if len(power_query_partitions) > 1:
                table_yaml["power_query"]["additional_queries"] = power_query_partitions[1:]

        # Calculated table expression
        if is_calc_table and calc_expr:
            table_yaml["expression"] = calc_expr
            table_yaml["is_calculated"] = True

        # Storage mode (import / directQuery) — skip for calculated tables
        if not is_calc_table:
            storage_mode = None
            for part in tbl.partitions:
                if part.mode:
                    storage_mode = part.mode.lower()
                    break
            if storage_mode:
                table_yaml["storage_mode"] = storage_mode

        # Data source — generalized (CSV, Parquet, JSON, Excel, SQL, etc.)
        if not is_calc_table and extracted_source and extracted_source.path:
            # File-based sources: copy the data file and write source block
            src_filename = os.path.basename(extracted_source.path)
            source_yaml: Dict[str, Any] = {
                "type": extracted_source.type,
                "path": f"data/{src_filename}",
            }
            if extracted_source.type == "csv" and extracted_source.delimiter == "\t":
                source_yaml["delimiter"] = "\t"
            table_yaml["source"] = source_yaml

            # Copy the raw data file as-is.  Numeric formatting (currency
            # symbols, thousands separators) is handled at load time by the
            # DuckDB loader using column type metadata from the YAML schema.
            if copy_data:
                src = Path(extracted_source.path)
                dst = data_dir / src_filename
                if src.exists() and not dst.exists():
                    try:
                        shutil.copy2(str(src), str(dst))
                        result.data_files_copied.append(src_filename)
                    except Exception as exc:
                        result.warnings.append(f"Failed to copy {src_filename}: {exc}")
                        result.data_files_missing.append(src_filename)
                elif not src.exists():
                    result.data_files_missing.append(src_filename)

        elif not is_calc_table and extracted_source and not extracted_source.path:
            # Non-file sources (SQL, OData, Web, SharePoint) — record metadata
            # but no data file to copy. User must provide data separately.
            # "unknown" sources get no source block (measure-only tables, etc.)
            if extracted_source.type != "unknown":
                source_yaml = {"type": extracted_source.type}
                if extracted_source.connection_string:
                    source_yaml["connection_string"] = extracted_source.connection_string
                if extracted_source.url:
                    source_yaml["url"] = extracted_source.url
                if extracted_source.schema:
                    source_yaml["schema"] = extracted_source.schema
                if extracted_source.table_name:
                    source_yaml["table_name"] = extracted_source.table_name
                table_yaml["source"] = source_yaml
                result.warnings.append(
                    f"Table '{tbl.name}': non-file source ({extracted_source.type}) — "
                    f"data must be exported and placed in data/ manually"
                )
            else:
                result.warnings.append(f"Table '{tbl.name}': unrecognized data source in M expression")

        elif not is_calc_table and not extracted_source:
            # No source detected — leave without source, user must configure
            result.warnings.append(f"Table '{tbl.name}': no data source detected")

        # Write table YAML
        table_path = tables_dir / f"{tbl.name}.yaml"
        table_path.write_text(
            yaml.dump(table_yaml, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        result.tables_created.append(tbl.name)

        # ── Collect measures ──────────────────────────────────────────
        is_measure_tbl = tbl.name in measure_table_names
        for meas in tbl.measures:
            md: Dict[str, Any] = {
                "name": meas.name,
                "dax": meas.expression,
            }
            if meas.format_string:
                md["format"] = meas.format_string
            if meas.description:
                md["description"] = meas.description

            # Folder logic:
            # - Measures from "measure tables" keep their original display_folder
            # - Measures from normal data tables get table name as folder prefix
            if is_measure_tbl:
                # Measure table: keep folder as-is
                if meas.display_folder:
                    md["folder"] = meas.display_folder
            else:
                # Normal table: prefix with table name
                if meas.display_folder:
                    md["folder"] = f"{tbl.name}/{meas.display_folder}"
                else:
                    md["folder"] = tbl.name

            if meas.is_hidden:
                md["is_hidden"] = True
            all_measures.append(md)

        # ── Collect hierarchies ───────────────────────────────────────
        for hier in tbl.hierarchies:
            levels = []
            for col_name in hier.levels:
                levels.append({"column": col_name, "name": col_name})
            all_hierarchies[hier.name] = {
                "table": tbl.name,
                "levels": levels,
            }

        # ── Collect calculation groups ────────────────────────────────
        if tbl.calc_group and tbl.calc_group.items:
            items = []
            for ci in tbl.calc_group.items:
                items.append({"name": ci.name, "expression": ci.expression})
            all_calc_groups[tbl.name] = {
                "precedence": 0,
                "items": items,
            }

    # ── Write measures.yaml ───────────────────────────────────────────
    if all_measures:
        measures_path = model_dir / "measures.yaml"
        measures_path.write_text(
            yaml.dump({"measures": all_measures}, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        result.measures_created = len(all_measures)

    # ── Write relationships.yaml ──────────────────────────────────────
    if model.relationships:
        rels_yaml = []
        for rel in model.relationships:
            ry: Dict[str, Any] = {
                "from": {"table": rel.from_table, "column": rel.from_column},
                "to": {"table": rel.to_table, "column": rel.to_column},
                "active": rel.is_active,
                "cross_filter_direction": rel.cross_filter,
                "cardinality": rel.cardinality,
                "rel_id": f"{rel.from_table}.{rel.from_column}->{rel.to_table}.{rel.to_column}",
            }
            rels_yaml.append(ry)
        rels_path = model_dir / "relationships.yaml"
        rels_path.write_text(
            yaml.dump({"relationships": rels_yaml}, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        result.relationships_created = len(rels_yaml)

    # ── Write hierarchies.yaml ────────────────────────────────────────
    if all_hierarchies:
        hier_path = model_dir / "hierarchies.yaml"
        hier_path.write_text(
            yaml.dump({"hierarchies": all_hierarchies}, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        result.hierarchies_created = len(all_hierarchies)

    # ── Write security.yaml ───────────────────────────────────────────
    if model.roles:
        roles_yaml = []
        for role in model.roles:
            ry: Dict[str, Any] = {"name": role.name}
            if role.rules:
                rls_rules = []
                for rule in role.rules:
                    rls_rules.append({
                        "table": rule.table,
                        "filter": rule.filter_expression,
                    })
                ry["rls"] = rls_rules
            roles_yaml.append(ry)
        sec_path = model_dir / "security.yaml"
        sec_path.write_text(
            yaml.dump({"roles": roles_yaml}, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        result.roles_created = len(roles_yaml)

    # ── Write calculation_groups.yaml ─────────────────────────────────
    if all_calc_groups:
        cg_path = model_dir / "calculation_groups.yaml"
        cg_path.write_text(
            yaml.dump({"calculation_groups": all_calc_groups}, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        result.calc_groups_created = len(all_calc_groups)

    # ── Write field_parameters.yaml ──────────────────────────────────
    (model_dir / "field_parameters.yaml").write_text(
        yaml.dump({"field_parameters": all_field_params}, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # ── Write what_if_parameters.yaml ─────────────────────────────────
    (model_dir / "what_if_parameters.yaml").write_text(
        yaml.dump({"what_if_parameters": all_what_if_params}, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # ── Write _folder.yaml ────────────────────────────────────────────
    folder_name = project_name or output_dir.name
    folder_yaml = {
        "display_name": folder_name,
        "description": f"Imported from TMDL: {definition_dir.parent.name}",
        "icon": "folder",
        "sort_order": 0,
    }
    (output_dir / "_folder.yaml").write_text(
        yaml.dump(folder_yaml, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    return result
