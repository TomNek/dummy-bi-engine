"""
Report Crawlers — comprehensive PBIR visual configuration extraction.

Ported from the Power BI Documentation notebook crawl_* functions.
All crawlers work on PBIR visual.json structures (after adapt_pbir_to_legacy).

Used by:
- report_transfer.py for comprehensive report transfer
- Row-count verification after transfer

NOTE: The crawlers produce sets/lists of tuples describing field references found
in the PBI configuration. Each tuple contains (Table, Field, UsedIn, ...) with
varying arity depending on the crawler.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constants & regex patterns
# ---------------------------------------------------------------------------

AGG_FUNCS = {
    "Sum", "Avg", "Min", "Max", "Count", "DistinctCount",
    "CountNonNull", "CountRows", "StdDev", "StdDevP", "Var", "VarP",
}

AGG_PAT = re.compile(
    rf"^(?P<agg>{'|'.join(AGG_FUNCS)})\(\s*(?P<src>[^.]+)\.(?P<prop>[^)]+?)\s*\)+$"
)

_AGG_REF_RE = re.compile(
    r"""^\s*
        (?P<agg>[A-Za-z]+)
        \(\s*
        (?P<src>[A-Za-z_][A-Za-z0-9_]*)\.
        (?P<prop>[^)]+?)
        \s*\)\s*$
    """, re.VERBOSE
)

_DOTTED_LABEL_RE = re.compile(r"^\s*(?P<left>[^.]+?)\.(?P<right>.+?)\s*$")

_HANDLE_RE = re.compile(
    r"""^\s*'+'                       # opening quotes
        (?P<table>[^']+?)             # table name until a quote
        '+'\s*                        # closing quotes
        \[\s*(?P<field>[^\]]+?)\s*\]  # [Field] (first closing ])
        .*?$                          # allow any trailing junk
    """,
    re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _decode_json_string(s: str) -> str:
    if isinstance(s, str) and len(s) >= 2 and s[0] == s[-1] == '"':
        try:
            return json.loads(s)
        except Exception:
            return s.strip('"')
    return s


def _parse_agg(alias: str):
    """
    Accepts 'd.Table.Field' or 'Sum(d.Table.Field)' (with extra ')' tolerated).
    Returns (agg|None, src, prop) or None on failure.
    """
    if not isinstance(alias, str):
        return None
    s = alias.strip()
    if s.endswith(")"):
        while s.endswith(")"):
            s = s[:-1].rstrip()
        i = s.find("(")
        if i > 0:
            agg = s[:i].strip()
            if agg in AGG_FUNCS:
                inside = s[i + 1:].strip()
                dot = inside.find(".")
                if dot >= 0:
                    return (agg, inside[:dot].strip(), inside[dot + 1:].strip())
    dot = s.find(".")
    if dot >= 0:
        return (None, s[:dot].strip(), s[dot + 1:].strip())
    return None


def _alias_label(alias: str) -> str:
    p = _parse_agg(alias)
    if p:
        return p[2]
    if isinstance(alias, str) and "." in alias:
        return alias.split(".", 1)[1]
    return alias


def _src_prop(obj, aliases):
    """Return (resolved_table, property) or (None, None)."""
    src = (obj.get("Expression", {}).get("SourceRef", {}).get("Source")
           or obj.get("Expression", {}).get("SourceRef", {}).get("Entity"))
    prop = obj.get("Property")
    if src and prop:
        return aliases.get(src, src), prop
    return None, None


def _extract_literal_value(props):
    """Recursively find the first expr.Literal.Value in a properties dict."""
    if not isinstance(props, dict):
        return None
    lit = props.get("expr", {}).get("Literal", {}).get("Value")
    if lit is not None:
        return lit
    for v in props.values():
        val = _extract_literal_value(v)
        if val is not None:
            return val
    return None


def _iter_field_refs(obj, path_prefix=None):
    """Yield (src, prop, path_list, node) for any nested Measure/Column refs."""
    if path_prefix is None:
        path_prefix = []
    if isinstance(obj, dict):
        if "Measure" in obj:
            ms = obj["Measure"]
            sref = (ms.get("Expression", {}) or {}).get("SourceRef", {}) or {}
            src = sref.get("Entity") or sref.get("Source")
            prop = ms.get("Property")
            if src and prop:
                yield src, prop, path_prefix + ["Measure"], ms
        if "Column" in obj:
            col = obj["Column"]
            sref = (col.get("Expression", {}) or {}).get("SourceRef", {}) or {}
            src = sref.get("Entity") or sref.get("Source")
            prop = col.get("Property")
            if src and prop:
                yield src, prop, path_prefix + ["Column"], col
        for k, v in obj.items():
            yield from _iter_field_refs(v, path_prefix + [k])
    elif isinstance(obj, list):
        for i, it in enumerate(obj):
            yield from _iter_field_refs(it, path_prefix + [i])


def _parse_filter_handle(literal_text: str):
    """Returns (table, field) from a Power BI handle-like literal."""
    s = _decode_json_string(literal_text or "")
    m = _HANDLE_RE.match(s)
    if m:
        return m.group("table").strip(), m.group("field").strip()
    return "", s.strip()


def normalize_filters(raw):
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, dict) and ("Version" in raw or "From" in raw or "Where" in raw):
        return raw
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if "byExpr" in raw or "byMeasure" in raw:
            return raw.get("byExpr", []) + raw.get("byMeasure", [])
        return raw
    return []


def build_alias_table_mapping(visual_config_json, visualname=None):
    """Builds alias->table mapping from prototypeQuery.From and filter-level From."""
    if visualname is None:
        visualname = "visual"
    alias_to_table = {}
    prototype_query = visual_config_json.get(visualname, {}).get("prototypeQuery", {})
    for from_entry in prototype_query.get("From", []):
        alias = from_entry.get("Name")
        table_entity = from_entry.get("Entity")
        if alias and table_entity:
            alias_to_table[alias] = table_entity

    filters_raw = visual_config_json.get("filters")
    if isinstance(filters_raw, str):
        try:
            filters_json = json.loads(filters_raw)
            for f in filters_json:
                filter_block = f.get("filter", {})
                for from_entry in filter_block.get("From", []):
                    alias = from_entry.get("Name")
                    table_entity = from_entry.get("Entity")
                    if alias and table_entity:
                        alias_to_table[alias] = table_entity
        except Exception:
            pass
    return alias_to_table


def _build_select_maps(config_json, visualname):
    sv = config_json.get(visualname, {}) or {}
    proto = sv.get("prototypeQuery", {}) or {}

    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def resolve_src(src):
        return from_map.get(src, src)

    alias_to_model, alias_to_display, alias_to_kind = {}, {}, {}

    for sel in (proto.get("Select") or []):
        name = sel.get("Name")
        if not name:
            continue

        if "Column" in sel:
            sref = (sel["Column"].get("Expression") or {}).get("SourceRef", {}) or {}
            src = sref.get("Source") or sref.get("Entity")
            table = resolve_src(src)
            prop = sel["Column"].get("Property")
            if table and prop:
                alias_to_model[name] = (table, prop)
                alias_to_kind[name] = "Column"
                p = _parse_agg(name)
                if p:
                    cleaned = f"{p[0]}({p[1]}.{p[2]})"
                    alias_to_model.setdefault(cleaned, (table, prop))

        elif "Measure" in sel:
            ms = sel["Measure"]
            sref = (ms.get("Expression", {}) or {}).get("SourceRef", {}) or {}
            src = sref.get("Entity") or sref.get("Source")
            table = resolve_src(src)
            prop = ms.get("Property")
            if table and prop:
                alias_to_model[name] = (table, prop)
                alias_to_kind[name] = "Measure"

        elif "HierarchyLevel" in sel:
            hl = sel["HierarchyLevel"]
            expr_h = hl.get("Expression", {})
            hier = expr_h.get("Hierarchy", {})
            hier_expr = hier.get("Expression", {})
            sr = hier_expr.get("SourceRef", {})
            src = sr.get("Source") or sr.get("Entity")
            table = resolve_src(src) if src else ""
            prop = hl.get("Level", "")
            if table and prop:
                alias_to_model[name] = (table, prop)
                alias_to_kind[name] = "HierarchyLevel"

        elif "Aggregation" in sel:
            ag = sel["Aggregation"] or {}
            exp = ag.get("Expression") or {}
            leaf = exp.get("Column") or exp.get("Measure") or {}
            sref = (leaf.get("Expression", {}) or {}).get("SourceRef", {}) or {}
            src = sref.get("Source") or sref.get("Entity")
            table = resolve_src(src) if src else ""
            prop = leaf.get("Property")
            if table and prop:
                alias_to_model[name] = (table, prop)
                alias_to_kind[name] = "Aggregation"

        # displayName from columnProperties
        col_props = sv.get("columnProperties", {}) or {}
        cp = col_props.get(name, {})
        dn = cp.get("displayName")
        if isinstance(dn, str) and dn:
            alias_to_display[name] = dn

    return alias_to_model, alias_to_display, alias_to_kind


def build_queryref_map(config_json, visualname=None):
    if visualname is None:
        visualname = "visual"
    sv = config_json.get(visualname, {}) or {}
    proto = sv.get("prototypeQuery", {}) or {}

    from_map = {f.get("Name"): f.get("Entity")
                for f in proto.get("From", []) if isinstance(f, dict)}

    def resolve_src(src):
        return from_map.get(src, src)

    def _leaf_refs(node):
        out = []
        if not isinstance(node, dict):
            return out
        if "Column" in node:
            c = node["Column"] or {}
            srf = (c.get("Expression") or {}).get("SourceRef") or {}
            src = srf.get("Source") or srf.get("Entity")
            out.append((resolve_src(src), c.get("Property"), "Column"))
            return out
        if "Measure" in node:
            m = node["Measure"] or {}
            srf = (m.get("Expression") or {}).get("SourceRef") or {}
            src = srf.get("Source") or srf.get("Entity")
            out.append((resolve_src(src), m.get("Property"), "Measure"))
            return out
        if "Aggregation" in node:
            exp = (node["Aggregation"] or {}).get("Expression") or {}
            return _leaf_refs(exp)
        if "Arithmetic" in node:
            ar = node["Arithmetic"] or {}
            out += _leaf_refs(ar.get("Left") or {})
            out += _leaf_refs(ar.get("Right") or {})
            return out
        if "ScopedEval" in node:
            se = node["ScopedEval"] or {}
            return _leaf_refs(se.get("Expression") or {})
        for v in node.values():
            out += _leaf_refs(v)
        return out

    qr_map = {}
    for i, sel in enumerate(proto.get("Select") or []):
        nm = sel.get("Name")
        if not nm:
            continue
        leaves = _leaf_refs(sel)
        if leaves:
            tbl, prop, kind = leaves[0]
            qr_map[nm] = {
                "table": tbl, "prop": prop, "kind": kind,
                "select_index": i, "fragment": json.dumps(sel, ensure_ascii=False)
            }
    return qr_map


# ---------------------------------------------------------------------------
# PBIR-to-legacy adapter
# ---------------------------------------------------------------------------

def adapt_pbir_to_legacy(config_json: dict) -> None:
    """
    Transform PBIR visual.json structure into legacy-compatible format
    so all existing crawlers work unchanged.

    Modifies config_json in-place.
    """
    visual = config_json.get("visual")
    if not visual:
        return

    query = visual.get("query", {})

    # Handle visuals with no query (shape, image, textbox)
    if not query:
        vco = visual.get("visualContainerObjects")
        if vco:
            visual["vcObjects"] = vco
            del visual["visualContainerObjects"]
        fc = config_json.get("filterConfig", {})
        if fc.get("filters"):
            adapted = []
            for f in fc["filters"]:
                af = dict(f)
                if "field" in af and "expression" not in af:
                    af["expression"] = af["field"]
                af.pop("field", None)
                adapted.append(af)
            config_json["filters"] = json.dumps(adapted)
        if "filterConfig" in config_json:
            del config_json["filterConfig"]
        visual["prototypeQuery"] = {"From": [], "Select": []}
        visual["projections"] = {}
        return

    query_state = query.get("queryState", {})
    sort_def = query.get("sortDefinition", {})

    # 1. Collect all entities and generate stable aliases
    entities = set()

    def _collect_entities(node):
        if isinstance(node, dict):
            sr = node.get("SourceRef")
            if isinstance(sr, dict) and "Entity" in sr:
                entities.add(sr["Entity"])
            for v in node.values():
                _collect_entities(v)
        elif isinstance(node, list):
            for v in node:
                _collect_entities(v)

    _collect_entities(query_state)
    _collect_entities(sort_def)
    _collect_entities(config_json.get("filterConfig", {}))

    entity_to_alias = {}
    used_aliases = set()
    for entity in sorted(entities):
        base = entity[0].lower() if entity else "x"
        alias = base
        if alias in used_aliases:
            for n in range(1, 100):
                candidate = f"{base}{n}"
                if candidate not in used_aliases:
                    alias = candidate
                    break
        entity_to_alias[entity] = alias
        used_aliases.add(alias)

    # 2. Deep-replace SourceRef.Entity with SourceRef.Source
    def _entity_to_source(node):
        if isinstance(node, dict):
            result = {}
            for k, v in node.items():
                if k == "SourceRef" and isinstance(v, dict) and "Entity" in v:
                    result[k] = {"Source": entity_to_alias.get(v["Entity"], v["Entity"])}
                else:
                    result[k] = _entity_to_source(v)
            return result
        elif isinstance(node, list):
            return [_entity_to_source(item) for item in node]
        return node

    # 3. Build prototypeQuery.From
    from_entries = [
        {"Name": alias, "Entity": entity, "Type": 0}
        for entity, alias in sorted(entity_to_alias.items(), key=lambda x: x[1])
    ]

    # 4. Build prototypeQuery.Select + projections from queryState
    select_entries = []
    projections_map = {}
    seen_query_refs = set()

    for role, role_data in query_state.items():
        role_projs = role_data.get("projections", [])
        proj_list = []

        for proj in role_projs:
            field = proj.get("field", {})
            query_ref = proj.get("queryRef", "")
            native_query_ref = proj.get("nativeQueryRef", "")

            if query_ref and query_ref not in seen_query_refs:
                select_entry = _entity_to_source(copy.deepcopy(field))
                select_entry["Name"] = query_ref
                if native_query_ref:
                    select_entry["NativeReferenceName"] = native_query_ref
                select_entries.append(select_entry)
                seen_query_refs.add(query_ref)

            proj_entry = {"queryRef": query_ref}
            proj_list.append(proj_entry)

        if proj_list:
            projections_map[role] = proj_list

    # 4b. Synthesize columnProperties from projections with explicit displayName
    column_properties = {}
    for role, role_data in query_state.items():
        for proj in role_data.get("projections", []):
            qr = proj.get("queryRef", "")
            dn = proj.get("displayName", "")
            is_native_calc = qr == "select" or (
                qr.startswith("select") and qr[6:].isdigit()
            )
            if qr and dn and not is_native_calc:
                column_properties[qr] = {"displayName": dn}
    if column_properties:
        visual["columnProperties"] = column_properties

    # 4c. Synthesize queryFieldParametersByRole from PBIR fieldParameters
    qfpbr = {}
    for role, role_data in query_state.items():
        fps = role_data.get("fieldParameters", [])
        if not fps:
            continue
        projs = role_data.get("projections", [])
        role_entries = []
        for fp in fps:
            param_expr = _entity_to_source(copy.deepcopy(fp["parameterExpr"]))
            idx = fp.get("index", 0)
            length = fp.get("length", 0)
            covered = projs[idx:idx + length]
            col_props = {}
            for p in covered:
                qr = p.get("queryRef", "")
                nr = p.get("nativeQueryRef", "")
                if qr and nr:
                    col_props[qr] = {"displayName": nr}
            entry = {"expr": param_expr}
            if col_props:
                entry["columnProperties"] = col_props
            role_entries.append(entry)
        if role_entries:
            qfpbr[role] = role_entries
    if qfpbr:
        visual["queryFieldParametersByRole"] = qfpbr

    # 5. Build prototypeQuery.OrderBy from sortDefinition
    order_by = []
    for sort_entry in sort_def.get("sort", []):
        field = sort_entry.get("field", {})
        direction_str = sort_entry.get("direction", "Ascending")
        direction = 1 if direction_str == "Ascending" else 2
        expr = _entity_to_source(copy.deepcopy(field))
        order_by.append({"Direction": direction, "Expression": expr})

    # 6. Assemble prototypeQuery
    prototype_query = {"From": from_entries, "Select": select_entries}
    if order_by:
        prototype_query["OrderBy"] = order_by

    visual["prototypeQuery"] = prototype_query
    visual["projections"] = projections_map

    # 7. vcObjects <- visualContainerObjects
    vco = visual.get("visualContainerObjects")
    if vco:
        visual["vcObjects"] = vco
        del visual["visualContainerObjects"]

    # 8. Attach filters from filterConfig (as JSON string, like old format)
    fc = config_json.get("filterConfig", {})
    filters = fc.get("filters", [])
    if filters:
        adapted = []
        for f in filters:
            af = dict(f)
            if "field" in af and "expression" not in af:
                af["expression"] = af["field"]
            af.pop("field", None)
            adapted.append(af)
        config_json["filters"] = json.dumps(adapted)
    if "filterConfig" in config_json:
        del config_json["filterConfig"]

    # 9. Remove PBIR query to prevent crawl_config double-counting
    if "query" in visual:
        del visual["query"]


# ---------------------------------------------------------------------------
# Crawl functions — all 24 ported from notebook
# ---------------------------------------------------------------------------

class _Bag(set):
    """Set-like container for crawl output (supports .add())."""
    pass


class _BagList(list):
    """List-like container for crawl output (supports .add() via append)."""
    def add(self, x):
        self.append(x)


def crawl_config(config, alias_map, output_set, source="Binding",
                 parent_key=None, path=None, visualname=None):
    """
    Walks arbitrary JSON trees and emits every Column/Measure it finds,
    except under projections, prototypeQuery, or filter blocks.
    Emits 5-tuples: (Table, Field, UsedIn, JsonPath, OriginalJson)
    """
    if path is None:
        path = []
    if parent_key in ("projections", "prototypeQuery", "filter",
                      "objects", "vcObjects", "queryFieldParametersByRole"):
        return

    if isinstance(config, dict):
        if "Column" in config:
            col = config["Column"]
            src = (col.get("Expression", {}).get("SourceRef", {}).get("Source")
                   or col.get("Expression", {}).get("SourceRef", {}).get("Entity"))
            prop = col.get("Property")
            if src and prop:
                tbl = alias_map.get(src, src)
                fragment = json.dumps(col, ensure_ascii=False)
                json_path = tuple(path + ["Column"])
                output_set.add((tbl, prop, source, json_path, fragment))

        if "Measure" in config:
            meas = config["Measure"]
            src = (meas.get("Expression", {}).get("SourceRef", {}).get("Source")
                   or meas.get("Expression", {}).get("SourceRef", {}).get("Entity"))
            prop = meas.get("Property")
            if src and prop:
                tbl = alias_map.get(src, src)
                fragment = json.dumps(meas, ensure_ascii=False)
                json_path = tuple(path + ["Measure"])
                output_set.add((tbl, prop, source, json_path, fragment))

        for key, val in config.items():
            crawl_config(val, alias_map, output_set, source,
                         parent_key=key, path=path + [key],
                         visualname=visualname)

    elif isinstance(config, list):
        for i, item in enumerate(config):
            crawl_config(item, alias_map, output_set, source,
                         parent_key=parent_key, path=path + [i],
                         visualname=visualname)


def crawl_filters(node, output_set, alias_map=None, *, negate=False,
                  in_filter=False, parent=None, path=None):
    """
    Walks filter trees and emits field references with filter conditions.
    Emits 7-tuples: (Table, Field, UsedIn, Condition, Value, JsonPath, OriginalJson)
    """
    if path is None:
        path = []
    aliases = alias_map or {}
    if isinstance(node, dict) and "From" in node:
        aliases = dict(aliases)
        for f in node["From"]:
            if isinstance(f, dict):
                aliases[f.get("Name")] = f.get("Entity", aliases.get(f.get("Name")))

    if isinstance(node, dict):
        how_created = node.get("howCreated") or (parent or {}).get("howCreated")
        reason = "Drillthrough Filter" if how_created == 5 else "Filter"

        # NOT wrapper
        if "Not" in node and len(node) == 1:
            crawl_filters(node["Not"], output_set, aliases,
                          negate=not negate, in_filter=in_filter,
                          parent=node, path=path + ["Not"])
            return

        # 'expression' block
        if "expression" in node:
            expr = node.get("expression") or {}
            inner = (expr.get("Column") or expr.get("Measure") or
                     (expr.get("Aggregation") or {}).get("Expression", {}).get("Column") or
                     (expr.get("Aggregation") or {}).get("Expression", {}).get("Measure"))
            if inner:
                src, col = _src_prop(inner, aliases)
                if src and col:
                    cond = node.get("type", "Expression")
                    if negate:
                        cond = f"NOT {cond}"
                    jp = tuple(path + ["expression"])
                    output_set.add((src, col, reason, cond, None, jp,
                                    json.dumps(expr, ensure_ascii=False)))

        # Comparison
        if "Comparison" in node:
            comp = node["Comparison"]
            left = comp.get("Left", {})
            right = comp.get("Right", {})
            inner_l = left.get("Column") or left.get("Measure")
            if inner_l:
                src, col = _src_prop(inner_l, aliases)
                if src and col:
                    kind_map = {0: "==", 1: ">", 2: ">=", 3: "<", 4: "<=", 5: "!="}
                    op = kind_map.get(comp.get("ComparisonKind", 0), "==")
                    if negate:
                        op = f"NOT {op}"
                    val = right.get("Literal", {}).get("Value")
                    jp = tuple(path + ["Comparison"])
                    output_set.add((src, col, reason, op, val, jp,
                                    json.dumps(comp, ensure_ascii=False)))

        # In (set membership)
        if "In" in node:
            in_node = node["In"]
            exprs = in_node.get("Expressions", [])
            for expr_item in exprs:
                inner_e = expr_item.get("Column") or expr_item.get("Measure")
                if inner_e:
                    src, col = _src_prop(inner_e, aliases)
                    if src and col:
                        cond = "NOT IN" if negate else "IN"
                        vals = in_node.get("Values", [])
                        flat_vals = []
                        for vl in vals:
                            for v in vl:
                                lit = v.get("Literal", {}).get("Value")
                                if lit is not None:
                                    flat_vals.append(str(lit))
                        jp = tuple(path + ["In"])
                        output_set.add((src, col, reason, cond,
                                        "|".join(flat_vals) if flat_vals else None,
                                        jp, json.dumps(in_node, ensure_ascii=False)))

        # Recurse into children (skip 'expression' to avoid duplicates)
        for key, val in node.items():
            if key == "expression":
                continue
            crawl_filters(val, output_set, aliases,
                          negate=negate, in_filter=True,
                          parent=node, path=path + [key])

    elif isinstance(node, list):
        for i, item in enumerate(node):
            crawl_filters(item, output_set, aliases,
                          negate=negate, in_filter=in_filter,
                          parent=parent, path=path + [i])


def crawl_field_parameters(config_json, output_set, alias_map=None,
                           path=None, visualname=None):
    """
    Walk visual.queryFieldParametersByRole and emit field parameter bindings.
    Emits 7-tuples: (Table, Field, "FieldParameter", DefaultRef, JsonPath, OriginalJson, extra)
    """
    if visualname is None:
        visualname = "visual"
    if path is None:
        base_path = [visualname, "queryFieldParametersByRole"]
    else:
        base_path = list(path)

    sv = config_json.get(visualname, {}) or {}
    qfp = sv.get("queryFieldParametersByRole", {}) or {}
    col_props = sv.get("columnProperties", {}) or {}

    for role, expressions in qfp.items():
        for idx, expr_entry in enumerate(expressions):
            expr = expr_entry.get("expr")
            if not isinstance(expr, dict):
                continue

            proj_vals = sv.get("projections", {}).get(role, [])
            if proj_vals and "queryRef" in proj_vals[0]:
                default_ref = proj_vals[0]["queryRef"]
            else:
                default_ref = next(iter(col_props.keys()), None)

            json_path = tuple(base_path + [role, idx, "expr"])
            original_bundle = {"expr": expr, "columnProperties": col_props}
            original_json = json.dumps(original_bundle, ensure_ascii=False)

            col_data = expr.get("Column")
            if isinstance(col_data, dict):
                sref = (col_data.get("Expression", {}) or {}).get("SourceRef", {}) or {}
                src = sref.get("Source") or sref.get("Entity")
                prop = col_data.get("Property")
                if src and prop:
                    tbl = (alias_map or {}).get(src, src)
                    output_set.add((tbl, prop, "FieldParameter", default_ref,
                                    json_path, original_json, role))

            meas_data = expr.get("Measure")
            if isinstance(meas_data, dict):
                sref = (meas_data.get("Expression", {}) or {}).get("SourceRef", {}) or {}
                src = sref.get("Source") or sref.get("Entity")
                prop = meas_data.get("Property")
                if src and prop:
                    tbl = (alias_map or {}).get(src, src)
                    output_set.add((tbl, prop, "FieldParameter", default_ref,
                                    json_path, original_json, role))


def crawl_order_by(proto_query, alias_map, output_set, source="OrderBy",
                   visualname=None):
    """
    Walks prototypeQuery.OrderBy and emits sort field references.
    Emits 6-tuples: (Table, Field, UsedIn, Direction, JsonPath, OriginalJson)
    """
    if not isinstance(proto_query, dict):
        return

    def resolve_src(src):
        return (alias_map or {}).get(src) or src

    def emit(table, field, used_in, direction, path_tuple, node_dict):
        frag = json.dumps(node_dict, ensure_ascii=False)
        output_set.add((table, field, used_in, direction, path_tuple, frag))

    def walk_expr(node, direction, label, path):
        if not isinstance(node, dict):
            return
        if "Measure" in node:
            ms = node["Measure"] or {}
            sref = (ms.get("Expression") or {}).get("SourceRef") or {}
            src = sref.get("Source") or sref.get("Entity")
            table = resolve_src(src) if src else ""
            field = ms.get("Property")
            emit(table, field, f"{source}({label}.Measure)",
                 direction, path + ("Measure", "Property"), ms)
        if "Column" in node:
            col = node["Column"] or {}
            sref = (col.get("Expression") or {}).get("SourceRef") or {}
            src = sref.get("Source") or sref.get("Entity")
            table = resolve_src(src) if src else ""
            field = col.get("Property")
            emit(table, field, f"{source}({label}.Column)",
                 direction, path + ("Column", "Property"), col)
        if "Aggregation" in node:
            ag = node["Aggregation"] or {}
            exp = ag.get("Expression") or {}
            if "Column" in exp:
                walk_expr({"Column": exp["Column"]}, direction,
                          f"{label}.Aggregation:Column", path + ("Aggregation", "Expression"))
        if "Arithmetic" in node:
            ar = node["Arithmetic"] or {}
            walk_expr(ar.get("Left") or {}, direction,
                      f"{label}.Arithmetic.Left", path + ("Arithmetic", "Left"))
            walk_expr(ar.get("Right") or {}, direction,
                      f"{label}.Arithmetic.Right", path + ("Arithmetic", "Right"))
        if "ScopedEval" in node:
            se = node["ScopedEval"] or {}
            walk_expr(se.get("Expression") or {}, direction,
                      f"{label}.ScopedEval", path + ("ScopedEval", "Expression"))

    for i, ob in enumerate(proto_query.get("OrderBy", [])):
        direction = ob.get("Direction", 1)
        expr = ob.get("Expression", {})
        base_path = (visualname or "visual", "prototypeQuery", "OrderBy", i, "Expression")
        walk_expr(expr, direction, "Expression", base_path)


def crawl_native_calcs(config, alias_map, output_set, source="Binding", path=None):
    """
    Walks prototypeQuery Select/OrderBy for NativeVisualCalculation blocks.
    Emits 7-tuples: (Table, CalcName, Source, Direction, DaxExpr, JsonPath, OriginalJson)
    """
    if path is None:
        path = []
    if isinstance(config, dict):
        nvc = config.get("NativeVisualCalculation")
        if isinstance(nvc, dict):
            name = nvc.get("Name")
            expr = nvc.get("Expression")
            direction = config.get("Direction")
            if name is not None and expr is not None:
                json_path = tuple(path + ["NativeVisualCalculation"])
                original_fragment = json.dumps(nvc, ensure_ascii=False)
                output_set.add(("", name, source, direction, expr,
                                json_path, original_fragment))
        for key, child in config.items():
            crawl_native_calcs(child, alias_map, output_set, source, path + [key])
    elif isinstance(config, list):
        for idx, item in enumerate(config):
            crawl_native_calcs(item, alias_map, output_set, source, path + [idx])


def crawl_column_formatting(config_json, alias_map, output_set,
                            source="Formatting", visualname=None):
    """
    Capture columnFormatting rules (formatString overrides per column).
    Emits 7-tuples: (Table, Field, Source, Condition, Value, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    alias_to_model, _alias_to_display, _ = _build_select_maps(config_json, visualname)
    sv = config_json.get(visualname, {}) or {}
    proto = sv.get("prototypeQuery", {}) or {}
    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def _resolve_src(src):
        ent = from_map.get(src, src)
        return alias_map.get(ent, ent) if alias_map else ent

    fmts = (sv.get("objects", {}).get("columnFormatting", []) or [])
    for idx, fmt in enumerate(fmts):
        alias = (fmt.get("selector", {}) or {}).get("metadata")
        if not alias:
            continue
        literal_value = _extract_literal_value(fmt.get("properties", {}) or {})
        field = _alias_label(alias)

        if alias in alias_to_model:
            table, _ = alias_to_model[alias]
        else:
            p = _parse_agg(alias)
            if p:
                _, src, prop = p
                table, field = _resolve_src(src), prop
            else:
                table = ""

        json_path = (visualname, "objects", "columnFormatting", idx)
        original_fragment = json.dumps(fmt, ensure_ascii=False)
        output_set.add((table, field, source, None, literal_value,
                        json_path, original_fragment))

        props = fmt.get("properties", {}) or {}
        for src, prop, pth, node in _iter_field_refs(
                props, path_prefix=list(json_path) + ["properties"]):
            tbl = (alias_map or {}).get(src, src)
            frag = json.dumps(node, ensure_ascii=False)
            output_set.add((tbl, prop, source, None, None, tuple(pth), frag))


def crawl_values_formatting(config_json, alias_map, output_set,
                            source="Formatting", visualname=None):
    """
    Capture values formatting rules (formatString overrides per value/measure).
    Emits 7-tuples: (Table, Field, Source, Condition, Value, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    alias_to_model, _alias_to_display, _ = _build_select_maps(config_json, visualname)
    sv = config_json.get(visualname, {}) or {}
    proto = sv.get("prototypeQuery", {}) or {}
    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def _resolve_src(src):
        ent = from_map.get(src, src)
        return alias_map.get(ent, ent) if alias_map else ent

    fmts = (sv.get("objects", {}).get("values", []) or [])
    for idx, fmt in enumerate(fmts):
        alias = (fmt.get("selector", {}) or {}).get("metadata")
        if not alias:
            continue
        literal_value = _extract_literal_value(fmt.get("properties", {}) or {})
        field = _alias_label(alias)

        if alias in alias_to_model:
            table, _ = alias_to_model[alias]
        else:
            p = _parse_agg(alias)
            if p:
                _, src, prop = p
                table, field = _resolve_src(src), prop
            else:
                table = ""

        json_path = (visualname, "objects", "values", idx)
        original_fragment = json.dumps(fmt, ensure_ascii=False)
        output_set.add((table, field, source, None, literal_value,
                        json_path, original_fragment))

        props = fmt.get("properties", {}) or {}
        for src, prop, pth, node in _iter_field_refs(
                props, path_prefix=list(json_path) + ["properties"]):
            tbl = (alias_map or {}).get(src, src)
            frag = json.dumps(node, ensure_ascii=False)
            output_set.add((tbl, prop, source, None, None, tuple(pth), frag))


# ---------------------------------------------------------------------------
# Structured conditional formatting extraction (for matrix/tablix rendering)
# ---------------------------------------------------------------------------

def _resolve_pbi_color(color_literal: str) -> str:
    """Resolve Power BI theme color tokens to CSS colors.

    Tokens like ``'maxColor'``, ``'minColor'``, ``'foreground'`` are theme
    references.  We map them to sensible defaults.  Hex colors pass through.
    """
    if not color_literal:
        return "#000000"
    s = color_literal.strip().strip("'\"")
    _theme = {
        "maxColor": "#118DFF",   # PBI default blue
        "minColor": "#D64550",   # PBI default red
        "foreground": "#333333",
        "background": "#FFFFFF",
        "neutralDark": "#212121",
        "neutralLight": "#EAEAEA",
    }
    return _theme.get(s, s)


def _get_literal(node) -> str | None:
    """Extract a raw literal string from a PBI expr node."""
    if isinstance(node, dict):
        lit = node.get("expr", node).get("Literal", {})
        if isinstance(lit, dict):
            v = lit.get("Value")
            if v is not None:
                return str(v).strip("'\"")
        # Recurse through solid→color→expr
        for sub in ("solid", "color"):
            if sub in node:
                return _get_literal(node[sub])
    return None


def _extract_fill_rule(prop_node: dict) -> dict | None:
    """Extract a FillRule (gradient) from a property node.

    Returns a dict like::

        {"type": "gradient", "target": "backColor"|"fontColor",
         "minColor": "#...", "maxColor": "#...",
         "measure": {"table": ..., "field": ...}}
    """
    # Navigate solid→color→expr→FillRule
    solid = prop_node.get("solid", prop_node)
    color_node = solid.get("color", solid)
    expr = color_node.get("expr", color_node)
    fr = expr.get("FillRule")
    if not fr:
        return None
    inp = fr.get("Input", {})
    measure_ref = inp.get("Measure", {})
    table = (measure_ref.get("Expression", {}).get("SourceRef", {}).get("Entity", ""))
    field = measure_ref.get("Property", "")
    rule = fr.get("FillRule", {})
    lg2 = rule.get("linearGradient2", {})
    if not lg2:
        lg3 = rule.get("linearGradient3", {})
        if lg3:
            min_c = _resolve_pbi_color(_get_literal(lg3.get("min", {}).get("color")))
            mid_c = _resolve_pbi_color(_get_literal(lg3.get("mid", {}).get("color")))
            max_c = _resolve_pbi_color(_get_literal(lg3.get("max", {}).get("color")))
            return {
                "type": "gradient3",
                "minColor": min_c,
                "midColor": mid_c,
                "maxColor": max_c,
                "measure": {"table": table, "field": field},
            }
        return None
    min_c = _resolve_pbi_color(_get_literal(lg2.get("min", {}).get("color")))
    max_c = _resolve_pbi_color(_get_literal(lg2.get("max", {}).get("color")))
    return {
        "type": "gradient",
        "minColor": min_c,
        "maxColor": max_c,
        "measure": {"table": table, "field": field},
    }


def _extract_conditional_icons(prop_node: dict) -> dict | None:
    """Extract conditional icon rules from a ``value.expr.Conditional`` node.

    Returns a dict like::

        {"type": "icons", "layout": "Before"|"After",
         "icons": [{"icon": "CircleHigh", "threshold": 0.67, "op": ">="},
                   {"icon": "SignMedium", "threshold": 0.33, "op": ">="},
                   {"icon": "SignLow", "threshold": null, "op": "default"}]}
    """
    value_node = prop_node.get("value", {})
    cond = (value_node.get("expr", {}) or {}).get("Conditional", {})
    cases = cond.get("Cases", [])
    if not cases:
        return None
    layout = _get_literal(prop_node.get("layout")) or "Before"
    icons = []
    for case in cases:
        icon_name = _get_literal(case.get("Value"))
        condition = case.get("Condition", {})
        threshold = _extract_range_percent(condition)
        icons.append({
            "icon": icon_name,
            "threshold": threshold,
        })
    return {
        "type": "icons",
        "layout": layout,
        "icons": icons,
    }


def _extract_range_percent(condition: dict) -> float | None:
    """Walk a Comparison/And tree to find the RangePercent.Percent value."""
    if "Comparison" in condition:
        right = condition["Comparison"].get("Right", {})
        if "RangePercent" in right:
            return right["RangePercent"].get("Percent")
    if "And" in condition:
        # The first leg of an AND usually carries the upper threshold
        left_t = _extract_range_percent(condition["And"].get("Left", {}))
        if left_t is not None:
            return left_t
        return _extract_range_percent(condition["And"].get("Right", {}))
    return None


def crawl_conditional_formatting(config_json, alias_map=None, visualname=None):
    """Extract structured conditional formatting rules from a PBIR visual.

    Returns a list of rule dicts, each with a ``type`` key:
    - ``"dataBars"`` — in-cell bar rendering
    - ``"gradient"`` / ``"gradient3"`` — color scale (fontColor or backColor)
    - ``"icons"`` — conditional KPI icons

    Each rule also has a ``measure`` key ``{"table": ..., "field": ...}``
    identifying which measure the rule applies to, and a ``target`` key
    (``"fontColor"``, ``"backColor"``, ``"dataBars"``, ``"icon"``).
    """
    if visualname is None:
        visualname = "visual"
    sv = config_json.get(visualname, {}) or {}
    objects = sv.get("objects", {}) or {}
    rules: list[dict] = []

    def _resolve_metadata(metadata: str) -> tuple[str, str]:
        """Resolve 'Table.Field' metadata to (table, field) with alias mapping."""
        if not metadata:
            return ("", "")
        parts = metadata.split(".", 1)
        if len(parts) == 2:
            tbl, fld = parts
            if alias_map:
                tbl = alias_map.get(tbl, tbl)
            return (tbl, fld)
        return ("", metadata)

    # --- columnFormatting: dataBars ---
    for fmt in objects.get("columnFormatting", []):
        metadata = (fmt.get("selector", {}) or {}).get("metadata", "")
        table, field = _resolve_metadata(metadata)
        props = fmt.get("properties", {}) or {}
        db = props.get("dataBars")
        if db:
            pos_color = _resolve_pbi_color(_get_literal(db.get("positiveColor")))
            neg_color = _resolve_pbi_color(_get_literal(db.get("negativeColor")))
            axis_color = _resolve_pbi_color(_get_literal(db.get("axisColor")))
            hide_text_raw = _get_literal(db.get("hideText"))
            hide_text = hide_text_raw in ("true", "True", True) if hide_text_raw is not None else False
            reverse_raw = _get_literal(db.get("reverseDirection"))
            reverse = reverse_raw in ("true", "True", True) if reverse_raw is not None else False
            rules.append({
                "type": "dataBars",
                "target": "dataBars",
                "measure": {"table": table, "field": field},
                "positiveColor": pos_color,
                "negativeColor": neg_color,
                "axisColor": axis_color,
                "hideText": hide_text,
                "reverseDirection": reverse,
            })

    # --- values: fontColor/backColor gradients and icons ---
    for fmt in objects.get("values", []):
        metadata = (fmt.get("selector", {}) or {}).get("metadata", "")
        table, field = _resolve_metadata(metadata)
        props = fmt.get("properties", {}) or {}

        # fontColor → gradient
        fc = props.get("fontColor")
        if fc:
            gr = _extract_fill_rule(fc)
            if gr:
                gr["target"] = "fontColor"
                if not gr["measure"]["table"]:
                    gr["measure"] = {"table": table, "field": field}
                rules.append(gr)

        # backColor → gradient
        bc = props.get("backColor")
        if bc:
            gr = _extract_fill_rule(bc)
            if gr:
                gr["target"] = "backColor"
                if not gr["measure"]["table"]:
                    gr["measure"] = {"table": table, "field": field}
                rules.append(gr)

        # icon → conditional icons
        ic = props.get("icon")
        if ic and ic.get("kind") == "Icon":
            icon_rule = _extract_conditional_icons(ic)
            if icon_rule:
                icon_rule["target"] = "icon"
                icon_rule["measure"] = {"table": table, "field": field}
                rules.append(icon_rule)

    return rules


def crawl_hierarchy_levels(config_json, output_set, alias_map=None,
                           visualname=None):
    """
    Walk prototypeQuery.Select for HierarchyLevel entries.
    Emits 6-tuples: (Table, Level, "Hierarchy", HierarchyName, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    select_items = (
        config_json.get(visualname, {})
        .get("prototypeQuery", {})
        .get("Select", [])
    )

    for idx, sel in enumerate(select_items):
        if "HierarchyLevel" not in sel:
            continue
        expr = sel["HierarchyLevel"].get("Expression", {})
        hier = expr.get("Hierarchy", {})
        prop = hier.get("Property")
        src_ref = (hier.get("Expression", {}).get("SourceRef", {}).get("Source")
                   or hier.get("Expression", {}).get("SourceRef", {}).get("Entity"))

        if (not src_ref or not prop) and "PropertyVariationSource" in hier.get("Expression", {}):
            var = hier["Expression"]["PropertyVariationSource"]
            var_sr = var.get("Expression", {}).get("SourceRef", {})
            src_ref = var_sr.get("Source") or var_sr.get("Entity")
            prop = var.get("Property")

        level = sel["HierarchyLevel"].get("Level")
        if not (src_ref and level):
            continue

        table = alias_map.get(src_ref, src_ref) if alias_map else src_ref
        json_path = (visualname, "prototypeQuery", "Select", idx)
        original_fragment = json.dumps(sel, ensure_ascii=False)
        output_set.add((table, level, "Hierarchy", prop, json_path, original_fragment))


def crawl_projections(config_json, output_set, alias_map=None,
                      prefer_select_path=False, path=None, visualname=None):
    """
    Emit projection rows — one per field bound to a visual role.
    Emits 4-tuples: (Table, Field, UsedIn, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    base = tuple(path) if path else tuple()
    sv = (config_json or {}).get(visualname, {}) or {}
    proto = sv.get("prototypeQuery", {}) or {}
    projections = (sv.get("projections", {}) or {})

    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def resolve_src(src):
        return (alias_map or {}).get(src) or from_map.get(src) or src

    try:
        qr_map = build_queryref_map(config_json, visualname) or {}
    except Exception:
        qr_map = {}

    for role, bindings in projections.items():
        if not isinstance(bindings, list):
            continue
        for i, b in enumerate(bindings):
            qr = (b or {}).get("queryRef")
            if not qr:
                # Inline object (bookmark snapshot)
                for key in ("Column", "Measure", "Aggregation"):
                    leaf = (b or {}).get(key)
                    if leaf:
                        refs = []
                        if key == "Aggregation":
                            inner = (leaf or {}).get("Expression", {})
                            for lk in ("Column", "Measure"):
                                ll = inner.get(lk)
                                if ll:
                                    srf = (ll.get("Expression", {}) or {}).get("SourceRef", {}) or {}
                                    src = srf.get("Source") or srf.get("Entity")
                                    refs.append((resolve_src(src), ll.get("Property")))
                        else:
                            srf = (leaf.get("Expression", {}) or {}).get("SourceRef", {}) or {}
                            src = srf.get("Source") or srf.get("Entity")
                            refs.append((resolve_src(src), leaf.get("Property")))
                        for tbl, prop in refs:
                            if tbl and prop:
                                output_set.add((tbl, prop, f"Projection:{role}",
                                                json.dumps(b, ensure_ascii=False)))
                continue

            if qr in qr_map:
                info = qr_map[qr]
                output_set.add((info["table"], info["prop"],
                                f"Projection:{role}", qr))
            else:
                # Fallback: parse qr as "alias.prop" or "Agg(alias.prop)"
                p = _parse_agg(qr)
                if p:
                    _, src, prop = p
                    output_set.add((resolve_src(src), prop,
                                    f"Projection:{role}", qr))
                elif "." in qr:
                    src, prop = qr.split(".", 1)
                    output_set.add((resolve_src(src), prop,
                                    f"Projection:{role}", qr))


def crawl_projections_category(config_json, output_set, alias_map=None,
                               path=None, visualname=None):
    """
    Emit Category projection rows specifically.
    Emits 4-tuples: (Table, Field, "Projection:Category", OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json or {}).get(visualname, {}) or {}
    proto = sv.get("prototypeQuery", {}) or {}
    projs = (sv.get("projections", {}) or {})
    bindings = projs.get("Category") or []
    if not isinstance(bindings, list):
        return

    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def resolve_src(src):
        return (alias_map or {}).get(src) or from_map.get(src) or src

    name_to_prop = {}
    for sel in (proto.get("Select") or []):
        nm = sel.get("Name")
        if not nm:
            continue
        prop = None
        if "Column" in sel:
            prop = (sel["Column"] or {}).get("Property")
        elif "Measure" in sel:
            prop = (sel["Measure"] or {}).get("Property")
        elif "Aggregation" in sel:
            inner = ((sel["Aggregation"] or {}).get("Expression") or {})
            leaf = inner.get("Column") or inner.get("Measure") or {}
            prop = leaf.get("Property")
        if prop:
            name_to_prop[nm] = prop

    for i, b in enumerate(bindings):
        qr = (b or {}).get("queryRef")
        if qr:
            if qr in name_to_prop:
                prop = name_to_prop[qr]
                p = _parse_agg(qr)
                if p:
                    table = resolve_src(p[1])
                else:
                    parts = qr.split(".", 1)
                    table = resolve_src(parts[0]) if len(parts) > 1 else ""
                output_set.add((table, prop, "Projection:Category", qr))
        else:
            # Inline object
            for key in ("Column", "Measure"):
                leaf = (b or {}).get(key)
                if leaf:
                    srf = (leaf.get("Expression", {}) or {}).get("SourceRef", {}) or {}
                    src = srf.get("Source") or srf.get("Entity")
                    prop = leaf.get("Property")
                    if src and prop:
                        output_set.add((resolve_src(src), prop,
                                        "Projection:Category",
                                        json.dumps(b, ensure_ascii=False)))


def crawl_prototype_query_select(config_json, output_set, alias_map=None,
                                 emit_usage=True, skip_if_referenced_by_projection=False,
                                 emit_parent=False, visualname=None):
    """
    Emit Select entries from the prototypeQuery.
    Emits 6-tuples: (Table, Field, UsedIn, Condition, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = config_json.get(visualname, {}) or {}
    proto = sv.get("prototypeQuery")
    if not isinstance(proto, dict):
        return

    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def resolve_src(src):
        return (alias_map or {}).get(src) or from_map.get(src) or src

    for i, sel in enumerate(proto.get("Select") or []):
        nm = sel.get("Name", "")
        base_path = (visualname, "prototypeQuery", "Select", i)

        if "Column" in sel:
            col = sel["Column"] or {}
            sref = (col.get("Expression", {}) or {}).get("SourceRef", {}) or {}
            src = sref.get("Source") or sref.get("Entity")
            prop = col.get("Property")
            if src and prop:
                output_set.add((resolve_src(src), prop,
                                "PrototypeQuery:Select(Column)", None,
                                base_path + ("Column", "Property"),
                                json.dumps(prop, ensure_ascii=False)))

        elif "Measure" in sel:
            ms = sel["Measure"] or {}
            sref = (ms.get("Expression", {}) or {}).get("SourceRef", {}) or {}
            src = sref.get("Source") or sref.get("Entity")
            prop = ms.get("Property")
            if src and prop:
                output_set.add((resolve_src(src), prop,
                                "PrototypeQuery:Select(Measure)", None,
                                base_path + ("Measure", "Property"),
                                json.dumps(prop, ensure_ascii=False)))

        elif "Aggregation" in sel:
            ag = sel["Aggregation"] or {}
            exp = ag.get("Expression") or {}
            for lk in ("Column", "Measure"):
                leaf = exp.get(lk)
                if leaf:
                    sref = (leaf.get("Expression", {}) or {}).get("SourceRef", {}) or {}
                    src = sref.get("Source") or sref.get("Entity")
                    prop = leaf.get("Property")
                    if src and prop:
                        output_set.add((resolve_src(src), prop,
                                        f"PrototypeQuery:Select(Aggregation:{lk})",
                                        None,
                                        base_path + ("Aggregation", "Expression", lk, "Property"),
                                        json.dumps(prop, ensure_ascii=False)))


def crawl_column_properties_labels(config_json, output_set, alias_map=None,
                                   source="ColumnProperties", visualname=None):
    """
    Emit label rows from columnProperties displayName overrides.
    Emits 6-tuples: (Table, Field, UsedIn, Condition, Value, JsonPath)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    colprops = (sv.get("columnProperties") or {})
    if not isinstance(colprops, dict):
        return

    proto = (sv.get("prototypeQuery") or {})
    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def _resolve_src(src):
        ent = from_map.get(src, src)
        return (alias_map or {}).get(ent, ent)

    try:
        qr_map = build_queryref_map(config_json, visualname) or {}
    except Exception:
        qr_map = {}

    for key, cp in colprops.items():
        if not isinstance(cp, dict):
            continue
        dn = cp.get("displayName")
        if not isinstance(dn, str) or not dn:
            continue

        # Resolve key to table.field
        table, field = "", key
        if key in qr_map:
            info = qr_map[key]
            table, field = info["table"], info["prop"]
        else:
            p = _parse_agg(key)
            if p:
                _, src, prop = p
                table, field = _resolve_src(src), prop
            elif "." in key:
                src, prop = key.split(".", 1)
                table, field = _resolve_src(src), prop

        json_path = (visualname, "columnProperties", key, "displayName")
        output_set.add((table, field, f"{source} (label only)", None,
                        dn, json_path))


def crawl_slicer_sync_group(config_json, output_set, visualname=None):
    """
    Emit the slicer sync group name.
    Emits 6-tuples: ("", GroupName, "Slicer:SyncGroup", None, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    sg = sv.get("syncGroup")
    if not isinstance(sg, dict):
        return
    group_name = sg.get("groupName")
    if not group_name:
        return
    json_path = (visualname, "syncGroup", "groupName")
    original_json = json.dumps({"groupName": group_name}, ensure_ascii=False)
    output_set.add(("", group_name, "Slicer:SyncGroup", None,
                    json_path, original_json))


def crawl_select_native_refnames(config_json, output_set, visualname=None):
    """
    Emit NativeReferenceName from each Select entry.
    Emits 6-tuples: ("", NativeRefName, "PrototypeQuery:NativeRefName", None, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    proto = sv.get("prototypeQuery")
    if not isinstance(proto, dict):
        return
    for idx, sel in enumerate(proto.get("Select") or []):
        native = sel.get("NativeReferenceName")
        if not native:
            continue
        json_path = (visualname, "prototypeQuery", "Select", idx,
                     "NativeReferenceName")
        original_json = json.dumps(native, ensure_ascii=False)
        output_set.add(("", native, "PrototypeQuery:NativeRefName", None,
                        json_path, original_json))


def crawl_objects_column_width(config_json, output_set, alias_map=None,
                               source="Formatting:ColumnWidth", visualname=None):
    """
    Capture column width rules that reference a field via selector.metadata.
    Emits 6-tuples: (Table, Field, Source, Value, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    objs = (sv.get("objects") or {})
    items = (objs.get("columnWidth") or [])
    if not isinstance(items, list):
        return

    alias_to_table = build_alias_table_mapping(config_json, visualname)

    def resolve_table(src_alias_or_entity: str) -> str:
        entity = alias_to_table.get(src_alias_or_entity, src_alias_or_entity)
        return (alias_map or {}).get(entity, entity)

    for i, it in enumerate(items):
        meta = (it.get("selector") or {}).get("metadata")
        if not isinstance(meta, str):
            continue

        table = field = ""
        parsed = _parse_agg(meta)
        if parsed:
            _, src, prop = parsed
            table, field = resolve_table(src), prop
        else:
            if "." in meta:
                src, prop = meta.split(".", 1)
                table, field = resolve_table(src), prop
            else:
                table, field = "", meta

        value = None
        try:
            value = it["properties"]["value"]["expr"]["Literal"]["Value"]
        except Exception:
            pass

        json_path = (visualname, "objects", "columnWidth", i)
        original_json = json.dumps(it, ensure_ascii=False)
        output_set.add((table, field, source, value, json_path, original_json))


def crawl_expansion_queryrefs(config_json, output_set, alias_map,
                              source="Binding:ExpansionStates(QueryRefs)",
                              path=None, visualname=None):
    """
    Capture strings in expansionStates[*].levels[*].queryRefs[*].
    Emits 6-tuples: (Table, Field, Source, None, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    base = tuple(path) if path else tuple()

    if isinstance(config_json, dict) and visualname in config_json:
        sv = (config_json.get(visualname) or {})
    else:
        sv = config_json or {}

    exp_list = (sv.get("expansionStates") or [])
    if not isinstance(exp_list, list):
        return

    proto = (sv.get("prototypeQuery") or {})
    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def resolve_src(src):
        ent = from_map.get(src, src)
        return (alias_map or {}).get(ent, ent)

    for i, exp in enumerate(exp_list):
        levels = (exp or {}).get("levels") or []
        for j, lvl in enumerate(levels):
            qrefs = (lvl or {}).get("queryRefs") or []
            for k, q in enumerate(qrefs):
                if not isinstance(q, str):
                    continue
                table, field = "", q
                p = _parse_agg(q)
                if p:
                    _, src, prop = p
                    table, field = resolve_src(src), prop
                elif "." in q:
                    src, prop = q.split(".", 1)
                    table, field = resolve_src(src), prop

                jp = base + (visualname, "expansionStates", i, "levels", j,
                             "queryRefs", k)
                output_set.add((table, field, source, None, jp,
                                json.dumps(q, ensure_ascii=False)))


def crawl_objects_scope_selectors(config_json, output_set, alias_map=None,
                                  source="SelectorScope",
                                  skip_sections=("dataPoint",),
                                  visualname=None):
    """
    Walk objects.*[*].selector.data[...] and emit Column/Measure refs.
    Emits 6-tuples: (Table, Field, UsedIn, None, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    objs = (sv.get("objects") or {})
    if not isinstance(objs, dict):
        return

    alias_to_table = build_alias_table_mapping(config_json, visualname)

    def resolve_table(src_alias_or_entity: str) -> str:
        entity = alias_to_table.get(src_alias_or_entity, src_alias_or_entity)
        return (alias_map or {}).get(entity, entity)

    def _collect_fields(node, out_list):
        if isinstance(node, dict):
            col = node.get("Column")
            if isinstance(col, dict):
                sref = (col.get("Expression") or {}).get("SourceRef") or {}
                src = sref.get("Source") or sref.get("Entity")
                prop = col.get("Property")
                if src and prop:
                    out_list.append(("Column", resolve_table(src), prop))
            ms = node.get("Measure")
            if isinstance(ms, dict):
                sref = (ms.get("Expression") or {}).get("SourceRef") or {}
                src = sref.get("Source") or sref.get("Entity")
                prop = ms.get("Property")
                if src and prop:
                    out_list.append(("Measure", resolve_table(src), prop))
            for v in node.values():
                _collect_fields(v, out_list)
        elif isinstance(node, list):
            for it in node:
                _collect_fields(it, out_list)

    for section, entries in objs.items():
        if section in skip_sections:
            continue
        if not isinstance(entries, list):
            continue
        for e_idx, entry in enumerate(entries):
            sel = (entry or {}).get("selector") or {}
            data = sel.get("data")
            if not data:
                continue
            fields = []
            _collect_fields(data, fields)
            for kind, tbl, prop in fields:
                jp = (visualname, "objects", section, e_idx, "selector", "data")
                frag = json.dumps(data, ensure_ascii=False)
                output_set.add((tbl, prop, f"{source}:{section}", None, jp, frag))


def crawl_datapoint_selectors(config_json, output_set, alias_map=None,
                              source="DataPoint:Selector", visualname=None):
    """
    Emit rows for series/category formatting in dataPoint selectors.
    Emits 7-tuples: (Table, Field, UsedIn, Condition, Value, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    proto = (sv.get("prototypeQuery") or {})
    from_map = {f.get("Name"): f.get("Entity")
                for f in (proto.get("From") or []) if isinstance(f, dict)}

    def resolve_src(src):
        return (alias_map or {}).get(src) or from_map.get(src) or src

    objs = (sv.get("objects") or {})
    dps = objs.get("dataPoint") or []

    for dp_idx, dp in enumerate(dps):
        sel = (dp.get("selector") or {})

        # metadata (series key string)
        meta = sel.get("metadata")
        if isinstance(meta, str) and meta.strip():
            table = ""
            field = meta
            m = _AGG_REF_RE.match(meta)
            if m:
                src = m.group("src")
                prop = m.group("prop").strip()
                table = resolve_src(src)
                field = prop
            else:
                m2 = _DOTTED_LABEL_RE.match(meta)
                if m2:
                    table = m2.group("left").strip()
                    field = m2.group("right").strip()

            jp = (visualname, "objects", "dataPoint", dp_idx, "selector", "metadata")
            ojson = json.dumps(meta, ensure_ascii=False)
            output_set.add((table, field, f"{source}(metadata)", None, None,
                            jp, ojson))

        # data/scopeId literals
        data_entries = sel.get("data") or []
        if isinstance(data_entries, dict):
            data_entries = [data_entries]
        for d_idx, d_entry in enumerate(data_entries):
            scope = (d_entry or {}).get("scopeId") or {}
            comp = scope.get("Comparison") or {}
            left = comp.get("Left", {})
            right = comp.get("Right", {})
            inner = left.get("Column") or left.get("Measure")
            if inner:
                src, col = _src_prop(inner, {})
                if src and col:
                    src = resolve_src(src)
                    val = (right.get("Literal") or {}).get("Value")
                    jp = (visualname, "objects", "dataPoint", dp_idx,
                          "selector", "data", d_idx, "scopeId")
                    output_set.add((src, col, f"{source}(scopeId)", None, val,
                                    jp, json.dumps(scope, ensure_ascii=False)))


def crawl_reference_lines(config_json, output_set, alias_map=None,
                          visualname=None):
    """
    Scan objects.y1AxisReferenceLine / y2AxisReferenceLine.
    Emits 7-tuples: (Table, Field, UsedIn, Condition, Value, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    objs = (sv.get("objects") or {})

    def _resolve_src(src):
        return (alias_map or {}).get(src) or src or ""

    def _walk_value_expr(expr, axis_tag, base_path):
        if not isinstance(expr, dict):
            return
        if "Measure" in expr:
            ms = expr["Measure"] or {}
            sref = (ms.get("Expression") or {}).get("SourceRef") or {}
            src = sref.get("Source") or sref.get("Entity")
            table = _resolve_src(src)
            prop = ms.get("Property")
            if table and prop:
                output_set.add((table, prop, f"ReferenceLine:{axis_tag}",
                                None, None, tuple(base_path + ["Measure", "Property"]),
                                json.dumps(prop, ensure_ascii=False)))
        if "Column" in expr:
            col = expr["Column"] or {}
            sref = (col.get("Expression") or {}).get("SourceRef") or {}
            src = sref.get("Source") or sref.get("Entity")
            table = _resolve_src(src)
            prop = col.get("Property")
            if table and prop:
                output_set.add((table, prop, f"ReferenceLine:{axis_tag}",
                                None, None, tuple(base_path + ["Column", "Property"]),
                                json.dumps(prop, ensure_ascii=False)))
        if "Aggregation" in expr:
            ag = expr["Aggregation"] or {}
            _walk_value_expr(ag.get("Expression") or {}, axis_tag,
                             base_path + ["Aggregation", "Expression"])
        if "ScopedEval" in expr:
            se = expr["ScopedEval"] or {}
            _walk_value_expr(se.get("Expression") or {}, axis_tag,
                             base_path + ["ScopedEval", "Expression"])

    for axis_key, axis_tag in [("y1AxisReferenceLine", "Y1"),
                               ("y2AxisReferenceLine", "Y2")]:
        lines = objs.get(axis_key) or []
        for rl_idx, rl in enumerate(lines):
            props = rl.get("properties", {}) or {}
            value = props.get("value", {})
            expr = value.get("expr")
            if isinstance(expr, dict):
                base_path = [visualname, "objects", axis_key, rl_idx,
                             "properties", "value", "expr"]
                _walk_value_expr(expr, axis_tag, base_path)

            # Label text
            dn = props.get("displayName", {})
            dn_expr = dn.get("expr", {}) if isinstance(dn, dict) else {}
            dn_lit = dn_expr.get("Literal", {}).get("Value")
            if dn_lit:
                jp = (visualname, "objects", axis_key, rl_idx,
                      "properties", "displayName", "expr", "Literal", "Value")
                output_set.add(("", str(dn_lit).strip("'"),
                                "ReferenceLine:DisplayName(Text)", None, None,
                                jp, json.dumps(dn_lit, ensure_ascii=False)))


def crawl_cached_filter_display_items(config_json, output_set, visualname=None):
    """
    Emit cached filter display item names.
    Emits 7-tuples: ("", DisplayName, "VisualFilter:CachedDisplayName", None, None, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    for i, item in enumerate(sv.get("cachedFilterDisplayItems") or []):
        name = item.get("displayName")
        if isinstance(name, str) and name:
            jp = (visualname, "cachedFilterDisplayItems", i, "displayName")
            output_set.add(("", name, "VisualFilter:CachedDisplayName",
                            None, None, jp, json.dumps(name, ensure_ascii=False)))


def crawl_cached_filter_ids(config_json, output_set, alias_map=None,
                            visualname=None):
    """
    Emit cached filter id literals.
    Emits 7-tuples: (Table, Field, "VisualFilter:CachedId", None, None, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    sv = (config_json.get(visualname) or {})
    items = sv.get("cachedFilterDisplayItems") or []
    for i, item in enumerate(items):
        comp = (((item.get("id") or {}).get("scopeId") or {})
                .get("Comparison") or {})
        lit = ((comp.get("Right") or {}).get("Literal") or {}).get("Value")
        if isinstance(lit, str) and lit.strip():
            table, field = _parse_filter_handle(lit)
            jp = (visualname, "cachedFilterDisplayItems", i,
                  "id", "scopeId", "Comparison", "Right", "Literal", "Value")
            output_set.add((table, field, "VisualFilter:CachedId", None, None,
                            jp, json.dumps(field, ensure_ascii=False)))


def crawl_visual_selector_objects(config_json, alias_map, output_list,
                                  visualname=None):
    """
    Walk objects.dataPoint selectors and emit formatting literals.
    Emits 6-tuples: (Table, Field, "Formatting (Hardcoded Value Selector)", Value, JsonPath, OriginalJson)
    """
    if visualname is None:
        visualname = "visual"
    selector_blocks = (config_json.get(visualname, {})
                       .get("objects", {})
                       .get("dataPoint", []))

    for i, obj in enumerate(selector_blocks):
        data_entries = obj.get("selector", {}).get("data", [])
        for j, entry in enumerate(data_entries):
            json_path = (visualname, "objects", "dataPoint", i,
                         "selector", "data", j)
            original_fragment = json.dumps(entry, ensure_ascii=False)

            comparison = entry.get("scopeId", {}).get("Comparison", {})
            left = comparison.get("Left", {})
            right = comparison.get("Right", {})

            if "Column" in left:
                col = left["Column"]
                entity = (col.get("Expression", {})
                          .get("SourceRef", {})
                          .get("Entity"))
                prop = col.get("Property")
                resolved = alias_map.get(entity, entity) if alias_map else entity

                value = None
                if "Literal" in right:
                    value = right["Literal"].get("Value", "").strip("'")

                if resolved and prop:
                    output_list.append((resolved, prop,
                                        "Formatting (Hardcoded Value Selector)",
                                        value, json_path, original_fragment))


# ---------------------------------------------------------------------------
# Orchestration — run all crawlers on a single visual
# ---------------------------------------------------------------------------

def crawl_visual_all(config_json: dict, visualname: str = "visual") -> dict:
    """
    Run ALL crawlers on a single adapted visual config and return categorized results.

    Args:
        config_json: Visual config dict (after adapt_pbir_to_legacy)
        visualname: Key under which visual data lives ("visual" for PBIR)

    Returns:
        Dict with category -> list of tuples
    """
    alias_to_table = build_alias_table_mapping(config_json, visualname)
    sv = config_json.get(visualname, {}) or {}
    proto = sv.get("prototypeQuery", {}) or {}

    results = {
        "config": _Bag(),
        "filters": _Bag(),
        "field_parameters": _Bag(),
        "order_by": _Bag(),
        "native_calcs": _Bag(),
        "column_formatting": _Bag(),
        "values_formatting": _Bag(),
        "hierarchy_levels": _Bag(),
        "projections": _Bag(),
        "projections_category": _Bag(),
        "prototype_query_select": _Bag(),
        "column_properties_labels": _Bag(),
        "slicer_sync_group": _Bag(),
        "native_refnames": _Bag(),
        "column_widths": _Bag(),
        "expansion_queryrefs": _Bag(),
        "scope_selectors": _Bag(),
        "datapoint_selectors": _Bag(),
        "reference_lines": _Bag(),
        "cached_filter_display_items": _Bag(),
        "cached_filter_ids": _Bag(),
        "visual_selector_objects": _BagList(),
    }

    crawl_config(config_json, alias_to_table, results["config"],
                 source="Binding", visualname=visualname)
    crawl_field_parameters(config_json, results["field_parameters"],
                           visualname=visualname)
    crawl_order_by(proto, alias_to_table, results["order_by"],
                   visualname=visualname)
    crawl_column_formatting(config_json, alias_to_table,
                            results["column_formatting"],
                            visualname=visualname)
    crawl_values_formatting(config_json, alias_to_table,
                            results["values_formatting"],
                            visualname=visualname)
    crawl_hierarchy_levels(config_json, results["hierarchy_levels"],
                           alias_to_table, visualname=visualname)
    crawl_projections(config_json, results["projections"],
                      alias_to_table, visualname=visualname)
    crawl_projections_category(config_json, results["projections_category"],
                               alias_to_table, visualname=visualname)
    crawl_prototype_query_select(config_json, results["prototype_query_select"],
                                 alias_to_table, visualname=visualname)
    crawl_native_calcs(proto.get("Select", []), alias_to_table,
                       results["native_calcs"], source="Binding")
    crawl_native_calcs(proto.get("OrderBy", []), alias_to_table,
                       results["native_calcs"], source="OrderBy",
                       path=[visualname, "prototypeQuery", "OrderBy"])
    crawl_column_properties_labels(config_json, results["column_properties_labels"],
                                   alias_to_table, visualname=visualname)
    crawl_slicer_sync_group(config_json, results["slicer_sync_group"],
                            visualname=visualname)
    crawl_select_native_refnames(config_json, results["native_refnames"],
                                 visualname=visualname)
    crawl_objects_column_width(config_json, results["column_widths"],
                               alias_to_table, visualname=visualname)
    crawl_expansion_queryrefs(config_json, results["expansion_queryrefs"],
                              alias_to_table, visualname=visualname)
    crawl_objects_scope_selectors(config_json, results["scope_selectors"],
                                  alias_to_table, visualname=visualname)
    crawl_datapoint_selectors(config_json, results["datapoint_selectors"],
                              alias_to_table, visualname=visualname)
    crawl_reference_lines(config_json, results["reference_lines"],
                          alias_to_table, visualname=visualname)
    crawl_cached_filter_display_items(config_json,
                                      results["cached_filter_display_items"],
                                      visualname=visualname)
    crawl_cached_filter_ids(config_json, results["cached_filter_ids"],
                            alias_to_table, visualname=visualname)
    crawl_visual_selector_objects(config_json, alias_to_table,
                                  results["visual_selector_objects"],
                                  visualname=visualname)

    # Structured conditional formatting (dataBars, gradients, icons)
    results["conditional_formatting"] = crawl_conditional_formatting(
        config_json, alias_map=alias_to_table, visualname=visualname,
    )

    # Filters (from serialized JSON string)
    filters_raw = config_json.get("filters")
    if isinstance(filters_raw, str):
        try:
            filters_json = json.loads(filters_raw)
        except Exception:
            filters_json = []
    elif isinstance(filters_raw, list):
        filters_json = filters_raw
    else:
        filters_json = []

    for f in filters_json:
        crawl_filters(f, results["filters"], alias_to_table)

    # General filter objects (visual.objects.general[*].properties.filter)
    for i, gen in enumerate((sv.get("objects", {}).get("general", []) or [])):
        filt_block = (gen.get("properties", {}) or {}).get("filter", {})
        if isinstance(filt_block, dict) and "filter" in filt_block:
            crawl_filters(filt_block["filter"], results["filters"], alias_to_table,
                          path=[visualname, "objects", "general", i,
                                "properties", "filter", "filter"])

    return results


# ---------------------------------------------------------------------------
# Report-level crawl summary — walk entire PBIR report and count
# ---------------------------------------------------------------------------

def crawl_report_summary(report_dir: str) -> dict:
    """
    Walk a PBIR .Report directory and produce per-category row counts
    by running all crawlers on every visual.

    Returns:
        {
            "pages": int,
            "visuals_total": int,
            "per_visual": {vis_id: {category: count}},
            "totals": {category: total_count},
            "report_filters": int,
            "page_filters": {page_id: int},
            "bookmarks": int,
        }
    """
    pages_dir = os.path.join(report_dir, "definition", "pages")
    if not os.path.isdir(pages_dir):
        return {"error": f"Not a valid PBIR .Report directory: {report_dir}"}

    # Read report-level filters
    report_json_path = os.path.join(report_dir, "definition", "report.json")
    report_data = {}
    if os.path.isfile(report_json_path):
        try:
            with open(report_json_path, encoding="utf-8") as f:
                report_data = json.load(f)
        except Exception:
            pass
    report_filters = report_data.get("filterConfig", {}).get("filters", [])

    # Pages
    pages_json = os.path.join(pages_dir, "pages.json")
    page_order = []
    if os.path.isfile(pages_json):
        try:
            with open(pages_json, encoding="utf-8") as f:
                pdata = json.load(f)
            page_order = pdata.get("pageOrder", [])
        except Exception:
            pass
    if not page_order:
        page_order = [x for x in os.listdir(pages_dir)
                       if os.path.isdir(os.path.join(pages_dir, x))]

    per_visual = {}
    page_filters = {}
    totals = {}

    for page_id in page_order:
        page_dir = os.path.join(pages_dir, page_id)
        if not os.path.isdir(page_dir):
            continue

        # Page-level filters
        pj_path = os.path.join(page_dir, "page.json")
        if os.path.isfile(pj_path):
            try:
                with open(pj_path, encoding="utf-8") as f:
                    pj = json.load(f)
                pf = pj.get("filterConfig", {}).get("filters", [])
                if pf:
                    page_filters[page_id] = len(pf)
            except Exception:
                pass

        # Visuals
        visuals_dir = os.path.join(page_dir, "visuals")
        if not os.path.isdir(visuals_dir):
            continue

        for vis_folder in os.listdir(visuals_dir):
            vis_json_path = os.path.join(visuals_dir, vis_folder, "visual.json")
            if not os.path.isfile(vis_json_path):
                continue

            try:
                with open(vis_json_path, encoding="utf-8") as f:
                    vdata = json.load(f)

                # Adapt to legacy format for crawlers
                adapted = copy.deepcopy(vdata)
                adapt_pbir_to_legacy(adapted)

                # Pop filters to separate them (like notebook does)
                adapted.pop("filters", None)

                # Run all crawlers
                results = crawl_visual_all(adapted, visualname="visual")

                # Count per category
                vis_id = vdata.get("name", vis_folder)
                vis_counts = {}
                for cat, items in results.items():
                    count = len(items)
                    vis_counts[cat] = count
                    totals[cat] = totals.get(cat, 0) + count

                per_visual[vis_id] = vis_counts

            except Exception as e:
                per_visual[vis_folder] = {"error": str(e)}

    # Bookmarks (supports both flat files and subdirectory layout)
    bookmarks_dir = os.path.join(report_dir, "definition", "bookmarks")
    bookmark_count = 0
    if os.path.isdir(bookmarks_dir):
        for entry in os.listdir(bookmarks_dir):
            entry_path = os.path.join(bookmarks_dir, entry)
            if entry.endswith(".bookmark.json") and os.path.isfile(entry_path):
                # Flat layout: <id>.bookmark.json
                bookmark_count += 1
            elif os.path.isdir(entry_path):
                # Subdirectory layout: <id>/bookmark.json
                bk_json = os.path.join(entry_path, "bookmark.json")
                if os.path.isfile(bk_json):
                    bookmark_count += 1

    return {
        "pages": len(page_order),
        "visuals_total": len(per_visual),
        "per_visual": per_visual,
        "totals": totals,
        "report_filters": len(report_filters),
        "page_filters": page_filters,
        "bookmarks": bookmark_count,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python report_crawlers.py <PBIR .Report directory>")
        sys.exit(1)

    report_dir = sys.argv[1]
    print(f"Crawling: {report_dir}")
    summary = crawl_report_summary(report_dir)

    if "error" in summary:
        print(f"Error: {summary['error']}")
        sys.exit(1)

    print(f"\nPages: {summary['pages']}")
    print(f"Visuals: {summary['visuals_total']}")
    print(f"Report filters: {summary['report_filters']}")
    print(f"Page filters: {sum(summary['page_filters'].values())}")
    print(f"Bookmarks: {summary['bookmarks']}")

    print(f"\n{'Category':<35s} {'Count':>6s}")
    print("-" * 42)
    for cat, count in sorted(summary["totals"].items()):
        print(f"  {cat:<33s} {count:>6d}")

    total_rows = sum(summary["totals"].values())
    print(f"\n  {'TOTAL':<33s} {total_rows:>6d}")
