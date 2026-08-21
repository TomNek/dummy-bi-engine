from __future__ import annotations

import re
from typing import Any, Mapping

from .source_map import map_source_bindings_from_m


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _query_id(query: Mapping[str, Any]) -> str:
    return str(query.get("query_id") or query.get("table_name") or query.get("partition_name") or "").strip()


def _quoted_identifier(name: str) -> str:
    return '#"' + name.replace('"', '""') + '"'


def _references(raw_m: str, candidates: list[str], own_id: str) -> list[str]:
    text = raw_m or ""
    refs: list[str] = []
    own = own_id.strip().upper()
    for candidate in candidates:
        name = candidate.strip()
        if not name or name.upper() == own:
            continue
        quoted = _quoted_identifier(name)
        found = quoted in text
        if not found and _IDENT_RE.match(name):
            found = re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None
        if found:
            refs.append(name)
    return sorted(set(refs), key=str.upper)


def _function_parameters(raw_m: str) -> list[str]:
    text = (raw_m or "").strip()
    match = re.search(r"\((?P<params>[^()]*)\)\s*(?:as\s+[A-Za-z0-9_.]+)?\s*=>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    params: list[str] = []
    for part in match.group("params").split(","):
        item = part.strip()
        if not item:
            continue
        item = re.sub(r"^optional\s+", "", item, flags=re.IGNORECASE)
        name = item.split()[0].strip()
        if name.startswith('#"') and name.endswith('"'):
            name = name[2:-1].replace('""', '"')
        if name:
            params.append(name)
    return params


def _parameter_metadata(raw_m: str) -> dict[str, Any]:
    text = raw_m or ""
    if "IsParameterQuery" not in text:
        return {}
    meta: dict[str, Any] = {"is_parameter": True}
    required_match = re.search(r"IsParameterQueryRequired\s*=\s*(true|false)", text, re.IGNORECASE)
    type_match = re.search(r'Type\s*=\s*"([^"]+)"', text, re.IGNORECASE)
    list_match = re.search(r"List\s*=\s*\{([^}]*)\}", text, re.IGNORECASE | re.DOTALL)
    if required_match:
        meta["required"] = required_match.group(1).lower() == "true"
    if type_match:
        meta["type"] = type_match.group(1)
    if list_match:
        values = []
        for value in list_match.group(1).split(","):
            cleaned = value.strip().strip('"')
            if cleaned:
                values.append(cleaned)
        if values:
            meta["suggested_values"] = values
    return meta


def _query_kind(query: Mapping[str, Any], parameter_meta: Mapping[str, Any], function_params: list[str]) -> str:
    if parameter_meta.get("is_parameter"):
        return "parameter"
    if function_params or "=>" in str(query.get("raw_m") or ""):
        return "function"
    qid = _query_id(query).strip().upper()
    table_name = str(query.get("table_name") or "").strip().upper()
    partition_name = str(query.get("partition_name") or "").strip().upper()
    if query.get("source_mapping") or query.get("source_mappings") or (qid and qid in {table_name, partition_name}):
        return "table"
    return "query"


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _unique_text(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _source_mappings(query: Mapping[str, Any], source_policy: Mapping[str, Any]) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    scalar = query.get("source_mapping") if isinstance(query.get("source_mapping"), Mapping) else {}
    mappings = _mapping_list(query.get("source_mappings"))
    if not mappings:
        mappings = _mapping_list(source_policy.get("sources"))
    if not mappings and scalar:
        mappings = [scalar]
    primary = scalar or (mappings[0] if mappings else {})
    return primary, mappings


def _source_bindings(query: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bindings = _mapping_list(query.get("source_bindings"))
    if bindings:
        return bindings
    raw_m = query.get("raw_m")
    if isinstance(raw_m, str) and raw_m.strip():
        return [binding.to_dict() for binding in map_source_bindings_from_m(raw_m)]
    return []


def _query_reference_targets(binding: Mapping[str, Any]) -> list[dict[str, str]]:
    refs = [
        {
            "step_id": str(ref.get("step_id") or ""),
            "query_id": str(ref.get("query_id") or ""),
            "kind": str(ref.get("kind") or "query_reference"),
        }
        for ref in binding.get("query_references") or []
        if isinstance(ref, Mapping) and ref.get("query_id")
    ]
    if refs:
        return refs
    block = binding.get("source_block") if isinstance(binding.get("source_block"), Mapping) else {}
    query_id = str(block.get("query_id") or "")
    if query_id:
        return [{"step_id": str(binding.get("source_step_id") or ""), "query_id": query_id, "kind": "query_reference"}]
    return []


def _resolved_source_bindings(
    query_id: str,
    query_by_id: Mapping[str, Mapping[str, Any]],
    *,
    seen: set[str] | None = None,
    via: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    seen = set(seen or set())
    if query_id in seen:
        return []
    seen.add(query_id)
    query = query_by_id.get(query_id)
    if query is None:
        return []
    out: list[dict[str, Any]] = []
    for binding in _source_bindings(query):
        source_type = str(binding.get("source_type") or "")
        if source_type == "query_reference":
            for ref in _query_reference_targets(binding):
                target_id = ref.get("query_id") or ""
                next_via = [*(via or []), {"from_query_id": query_id, **ref}]
                resolved = _resolved_source_bindings(target_id, query_by_id, seen=seen, via=next_via)
                if resolved:
                    out.extend(resolved)
                else:
                    out.append({
                        "origin_query_id": query_id,
                        "source_type": "query_reference",
                        "connector_id": "query_reference",
                        "source_step_id": ref.get("step_id"),
                        "target_query_id": target_id,
                        "resolved": False,
                        "via_query_references": next_via,
                    })
            continue
        out.append({
            "origin_query_id": query_id,
            "source_type": source_type,
            "connector_id": binding.get("connector_id"),
            "source_step_id": binding.get("source_step_id"),
            "privacy_partition": binding.get("privacy_partition") or binding.get("firewall_partition"),
            "schema_probe_candidate": binding.get("schema_probe_candidate"),
            "resolved": True,
            "via_query_references": list(via or []),
        })
    return out


def _bool_meta(query: Mapping[str, Any], *keys: str, default: bool | None = None) -> bool | None:
    for key in keys:
        if key in query:
            value = query.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
                return value.strip().lower() == "true"
    return default


def _load_state(kind: str, load_enabled: bool, referenced_by: list[str]) -> str:
    if kind in {"parameter", "function"}:
        return kind
    if load_enabled:
        return "loaded"
    if referenced_by:
        return "referenced_only"
    return "staging_only"


def build_power_query_graph(queries: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a conservative query dependency graph for Transform Studio.

    This is intentionally metadata-only. It preserves and classifies imported M
    assets without requiring executable support for parameters, custom
    functions, or helper queries.
    """

    ids = [_query_id(query) for query in queries if _query_id(query)]
    query_by_id = {_query_id(query): query for query in queries if _query_id(query)}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    referenced_by_map: dict[str, list[str]] = {qid: [] for qid in ids}

    for query in queries:
        qid = _query_id(query)
        if not qid:
            continue
        raw_m = str(query.get("raw_m") or "")
        source_policy = query.get("source_policy") if isinstance(query.get("source_policy"), Mapping) else {}
        source_mapping, source_mappings = _source_mappings(query, source_policy)
        source_bindings = _source_bindings(query)
        resolved_bindings = _resolved_source_bindings(qid, query_by_id)
        compat = query.get("compatibility_report") if isinstance(query.get("compatibility_report"), Mapping) else {}
        parameter_meta = _parameter_metadata(raw_m)
        function_params = _function_parameters(raw_m)
        refs = _references(raw_m, ids, qid)
        kind = _query_kind(query, parameter_meta, function_params)
        source_rollup = {}
        if len(source_mappings) > 1:
            source_rollup = {
                "source_count": len(source_mappings),
                "source_types": _unique_text([mapping.get("source_type") for mapping in source_mappings]),
                "connector_ids": _unique_text([mapping.get("connector_id") for mapping in source_mappings]),
            }

        nodes.append(
            {
                "id": qid,
                "label": qid,
                "kind": kind,
                "table_name": query.get("table_name"),
                "partition_name": query.get("partition_name"),
                "mode": query.get("mode"),
                "load_enabled": _bool_meta(query, "load_enabled", "is_load_enabled", default=bool(query.get("table_name")) and kind == "table"),
                "refresh_enabled": _bool_meta(query, "refresh_enabled", "is_refresh_enabled", default=True),
                "group": query.get("group") or query.get("query_group"),
                "description": query.get("description"),
                "compatibility_level": query.get("compatibility_level") or compat.get("compatibility_level"),
                "execution_status": query.get("execution_status") or compat.get("execution_status"),
                "source_type": source_mapping.get("source_type"),
                "connector_id": source_mapping.get("connector_id"),
                "privacy_level": source_mapping.get("privacy_level"),
                "folding_status": source_mapping.get("folding_status"),
                "source_binding_count": len(source_bindings),
                "source_binding_types": _unique_text([binding.get("source_type") for binding in source_bindings]),
                "resolved_source_binding_count": len(resolved_bindings),
                "resolved_source_types": _unique_text([binding.get("source_type") for binding in resolved_bindings if binding.get("resolved")]),
                "resolved_connector_ids": _unique_text([binding.get("connector_id") for binding in resolved_bindings if binding.get("resolved")]),
                "resolved_privacy_partitions": _unique_text([binding.get("privacy_partition") for binding in resolved_bindings if binding.get("privacy_partition")]),
                "resolved_source_bindings": resolved_bindings,
                "query_reference_bindings": [
                    ref
                    for binding in source_bindings
                    for ref in (binding.get("query_references") or [])
                    if isinstance(ref, Mapping)
                ],
                **source_rollup,
                "firewall_status": source_policy.get("firewall_status"),
                "references": refs,
                "referenced_by": [],
                "load_state": "unknown",
                "function_parameters": function_params,
                "parameter": parameter_meta,
            }
        )
        for ref in refs:
            edges.append({"from": qid, "to": ref, "kind": "query_reference"})
            referenced_by_map.setdefault(ref, []).append(qid)

    for node in nodes:
        referenced_by = sorted(set(referenced_by_map.get(str(node.get("id") or ""), [])), key=str.upper)
        node["referenced_by"] = referenced_by
        node["load_state"] = _load_state(str(node.get("kind") or "query"), bool(node.get("load_enabled")), referenced_by)

    kind_counts: dict[str, int] = {}
    load_state_counts: dict[str, int] = {}
    for node in nodes:
        kind = str(node.get("kind") or "query")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        load_state = str(node.get("load_state") or "unknown")
        load_state_counts[load_state] = load_state_counts.get(load_state, 0) + 1

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "query_count": len(nodes),
            "edge_count": len(edges),
            "kind_counts": kind_counts,
            "load_state_counts": load_state_counts,
        },
    }
