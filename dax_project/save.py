from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, MutableMapping, MutableSequence, Optional


def _sorted_filter_items(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def _k(x: Mapping[str, Any]) -> tuple:
        col = x.get("column") if isinstance(x.get("column"), Mapping) else {}
        table = str(col.get("table") or "")
        column = str(col.get("column") or "")
        op = str(x.get("operator") or "")
        keep = bool(x.get("keep") or False)
        target = str(x.get("target") or "")
        values = x.get("values")
        try:
            vkey = str(values)
        except Exception:
            vkey = ""
        return (str(x.get("scope") or ""), target, table, column, op, keep, vkey)

    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, Mapping):
            out.append(dict(it))
    out.sort(key=_k)
    return out


def _canonicalize_filter_item(item: Mapping[str, Any], *, scope: str, target: Optional[str]) -> dict[str, Any]:
    # Keep this minimal and stable for diffs. Drop ephemeral fields like 'id'.
    col = item.get("column")
    if not isinstance(col, Mapping):
        raise ValueError("filter.column must be an object")

    col_type = str(col.get("type") or "ColumnRef").strip()

    # MeasureRef filters (e.g. "exists" measure filters from PBI) use 'name'
    # instead of 'column'. Preserve them as-is — they are skipped at render
    # time but remain visible in the UI for debugging.
    if col_type == "MeasureRef":
        out: dict[str, Any] = {
            "scope": scope,
            "target": target,
            "column": {
                "type": "MeasureRef",
                "table": str(col.get("table") or ""),
                "name": str(col.get("name") or ""),
            },
            "operator": str(item.get("operator") or "").strip() or "exists",
        }
        if item.get("filter_type"):
            out["filter_type"] = str(item["filter_type"])
        return out

    # HierarchyRef filters reference a hierarchy level (e.g. Date hierarchy → Jahr).
    # They have _source_table and _level instead of table/column.
    # Preserve as-is — skipped at render time, visible in UI for debugging.
    if col_type == "HierarchyRef":
        out = {
            "scope": scope,
            "target": target,
            "column": {
                "type": "HierarchyRef",
                "name": str(col.get("name") or ""),
                "_source_table": str(col.get("_source_table") or ""),
                "_level": str(col.get("_level") or ""),
            },
            "operator": str(item.get("operator") or "").strip() or "exists",
        }
        if item.get("filter_type"):
            out["filter_type"] = str(item["filter_type"])
        return out

    out = {
        "scope": scope,
        "target": target,
        "keep": bool(item.get("keep") or False),
        "column": {"type": "ColumnRef", "table": str(col.get("table") or ""), "column": str(col.get("column") or "")},
        "operator": str(item.get("operator") or "").strip(),
        "values": list(item.get("values") or []),
    }
    if not out["column"]["table"] or not out["column"]["column"]:
        raise ValueError("filter.column.table and filter.column.column are required")
    if not out["operator"]:
        raise ValueError("filter.operator is required")
    if out["values"] is None:
        out["values"] = []
    if not isinstance(out["values"], list):
        out["values"] = [out["values"]]
    # Preserve filter_type for UI display
    if item.get("filter_type"):
        out["filter_type"] = str(item["filter_type"])
    return out


def load_report_filters(project_path: str) -> dict[str, Any]:
    """Load persisted report/page/visual filters from <project>/reports/filters.yaml.

    Returns canonical shape:
      {"report_filters": [...], "page_filters": {page_id: [...]}, "visual_filters": {visual_id: [...]}}
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "reports" / "filters.yaml"
    raw = _load_yaml(path)
    if raw is None:
        return {"report_filters": [], "page_filters": {}, "visual_filters": {}}
    if not isinstance(raw, Mapping):
        raise ValueError("reports/filters.yaml must be a mapping")

    report_filters = raw.get("report_filters")
    page_filters = raw.get("page_filters")
    visual_filters = raw.get("visual_filters")

    if report_filters is None:
        report_filters = []
    if page_filters is None:
        page_filters = {}
    if visual_filters is None:
        visual_filters = {}

    if not isinstance(report_filters, list):
        raise ValueError("report_filters must be a list")
    if not isinstance(page_filters, Mapping):
        raise ValueError("page_filters must be a mapping")
    if not isinstance(visual_filters, Mapping):
        raise ValueError("visual_filters must be a mapping")

    # Canonicalize/normalize.
    out_report: list[dict[str, Any]] = []
    for it in report_filters:
        if not isinstance(it, Mapping):
            continue
        out_report.append(_canonicalize_filter_item(it, scope="report", target=None))

    out_pages: dict[str, list[dict[str, Any]]] = {}
    for k, v in page_filters.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if not isinstance(v, list):
            continue
        items: list[dict[str, Any]] = []
        for it in v:
            if not isinstance(it, Mapping):
                continue
            items.append(_canonicalize_filter_item(it, scope="page", target=k))
        out_pages[k] = items

    out_visuals: dict[str, list[dict[str, Any]]] = {}
    for k, v in visual_filters.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if not isinstance(v, list):
            continue
        items = []
        for it in v:
            if not isinstance(it, Mapping):
                continue
            items.append(_canonicalize_filter_item(it, scope="visual", target=k))
        out_visuals[k] = items

    out_report = _sorted_filter_items(out_report)
    out_pages = {k: _sorted_filter_items(v) for k, v in sorted(out_pages.items(), key=lambda kv: kv[0].upper())}
    out_visuals = {k: _sorted_filter_items(v) for k, v in sorted(out_visuals.items(), key=lambda kv: kv[0].upper())}

    return {"report_filters": out_report, "page_filters": out_pages, "visual_filters": out_visuals}


def save_report_filters(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist canonical report/page/visual filters to <project>/reports/filters.yaml.

    Returns the canonical normalized payload written.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "filters.yaml"

    # Accept either canonical separated shape, or a flat 'filters' list.
    if isinstance(payload.get("filters"), list):
        flat = payload.get("filters") or []
        report_filters: list[Any] = []
        page_filters: dict[str, list[Any]] = {}
        visual_filters: dict[str, list[Any]] = {}
        for it in flat:
            if not isinstance(it, Mapping):
                continue
            scope = str(it.get("scope") or "").strip().lower()
            tgt = it.get("target")
            tgt_s = str(tgt).strip() if isinstance(tgt, str) and tgt.strip() else None
            if scope == "report":
                report_filters.append(it)
            elif scope == "page" and tgt_s:
                page_filters.setdefault(tgt_s, []).append(it)
            elif scope == "visual" and tgt_s:
                visual_filters.setdefault(tgt_s, []).append(it)
        payload = {"report_filters": report_filters, "page_filters": page_filters, "visual_filters": visual_filters}

    report_in = payload.get("report_filters") or []
    page_in = payload.get("page_filters") or {}
    vis_in = payload.get("visual_filters") or {}

    if not isinstance(report_in, list):
        raise ValueError("report_filters must be a list")
    if not isinstance(page_in, Mapping):
        raise ValueError("page_filters must be a mapping")
    if not isinstance(vis_in, Mapping):
        raise ValueError("visual_filters must be a mapping")

    out_report: list[dict[str, Any]] = []
    for it in report_in:
        if not isinstance(it, Mapping):
            continue
        out_report.append(_canonicalize_filter_item(it, scope="report", target=None))

    out_pages: dict[str, list[dict[str, Any]]] = {}
    for pid, items in page_in.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(items, list):
            continue
        out_pages[pid] = [
            _canonicalize_filter_item(it, scope="page", target=pid)
            for it in items
            if isinstance(it, Mapping)
        ]

    out_visuals: dict[str, list[dict[str, Any]]] = {}
    for vid, items in vis_in.items():
        if not isinstance(vid, str) or not vid.strip():
            continue
        if not isinstance(items, list):
            continue
        out_visuals[vid] = [
            _canonicalize_filter_item(it, scope="visual", target=vid)
            for it in items
            if isinstance(it, Mapping)
        ]

    canon = {
        "report_filters": _sorted_filter_items(out_report),
        "page_filters": {k: _sorted_filter_items(v) for k, v in sorted(out_pages.items(), key=lambda kv: kv[0].upper())},
        "visual_filters": {k: _sorted_filter_items(v) for k, v in sorted(out_visuals.items(), key=lambda kv: kv[0].upper())},
    }

    _dump_yaml(path, canon)
    return canon


# === Calculation group selections (Phase 2.1) ===


def _sorted_calc_group_selection_items(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def _k(x: Mapping[str, Any]) -> tuple:
        scope = str(x.get("scope") or "")
        target = str(x.get("target") or "")
        group = str(x.get("group") or "")
        item = str(x.get("item") or "")
        return (scope, target.upper(), group.upper(), item.upper())

    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, Mapping):
            out.append(dict(it))
    out.sort(key=_k)
    return out


def _canonicalize_calc_group_selection_item(
    item: Mapping[str, Any], *, scope: str, target: Optional[str]
) -> dict[str, Any]:
    group = str(item.get("group") or "").strip()
    sel = str(item.get("item") or "").strip()
    if not group:
        raise ValueError("calc_group_selection.group is required")
    if not sel:
        raise ValueError("calc_group_selection.item is required")
    return {"scope": scope, "target": target, "group": group, "item": sel}


def load_calc_group_selections(project_path: str) -> dict[str, Any]:
    """Load persisted calc-group selections from <project>/reports/calc_group_selections.yaml.

    Canonical shape:
      {
        "report": {group: item, ...},
        "page": {page_id: {group: item, ...}},
        "visual": {visual_id: {group: item, ...}},
      }
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "reports" / "calc_group_selections.yaml"
    raw = _load_yaml(path)
    if raw is None:
        return {"report": {}, "page": {}, "visual": {}}
    if not isinstance(raw, Mapping):
        raise ValueError("reports/calc_group_selections.yaml must be a mapping")

    report = raw.get("report") or {}
    page = raw.get("page") or {}
    visual = raw.get("visual") or {}

    if not isinstance(report, Mapping):
        raise ValueError("calc_group_selections.report must be a mapping")
    if not isinstance(page, Mapping):
        raise ValueError("calc_group_selections.page must be a mapping")
    if not isinstance(visual, Mapping):
        raise ValueError("calc_group_selections.visual must be a mapping")

    out_report: dict[str, str] = {}
    for k, v in report.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if not isinstance(v, str) or not v.strip():
            continue
        out_report[k.strip()] = v.strip()

    out_page: dict[str, dict[str, str]] = {}
    for pid, m in page.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, str] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if not isinstance(v, str) or not v.strip():
                continue
            inner[k.strip()] = v.strip()
        if inner:
            out_page[pid.strip()] = inner

    out_visual: dict[str, dict[str, str]] = {}
    for vid, m in visual.items():
        if not isinstance(vid, str) or not vid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, str] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if not isinstance(v, str) or not v.strip():
                continue
            inner[k.strip()] = v.strip()
        if inner:
            out_visual[vid.strip()] = inner

    # Deterministic ordering.
    out_report = {k: out_report[k] for k in sorted(out_report.keys(), key=lambda s: s.upper())}
    out_page = {k: out_page[k] for k in sorted(out_page.keys(), key=lambda s: s.upper())}
    out_visual = {k: out_visual[k] for k in sorted(out_visual.keys(), key=lambda s: s.upper())}
    for k in list(out_page.keys()):
        inner = out_page[k]
        out_page[k] = {g: inner[g] for g in sorted(inner.keys(), key=lambda s: s.upper())}
    for k in list(out_visual.keys()):
        inner = out_visual[k]
        out_visual[k] = {g: inner[g] for g in sorted(inner.keys(), key=lambda s: s.upper())}

    return {"report": out_report, "page": out_page, "visual": out_visual}


def save_calc_group_selections(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist canonical calc-group selections to <project>/reports/calc_group_selections.yaml.

    Accepts either:
    - canonical nested mapping shape (report/page/visual)
    - flat list under key "selections": [{scope,target,group,item}, ...]

    Returns canonical normalized payload written.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "calc_group_selections.yaml"

    if isinstance(payload.get("selections"), list):
        flat = payload.get("selections") or []
        report: dict[str, str] = {}
        page: dict[str, dict[str, str]] = {}
        visual: dict[str, dict[str, str]] = {}
        for it in flat:
            if not isinstance(it, Mapping):
                continue
            scope = str(it.get("scope") or "").strip().lower()
            tgt = it.get("target")
            tgt_s = str(tgt).strip() if isinstance(tgt, str) and tgt.strip() else None
            group = str(it.get("group") or "").strip()
            item = str(it.get("item") or "").strip()
            if not scope or not group or not item:
                continue
            if scope == "report":
                report[group] = item
            elif scope == "page" and tgt_s:
                page.setdefault(tgt_s, {})[group] = item
            elif scope == "visual" and tgt_s:
                visual.setdefault(tgt_s, {})[group] = item
        payload = {"report": report, "page": page, "visual": visual}

    report_in = payload.get("report") or {}
    page_in = payload.get("page") or {}
    visual_in = payload.get("visual") or {}

    if not isinstance(report_in, Mapping):
        raise ValueError("calc_group_selections.report must be a mapping")
    if not isinstance(page_in, Mapping):
        raise ValueError("calc_group_selections.page must be a mapping")
    if not isinstance(visual_in, Mapping):
        raise ValueError("calc_group_selections.visual must be a mapping")

    out_report: dict[str, str] = {}
    for g, it in report_in.items():
        if not isinstance(g, str) or not g.strip():
            continue
        if not isinstance(it, str) or not it.strip():
            continue
        out_report[g.strip()] = it.strip()

    out_page: dict[str, dict[str, str]] = {}
    for pid, m in page_in.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, str] = {}
        for g, it in m.items():
            if not isinstance(g, str) or not g.strip():
                continue
            if not isinstance(it, str) or not it.strip():
                continue
            inner[g.strip()] = it.strip()
        if inner:
            out_page[pid.strip()] = inner

    out_visual: dict[str, dict[str, str]] = {}
    for vid, m in visual_in.items():
        if not isinstance(vid, str) or not vid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, str] = {}
        for g, it in m.items():
            if not isinstance(g, str) or not g.strip():
                continue
            if not isinstance(it, str) or not it.strip():
                continue
            inner[g.strip()] = it.strip()
        if inner:
            out_visual[vid.strip()] = inner

    # Deterministic ordering.
    out_report = {k: out_report[k] for k in sorted(out_report.keys(), key=lambda s: s.upper())}
    out_page = {k: out_page[k] for k in sorted(out_page.keys(), key=lambda s: s.upper())}
    out_visual = {k: out_visual[k] for k in sorted(out_visual.keys(), key=lambda s: s.upper())}
    for k in list(out_page.keys()):
        inner = out_page[k]
        out_page[k] = {g: inner[g] for g in sorted(inner.keys(), key=lambda s: s.upper())}
    for k in list(out_visual.keys()):
        inner = out_visual[k]
        out_visual[k] = {g: inner[g] for g in sorted(inner.keys(), key=lambda s: s.upper())}

    canon = {"report": out_report, "page": out_page, "visual": out_visual}
    _dump_yaml(path, canon)
    return canon


def flatten_calc_group_selections(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    report = payload.get("report") or {}
    page = payload.get("page") or {}
    visual = payload.get("visual") or {}
    if isinstance(report, Mapping):
        for g, it in report.items():
            if isinstance(g, str) and g.strip() and isinstance(it, str) and it.strip():
                flat.append({"scope": "report", "target": None, "group": g.strip(), "item": it.strip()})
    if isinstance(page, Mapping):
        for pid, m in page.items():
            if not isinstance(pid, str) or not pid.strip() or not isinstance(m, Mapping):
                continue
            for g, it in m.items():
                if isinstance(g, str) and g.strip() and isinstance(it, str) and it.strip():
                    flat.append({"scope": "page", "target": pid.strip(), "group": g.strip(), "item": it.strip()})
    if isinstance(visual, Mapping):
        for vid, m in visual.items():
            if not isinstance(vid, str) or not vid.strip() or not isinstance(m, Mapping):
                continue
            for g, it in m.items():
                if isinstance(g, str) and g.strip() and isinstance(it, str) and it.strip():
                    flat.append({"scope": "visual", "target": vid.strip(), "group": g.strip(), "item": it.strip()})
    return _sorted_calc_group_selection_items(flat)


def resolve_effective_calc_group_selections(
    payload: Mapping[str, Any], *, page_id: Optional[str], visual_id: Optional[str]
) -> dict[str, str]:
    """Resolve effective selections for a given (page_id, visual_id).

    Precedence: report -> page -> visual.
    """

    out: dict[str, str] = {}
    report = payload.get("report")
    if isinstance(report, Mapping):
        for g, it in report.items():
            if isinstance(g, str) and g.strip() and isinstance(it, str) and it.strip():
                out[g.strip()] = it.strip()

    if isinstance(page_id, str) and page_id.strip():
        page = payload.get("page")
        if isinstance(page, Mapping):
            page_map = page.get(page_id)
            if isinstance(page_map, Mapping):
                for g, it in page_map.items():
                    if isinstance(g, str) and g.strip() and isinstance(it, str) and it.strip():
                        out[g.strip()] = it.strip()

    if isinstance(visual_id, str) and visual_id.strip():
        visual = payload.get("visual")
        if isinstance(visual, Mapping):
            vis_map = visual.get(visual_id)
            if isinstance(vis_map, Mapping):
                for g, it in vis_map.items():
                    if isinstance(g, str) and g.strip() and isinstance(it, str) and it.strip():
                        out[g.strip()] = it.strip()

    return out


def _sorted_field_parameter_selection_items(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def _k(x: Mapping[str, Any]) -> tuple:
        scope = str(x.get("scope") or "")
        target = str(x.get("target") or "")
        param = str(x.get("param") or "")
        value = str(x.get("value") or "")
        return (scope, target.upper(), param.upper(), value.upper())

    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, Mapping):
            out.append(dict(it))
    out.sort(key=_k)
    return out


def load_field_parameter_selections(project_path: str) -> dict[str, Any]:
    """Load persisted field parameter selections from <project>/reports/field_parameter_selections.yaml.

    Canonical v2 shape:
      {
        "report": {param: {selected_item_name|selected_item_names}, ...},
        "page": {page_id: {param: {..}, ...}},
        "visual": {visual_id: {param: {..}, ...}},
      }

    Back-compat accepted on disk:
    - leaf string: treated as {selected_item_name: <string>}
    - leaf list[str]: treated as {selected_item_names: [...]}
    """

    def _canon_leaf(v: Any) -> Optional[dict[str, Any]]:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            return {"selected_item_name": s}

        if isinstance(v, list):
            items: list[str] = []
            seen: set[str] = set()
            for it in v:
                if not isinstance(it, str) or not it.strip():
                    continue
                k = it.strip()
                key = k.upper()
                if key in seen:
                    continue
                seen.add(key)
                items.append(k)
            if not items:
                return None
            return {"selected_item_names": items}

        if isinstance(v, Mapping):
            one = v.get("selected_item_name")
            many = v.get("selected_item_names")
            # Accept a few legacy/alternate field names for resilience.
            if many is None and isinstance(v.get("values"), list):
                many = v.get("values")
            if one is None and isinstance(v.get("value"), str):
                one = v.get("value")

            if many is not None:
                if not isinstance(many, list):
                    raise ValueError("field_parameter selection.selected_item_names must be a list")
                return _canon_leaf(list(many))
            if one is not None:
                if not isinstance(one, str):
                    raise ValueError("field_parameter selection.selected_item_name must be a string")
                return _canon_leaf(str(one))
            return None

        return None

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "reports" / "field_parameter_selections.yaml"
    raw = _load_yaml(path)
    if raw is None:
        return {"report": {}, "page": {}, "visual": {}}
    if not isinstance(raw, Mapping):
        raise ValueError("reports/field_parameter_selections.yaml must be a mapping")

    report = raw.get("report") or {}
    page = raw.get("page") or {}
    visual = raw.get("visual") or {}

    if not isinstance(report, Mapping):
        raise ValueError("field_parameter_selections.report must be a mapping")
    if not isinstance(page, Mapping):
        raise ValueError("field_parameter_selections.page must be a mapping")
    if not isinstance(visual, Mapping):
        raise ValueError("field_parameter_selections.visual must be a mapping")

    out_report: dict[str, Any] = {}
    for k, v in report.items():
        if not isinstance(k, str) or not k.strip():
            continue
        leaf = _canon_leaf(v)
        if leaf is None:
            continue
        out_report[k.strip()] = leaf

    out_page: dict[str, dict[str, Any]] = {}
    for pid, m in page.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, Any] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                continue
            leaf = _canon_leaf(v)
            if leaf is None:
                continue
            inner[k.strip()] = leaf
        if inner:
            out_page[pid.strip()] = inner

    out_visual: dict[str, dict[str, Any]] = {}
    for vid, m in visual.items():
        if not isinstance(vid, str) or not vid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, Any] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                continue
            leaf = _canon_leaf(v)
            if leaf is None:
                continue
            inner[k.strip()] = leaf
        if inner:
            out_visual[vid.strip()] = inner

    # Deterministic ordering.
    out_report = {k: out_report[k] for k in sorted(out_report.keys(), key=lambda s: s.upper())}
    out_page = {k: out_page[k] for k in sorted(out_page.keys(), key=lambda s: s.upper())}
    out_visual = {k: out_visual[k] for k in sorted(out_visual.keys(), key=lambda s: s.upper())}
    for k in list(out_page.keys()):
        inner = out_page[k]
        out_page[k] = {p: inner[p] for p in sorted(inner.keys(), key=lambda s: s.upper())}
    for k in list(out_visual.keys()):
        inner = out_visual[k]
        out_visual[k] = {p: inner[p] for p in sorted(inner.keys(), key=lambda s: s.upper())}

    return {"report": out_report, "page": out_page, "visual": out_visual}


def save_field_parameter_selections(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist canonical field parameter selections to <project>/reports/field_parameter_selections.yaml.

    Accepts either:
    - canonical nested mapping shape (report/page/visual) where leaf values may be:
      - string (legacy)
      - list[str] (multi-select)
      - object with selected_item_name / selected_item_names
    - flat list under key "selections":
      [{scope,target,param,value|values|selected_item_name|selected_item_names}, ...]

    Returns canonical normalized payload written.
    """

    def _canon_leaf(v: Any) -> Optional[dict[str, Any]]:
        # Mirror loader canonicalization.
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            return {"selected_item_name": s}
        if isinstance(v, list):
            items: list[str] = []
            seen: set[str] = set()
            for it in v:
                if not isinstance(it, str) or not it.strip():
                    continue
                k = it.strip()
                key = k.upper()
                if key in seen:
                    continue
                seen.add(key)
                items.append(k)
            if not items:
                return None
            return {"selected_item_names": items}
        if isinstance(v, Mapping):
            if "selected_item_names" in v or "values" in v:
                many = v.get("selected_item_names") if "selected_item_names" in v else v.get("values")
                return _canon_leaf(many)
            if "selected_item_name" in v or "value" in v:
                one = v.get("selected_item_name") if "selected_item_name" in v else v.get("value")
                return _canon_leaf(one)
        return None

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "field_parameter_selections.yaml"

    if isinstance(payload.get("selections"), list):
        flat = payload.get("selections") or []
        report: dict[str, Any] = {}
        page: dict[str, dict[str, Any]] = {}
        visual: dict[str, dict[str, Any]] = {}
        for it in flat:
            if not isinstance(it, Mapping):
                continue
            scope = str(it.get("scope") or "").strip().lower()
            tgt = it.get("target")
            tgt_s = str(tgt).strip() if isinstance(tgt, str) and tgt.strip() else None
            param = str(it.get("param") or "").strip()
            leaf = _canon_leaf(
                it.get("selected_item_names")
                if "selected_item_names" in it
                else it.get("selected_item_name")
                if "selected_item_name" in it
                else it.get("values")
                if "values" in it
                else it.get("value")
            )
            if not scope or not param or leaf is None:
                continue
            if scope == "report":
                report[param] = leaf
            elif scope == "page" and tgt_s:
                page.setdefault(tgt_s, {})[param] = leaf
            elif scope == "visual" and tgt_s:
                visual.setdefault(tgt_s, {})[param] = leaf
        payload = {"report": report, "page": page, "visual": visual}

    report_in = payload.get("report") or {}
    page_in = payload.get("page") or {}
    visual_in = payload.get("visual") or {}

    if not isinstance(report_in, Mapping):
        raise ValueError("field_parameter_selections.report must be a mapping")
    if not isinstance(page_in, Mapping):
        raise ValueError("field_parameter_selections.page must be a mapping")
    if not isinstance(visual_in, Mapping):
        raise ValueError("field_parameter_selections.visual must be a mapping")

    out_report: dict[str, Any] = {}
    for p, v in report_in.items():
        if not isinstance(p, str) or not p.strip():
            continue
        leaf = _canon_leaf(v)
        if leaf is None:
            continue
        out_report[p.strip()] = leaf

    out_page: dict[str, dict[str, Any]] = {}
    for pid, m in page_in.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, Any] = {}
        for p, v in m.items():
            if not isinstance(p, str) or not p.strip():
                continue
            leaf = _canon_leaf(v)
            if leaf is None:
                continue
            inner[p.strip()] = leaf
        if inner:
            out_page[pid.strip()] = inner

    out_visual: dict[str, dict[str, Any]] = {}
    for vid, m in visual_in.items():
        if not isinstance(vid, str) or not vid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, Any] = {}
        for p, v in m.items():
            if not isinstance(p, str) or not p.strip():
                continue
            leaf = _canon_leaf(v)
            if leaf is None:
                continue
            inner[p.strip()] = leaf
        if inner:
            out_visual[vid.strip()] = inner

    # Deterministic ordering.
    out_report = {k: out_report[k] for k in sorted(out_report.keys(), key=lambda s: s.upper())}
    out_page = {k: out_page[k] for k in sorted(out_page.keys(), key=lambda s: s.upper())}
    out_visual = {k: out_visual[k] for k in sorted(out_visual.keys(), key=lambda s: s.upper())}
    for k in list(out_page.keys()):
        inner = out_page[k]
        out_page[k] = {p: inner[p] for p in sorted(inner.keys(), key=lambda s: s.upper())}
    for k in list(out_visual.keys()):
        inner = out_visual[k]
        out_visual[k] = {p: inner[p] for p in sorted(inner.keys(), key=lambda s: s.upper())}

    canon = {"report": out_report, "page": out_page, "visual": out_visual}
    _dump_yaml(path, canon)
    return canon


def flatten_field_parameter_selections(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    def _values_from_leaf(v: Any) -> list[str]:
        if isinstance(v, str):
            s = v.strip()
            return [s] if s else []
        if isinstance(v, Mapping):
            if isinstance(v.get("selected_item_names"), list):
                return [str(x).strip() for x in v.get("selected_item_names") if isinstance(x, str) and str(x).strip()]
            if isinstance(v.get("selected_item_name"), str) and str(v.get("selected_item_name")).strip():
                return [str(v.get("selected_item_name")).strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v if isinstance(x, str) and str(x).strip()]
        return []

    flat: list[dict[str, Any]] = []
    report = payload.get("report") or {}
    page = payload.get("page") or {}
    visual = payload.get("visual") or {}
    if isinstance(report, Mapping):
        for p, v in report.items():
            if not (isinstance(p, str) and p.strip()):
                continue
            values = _values_from_leaf(v)
            if not values:
                continue
            flat.append(
                {
                    "scope": "report",
                    "target": None,
                    "param": p.strip(),
                    "value": values[0],
                    "values": values,
                    "is_multi": len(values) > 1,
                }
            )
    if isinstance(page, Mapping):
        for pid, m in page.items():
            if not isinstance(pid, str) or not pid.strip() or not isinstance(m, Mapping):
                continue
            for p, v in m.items():
                if not (isinstance(p, str) and p.strip()):
                    continue
                values = _values_from_leaf(v)
                if not values:
                    continue
                flat.append(
                    {
                        "scope": "page",
                        "target": pid.strip(),
                        "param": p.strip(),
                        "value": values[0],
                        "values": values,
                        "is_multi": len(values) > 1,
                    }
                )
    if isinstance(visual, Mapping):
        for vid, m in visual.items():
            if not isinstance(vid, str) or not vid.strip() or not isinstance(m, Mapping):
                continue
            for p, v in m.items():
                if not (isinstance(p, str) and p.strip()):
                    continue
                values = _values_from_leaf(v)
                if not values:
                    continue
                flat.append(
                    {
                        "scope": "visual",
                        "target": vid.strip(),
                        "param": p.strip(),
                        "value": values[0],
                        "values": values,
                        "is_multi": len(values) > 1,
                    }
                )
    return _sorted_field_parameter_selection_items(flat)


def resolve_effective_field_parameter_selections(
    payload: Mapping[str, Any], *, page_id: Optional[str], visual_id: Optional[str]
) -> dict[str, Any]:
    """Resolve effective field parameter selections for a given (page_id, visual_id).

    Precedence: report -> page -> visual.
    """

    def _values_from_leaf(v: Any) -> list[str]:
        if isinstance(v, str):
            s = v.strip()
            return [s] if s else []
        if isinstance(v, Mapping):
            many = v.get("selected_item_names")
            one = v.get("selected_item_name")
            if isinstance(many, list):
                return [str(x).strip() for x in many if isinstance(x, str) and str(x).strip()]
            if isinstance(one, str) and one.strip():
                return [one.strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v if isinstance(x, str) and str(x).strip()]
        return []

    def _set_leaf(param: str, leaf: Any) -> None:
        values = _values_from_leaf(leaf)
        if not values:
            return
        out[param] = values if len(values) > 1 else values[0]

    out: dict[str, Any] = {}
    report = payload.get("report")
    if isinstance(report, Mapping):
        for p, v in report.items():
            if isinstance(p, str) and p.strip():
                _set_leaf(p.strip(), v)

    if isinstance(page_id, str) and page_id.strip():
        page = payload.get("page")
        if isinstance(page, Mapping):
            page_map = page.get(page_id)
            if isinstance(page_map, Mapping):
                for p, v in page_map.items():
                    if isinstance(p, str) and p.strip():
                        _set_leaf(p.strip(), v)

    if isinstance(visual_id, str) and visual_id.strip():
        visual = payload.get("visual")
        if isinstance(visual, Mapping):
            vis_map = visual.get(visual_id)
            if isinstance(vis_map, Mapping):
                for p, v in vis_map.items():
                    if isinstance(p, str) and p.strip():
                        _set_leaf(p.strip(), v)

    return out


def _norm_key(s: str) -> str:
    return s.strip().upper()


def _load_yaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to save project YAML files. Please install 'pyyaml'.") from exc

    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _dump_yaml(path: Path, obj: Any) -> None:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to save project YAML files. Please install 'pyyaml'.") from exc

    text = yaml.safe_dump(
        obj,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    # Atomic write: write to a temp file and replace.
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _sorted_slicer_defs(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def _k(x: Mapping[str, Any]) -> tuple:
        col = x.get("column") if isinstance(x.get("column"), Mapping) else {}
        table = str(col.get("table") or "")
        column = str(col.get("column") or "")
        name = str(x.get("name") or "")
        scope = str(x.get("scope") or "")
        target = str(x.get("target") or "")
        sid = str(x.get("id") or "")
        return (scope, target.upper(), name.upper(), table.upper(), column.upper(), sid.upper())

    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, Mapping):
            out.append(dict(it))
    out.sort(key=_k)
    return out


def _canonicalize_slicer_defaults(defaults_raw: Any, *, slicer_type: str) -> Optional[dict[str, Any]]:
    if defaults_raw is None:
        return None
    if not isinstance(defaults_raw, Mapping):
        raise ValueError("slicer_def.defaults must be an object")

    mode = str(defaults_raw.get("mode") or "none").strip().lower()
    if mode not in {"none", "measure", "measure_set"}:
        raise ValueError("slicer_def.defaults.mode must be 'none', 'measure', or 'measure_set'")

    apply_on_load_raw = defaults_raw.get("apply_on_load")
    if apply_on_load_raw is None:
        apply_on_load = False
    else:
        if not isinstance(apply_on_load_raw, bool):
            raise ValueError("slicer_def.defaults.apply_on_load must be a boolean")
        apply_on_load = bool(apply_on_load_raw)

    def _canon_meas(m: Any, *, path: str) -> dict[str, str]:
        if isinstance(m, str):
            name = m.strip()
        elif isinstance(m, Mapping):
            t = str(m.get("type") or "").strip()
            if t != "MeasureRef":
                raise ValueError(f"{path} must be a MeasureRef")
            name = str(m.get("name") or "").strip()
        else:
            raise ValueError(f"{path} must be a MeasureRef")
        if not name:
            raise ValueError(f"{path}.name is required")
        return {"type": "MeasureRef", "name": name}

    if mode == "none":
        # Keep files minimal: omit defaults when it has no effect.
        if apply_on_load:
            return {"mode": "none", "apply_on_load": True}
        return None

    # mode == "measure" or "measure_set"
    if str(slicer_type).strip().lower() in {"date_range", "relative_date", "relative_time"}:
        if mode != "measure":
            raise ValueError("slicer_def.defaults.mode must be 'measure' for date range slicers")
        dr_raw = defaults_raw.get("date_range")
        if dr_raw is None:
            dr_raw = {}
        if not isinstance(dr_raw, Mapping):
            raise ValueError("slicer_def.defaults.date_range must be an object")

        start_m_raw = dr_raw.get("start_measure")
        end_m_raw = dr_raw.get("end_measure")
        if start_m_raw is None and end_m_raw is None:
            raise ValueError("slicer_def.defaults.date_range.start_measure or end_measure is required")

        out_dr: dict[str, Any] = {}
        if start_m_raw is not None:
            out_dr["start_measure"] = _canon_meas(start_m_raw, path="slicer_def.defaults.date_range.start_measure")
        if end_m_raw is not None:
            out_dr["end_measure"] = _canon_meas(end_m_raw, path="slicer_def.defaults.date_range.end_measure")

        return {
            "mode": "measure",
            "apply_on_load": bool(apply_on_load),
            "date_range": out_dr,
        }

    meas_raw = defaults_raw.get("measure")
    if meas_raw is None:
        raise ValueError("slicer_def.defaults.measure is required when defaults.mode in ('measure', 'measure_set')")
    return {
        "mode": mode,
        "apply_on_load": bool(apply_on_load),
        "measure": _canon_meas(meas_raw, path="slicer_def.defaults.measure"),
    }


def _canonicalize_slicer_def(item: Mapping[str, Any]) -> dict[str, Any]:
    """Legacy canonicalize for old-format slicer definitions (scope/target).

    Used by compat wrappers and validation code that still passes old-format dicts.
    Internally converts to unified format and back.
    """
    # Convert to unified format first, then project back to legacy format
    unified = _canonicalize_unified_slicer(item)
    # Project back to legacy def format
    pages = unified.get("pages") or {}
    # Derive scope/target from pages
    scope = "page"
    target = None
    for pid, pcfg in pages.items():
        if pcfg.get("visible") or pcfg.get("sync"):
            target = pid
            break
    if not target:
        # If no pages have visible/sync, check for legacy scope
        scope_raw = str(item.get("scope") or "").strip().lower()
        if scope_raw == "report":
            scope = "report"
        else:
            scope = "page"
            target_raw = item.get("target")
            target = str(target_raw).strip() if isinstance(target_raw, str) and target_raw.strip() else None
    # If there's exactly 0 pages or all are sync'd, could be report scope
    scope_raw = str(item.get("scope") or "").strip().lower()
    if scope_raw == "report":
        scope = "report"
        target = None

    out: dict[str, Any] = {
        "id": unified["id"],
        "name": unified["name"],
        "title": unified.get("title", ""),
        "scope": scope,
        "target": target,
        "column": unified["column"],
        "type": unified["type"],
        "behavior": unified["behavior"],
        "selection": unified["selection"],
        "ui": unified["ui"],
    }
    if "defaults" in unified:
        out["defaults"] = unified["defaults"]
    if "sync_group" in unified:
        out["sync_group"] = unified["sync_group"]
    # Build sync_pages from pages dict
    if pages:
        sp: dict[str, dict[str, bool]] = {}
        for pid, pcfg in pages.items():
            sp[pid] = {"sync": bool(pcfg.get("sync", True)), "visible": bool(pcfg.get("visible", True))}
        out["sync_pages"] = sp
    return out


# ---------------------------------------------------------------------------
# Unified slicer model
# ---------------------------------------------------------------------------

_DEFAULT_SLICER_LAYOUT: dict[str, int] = {"x": 0, "y": 0, "w": 240, "h": 260}


def _canonicalize_slicer_page_entry(page_id: str, entry: Any) -> dict[str, Any]:
    """Canonicalize a per-page entry in a unified slicer."""
    if entry is None:
        return {"visible": True, "sync": True, "layout": dict(_DEFAULT_SLICER_LAYOUT)}
    if not isinstance(entry, Mapping):
        raise ValueError(f"slicer.pages[{page_id}] must be an object")
    visible = entry.get("visible")
    if visible is None:
        visible = True
    sync = entry.get("sync")
    if sync is None:
        sync = True
    layout_raw = entry.get("layout")
    if layout_raw is None:
        layout = dict(_DEFAULT_SLICER_LAYOUT)
    elif not isinstance(layout_raw, Mapping):
        raise ValueError(f"slicer.pages[{page_id}].layout must be an object")
    else:
        def _as_num(v: Any) -> float:
            if isinstance(v, bool) or v is None:
                raise ValueError("not a number")
            if isinstance(v, (int, float)):
                return float(v)
            raise ValueError("not a number")
        try:
            xf = _as_num(layout_raw.get("x", 0))
            yf = _as_num(layout_raw.get("y", 0))
            wf = _as_num(layout_raw.get("w", _DEFAULT_SLICER_LAYOUT["w"]))
            hf = _as_num(layout_raw.get("h", _DEFAULT_SLICER_LAYOUT["h"]))
        except Exception as exc:
            raise ValueError(f"slicer.pages[{page_id}].layout must have numeric x,y,w,h") from exc

        def _maybe_int(v: float) -> Any:
            return int(v) if float(v).is_integer() else v
        layout = {"x": _maybe_int(xf), "y": _maybe_int(yf), "w": _maybe_int(wf), "h": _maybe_int(hf)}

    out = {"visible": bool(visible), "sync": bool(sync), "layout": layout}
    instance_id = entry.get("instance_id")
    if isinstance(instance_id, str) and instance_id.strip():
        out["instance_id"] = instance_id.strip()
    instance_title = entry.get("instance_title")
    if isinstance(instance_title, str):
        out["instance_title"] = instance_title.strip()
    return out


def _canonicalize_unified_slicer(item: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize a unified slicer (merged definition + page placement).

    Accepts both unified format (with 'pages' dict) and legacy format (with
    'scope'/'target'/'sync_pages') for migration compatibility.
    """
    sid = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    title = str(item.get("title") or "").strip()
    if not sid:
        raise ValueError("slicer.id is required")
    if not name:
        raise ValueError("slicer.name is required")

    type_raw = item.get("type")
    s_type = str(type_raw or "list").strip().lower()
    allowed_slicer_types = {"list", "dropdown", "date_range", "button", "tile", "input", "relative_date", "relative_time"}
    if s_type not in allowed_slicer_types:
        raise ValueError("slicer.type must be one of: list, dropdown, date_range, button, tile, input, relative_date, relative_time")

    ui_raw = item.get("ui")
    if ui_raw is None:
        ui_raw = {}
    if not isinstance(ui_raw, Mapping):
        raise ValueError("slicer.ui must be an object")
    input_mode_raw = ui_raw.get("input_mode")
    input_mode = str(input_mode_raw or ("input" if s_type == "input" and item.get("column") is None else "filter")).strip().lower()
    if input_mode not in {"filter", "input"}:
        raise ValueError("slicer.ui.input_mode must be 'filter' or 'input'")
    pure_input = s_type == "input" and input_mode == "input"

    col = item.get("column")
    if col is None and pure_input:
        col = {"type": "InputRef", "table": "", "column": ""}
    if not isinstance(col, Mapping):
        raise ValueError("slicer.column must be an object")
    col_type = str(col.get("type") or ("InputRef" if pure_input else "ColumnRef")).strip()
    t = str(col.get("table") or "").strip()
    c = str(col.get("column") or "").strip()
    if not pure_input and (not t or not c):
        raise ValueError("slicer.column.table and slicer.column.column are required")

    sel = _canonicalize_slicer_selection(item.get("selection"), slicer_type=s_type)
    defaults = _canonicalize_slicer_defaults(item.get("defaults"), slicer_type=s_type)

    behavior_raw = item.get("behavior")
    behavior: dict[str, Any] = {}
    if behavior_raw is None:
        behavior = {"apply_to": "all_visuals", "auto_apply": True, "force_selection": False}
    elif isinstance(behavior_raw, Mapping):
        apply_to = str(behavior_raw.get("apply_to") or "all_visuals").strip().lower()
        if apply_to != "all_visuals":
            raise ValueError("slicer.behavior.apply_to must be 'all_visuals'")
        auto_apply = behavior_raw.get("auto_apply")
        if auto_apply is None:
            auto_apply = True
        if not isinstance(auto_apply, bool):
            raise ValueError("slicer.behavior.auto_apply must be a boolean")
        force_selection_raw = behavior_raw.get("force_selection")
        if force_selection_raw is None:
            force_selection_raw = False
        if not isinstance(force_selection_raw, bool):
            raise ValueError("slicer.behavior.force_selection must be a boolean")
        behavior = {"apply_to": "all_visuals", "auto_apply": bool(auto_apply), "force_selection": bool(force_selection_raw)}
    else:
        raise ValueError("slicer.behavior must be an object")

    multi_raw = ui_raw.get("multi")
    if multi_raw is None:
        multi_raw = item.get("multi")
    if multi_raw is None:
        multi_raw = False if s_type in {"dropdown", "date_range", "relative_date", "relative_time", "input"} else True
    if not isinstance(multi_raw, bool):
        raise ValueError("slicer.ui.multi must be a boolean")

    search_raw = ui_raw.get("search")
    if search_raw is None:
        search_raw = item.get("search")
    if search_raw is None:
        search_raw = False if s_type in {"date_range", "relative_date", "relative_time", "input"} else True
    if not isinstance(search_raw, bool):
        raise ValueError("slicer.ui.search must be a boolean")

    style_raw = ui_raw.get("style")
    style = str(style_raw or s_type).strip().lower()
    if style not in allowed_slicer_types:
        style = s_type

    show_select_all_raw = ui_raw.get("show_select_all")
    if show_select_all_raw is None:
        show_select_all_raw = True
    if not isinstance(show_select_all_raw, bool):
        raise ValueError("slicer.ui.show_select_all must be a boolean")

    paste_values_raw = ui_raw.get("paste_values")
    if paste_values_raw is None:
        paste_values_raw = False
    if not isinstance(paste_values_raw, bool):
        raise ValueError("slicer.ui.paste_values must be a boolean")

    leaf_only_raw = ui_raw.get("leaf_only")
    if leaf_only_raw is None:
        leaf_only_raw = False
    if not isinstance(leaf_only_raw, bool):
        raise ValueError("slicer.ui.leaf_only must be a boolean")

    image_fit_raw = ui_raw.get("image_fit", ui_raw.get("imageFit"))
    image_fit: str | None = None
    if image_fit_raw is not None:
        image_fit = str(image_fit_raw).strip().lower()
        allowed_image_fits = {"cover", "contain", "fill", "none", "scale-down", "fit", "crop", "stretch", "normal", "actual"}
        if image_fit not in allowed_image_fits:
            raise ValueError("slicer.ui.image_fit must be one of: cover, contain, fill, none, scale-down")

    image_position_raw = ui_raw.get("image_position", ui_raw.get("imagePosition"))
    image_position: str | None = None
    if image_position_raw is not None:
        image_position = str(image_position_raw).strip()
        if not image_position:
            image_position = None

    image_saturation_raw = ui_raw.get("image_saturation", ui_raw.get("imageSaturation"))
    image_saturation: int | float | str | None = None
    if image_saturation_raw is not None:
        if isinstance(image_saturation_raw, (int, float)):
            image_saturation = image_saturation_raw
        else:
            image_saturation = str(image_saturation_raw).strip()
            if not image_saturation:
                image_saturation = None

    image_background_raw = ui_raw.get("image_background", ui_raw.get("imageBackground"))
    image_background: str | None = None
    if image_background_raw is not None:
        image_background = str(image_background_raw).strip()
        if not image_background:
            image_background = None

    image_padding_raw = ui_raw.get("image_padding", ui_raw.get("imagePadding"))
    image_padding: int | float | str | None = None
    if image_padding_raw is not None:
        if isinstance(image_padding_raw, (int, float)):
            image_padding = image_padding_raw
        else:
            image_padding = str(image_padding_raw).strip()
            if not image_padding:
                image_padding = None

    filter_operator_raw = ui_raw.get("filter_operator")
    filter_operator = str(filter_operator_raw or ("contains" if s_type == "input" else "in")).strip().lower()
    allowed_filter_operators = {
        "in", "not_in",
        "contains", "contains_any", "contains_all", "notcontains_any",
        "startswith", "startswith_any", "notstartswith_any",
        "endswith", "endswith_any", "notendswith_any",
        "=", "!=", ">", ">=", "<", "<=",
    }
    if filter_operator not in allowed_filter_operators:
        raise ValueError("slicer.ui.filter_operator must be one of: in, not_in, contains, contains_any, contains_all, notcontains_any, startswith, startswith_any, notstartswith_any, endswith, endswith_any, notendswith_any, =, !=, >, >=, <, <=")

    # Build pages dict — accept unified 'pages' or legacy 'scope'/'target'/'sync_pages'
    pages_raw = item.get("pages")
    pages: dict[str, dict[str, Any]] = {}

    if pages_raw is not None and isinstance(pages_raw, Mapping):
        # Unified format
        for pid_raw, entry in pages_raw.items():
            pid = str(pid_raw).strip()
            if not pid:
                continue
            pages[pid] = _canonicalize_slicer_page_entry(pid, entry)
    else:
        # Legacy format: derive from scope/target/sync_pages
        scope = str(item.get("scope") or "").strip().lower()
        target_raw = item.get("target")
        target = str(target_raw).strip() if isinstance(target_raw, str) and target_raw.strip() else None

        sync_pages_raw = item.get("sync_pages")
        if sync_pages_raw is not None and isinstance(sync_pages_raw, Mapping):
            for pid_raw, pcfg in sync_pages_raw.items():
                pid = str(pid_raw).strip()
                if not pid:
                    continue
                if isinstance(pcfg, Mapping):
                    pages[pid] = {
                        "visible": bool(pcfg.get("visible", True)),
                        "sync": bool(pcfg.get("sync", True)),
                        "layout": dict(_DEFAULT_SLICER_LAYOUT),
                    }
        elif scope == "page" and target:
            pages[target] = {"visible": True, "sync": True, "layout": dict(_DEFAULT_SLICER_LAYOUT)}

    out: dict[str, Any] = {
        "id": sid,
        "name": name,
        "title": title,
        "column": {"type": col_type, "table": t, "column": c},
        "type": s_type,
        "behavior": behavior,
        "selection": sel,
        "ui": {
            "multi": bool(multi_raw),
            "search": bool(search_raw),
            "style": style,
            "show_select_all": bool(show_select_all_raw),
            "paste_values": bool(paste_values_raw),
            "leaf_only": bool(leaf_only_raw),
            "filter_operator": filter_operator,
            "input_mode": input_mode,
        },
        "pages": pages,
    }

    if defaults is not None:
        out["defaults"] = defaults

    if image_fit is not None:
        out["ui"]["image_fit"] = image_fit
    if image_position is not None:
        out["ui"]["image_position"] = image_position
    if image_saturation is not None:
        out["ui"]["image_saturation"] = image_saturation
    if image_background is not None:
        out["ui"]["image_background"] = image_background
    if image_padding is not None:
        out["ui"]["image_padding"] = image_padding

    sync_group_raw = item.get("sync_group")
    if sync_group_raw is not None:
        sg = str(sync_group_raw).strip()
        if sg:
            out["sync_group"] = sg

    return out


def _sorted_unified_slicers(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def _k(x: Mapping[str, Any]) -> tuple:
        col = x.get("column") if isinstance(x.get("column"), Mapping) else {}
        table = str(col.get("table") or "")
        column = str(col.get("column") or "")
        name = str(x.get("name") or "")
        sid = str(x.get("id") or "")
        return (name.upper(), table.upper(), column.upper(), sid.upper())

    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, Mapping):
            out.append(dict(it))
    out.sort(key=_k)
    return out


def _sorted_slicer_instances(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def _k(x: Mapping[str, Any]) -> tuple:
        def_id = str(x.get("def_id") or "")
        title = str(x.get("title") or "")
        sid = str(x.get("id") or "")
        return (title.upper(), def_id.upper(), sid.upper())

    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, Mapping):
            out.append(dict(it))
    out.sort(key=_k)
    return out


def _canonicalize_slicer_selection(sel: Any, *, slicer_type: str) -> dict[str, Any]:
    st = str(slicer_type or "").strip().lower()
    if st not in {"list", "dropdown", "date_range", "button", "tile", "input", "relative_date", "relative_time"}:
        raise ValueError("slicer_type must be one of: list, dropdown, date_range, button, tile, input, relative_date, relative_time")

    if sel is None:
        if st in {"date_range", "relative_date", "relative_time"}:
            return {"mode": "all", "start": None, "end": None}
        return {"mode": "all", "values": []}
    if not isinstance(sel, Mapping):
        raise ValueError("slicer_instance.selection must be an object")

    if st in {"date_range", "relative_date", "relative_time"}:
        mode = str(sel.get("mode") or "all").strip().lower()
        if mode == "relative" and st not in {"relative_date", "relative_time"}:
            raise ValueError("date_range slicer selection.mode must be 'all' or 'range'")
        if mode not in {"all", "range", "relative"}:
            raise ValueError("date_range slicer selection.mode must be 'all', 'range', or 'relative'")

        start_raw = sel.get("start")
        end_raw = sel.get("end")

        start = None if start_raw is None else str(start_raw).strip()
        end = None if end_raw is None else str(end_raw).strip()
        if start == "":
            start = None
        if end == "":
            end = None

        if mode == "all":
            return {"mode": "all", "start": None, "end": None}

        if mode == "relative":
            direction_raw = str(sel.get("direction") or sel.get("period") or "last").strip().lower()
            direction_aliases = {
                "previous": "last",
                "prev": "last",
                "past": "last",
                "future": "next",
                "current": "this",
            }
            direction = direction_aliases.get(direction_raw, direction_raw)
            if direction not in {"last", "next", "this"}:
                raise ValueError("relative slicer selection.direction must be 'last', 'next', or 'this'")

            unit_raw = str(sel.get("unit") or "day").strip().lower().replace("_", " ").replace("-", " ")
            if st == "relative_time":
                unit_aliases = {
                    "minute": "minute",
                    "minutes": "minute",
                    "min": "minute",
                    "mins": "minute",
                    "hour": "hour",
                    "hours": "hour",
                    "hr": "hour",
                    "hrs": "hour",
                }
                unit_error = "relative_time slicer selection.unit must be minute or hour"
            else:
                unit_aliases = {
                    "day": "day",
                    "days": "day",
                    "week": "week",
                    "weeks": "week",
                    "month": "month",
                    "months": "month",
                    "quarter": "quarter",
                    "quarters": "quarter",
                    "year": "year",
                    "years": "year",
                }
                unit_error = "relative_date slicer selection.unit must be day, week, month, quarter, or year"
            unit = unit_aliases.get(unit_raw)
            if unit is None:
                raise ValueError(unit_error)

            count_raw = sel.get("count", 1)
            try:
                count = int(count_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("relative_date slicer selection.count must be a positive integer") from exc
            if count < 1:
                raise ValueError("relative_date slicer selection.count must be a positive integer")

            include_raw = sel.get("include_current", sel.get("include_today", True))
            if isinstance(include_raw, str):
                include_current = include_raw.strip().lower() not in {"0", "false", "no", "off"}
            else:
                include_current = bool(include_raw)

            window = "rolling"
            if st != "relative_time":
                window_raw = sel.get("window")
                if window_raw is None and "calendar" in sel:
                    window_raw = "calendar" if bool(sel.get("calendar")) else "rolling"
                window = str(window_raw or "rolling").strip().lower()
                if window not in {"rolling", "calendar"}:
                    raise ValueError("relative_date slicer selection.window must be 'rolling' or 'calendar'")

            anchor_raw = sel.get("anchor")
            anchor = None if anchor_raw is None else str(anchor_raw).strip()
            out = {
                "mode": "relative",
                "direction": direction,
                "count": count,
                "unit": unit,
            }
            if st == "relative_time":
                out["include_current"] = include_current
            else:
                out["include_today"] = include_current
                out["window"] = window
            if anchor:
                out["anchor"] = anchor
            return out

        # Deterministic normalization: empty range means ALL.
        if start is None and end is None:
            return {"mode": "all", "start": None, "end": None}

        if start is not None and end is not None and start > end:
            raise ValueError("date_range slicer selection.start must be <= selection.end")

        return {"mode": "range", "start": start, "end": end}

    mode = str(sel.get("mode") or "all").strip().lower()
    if mode == "selected":
        mode = "values"
    if mode not in {"all", "values"}:
        raise ValueError("slicer_instance.selection.mode must be 'all' or 'values'")
    values_raw = sel.get("values")
    if mode == "all":
        return {"mode": "all", "values": []}
    if values_raw is None:
        values: list[Any] = []
    elif isinstance(values_raw, list):
        values = list(values_raw)
    else:
        values = [values_raw]

    # Normalize None -> __BLANK__ for stable persistence.
    norm_values: list[Any] = ["__BLANK__" if v is None else v for v in values]

    # Deterministic normalization: empty selection means ALL.
    if not norm_values:
        return {"mode": "all", "values": []}
    return {"mode": "values", "values": norm_values}


def _canonicalize_slicer_instance(item: Mapping[str, Any], *, known_def_ids: set[str]) -> dict[str, Any]:
    """Legacy canonicalize for old-format slicer instances.

    Still used by compat wrappers that accept old-format payloads.
    """
    sid = str(item.get("id") or "").strip()
    # Back-compat: accept slicer_def_id but canonicalize to def_id.
    def_id = str(item.get("def_id") or item.get("slicer_def_id") or "").strip()
    title = str(item.get("title") or "").strip()
    page_id_raw = item.get("page_id")
    page_id = str(page_id_raw).strip() if isinstance(page_id_raw, str) and page_id_raw.strip() else None

    container_raw = item.get("container")
    container = str(container_raw).strip() if isinstance(container_raw, str) and container_raw.strip() else None
    if container is not None and container not in {"canvas"}:
        raise ValueError("slicer_instance.container must be 'canvas'")

    layout_raw = item.get("layout")
    layout: Optional[dict[str, Any]] = None
    if layout_raw is None:
        layout = None
    elif not isinstance(layout_raw, Mapping):
        raise ValueError("slicer_instance.layout must be an object")
    else:
        x = layout_raw.get("x")
        y = layout_raw.get("y")
        w = layout_raw.get("w")
        h = layout_raw.get("h")

        def _as_number(v: Any) -> float:
            if isinstance(v, bool) or v is None:
                raise ValueError("not a number")
            if isinstance(v, (int, float)):
                return float(v)
            raise ValueError("not a number")

        try:
            xf = _as_number(x)
            yf = _as_number(y)
            wf = _as_number(w)
            hf = _as_number(h)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("slicer_instance.layout must have numeric x,y,w,h") from exc

        def _maybe_int(v: float) -> Any:
            return int(v) if float(v).is_integer() else v

        layout = {"x": _maybe_int(xf), "y": _maybe_int(yf), "w": _maybe_int(wf), "h": _maybe_int(hf)}
    if not sid:
        raise ValueError("slicer_instance.id is required")
    if not def_id:
        raise ValueError("slicer_instance.def_id is required")
    if def_id.upper() not in {d.upper() for d in known_def_ids}:
        raise ValueError(f"slicer_instance.def_id not found in defs: {def_id!r}")
    out: dict[str, Any] = {
        "id": sid,
        "def_id": def_id,
        "title": title,
    }

    if page_id is not None:
        out["page_id"] = page_id
    if container is not None:
        out["container"] = container
    if layout is not None:
        out["layout"] = layout
    return out


def load_slicers(project_path: str) -> dict[str, Any]:
    """Load unified slicers from <project>/reports/slicers.yaml.

    Returns canonical shape:
      {"slicers": [ {id, name, column, type, behavior, selection, ui, pages:{...}}, ... ]}

    Auto-migrates from legacy slicer_defs.yaml + slicer_instances.yaml if slicers.yaml
    doesn't exist yet.
    """
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "reports" / "slicers.yaml"
    if not path.exists():
        # Try migration from legacy files
        return _migrate_legacy_slicer_files(project_path)

    raw = _load_yaml(path)
    if raw is None:
        return {"slicers": []}
    if not isinstance(raw, Mapping):
        raise ValueError("reports/slicers.yaml must be a mapping")

    slicers_raw = raw.get("slicers")
    if slicers_raw is None:
        slicers_raw = []
    if not isinstance(slicers_raw, list):
        raise ValueError("slicers must be a list")

    out: list[dict[str, Any]] = []
    for it in slicers_raw:
        if not isinstance(it, Mapping):
            continue
        out.append(_canonicalize_unified_slicer(it))

    # Enforce unique ids
    seen: set[str] = set()
    for s in out:
        sid = str(s.get("id") or "")
        key = sid.upper()
        if key in seen:
            raise ValueError(f"Duplicate slicer.id: {sid!r}")
        seen.add(key)

    return {"slicers": _sorted_unified_slicers(out)}


def save_slicers(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist unified slicers to <project>/reports/slicers.yaml."""
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "slicers.yaml"

    slicers_in = payload.get("slicers") if isinstance(payload, Mapping) else None
    if slicers_in is None:
        slicers_in = []
    if not isinstance(slicers_in, list):
        raise ValueError("slicers must be a list")

    out: list[dict[str, Any]] = []
    for it in slicers_in:
        if not isinstance(it, Mapping):
            continue
        out.append(_canonicalize_unified_slicer(it))

    seen: set[str] = set()
    for s in out:
        sid = str(s.get("id") or "")
        key = sid.upper()
        if key in seen:
            raise ValueError(f"Duplicate slicer.id: {sid!r}")
        seen.add(key)

    canon = {"slicers": _sorted_unified_slicers(out)}
    _dump_yaml(path, canon)

    # Clean up legacy files if they exist
    for legacy in ("slicer_defs.yaml", "slicer_instances.yaml"):
        lp = reports_dir / legacy
        if lp.exists():
            lp.unlink()

    return canon


def _migrate_legacy_slicer_files(project_path: str) -> dict[str, Any]:
    """Migrate legacy slicer_defs.yaml + slicer_instances.yaml into unified slicers.yaml.

    Returns the unified format. If no legacy files exist, returns empty.
    """
    root = Path(project_path)
    defs_path = root / "reports" / "slicer_defs.yaml"
    inst_path = root / "reports" / "slicer_instances.yaml"

    defs_raw = _load_yaml(defs_path)
    inst_raw = _load_yaml(inst_path)

    if defs_raw is None and inst_raw is None:
        return {"slicers": []}

    # Parse legacy defs
    defs_list: list[dict[str, Any]] = []
    if defs_raw is not None and isinstance(defs_raw, Mapping):
        for it in (defs_raw.get("defs") or []):
            if isinstance(it, Mapping):
                defs_list.append(dict(it))

    # Parse legacy instances (map def_id → [instances])
    inst_by_def: dict[str, list[dict[str, Any]]] = {}
    if inst_raw is not None and isinstance(inst_raw, Mapping):
        for it in (inst_raw.get("instances") or []):
            if isinstance(it, Mapping):
                did = str(it.get("def_id") or it.get("slicer_def_id") or "").strip()
                if did:
                    inst_by_def.setdefault(did, []).append(dict(it))

    # Merge: each def becomes a unified slicer with pages from sync_pages + instances
    slicers: list[dict[str, Any]] = []
    for d in defs_list:
        sid = str(d.get("id") or "").strip()
        # Start with pages from sync_pages metadata
        pages: dict[str, dict[str, Any]] = {}
        sync_pages = d.get("sync_pages")
        if isinstance(sync_pages, Mapping):
            for pid, pcfg in sync_pages.items():
                pid_s = str(pid).strip()
                if pid_s and isinstance(pcfg, Mapping):
                    pages[pid_s] = {
                        "visible": bool(pcfg.get("visible", True)),
                        "sync": bool(pcfg.get("sync", True)),
                        "layout": dict(_DEFAULT_SLICER_LAYOUT),
                    }

        # Enrich with instance layout data
        instances = inst_by_def.get(sid, [])
        for inst in instances:
            pid = str(inst.get("page_id") or "").strip()
            if not pid:
                continue
            layout_raw = inst.get("layout")
            layout = dict(_DEFAULT_SLICER_LAYOUT)
            if isinstance(layout_raw, Mapping):
                try:
                    layout = {
                        "x": int(layout_raw.get("x", 0)),
                        "y": int(layout_raw.get("y", 0)),
                        "w": int(layout_raw.get("w", 240)),
                        "h": int(layout_raw.get("h", 260)),
                    }
                except (TypeError, ValueError):
                    pass
            if pid in pages:
                pages[pid]["layout"] = layout
            else:
                pages[pid] = {"visible": True, "sync": True, "layout": layout}

        # If no pages from sync_pages or instances, derive from scope/target
        if not pages:
            scope = str(d.get("scope") or "").strip().lower()
            target = str(d.get("target") or "").strip() if d.get("target") else None
            if scope == "page" and target:
                pages[target] = {"visible": True, "sync": True, "layout": dict(_DEFAULT_SLICER_LAYOUT)}

        # Build unified slicer (strip legacy fields)
        slicer = dict(d)
        for legacy_key in ("scope", "target", "sync_pages"):
            slicer.pop(legacy_key, None)
        slicer["pages"] = pages
        slicers.append(slicer)

    # Canonicalize and save
    result = {"slicers": slicers}
    try:
        saved = save_slicers(project_path, result)
    except Exception:
        # If save fails (validation), return canonical anyway
        out = []
        for s in slicers:
            try:
                out.append(_canonicalize_unified_slicer(s))
            except Exception:
                continue
        saved = {"slicers": _sorted_unified_slicers(out)}
    return saved


# ---------------------------------------------------------------------------
# Backward-compatible wrappers (project unified → legacy format)
# ---------------------------------------------------------------------------

def load_slicer_defs(project_path: str) -> dict[str, Any]:
    """Compat wrapper: Load slicer definitions projected from unified slicers.yaml.

    Returns legacy shape:
      {"defs": [ {id, name, scope, target, column, type, ...}, ... ]}
    """
    unified = load_slicers(project_path)
    slicers = unified.get("slicers") or []

    defs: list[dict[str, Any]] = []
    for s in slicers:
        if not isinstance(s, Mapping):
            continue
        pages = s.get("pages") or {}
        # Derive scope/target: page-scope if slicer appears on any page.
        # In PBI, slicers filter only their own page (even hidden ones).
        # Priority: first visible page, fallback to first page entry.
        scope = "page"
        target = None
        first_page = None
        for pid, pcfg in pages.items():
            if first_page is None:
                first_page = pid
            if isinstance(pcfg, Mapping) and pcfg.get("visible"):
                target = pid
                break
        if not target:
            # Hidden slicer — still page-scoped to its page
            target = first_page
        if not target:
            # No pages at all — report-scope
            scope = "report"

        d: dict[str, Any] = {
            "id": s.get("id"),
            "name": s.get("name"),
            "title": s.get("title", ""),
            "scope": scope,
            "target": target,
            "column": s.get("column"),
            "type": s.get("type"),
            "behavior": s.get("behavior"),
            "selection": s.get("selection"),
            "ui": s.get("ui"),
        }
        ui = s.get("ui") if isinstance(s.get("ui"), Mapping) else {}
        if isinstance(ui, Mapping) and isinstance(ui.get("filter_operator"), str):
            d["filter_operator"] = ui["filter_operator"]
        if "defaults" in s:
            d["defaults"] = s["defaults"]
        if "sync_group" in s:
            d["sync_group"] = s["sync_group"]
        # Build sync_pages from pages
        if pages:
            sp: dict[str, dict[str, bool]] = {}
            for pid, pcfg in pages.items():
                if isinstance(pcfg, Mapping):
                    sp[pid] = {"sync": bool(pcfg.get("sync", True)), "visible": bool(pcfg.get("visible", True))}
            if sp:
                d["sync_pages"] = sp
        defs.append(d)

    return {"defs": _sorted_slicer_defs(defs)}


def save_slicer_defs(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compat wrapper: Save slicer definitions by updating unified slicers.yaml.

    Accepts legacy shape: {"defs": [...]} with scope/target fields.
    Updates the unified file, preserving page layouts from existing data.
    """
    defs_in = payload.get("defs") if isinstance(payload, Mapping) else None
    if defs_in is None:
        defs_in = []
    if not isinstance(defs_in, list):
        raise ValueError("defs must be a list")

    # Load existing unified data to preserve page layouts
    try:
        existing = load_slicers(project_path)
    except FileNotFoundError:
        existing = {"slicers": []}
    existing_by_id: dict[str, dict[str, Any]] = {}
    for s in (existing.get("slicers") or []):
        if isinstance(s, Mapping):
            sid = str(s.get("id") or "").strip().upper()
            if sid:
                existing_by_id[sid] = dict(s)

    # Convert each def to unified format, preserving existing page layouts
    slicers: list[dict[str, Any]] = []
    for d in defs_in:
        if not isinstance(d, Mapping):
            continue
        d_dict = dict(d)
        sid = str(d_dict.get("id") or "").strip().upper()

        # Merge page layouts from existing data
        existing_slicer = existing_by_id.get(sid)
        existing_pages: dict[str, Any] = {}
        if existing_slicer:
            existing_pages = existing_slicer.get("pages") or {}

        # If the def has sync_pages, use those as authority for sync/visible flags
        # but preserve layout from existing
        sync_pages = d_dict.get("sync_pages")
        if isinstance(sync_pages, Mapping):
            pages: dict[str, Any] = {}
            for pid, pcfg in sync_pages.items():
                pid_s = str(pid).strip()
                if not pid_s:
                    continue
                existing_entry = existing_pages.get(pid_s) or {}
                existing_layout = existing_entry.get("layout") if isinstance(existing_entry, Mapping) else None
                if isinstance(pcfg, Mapping):
                    pages[pid_s] = {
                        "visible": bool(pcfg.get("visible", True)),
                        "sync": bool(pcfg.get("sync", True)),
                        "layout": existing_layout or dict(_DEFAULT_SLICER_LAYOUT),
                    }
            d_dict["pages"] = pages
        elif existing_pages:
            d_dict["pages"] = existing_pages

        # Strip legacy fields
        for legacy_key in ("scope", "target", "sync_pages"):
            d_dict.pop(legacy_key, None)

        slicers.append(d_dict)

    result = save_slicers(project_path, {"slicers": slicers})

    # Project back to legacy format for the return value
    return load_slicer_defs(project_path)


def load_slicer_instances(project_path: str) -> dict[str, Any]:
    """Compat wrapper: Load slicer instances projected from unified slicers.yaml.

    Returns legacy shape:
      {"instances": [ {id, def_id, title, page_id, container, layout}, ... ]}

    Each page entry with visible=True in a slicer generates one synthetic instance.
    """
    unified = load_slicers(project_path)
    slicers = unified.get("slicers") or []

    instances: list[dict[str, Any]] = []
    for s in slicers:
        if not isinstance(s, Mapping):
            continue
        sid = str(s.get("id") or "")
        name = str(s.get("name") or s.get("title") or "")
        pages = s.get("pages") or {}
        for pid, pcfg in pages.items():
            if not isinstance(pcfg, Mapping):
                continue
            if not pcfg.get("visible", True):
                continue
            layout = pcfg.get("layout") or dict(_DEFAULT_SLICER_LAYOUT)
            # Generate stable instance ID from slicer ID + page ID
            inst_id_raw = pcfg.get("instance_id")
            inst_id = str(inst_id_raw).strip() if isinstance(inst_id_raw, str) and inst_id_raw.strip() else f"si_{sid}_{pid}"
            title_raw = pcfg.get("instance_title")
            title = str(title_raw).strip() if isinstance(title_raw, str) and title_raw.strip() else name
            instances.append({
                "id": inst_id,
                "def_id": sid,
                "title": title,
                "page_id": pid,
                "container": "canvas",
                "layout": layout,
            })

    return {"instances": _sorted_slicer_instances(instances)}


def save_slicer_instances(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compat wrapper: Save slicer instances by updating page entries in unified slicers.yaml.

    Accepts legacy shape: {"instances": [...]} with def_id/page_id/layout.
    Updates the corresponding page entries in the unified file.
    """
    inst_in = payload.get("instances") if isinstance(payload, Mapping) else None
    if inst_in is None:
        inst_in = []
    if not isinstance(inst_in, list):
        raise ValueError("instances must be a list")

    # Load existing unified data
    try:
        existing = load_slicers(project_path)
    except FileNotFoundError:
        existing = {"slicers": []}

    slicers = list(existing.get("slicers") or [])
    slicers_by_id: dict[str, int] = {}
    for i, s in enumerate(slicers):
        if isinstance(s, Mapping):
            sid = str(s.get("id") or "").strip().upper()
            if sid:
                slicers_by_id[sid] = i

    known_def_ids = {str(s.get("id") or "").strip() for s in slicers if isinstance(s, Mapping) and str(s.get("id") or "").strip()}
    canonical_instances: list[dict[str, Any]] = []

    # Build a set of (def_id, page_id) pairs from the incoming instances
    incoming_pages: dict[str, dict[str, dict[str, Any]]] = {}  # def_id -> {page_id -> layout}
    for inst in inst_in:
        if not isinstance(inst, Mapping):
            continue
        canonical = _canonicalize_slicer_instance(inst, known_def_ids=known_def_ids)
        canonical_instances.append(canonical)
        def_id = str(canonical.get("def_id") or "").strip()
        page_id = str(canonical.get("page_id") or "").strip()
        if not def_id or not page_id:
            continue
        layout = canonical.get("layout") if isinstance(canonical.get("layout"), Mapping) else dict(_DEFAULT_SLICER_LAYOUT)
        incoming_pages.setdefault(def_id, {})[page_id] = dict(layout)

    # Update each slicer's pages based on incoming instances
    for def_id_upper, idx in slicers_by_id.items():
        slicer = dict(slicers[idx])
        def_id_orig = str(slicer.get("id") or "")
        pages = dict(slicer.get("pages") or {})

        if def_id_orig in incoming_pages or def_id_orig.upper() in {k.upper() for k in incoming_pages}:
            # Find the matching key
            match_key = def_id_orig if def_id_orig in incoming_pages else next(
                (k for k in incoming_pages if k.upper() == def_id_orig.upper()), None
            )
            if match_key:
                new_page_data = incoming_pages[match_key]
                # Update layouts for specified pages
                for pid, layout in new_page_data.items():
                    if pid and pid in pages:
                        pages[pid] = dict(pages[pid])
                        pages[pid]["layout"] = layout
                    elif pid:
                        pages[pid] = {"visible": True, "sync": True, "layout": layout}
                    if pid:
                        inst = next(
                            (
                                ci for ci in canonical_instances
                                if str(ci.get("def_id") or "").strip().upper() == def_id_orig.upper()
                                and str(ci.get("page_id") or "").strip() == pid
                            ),
                            None,
                        )
                        if inst is not None and pid in pages:
                            pages[pid]["instance_id"] = inst.get("id")
                            pages[pid]["instance_title"] = inst.get("title")

        slicer["pages"] = pages
        slicers[idx] = slicer

    save_slicers(project_path, {"slicers": slicers})
    return {"instances": _sorted_slicer_instances(canonical_instances)}


def save_security_yaml(
        project_path: str,
        *,
        roles: list[Mapping[str, Any]],
        default_role: Optional[str] = None,
) -> None:
        """Persist <project>/model/security.yaml.

        Shape:
            {
                default_role?: string,
                roles: [
                    {name: string, rls: [{table: string, filter: string}], ols: {tables:[], measures:[], columns:{}}}
                ]
            }

        Notes:
        - This function does not perform semantic validation; callers must validate.
        - Ordering is preserved as provided by the caller (roles list order, rls order).
        - Writes using yaml.safe_dump(sort_keys=False) via _dump_yaml (atomic).
        """

        root = Path(project_path)
        if not root.exists() or not root.is_dir():
                raise FileNotFoundError(str(root))

        model_dir = root / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        path = model_dir / "security.yaml"

        obj: dict[str, Any] = {}
        if isinstance(default_role, str) and default_role.strip():
                obj["default_role"] = default_role.strip()

        # Ensure JSON/YAML-friendly deep copies.
        out_roles: list[dict[str, Any]] = []
        for r in roles:
                if not isinstance(r, Mapping):
                        continue
                out_roles.append(dict(r))
        obj["roles"] = out_roles

        _dump_yaml(path, obj)


def update_measure_yaml(
    project_path: str,
    *,
    name: str,
    dax: str,
    description: Optional[str] = None,
    folder: Optional[str] = None,
    format: Optional[str] = None,
) -> None:
    """Update a single measure in <project>/model/measures.yaml.

    Preserves other measures and unknown fields.
    Writes using yaml.safe_dump(sort_keys=False).
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    measures_path = root / "model" / "measures.yaml"
    measures_path.parent.mkdir(parents=True, exist_ok=True)

    raw = _load_yaml(measures_path)

    # Preserve the original root shape:
    # - mapping with 'measures' list
    # - or list root
    root_obj: Any
    measures_list: MutableSequence[Any]

    if raw is None:
        root_obj = {"measures": []}
        measures_list = root_obj["measures"]
    elif isinstance(raw, list):
        root_obj = raw
        measures_list = raw
    elif isinstance(raw, Mapping):
        root_obj = dict(raw)
        existing = root_obj.get("measures")
        if existing is None:
            root_obj["measures"] = []
            measures_list = root_obj["measures"]
        elif isinstance(existing, list):
            measures_list = existing
        else:
            raise ValueError("measures.yaml: 'measures' must be a list if present")
    else:
        raise ValueError("measures.yaml must be a list or a mapping")

    target_key = _norm_key(name)
    found = False

    for item in measures_list:
        if not isinstance(item, MutableMapping):
            continue
        existing_name = item.get("name")
        if isinstance(existing_name, str) and _norm_key(existing_name) == target_key:
            item["name"] = name
            item["dax"] = dax

            if description is None or not str(description).strip():
                item.pop("description", None)
            else:
                item["description"] = str(description)

            if folder is None or not str(folder).strip():
                item.pop("folder", None)
            else:
                item["folder"] = str(folder)

            if format is None or not str(format).strip():
                item.pop("format", None)
            else:
                item["format"] = str(format)

            found = True
            break

    if not found:
        new_item: MutableMapping[str, Any] = {"name": name, "dax": dax}
        if description is not None and str(description).strip():
            new_item["description"] = str(description)
        if folder is not None and str(folder).strip():
            new_item["folder"] = str(folder)
        if format is not None and str(format).strip():
            new_item["format"] = str(format)
        measures_list.append(new_item)

    _dump_yaml(measures_path, root_obj)


def delete_measure_yaml(project_path: str, *, name: str) -> bool:
    """Delete a single measure from <project>/model/measures.yaml.

    Preserves root shape and unknown fields. Returns True if a measure was removed.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    measures_path = root / "model" / "measures.yaml"
    if not measures_path.exists():
        return False

    raw = _load_yaml(measures_path)

    root_obj: Any
    measures_list: MutableSequence[Any]

    if raw is None:
        return False
    if isinstance(raw, list):
        root_obj = raw
        measures_list = raw
    elif isinstance(raw, Mapping):
        root_obj = dict(raw)
        existing = root_obj.get("measures")
        if existing is None:
            return False
        if not isinstance(existing, list):
            raise ValueError("measures.yaml: 'measures' must be a list if present")
        measures_list = existing
    else:
        raise ValueError("measures.yaml must be a list or a mapping")

    target_key = _norm_key(name)
    before = len(measures_list)

    kept: list[Any] = []
    for item in measures_list:
        if not isinstance(item, Mapping):
            kept.append(item)
            continue
        existing_name = item.get("name")
        if isinstance(existing_name, str) and _norm_key(existing_name) == target_key:
            continue
        kept.append(item)

    if len(kept) == before:
        return False

    if measures_list is root_obj:
        # list root
        root_obj[:] = kept  # type: ignore[index]
    else:
        root_obj["measures"] = kept

    _dump_yaml(measures_path, root_obj)
    return True


def save_measures(project_path: str, model: Any) -> None:
    """Persist measures from a loaded SemanticModel back to measures.yaml.

    This is a narrow persistence helper for local tooling (e.g., the measure editor).
    """

    measures = getattr(model, "measures", None)
    if measures is None:
        raise ValueError("Model has no 'measures' attribute")

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    measures_path = root / "model" / "measures.yaml"
    measures_path.parent.mkdir(parents=True, exist_ok=True)

    out_list: list[dict[str, Any]] = []
    for m in measures:
        name = getattr(m, "name", None)
        dax = getattr(m, "dax", None)
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(dax, str) or not dax.strip():
            continue

        row: dict[str, Any] = {"name": name, "dax": dax}
        desc = getattr(m, "description", None)
        fmt = getattr(m, "format", None)
        folder = getattr(m, "folder", None)
        if isinstance(desc, str) and desc.strip():
            row["description"] = desc
        if isinstance(folder, str) and folder.strip():
            row["folder"] = folder
        if isinstance(fmt, str) and fmt.strip():
            row["format"] = fmt
        out_list.append(row)

    # Use mapping root for consistency with loader examples.
    _dump_yaml(measures_path, {"measures": out_list})


def load_field_parameters_yaml(project_path: str) -> dict[str, Any]:
    """Load field parameters YAML from <project>/model/field_parameters.yaml.

    Returns the raw YAML object (mapping) or an empty mapping when missing.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "model" / "field_parameters.yaml"
    raw = _load_yaml(path)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("field_parameters.yaml must be a mapping")
    return dict(raw)


# --- Field Parameter DAX table schema inference (authoritative) ---

UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG = (
    "Unsupported field parameter DAX shape. Use DATATABLE, SELECTCOLUMNS, ROW, or UNION(ROW…)."
)


def infer_field_parameter_dax_columns(dax: str) -> list[str]:
    """Infer column names for a field parameter DAX table expression.

    Supported shapes (authoritative):
    - DATATABLE(...)
    - SELECTCOLUMNS(...)
    - ROW(...)
    - UNION(ROW(...), ROW(...), ...) and nested UNION chains

    Returns column names in the order they appear.
    Raises ValueError with a stable message on unsupported shapes.
    """

    from dax_parser.ast import FuncCallNode as _FuncCallNode
    from dax_parser.ast import LiteralNode as _LiteralNode
    from dax_parser.ast import ParenNode as _ParenNode
    from dax_parser.parser import parse_expression as _parse_expression

    if not isinstance(dax, str) or not dax.strip():
        raise ValueError("field parameter dax must be a non-empty string")

    try:
        ast = _parse_expression(dax)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(str(exc)) from exc

    def _unwrap_parens(node: Any) -> Any:
        n = node
        while isinstance(n, _ParenNode):
            n = n.inner
        return n

    def _cols_from_row(node: Any) -> list[str]:
        n = _unwrap_parens(node)
        if not isinstance(n, _FuncCallNode) or str(n.name or "").strip().upper() != "ROW":
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        cols: list[str] = []
        args = list(n.args or [])
        if len(args) < 2 or len(args) % 2 != 0:
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        for i in range(0, len(args), 2):
            name_node = _unwrap_parens(args[i])
            if (
                not isinstance(name_node, _LiteralNode)
                or not isinstance(name_node.value, str)
                or not name_node.value.strip()
            ):
                raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
            cols.append(name_node.value.strip())
        return cols

    def _cols_from_selectcolumns(node: Any) -> list[str]:
        n = _unwrap_parens(node)
        if not isinstance(n, _FuncCallNode) or str(n.name or "").strip().upper() != "SELECTCOLUMNS":
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        args = list(n.args or [])
        if len(args) < 3:
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        if (len(args) - 1) % 2 != 0:
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        cols: list[str] = []
        for i in range(1, len(args), 2):
            name_node = _unwrap_parens(args[i])
            if (
                not isinstance(name_node, _LiteralNode)
                or not isinstance(name_node.value, str)
                or not name_node.value.strip()
            ):
                raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
            cols.append(name_node.value.strip())
        return cols

    def _cols_from_datatable(node: Any) -> list[str]:
        n = _unwrap_parens(node)
        if not isinstance(n, _FuncCallNode) or str(n.name or "").strip().upper() != "DATATABLE":
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        args = list(n.args or [])
        if len(args) < 2:
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        # DATATABLE("Col", TYPE, "Col2", TYPE2, ... , <rows-set>)
        cols: list[str] = []
        i = 0
        while i + 1 < len(args):
            name_node = _unwrap_parens(args[i])
            if (
                not isinstance(name_node, _LiteralNode)
                or not isinstance(name_node.value, str)
                or not name_node.value.strip()
            ):
                break
            cols.append(name_node.value.strip())
            i += 2
        if not cols:
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        return cols

    def _cols_from_union_chain(node: Any) -> list[str]:
        n = _unwrap_parens(node)
        if not isinstance(n, _FuncCallNode) or str(n.name or "").strip().upper() != "UNION":
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        args = list(n.args or [])
        if len(args) < 2:
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)

        flat: list[Any] = []

        def _walk(x: Any) -> None:
            xx = _unwrap_parens(x)
            if isinstance(xx, _FuncCallNode) and str(xx.name or "").strip().upper() == "UNION":
                for a in list(xx.args or []):
                    _walk(a)
            else:
                flat.append(xx)

        _walk(n)

        cols0: list[str] | None = None
        cols0_norm: list[str] | None = None
        for leaf in flat:
            cols = _cols_from_row(leaf)
            if cols0 is None:
                cols0 = cols
                cols0_norm = [c.upper() for c in cols]
                continue
            if [c.upper() for c in cols] != cols0_norm:
                raise ValueError("UNION(ROW...) rows must have identical column sets")
        if cols0 is None:
            raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)
        return cols0

    root = _unwrap_parens(ast)
    if isinstance(root, _FuncCallNode):
        fn = str(root.name or "").strip().upper()
        if fn == "ROW":
            return _cols_from_row(root)
        if fn == "UNION":
            return _cols_from_union_chain(root)
        if fn == "SELECTCOLUMNS":
            return _cols_from_selectcolumns(root)
        if fn == "DATATABLE":
            return _cols_from_datatable(root)

    raise ValueError(UNSUPPORTED_FIELD_PARAMETER_DAX_SHAPE_MSG)


def _generate_field_parameter_dax(fp_name: str, items: list[dict[str, Any]]) -> str:
    """Generate Power BI-style DAX table literal from field parameter items.
    
    Returns DAX like:
        AxisField = {
            ("Brand", NAMEOF('Product'[Brand]), 0),
            ("Category", NAMEOF('Product'[Category]), 1)
        }
    """
    if not items:
        return f"{fp_name} = {{}}"
    
    # Gather custom property keys across all items (preserve order of first appearance)
    custom_keys: list[str] = []
    standard_keys = {"name", "ref", "sort", "sortColumn"}
    for item in items:
        for k in item:
            if k not in standard_keys and k not in custom_keys:
                custom_keys.append(k)
    
    lines = []
    for item in items:
        name = item.get("name", "")
        ref = item.get("ref", {})
        sort = item.get("sort", 0)
        
        # Build NAMEOF expression
        ref_type = ref.get("type", "")
        if ref_type == "ColumnRef":
            table = ref.get("table", "")
            column = ref.get("column", "")
            nameof_expr = f"NAMEOF('{table}'[{column}])" if table else f"NAMEOF([{column}])"
        elif ref_type == "MeasureRef":
            measure_name = ref.get("name", "")
            nameof_expr = f"NAMEOF([{measure_name}])"
        else:
            nameof_expr = '""'
        
        # Build tuple elements: name, nameof, sort, [sortColumn], [custom props...]
        parts = [f'"{ name}"', nameof_expr, str(sort)]
        
        sort_column = item.get("sortColumn")
        if sort_column:
            parts.append(f"NAMEOF({sort_column})")
        
        # Append custom property values as quoted strings
        for ck in custom_keys:
            val = item.get(ck, "")
            parts.append(f'"{val}"')
        
        lines.append(f'    ({", ".join(parts)})')
    
    return f"{fp_name} = {{\n" + ",\n".join(lines) + "\n}"


def save_field_parameters_yaml(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist canonical field parameters to <project>/model/field_parameters.yaml.

        Power BI parity schema (simplified):
      {
        "field_parameters": {
          <param_name>: {
                        "dax": str (optional; DAX table expression for schema inference/UI editing),
            "default_item": str (optional; defaults to first item),
            "items": [
              {"name": str, "ref": <ExprJson>, "sort": int?},
              ...
            ]
          }
        }
      }

    The function preserves insertion order of parameters/items from the provided payload.
    """

    # infer_field_parameter_dax_columns is defined at module scope for reuse.

    from dax_engine.ir import ColumnRef, MeasureRef
    from dax_project.expr_json import parse_expr

    def _ref_to_json(ref: Any) -> dict[str, Any]:
        if isinstance(ref, ColumnRef):
            result: dict[str, Any] = {"type": "ColumnRef", "column": ref.column}
            if ref.table:  # Only include table if non-empty
                result["table"] = ref.table
            return result
        if isinstance(ref, MeasureRef):
            return {"type": "MeasureRef", "name": ref.name}
        raise ValueError(f"field_parameters item ref must be ColumnRef or MeasureRef; got {type(ref).__name__}")

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    model_dir = root / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / "field_parameters.yaml"

    fps_raw = payload.get("field_parameters")
    if fps_raw is None:
        fps_raw = {}
    if not isinstance(fps_raw, Mapping):
        raise ValueError("field_parameters must be a mapping")

    # Helper: check if DAX is Power BI table literal format (Name = { ... })
    # These use NAMEOF() and tuple literals which our parser doesn't support,
    # but the client-side JS parses them into items[], so no server validation needed.
    import re as _re
    def _is_power_bi_table_literal(dax: str) -> bool:
        # Pattern: OptionalName = { ... }
        return bool(_re.match(r"^\s*\w+\s*=\s*\{", dax.strip()))

    out_fps: dict[str, Any] = {}
    for fp_name, fp_spec in fps_raw.items():
        if not isinstance(fp_name, str) or not fp_name.strip():
            raise ValueError("field_parameters keys must be non-empty strings")
        if not isinstance(fp_spec, Mapping):
            raise ValueError(f"field_parameters[{fp_name!r}] must be a mapping")

        dax_text = fp_spec.get("dax")
        if dax_text is not None:
            if not isinstance(dax_text, str) or not dax_text.strip():
                raise ValueError(f"field_parameters[{fp_name!r}].dax must be a non-empty string if provided")
            # Validate supported shape (and provide a stable error message on mismatch).
            # Skip validation for Power BI table literal format (already validated by client JS).
            if not _is_power_bi_table_literal(dax_text):
                infer_field_parameter_dax_columns(dax_text)

        # Accept both new schema (items) and legacy schema (options) for back-compat.
        items_raw = fp_spec.get("items") or fp_spec.get("options")
        if items_raw is None:
            items_raw = []
        if not isinstance(items_raw, list) or not items_raw:
            raise ValueError(f"field_parameters[{fp_name!r}].items must be a non-empty list")

        out_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        valid_names: set[str] = set()
        for i, item in enumerate(items_raw):
            if not isinstance(item, Mapping):
                raise ValueError(f"field_parameters[{fp_name!r}].items[{i}] must be an object")
            
            # New schema: name + ref. Legacy: key + label + expr.
            item_name = item.get("name") or item.get("label") or item.get("key")
            ref_obj = item.get("ref") or item.get("expr")
            sort_raw = item.get("sort")
            sort_column_raw = item.get("sortColumn")  # Optional sort-by column
            
            if not isinstance(item_name, str) or not item_name.strip():
                raise ValueError(f"field_parameters[{fp_name!r}].items[{i}].name is required")
            if not isinstance(ref_obj, Mapping):
                raise ValueError(f"field_parameters[{fp_name!r}].items[{i}].ref must be an object")
            if sort_raw is not None and not isinstance(sort_raw, int):
                raise ValueError(f"field_parameters[{fp_name!r}].items[{i}].sort must be an int if provided")
            if sort_column_raw is not None and not isinstance(sort_column_raw, str):
                raise ValueError(f"field_parameters[{fp_name!r}].items[{i}].sortColumn must be a string if provided")

            name_s = item_name.strip()
            if name_s.upper() in seen:
                raise ValueError(f"field_parameters[{fp_name!r}] has duplicate item name: {name_s!r}")
            seen.add(name_s.upper())
            valid_names.add(name_s.upper())

            ref = parse_expr(ref_obj)
            if not isinstance(ref, (ColumnRef, MeasureRef)):
                raise ValueError(
                    f"field_parameters[{fp_name!r}].items[{i}].ref must be ColumnRef or MeasureRef"
                )

            row: dict[str, Any] = {"name": name_s, "ref": _ref_to_json(ref)}
            if isinstance(sort_raw, int):
                row["sort"] = int(sort_raw)
            if isinstance(sort_column_raw, str) and sort_column_raw.strip():
                row["sortColumn"] = sort_column_raw.strip()
            
            # Preserve custom properties (any key not in standard fields)
            standard_keys = {"name", "label", "key", "ref", "expr", "sort", "sortColumn"}
            for k, v in item.items():
                if k not in standard_keys and isinstance(v, str) and v.strip():
                    row[k] = v.strip()
            
            out_items.append(row)

        # Default item: accept default_item (new) or default (legacy).
        default_item = fp_spec.get("default_item") or fp_spec.get("default")
        if default_item is not None:
            if not isinstance(default_item, str) or not default_item.strip():
                raise ValueError(f"field_parameters[{fp_name!r}].default_item must be a non-empty string if provided")
            default_item = default_item.strip()
            if default_item.upper() not in valid_names:
                raise ValueError(
                    f"field_parameters[{fp_name!r}].default_item {default_item!r} is not a valid item name; valid: {sorted(valid_names)}"
                )
        else:
            # Default to first item.
            default_item = out_items[0]["name"] if out_items else None

        out_spec: dict[str, Any] = {"items": out_items}
        # Always regenerate DAX from items to keep it in sync
        generated_dax = _generate_field_parameter_dax(fp_name.strip(), out_items)
        out_spec["dax"] = generated_dax
        if default_item:
            out_spec["default_item"] = default_item
        out_fps[fp_name.strip()] = out_spec

    safe: dict[str, Any] = {"field_parameters": out_fps}
    _dump_yaml(path, safe)
    return safe


def save_what_if_parameters_yaml(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist What-If parameters to <project>/model/what_if_parameters.yaml."""

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    model_dir = root / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / "what_if_parameters.yaml"

    params_raw = payload.get("what_if_parameters")
    if params_raw is None:
        params_raw = {}
    if not isinstance(params_raw, Mapping):
        raise ValueError("what_if_parameters must be a mapping")

    out_params: dict[str, Any] = {}
    for name, spec in params_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("what_if_parameters keys must be non-empty strings")
        if not isinstance(spec, Mapping):
            raise ValueError(f"what_if_parameters[{name!r}] must be a mapping")

        min_val = spec.get("min")
        max_val = spec.get("max")
        step = spec.get("step")
        default_val = spec.get("default")
        format_str = spec.get("format")

        if not isinstance(min_val, (int, float)):
            raise ValueError(f"what_if_parameters[{name!r}].min must be a number")
        if not isinstance(max_val, (int, float)):
            raise ValueError(f"what_if_parameters[{name!r}].max must be a number")
        if not isinstance(step, (int, float)) or step <= 0:
            raise ValueError(f"what_if_parameters[{name!r}].step must be a positive number")
        if not isinstance(default_val, (int, float)):
            raise ValueError(f"what_if_parameters[{name!r}].default must be a number")
        if format_str is not None and not isinstance(format_str, str):
            raise ValueError(f"what_if_parameters[{name!r}].format must be a string if provided")

        if min_val > max_val:
            raise ValueError(f"what_if_parameters[{name!r}].min must be <= max")
        if default_val < min_val or default_val > max_val:
            raise ValueError(f"what_if_parameters[{name!r}].default must be between min and max")

        out_spec: dict[str, Any] = {
            "min": float(min_val),
            "max": float(max_val),
            "step": float(step),
            "default": float(default_val),
        }
        if format_str:
            out_spec["format"] = format_str.strip()
        out_params[name.strip()] = out_spec

    safe: dict[str, Any] = {"what_if_parameters": out_params}
    _dump_yaml(path, safe)
    return safe


# ------------------------------------------------------------------------------
# What-If Selections
# ------------------------------------------------------------------------------


def load_what_if_selections(project_path: str) -> dict[str, Any]:
    """Load persisted What-If parameter selections from <project>/reports/what_if_selections.yaml.

    Canonical shape:
      {
        "report": {param: value, ...},
        "page": {page_id: {param: value, ...}},
        "visual": {visual_id: {param: value, ...}},
      }

    Values are numeric (float).
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "reports" / "what_if_selections.yaml"
    raw = _load_yaml(path)
    if raw is None:
        return {"report": {}, "page": {}, "visual": {}}
    if not isinstance(raw, Mapping):
        raise ValueError("reports/what_if_selections.yaml must be a mapping")

    def _parse_value(v: Any) -> Optional[float]:
        if isinstance(v, (int, float)):
            return float(v)
        return None

    report = raw.get("report") or {}
    page = raw.get("page") or {}
    visual = raw.get("visual") or {}

    if not isinstance(report, Mapping):
        raise ValueError("what_if_selections.report must be a mapping")
    if not isinstance(page, Mapping):
        raise ValueError("what_if_selections.page must be a mapping")
    if not isinstance(visual, Mapping):
        raise ValueError("what_if_selections.visual must be a mapping")

    out_report: dict[str, float] = {}
    for k, v in report.items():
        if not isinstance(k, str) or not k.strip():
            continue
        val = _parse_value(v)
        if val is not None:
            out_report[k.strip()] = val

    out_page: dict[str, dict[str, float]] = {}
    for pid, m in page.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, float] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                continue
            val = _parse_value(v)
            if val is not None:
                inner[k.strip()] = val
        if inner:
            out_page[pid.strip()] = inner

    out_visual: dict[str, dict[str, float]] = {}
    for vid, m in visual.items():
        if not isinstance(vid, str) or not vid.strip():
            continue
        if not isinstance(m, Mapping):
            continue
        inner: dict[str, float] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                continue
            val = _parse_value(v)
            if val is not None:
                inner[k.strip()] = val
        if inner:
            out_visual[vid.strip()] = inner

    # Deterministic ordering.
    out_report = {k: out_report[k] for k in sorted(out_report.keys(), key=lambda s: s.upper())}
    out_page = {k: out_page[k] for k in sorted(out_page.keys(), key=lambda s: s.upper())}
    out_visual = {k: out_visual[k] for k in sorted(out_visual.keys(), key=lambda s: s.upper())}
    for k in list(out_page.keys()):
        inner = out_page[k]
        out_page[k] = {x: inner[x] for x in sorted(inner.keys(), key=lambda s: s.upper())}
    for k in list(out_visual.keys()):
        inner = out_visual[k]
        out_visual[k] = {x: inner[x] for x in sorted(inner.keys(), key=lambda s: s.upper())}

    return {"report": out_report, "page": out_page, "visual": out_visual}


def save_what_if_selections(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist What-If parameter selections to <project>/reports/what_if_selections.yaml."""

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "what_if_selections.yaml"

    report = payload.get("report") or {}
    page = payload.get("page") or {}
    visual = payload.get("visual") or {}

    if not isinstance(report, Mapping):
        raise ValueError("what_if_selections.report must be a mapping")
    if not isinstance(page, Mapping):
        raise ValueError("what_if_selections.page must be a mapping")
    if not isinstance(visual, Mapping):
        raise ValueError("what_if_selections.visual must be a mapping")

    def _parse_value(v: Any) -> Optional[float]:
        if isinstance(v, (int, float)):
            return float(v)
        return None

    out_report: dict[str, float] = {}
    for k, v in report.items():
        if not isinstance(k, str) or not k.strip():
            raise ValueError("what_if_selections.report keys must be non-empty strings")
        val = _parse_value(v)
        if val is None:
            raise ValueError(f"what_if_selections.report[{k!r}] must be a number")
        out_report[k.strip()] = val

    out_page: dict[str, dict[str, float]] = {}
    for pid, m in page.items():
        if not isinstance(pid, str) or not pid.strip():
            raise ValueError("what_if_selections.page keys must be non-empty strings")
        if not isinstance(m, Mapping):
            raise ValueError(f"what_if_selections.page[{pid!r}] must be a mapping")
        inner: dict[str, float] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(f"what_if_selections.page[{pid!r}] keys must be non-empty strings")
            val = _parse_value(v)
            if val is None:
                raise ValueError(f"what_if_selections.page[{pid!r}][{k!r}] must be a number")
            inner[k.strip()] = val
        if inner:
            out_page[pid.strip()] = inner

    out_visual: dict[str, dict[str, float]] = {}
    for vid, m in visual.items():
        if not isinstance(vid, str) or not vid.strip():
            raise ValueError("what_if_selections.visual keys must be non-empty strings")
        if not isinstance(m, Mapping):
            raise ValueError(f"what_if_selections.visual[{vid!r}] must be a mapping")
        inner: dict[str, float] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(f"what_if_selections.visual[{vid!r}] keys must be non-empty strings")
            val = _parse_value(v)
            if val is None:
                raise ValueError(f"what_if_selections.visual[{vid!r}][{k!r}] must be a number")
            inner[k.strip()] = val
        if inner:
            out_visual[vid.strip()] = inner

    # Deterministic ordering.
    out_report = {k: out_report[k] for k in sorted(out_report.keys(), key=lambda s: s.upper())}
    out_page = {k: out_page[k] for k in sorted(out_page.keys(), key=lambda s: s.upper())}
    out_visual = {k: out_visual[k] for k in sorted(out_visual.keys(), key=lambda s: s.upper())}
    for k in list(out_page.keys()):
        inner = out_page[k]
        out_page[k] = {x: inner[x] for x in sorted(inner.keys(), key=lambda s: s.upper())}
    for k in list(out_visual.keys()):
        inner = out_visual[k]
        out_visual[k] = {x: inner[x] for x in sorted(inner.keys(), key=lambda s: s.upper())}

    safe: dict[str, Any] = {"report": out_report, "page": out_page, "visual": out_visual}
    _dump_yaml(path, safe)
    return safe


def flatten_what_if_selections(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten What-If selections into a list of {scope, target, param, value} items."""

    flat: list[dict[str, Any]] = []
    report = payload.get("report") or {}
    pages = payload.get("pages") or {}
    visuals = payload.get("visuals") or {}

    if isinstance(report, Mapping):
        for p, v in report.items():
            if not isinstance(p, str) or not p.strip():
                continue
            if not isinstance(v, (int, float)):
                continue
            flat.append({"scope": "report", "target": None, "param": p.strip(), "value": float(v)})

    if isinstance(pages, Mapping):
        for pid, m in pages.items():
            if not isinstance(pid, str) or not pid.strip() or not isinstance(m, Mapping):
                continue
            for p, v in m.items():
                if not isinstance(p, str) or not p.strip():
                    continue
                if not isinstance(v, (int, float)):
                    continue
                flat.append({"scope": "page", "target": pid.strip(), "param": p.strip(), "value": float(v)})

    if isinstance(visuals, Mapping):
        for vid, m in visuals.items():
            if not isinstance(vid, str) or not vid.strip() or not isinstance(m, Mapping):
                continue
            for p, v in m.items():
                if not isinstance(p, str) or not p.strip():
                    continue
                if not isinstance(v, (int, float)):
                    continue
                flat.append({"scope": "visual", "target": vid.strip(), "param": p.strip(), "value": float(v)})

    # Sort by scope (report → page → visual) then target then param.
    scope_order = {"report": 0, "page": 1, "visual": 2}
    flat.sort(key=lambda x: (scope_order.get(x["scope"], 99), str(x["target"] or "").upper(), str(x["param"]).upper()))
    return flat

    # Sort by scope (report → page → visual) then target then param.
    scope_order = {"report": 0, "page": 1, "visual": 2}
    flat.sort(key=lambda x: (scope_order.get(x["scope"], 99), str(x["target"] or "").upper(), str(x["param"]).upper()))
    return flat


def resolve_effective_what_if_selections(
    payload: Mapping[str, Any], *, page_id: Optional[str], visual_id: Optional[str]
) -> dict[str, float]:
    """Resolve effective What-If selections for a given (page_id, visual_id).

    Precedence: report → page → visual (visual overrides page, page overrides report).
    Returns {param_name: value}.
    """

    result: dict[str, float] = {}

    report = payload.get("report") or {}
    pages = payload.get("pages") or {}
    visuals = payload.get("visuals") or {}

    # Apply report-level selections.
    if isinstance(report, Mapping):
        for p, v in report.items():
            if isinstance(p, str) and p.strip() and isinstance(v, (int, float)):
                result[p.strip().upper()] = float(v)

    # Apply page-level selections (override report).
    if page_id and isinstance(pages, Mapping):
        page_sel = pages.get(page_id)
        if page_sel is None:
            # Try case-insensitive match.
            for pid, m in pages.items():
                if isinstance(pid, str) and pid.strip().upper() == page_id.strip().upper():
                    page_sel = m
                    break
        if isinstance(page_sel, Mapping):
            for p, v in page_sel.items():
                if isinstance(p, str) and p.strip() and isinstance(v, (int, float)):
                    result[p.strip().upper()] = float(v)

    # Apply visual-level selections (override page).
    if visual_id and isinstance(visuals, Mapping):
        vis_sel = visuals.get(visual_id)
        if vis_sel is None:
            # Try case-insensitive match.
            for vid, m in visuals.items():
                if isinstance(vid, str) and vid.strip().upper() == visual_id.strip().upper():
                    vis_sel = m
                    break
        if isinstance(vis_sel, Mapping):
            for p, v in vis_sel.items():
                if isinstance(p, str) and p.strip() and isinstance(v, (int, float)):
                    result[p.strip().upper()] = float(v)

    return result


def load_calculation_groups_yaml(project_path: str) -> dict[str, Any]:
    """Load calculation groups YAML from <project>/model/calculation_groups.yaml.

    Falls back to legacy <project>/model/calc_groups.yaml if present.
    Returns the raw YAML object (mapping) or an empty mapping when missing.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    model_dir = root / "model"
    path = model_dir / "calculation_groups.yaml"
    if not path.exists():
        legacy = model_dir / "calc_groups.yaml"
        path = legacy if legacy.exists() else path

    raw = _load_yaml(path)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path.name} must be a mapping")
    return dict(raw)


def save_calculation_groups_yaml(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist canonical calculation groups to <project>/model/calculation_groups.yaml.

    Expected canonical shape:
      {"calculation_groups": { <group_name>: {"precedence": int, "items": [{"name": str, "expression": str, ...}]} }}

    The function preserves insertion order of groups/items from the provided payload.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    model_dir = root / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / "calculation_groups.yaml"

    safe: dict[str, Any] = {}
    groups_raw = payload.get("calculation_groups")
    if groups_raw is None:
        groups_raw = {}
    if not isinstance(groups_raw, Mapping):
        raise ValueError("calculation_groups must be a mapping")

    out_groups: dict[str, Any] = {}
    for g_name, g_spec in groups_raw.items():
        if not isinstance(g_name, str) or not g_name.strip():
            raise ValueError("calculation_groups keys must be non-empty strings")
        if not isinstance(g_spec, Mapping):
            raise ValueError(f"calculation_groups[{g_name!r}] must be a mapping")

        precedence = g_spec.get("precedence", 0)
        if precedence is None:
            precedence = 0
        if not isinstance(precedence, int):
            raise ValueError(f"calculation_groups[{g_name!r}].precedence must be an int")

        items_raw = g_spec.get("items")
        if items_raw is None:
            items_raw = []
        if not isinstance(items_raw, list):
            raise ValueError(f"calculation_groups[{g_name!r}].items must be a list")

        out_items: list[dict[str, Any]] = []
        for i, it in enumerate(items_raw):
            if not isinstance(it, Mapping):
                raise ValueError(f"calculation_groups[{g_name!r}].items[{i}] must be an object")
            nm = it.get("name")
            expr = it.get("expression")
            fmt = it.get("format_string")
            if not isinstance(nm, str) or not nm.strip():
                raise ValueError(f"calculation_groups[{g_name!r}].items[{i}].name is required")
            if not isinstance(expr, str) or not expr.strip():
                raise ValueError(f"calculation_groups[{g_name!r}].items[{i}].expression is required")

            row: dict[str, Any] = {"name": nm.strip(), "expression": expr.strip()}
            if isinstance(fmt, str) and fmt.strip():
                row["format_string"] = fmt.strip()
            out_items.append(row)

        out_groups[g_name.strip()] = {"precedence": int(precedence), "items": out_items}

    safe["calculation_groups"] = out_groups
    _dump_yaml(path, safe)
    return safe


def upsert_table_yaml(
    project_path: str,
    *,
    name: str,
    columns: list[Mapping[str, Any]] | None = None,
    source: Optional[Mapping[str, Any]] = None,
    expression: Optional[str] = None,
    is_calculated: Optional[bool] = None,
    description: Optional[str] = None,
    folder: Optional[str] = None,
    table_type: Optional[str] = None,
    storage_mode: Optional[str] = None,
) -> None:
    """Create/update a table YAML file under <project>/model/tables/<name>.yaml.

    This is used by the runtime authoring UI for calculated tables.
    Preserves unknown top-level fields when updating an existing file.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    tables_dir = root / "model" / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    path = tables_dir / f"{name}.yaml"
    raw = _load_yaml(path)
    obj: MutableMapping[str, Any]
    if raw is None:
        obj = {}
    elif isinstance(raw, Mapping):
        obj = dict(raw)  # preserve unknown fields
    else:
        raise ValueError(f"Table file must be a mapping: {path}")

    obj["name"] = str(name)

    if columns is not None:
        cols = [dict(c) for c in columns]
        cols.sort(key=lambda d: str(d.get("name", "")).strip().upper())
        obj["columns"] = cols
    elif "columns" not in obj:
        obj["columns"] = []

    if source is None:
        obj.pop("source", None)
    else:
        obj["source"] = dict(source)

    if expression is None or not str(expression).strip():
        obj.pop("expression", None)
    else:
        obj["expression"] = str(expression)

    if description is None or not str(description).strip():
        obj.pop("description", None)
    else:
        obj["description"] = str(description)

    if folder is None or not str(folder).strip():
        obj.pop("folder", None)
    else:
        obj["folder"] = str(folder)

    if table_type is None or str(table_type).strip().lower() not in ("fact", "dim", "bridge"):
        obj.pop("table_type", None)
    else:
        obj["table_type"] = str(table_type).strip().lower()

    if is_calculated is None:
        # If expression is present, keep is_calculated true (or omit).
        if "expression" in obj:
            obj["is_calculated"] = True
        else:
            obj.pop("is_calculated", None)
    else:
        obj["is_calculated"] = bool(is_calculated)

    # Guardrail: physical source tables cannot be marked calculated unless they
    # also define an expression. Keep persisted YAML loader-compatible.
    if "source" in obj and "expression" not in obj and bool(obj.get("is_calculated", False)):
        obj["is_calculated"] = False

    # Phase 9: persist storage_mode if provided.
    if storage_mode is not None and str(storage_mode).strip():
        obj["storage_mode"] = str(storage_mode).strip().lower()
    else:
        obj.pop("storage_mode", None)

    _dump_yaml(path, obj)


def delete_table_yaml(project_path: str, *, name: str) -> bool:
    """Delete <project>/model/tables/<name>.yaml. Returns True if removed."""

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "model" / "tables" / f"{name}.yaml"
    if not path.exists():
        return False
    path.unlink()
    return True


def upsert_column_yaml(
    project_path: str,
    *,
    table: str,
    name: str,
    col_type: str = "UNKNOWN",
    source: Optional[Mapping[str, Any]] = None,
    expression: Optional[str] = None,
    is_calculated: Optional[bool] = None,
    description: Optional[str] = None,
    folder: Optional[str] = None,
) -> None:
    """Upsert a column entry in <project>/model/tables/<table>.yaml.

    Preserves unknown top-level fields and unknown column fields.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "model" / "tables" / f"{table}.yaml"
    if not path.exists():
        raise FileNotFoundError(str(path))

    raw = _load_yaml(path)
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Table file must be a mapping: {path}")

    obj: MutableMapping[str, Any] = dict(raw)
    cols_raw = obj.get("columns")
    if cols_raw is None:
        cols: MutableSequence[Any] = []
        obj["columns"] = cols
    elif isinstance(cols_raw, list):
        cols = cols_raw
    else:
        raise ValueError(f"{path}: columns must be a list")

    target_key = _norm_key(name)
    found = False
    for item in cols:
        if not isinstance(item, MutableMapping):
            continue
        existing_name = item.get("name")
        if isinstance(existing_name, str) and _norm_key(existing_name) == target_key:
            item["name"] = str(name)
            item["type"] = str(col_type)

            if source is None:
                item.pop("source", None)
            else:
                item["source"] = dict(source)

            if expression is None or not str(expression).strip():
                item.pop("expression", None)
            else:
                item["expression"] = str(expression)

            if description is None or not str(description).strip():
                item.pop("description", None)
            else:
                item["description"] = str(description)

            if folder is None or not str(folder).strip():
                item.pop("folder", None)
            else:
                item["folder"] = str(folder)

            if is_calculated is None:
                if "expression" in item:
                    item["is_calculated"] = True
                else:
                    item.pop("is_calculated", None)
            else:
                item["is_calculated"] = bool(is_calculated)

            found = True
            break

    if not found:
        new_item: MutableMapping[str, Any] = {"name": str(name), "type": str(col_type)}
        if source is not None:
            new_item["source"] = dict(source)
        if expression is not None and str(expression).strip():
            new_item["expression"] = str(expression)
            new_item["is_calculated"] = True if is_calculated is None else bool(is_calculated)
        elif is_calculated is not None:
            new_item["is_calculated"] = bool(is_calculated)
        if description is not None and str(description).strip():
            new_item["description"] = str(description)
        if folder is not None and str(folder).strip():
            new_item["folder"] = str(folder)
        cols.append(new_item)

    # Deterministic ordering: sort mapping items by column name (case-insensitive).
    sortable: list[tuple[str, Any]] = []
    rest: list[Any] = []
    for it in list(cols):
        if isinstance(it, Mapping):
            sortable.append((str(it.get("name", "")).strip().upper(), it))
        else:
            rest.append(it)
    sortable.sort(key=lambda t: t[0])
    cols[:] = [it for _k, it in sortable] + rest

    _dump_yaml(path, obj)


def delete_column_yaml(project_path: str, *, table: str, name: str) -> bool:
    """Delete a column entry from <project>/model/tables/<table>.yaml.

    Returns True if a column was removed.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "model" / "tables" / f"{table}.yaml"
    if not path.exists():
        return False

    raw = _load_yaml(path)
    if raw is None or not isinstance(raw, Mapping):
        return False

    obj: MutableMapping[str, Any] = dict(raw)
    cols_raw = obj.get("columns")
    if not isinstance(cols_raw, list):
        return False

    target_key = _norm_key(name)
    before = len(cols_raw)
    kept: list[Any] = []
    for item in cols_raw:
        if not isinstance(item, Mapping):
            kept.append(item)
            continue
        existing_name = item.get("name")
        if isinstance(existing_name, str) and _norm_key(existing_name) == target_key:
            continue
        kept.append(item)

    if len(kept) == before:
        return False

    sortable: list[tuple[str, Any]] = []
    rest: list[Any] = []
    for it in kept:
        if isinstance(it, Mapping):
            sortable.append((str(it.get("name", "")).strip().upper(), it))
        else:
            rest.append(it)
    sortable.sort(key=lambda t: t[0])
    obj["columns"] = [it for _k, it in sortable] + rest
    _dump_yaml(path, obj)
    return True


# ── Page persistence ──────────────────────────────────────────────


def save_pages(project_path: str, pages: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Persist the pages list to ``reports/pages.yaml``.

    Each page must have ``id`` (non-empty str) and ``title`` (non-empty str).
    ``order`` is optional (int).  Duplicates (case-insensitive id) are rejected.

    Returns the canonicalized list that was written.
    """
    reports_dir = Path(project_path) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "pages.yaml"

    canonical: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, p in enumerate(pages):
        if not isinstance(p, Mapping):
            raise ValueError(f"pages[{i}] must be an object")
        page_id = p.get("id")
        title = p.get("title")
        order = p.get("order")
        if not isinstance(page_id, str) or not page_id.strip():
            raise ValueError(f"pages[{i}].id is required")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"pages[{i}].title is required")
        norm = page_id.strip().upper()
        if norm in seen:
            raise ValueError(f"Duplicate page id: {page_id.strip()!r}")
        seen.add(norm)
        entry: dict[str, Any] = {"id": page_id.strip(), "title": title.strip()}
        if order is not None:
            if not isinstance(order, int):
                raise ValueError(f"pages[{i}].order must be an int if provided")
            entry["order"] = order
        hidden = p.get("hidden")
        if hidden:
            entry["hidden"] = True
        page_type = p.get("page_type")
        if isinstance(page_type, str) and page_type.strip():
            entry["page_type"] = page_type.strip()
        canonical.append(entry)

    _dump_yaml(path, {"pages": canonical})
    return canonical


def save_hierarchies_yaml(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist hierarchy definitions to <project>/model/hierarchies.yaml.

    Expected payload shape:
      {
        "hierarchies": {
          "<hierarchy_name>": {
            "table": "<table_name>",
            "levels": [
              {"column": "<col>", "name": "<display_name>"},
              ...
            ]
          }
        }
      }
    """
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    model_dir = root / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / "hierarchies.yaml"

    h_raw = payload.get("hierarchies")
    if h_raw is None:
        h_raw = {}
    if not isinstance(h_raw, Mapping):
        raise ValueError("hierarchies must be a mapping")

    out_hierarchies: dict[str, Any] = {}
    for h_name, h_spec in h_raw.items():
        if not isinstance(h_name, str) or not h_name.strip():
            raise ValueError("hierarchy keys must be non-empty strings")
        if not isinstance(h_spec, Mapping):
            raise ValueError(f"hierarchies[{h_name!r}] must be a mapping")

        table = h_spec.get("table")
        if not isinstance(table, str) or not table.strip():
            raise ValueError(f"hierarchies[{h_name!r}].table is required")

        levels_raw = h_spec.get("levels")
        if not isinstance(levels_raw, list) or len(levels_raw) < 2:
            raise ValueError(
                f"hierarchies[{h_name!r}].levels must be a list with at least 2 levels"
            )

        out_levels: list[dict[str, str]] = []
        names_seen: set[str] = set()
        for i, lvl in enumerate(levels_raw):
            if not isinstance(lvl, Mapping):
                raise ValueError(f"hierarchies[{h_name!r}].levels[{i}] must be a mapping")
            col = lvl.get("column")
            if not isinstance(col, str) or not col.strip():
                raise ValueError(f"hierarchies[{h_name!r}].levels[{i}].column is required")
            display_name = lvl.get("name")
            if display_name is None:
                display_name = col.strip()
            elif not isinstance(display_name, str) or not display_name.strip():
                raise ValueError(
                    f"hierarchies[{h_name!r}].levels[{i}].name must be a non-empty string if provided"
                )
            else:
                display_name = display_name.strip()

            if display_name.upper() in names_seen:
                raise ValueError(
                    f"hierarchies[{h_name!r}] has duplicate level name: {display_name!r}"
                )
            names_seen.add(display_name.upper())

            out_levels.append({"column": col.strip(), "name": display_name})

        out_hierarchies[h_name.strip()] = {
            "table": table.strip(),
            "levels": out_levels,
        }

    _dump_yaml(path, {"hierarchies": out_hierarchies})
    return out_hierarchies


# ---------------------------------------------------------------------------
#  Bookmarks (Phase 1.5)
# ---------------------------------------------------------------------------


def load_bookmarks(project_path: str) -> dict[str, Any]:
    """Load bookmarks from <project>/reports/bookmarks.yaml.

    Returns canonical shape:
      {"bookmarks": [ {id, name, description?, created_at, updated_at,
                        current_page_id, filters?, slicer_selections?,
                        interaction_selections?}, ... ]}
    """
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "reports" / "bookmarks.yaml"
    raw = _load_yaml(path)
    if raw is None:
        return {"bookmarks": []}
    if not isinstance(raw, Mapping):
        raise ValueError("reports/bookmarks.yaml must be a mapping")

    items = raw.get("bookmarks")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError("bookmarks must be a list")

    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, Mapping):
            continue
        out.append(_canonicalize_bookmark(it))

    # Enforce unique ids.
    seen: set[str] = set()
    for bk in out:
        bid = str(bk.get("id") or "")
        key = bid.upper()
        if key in seen:
            raise ValueError(f"Duplicate bookmark.id: {bid!r}")
        seen.add(key)

    return {"bookmarks": _sorted_bookmarks(out)}


def save_bookmarks(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist bookmarks to <project>/reports/bookmarks.yaml (bulk replace)."""
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "bookmarks.yaml"

    items_in = payload.get("bookmarks") if isinstance(payload, Mapping) else None
    if items_in is None:
        items_in = []
    if not isinstance(items_in, list):
        raise ValueError("bookmarks must be a list")

    out: list[dict[str, Any]] = []
    for it in items_in:
        if not isinstance(it, Mapping):
            continue
        out.append(_canonicalize_bookmark(it))

    seen: set[str] = set()
    for bk in out:
        bid = str(bk.get("id") or "")
        key = bid.upper()
        if key in seen:
            raise ValueError(f"Duplicate bookmark.id: {bid!r}")
        seen.add(key)

    canon = {"bookmarks": _sorted_bookmarks(out)}
    _dump_yaml(path, canon)
    return canon


def _canonicalize_bookmark(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a single bookmark dict into canonical shape."""
    bid = str(item.get("id") or "").strip()
    if not bid:
        raise ValueError("bookmark.id is required")

    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("bookmark.name is required")

    description = str(item.get("description") or "").strip()
    created_at = str(item.get("created_at") or "").strip()
    updated_at = str(item.get("updated_at") or "").strip()
    current_page_id = str(item.get("current_page_id") or "").strip()

    # Filters: preserve as-is (list of filter objects, already validated on create).
    filters = item.get("filters")
    if filters is not None and not isinstance(filters, list):
        raise ValueError("bookmark.filters must be a list")
    # Deep-copy to avoid mutation.
    if isinstance(filters, list):
        filters = [dict(f) if isinstance(f, Mapping) else f for f in filters]
    else:
        filters = []

    # Slicer selections: map of slicer_instance_id → selected_values list.
    slicer_selections = item.get("slicer_selections")
    if slicer_selections is not None and not isinstance(slicer_selections, Mapping):
        raise ValueError("bookmark.slicer_selections must be a mapping")
    if isinstance(slicer_selections, Mapping):
        slicer_selections = {
            str(k): list(v) if isinstance(v, list) else []
            for k, v in slicer_selections.items()
        }
    else:
        slicer_selections = {}

    # Interaction selections: list of {source_visual_id, filters:[...]} objects.
    interaction_selections = item.get("interaction_selections")
    if interaction_selections is not None and not isinstance(interaction_selections, list):
        raise ValueError("bookmark.interaction_selections must be a list")
    if isinstance(interaction_selections, list):
        interaction_selections = [
            dict(ix) if isinstance(ix, Mapping) else ix
            for ix in interaction_selections
        ]
    else:
        interaction_selections = []

    # Capture options (Power BI-style): which dimensions of state the bookmark captures.
    # All default to True for backwards compatibility.
    capture_page = bool(item.get("capture_page", True))
    capture_data = bool(item.get("capture_data", True))
    capture_display = bool(item.get("capture_display", True))

    # Visual visibility: map of visual_id → visible (bool).
    # Captured when capture_display is True.
    visual_visibility = item.get("visual_visibility")
    if visual_visibility is not None and not isinstance(visual_visibility, Mapping):
        raise ValueError("bookmark.visual_visibility must be a mapping")
    if isinstance(visual_visibility, Mapping):
        visual_visibility = {str(k): bool(v) for k, v in visual_visibility.items()}
    else:
        visual_visibility = {}

    out: dict[str, Any] = {
        "id": bid,
        "name": name,
        "current_page_id": current_page_id,
        "filters": filters,
        "slicer_selections": slicer_selections,
        "interaction_selections": interaction_selections,
        "capture_page": capture_page,
        "capture_data": capture_data,
        "capture_display": capture_display,
        "visual_visibility": visual_visibility,
    }
    if description:
        out["description"] = description
    if created_at:
        out["created_at"] = created_at
    if updated_at:
        out["updated_at"] = updated_at

    return out


def _sorted_bookmarks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort bookmarks by name (case-insensitive), then id."""
    return sorted(items, key=lambda b: (str(b.get("name") or "").upper(), str(b.get("id") or "").upper()))


# ---------------------------------------------------------------------------
# Stories (Phase 23E)
# ---------------------------------------------------------------------------

def load_stories(project_path: str) -> dict[str, Any]:
    """Load stories from <project>/reports/stories.yaml.

    Returns canonical shape:
      {"stories": [ {id, name, slides: [{id, page_id, title, narration,
                      captured_state?, bookmark_id?}, ...] }, ... ]}
    """
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    path = root / "reports" / "stories.yaml"
    raw = _load_yaml(path)
    if raw is None:
        return {"stories": []}
    if not isinstance(raw, Mapping):
        raise ValueError("reports/stories.yaml must be a mapping")

    items = raw.get("stories")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError("stories must be a list")

    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, Mapping):
            continue
        out.append(_canonicalize_story(it))

    # Enforce unique story ids.
    seen: set[str] = set()
    for st in out:
        sid = str(st.get("id") or "")
        key = sid.upper()
        if key in seen:
            raise ValueError(f"Duplicate story.id: {sid!r}")
        seen.add(key)

    return {"stories": out}


def save_stories(project_path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist stories to <project>/reports/stories.yaml (bulk replace)."""
    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "stories.yaml"

    items_in = payload.get("stories") if isinstance(payload, Mapping) else None
    if items_in is None:
        items_in = []
    if not isinstance(items_in, list):
        raise ValueError("stories must be a list")

    out: list[dict[str, Any]] = []
    for it in items_in:
        if not isinstance(it, Mapping):
            continue
        out.append(_canonicalize_story(it))

    seen: set[str] = set()
    for st in out:
        sid = str(st.get("id") or "")
        key = sid.upper()
        if key in seen:
            raise ValueError(f"Duplicate story.id: {sid!r}")
        seen.add(key)

    canon = {"stories": out}
    _dump_yaml(path, canon)
    return canon


def _canonicalize_story(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a single story dict into canonical shape."""
    sid = str(item.get("id") or "").strip()
    if not sid:
        raise ValueError("story.id is required")

    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("story.name is required")

    slides_raw = item.get("slides")
    if slides_raw is None:
        slides_raw = []
    if not isinstance(slides_raw, list):
        raise ValueError("story.slides must be a list")

    slides: list[dict[str, Any]] = []
    slide_ids: set[str] = set()
    for s in slides_raw:
        if not isinstance(s, Mapping):
            continue
        cs = _canonicalize_slide(s)
        csid = str(cs.get("id") or "").upper()
        if csid in slide_ids:
            raise ValueError(f"Duplicate slide.id: {cs.get('id')!r} in story {sid!r}")
        slide_ids.add(csid)
        slides.append(cs)

    return {
        "id": sid,
        "name": name,
        "slides": slides,
        **({
            "description": str(item.get("description") or "").strip(),
        } if item.get("description") else {}),
        **({
            "navigator_style": str(item.get("navigator_style") or "").strip(),
        } if item.get("navigator_style") else {}),
        **({
            "sizing": str(item.get("sizing") or "").strip(),
        } if item.get("sizing") else {}),
    }


def _canonicalize_slide(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a single slide dict into canonical shape."""
    slide_id = str(item.get("id") or "").strip()
    if not slide_id:
        raise ValueError("slide.id is required")

    page_id = str(item.get("page_id") or "").strip()
    title = str(item.get("title") or "").strip()
    narration = str(item.get("narration") or "").strip()
    bookmark_id = str(item.get("bookmark_id") or "").strip() or None

    # captured_state: same schema as bookmark state
    captured_state_raw = item.get("captured_state")
    captured_state: dict[str, Any] | None = None
    if isinstance(captured_state_raw, Mapping):
        captured_state = _canonicalize_captured_state(captured_state_raw)

    out: dict[str, Any] = {
        "id": slide_id,
        "page_id": page_id,
        "title": title,
        "narration": narration,
    }
    if captured_state is not None:
        out["captured_state"] = captured_state
    if bookmark_id:
        out["bookmark_id"] = bookmark_id
    annotation = str(item.get("annotation") or "").strip()
    if annotation:
        out["annotation"] = annotation

    return out


def _canonicalize_captured_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize captured_state into canonical shape (same schema as bookmark state)."""
    # Filters
    filters = state.get("filters")
    if filters is not None and not isinstance(filters, list):
        raise ValueError("captured_state.filters must be a list")
    if isinstance(filters, list):
        filters = [dict(f) if isinstance(f, Mapping) else f for f in filters]
    else:
        filters = []

    # Slicer selections
    slicer_selections = state.get("slicer_selections")
    if slicer_selections is not None and not isinstance(slicer_selections, Mapping):
        raise ValueError("captured_state.slicer_selections must be a mapping")
    if isinstance(slicer_selections, Mapping):
        slicer_selections = {
            str(k): list(v) if isinstance(v, list) else []
            for k, v in slicer_selections.items()
        }
    else:
        slicer_selections = {}

    # Interaction selections
    interaction_selections = state.get("interaction_selections")
    if interaction_selections is not None and not isinstance(interaction_selections, list):
        raise ValueError("captured_state.interaction_selections must be a list")
    if isinstance(interaction_selections, list):
        interaction_selections = [
            dict(ix) if isinstance(ix, Mapping) else ix
            for ix in interaction_selections
        ]
    else:
        interaction_selections = []

    # Visual visibility
    visual_visibility = state.get("visual_visibility")
    if visual_visibility is not None and not isinstance(visual_visibility, Mapping):
        raise ValueError("captured_state.visual_visibility must be a mapping")
    if isinstance(visual_visibility, Mapping):
        visual_visibility = {str(k): bool(v) for k, v in visual_visibility.items()}
    else:
        visual_visibility = {}

    return {
        "filters": filters,
        "slicer_selections": slicer_selections,
        "interaction_selections": interaction_selections,
        "visual_visibility": visual_visibility,
    }
