from __future__ import annotations

import re
from typing import Any, Mapping

from .credentials import redact_secret_value
from .function_catalog import function_catalog_rows
from .parser import parse_m_query
from .source_map import map_sources_from_m


_PREFIX_RE = re.compile(r"[#\"A-Za-z0-9_\.]+$")


def _m_identifier(value: str) -> str:
    text = str(value or "")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return text
    return '#"' + text.replace('"', '""') + '"'


def _cursor_prefix(raw_m: str, cursor_offset: int) -> tuple[str, int, int]:
    offset = max(0, min(int(cursor_offset), len(raw_m)))
    before = raw_m[:offset]
    match = _PREFIX_RE.search(before)
    if not match:
        return "", offset, offset
    return match.group(0), match.start(), offset


def _matches_prefix(value: str, prefix: str) -> bool:
    if not prefix:
        return True
    return value.upper().startswith(prefix.upper())


def _completion(
    *,
    label: str,
    kind: str,
    insert_text: str,
    detail: str = "",
    documentation: str = "",
    score: int = 0,
) -> dict[str, Any]:
    return {
        "label": label,
        "kind": kind,
        "insert_text": insert_text,
        "detail": detail,
        "documentation": documentation,
        "score": score,
    }


def _query_entries(entries: list[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in entries or []:
        if not isinstance(item, Mapping):
            continue
        qid = str(item.get("query_id") or item.get("table_name") or item.get("partition_name") or "").strip()
        if not qid or qid.upper() in seen:
            continue
        seen.add(qid.upper())
        graph_kind = "parameter" if item.get("is_parameter") else "function" if item.get("is_function") else "query"
        out.append({"id": qid, "kind": graph_kind})
    return out


def build_power_query_intellisense(
    raw_m: str,
    *,
    cursor_offset: int | None = None,
    step_id: str | None = None,
    query_entries: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return lightweight Transform Studio authoring assists for a draft M text."""

    text = raw_m or ""
    prefix, replace_start, replace_end = _cursor_prefix(text, len(text) if cursor_offset is None else cursor_offset)
    steps, result_expression, _functions, diagnostics = parse_m_query(text)
    selected_step = next((step for step in steps if step.id.upper() == str(step_id or "").upper()), None)
    source_hints = [redact_secret_value(mapping.to_dict()) for mapping in map_sources_from_m(text)]

    completions: list[dict[str, Any]] = []
    for row in function_catalog_rows():
        name = str(row.get("function") or "")
        if not name or not _matches_prefix(name, prefix):
            continue
        detail_bits = [
            str(row.get("compatibility_level") or ""),
            str(row.get("execution_lane") or ""),
            str(row.get("support_track") or ""),
        ]
        detail = " | ".join(bit for bit in detail_bits if bit)
        completions.append(
            _completion(
                label=name,
                kind="function",
                insert_text=f"{name}(",
                detail=detail,
                documentation=str(row.get("duckdb_sql_equivalent") or row.get("risk") or ""),
                score=300 if name.upper().startswith(prefix.upper()) else 100,
            )
        )

    for step in steps:
        if not _matches_prefix(step.id, prefix):
            continue
        completions.append(
            _completion(
                label=step.id,
                kind="step",
                insert_text=_m_identifier(step.id),
                detail=str(step.operation or "applied step"),
                documentation=str(redact_secret_value(str(step.expression or ""))),
                score=240,
            )
        )

    for entry in _query_entries(query_entries):
        label = entry["id"]
        if not _matches_prefix(label, prefix):
            continue
        completions.append(
            _completion(
                label=label,
                kind=entry["kind"],
                insert_text=_m_identifier(label),
                detail=f"{entry['kind']} reference",
                documentation="Reference another Power Query asset in this project.",
                score=220,
            )
        )

    completions.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("label") or "").upper()))
    help_item = completions[0] if completions else None
    return {
        "prefix": prefix,
        "replace_start": replace_start,
        "replace_end": replace_end,
        "step_context": redact_secret_value(selected_step.to_dict()) if selected_step is not None else None,
        "result_expression": result_expression,
        "completions": completions[:40],
        "help": help_item,
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "source_hints": source_hints,
    }
