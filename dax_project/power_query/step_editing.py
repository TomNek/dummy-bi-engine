from __future__ import annotations

from typing import Any, Mapping

from .parser import parse_m_query
from .parity_gap_report import build_power_query_parity_gap_report
from .transpiler import build_neutral_transform_plan


def _step_map(raw_m: str) -> dict[str, dict[str, Any]]:
    steps, _result_expression, _functions, diagnostics = parse_m_query(raw_m)
    return {
        step.id: {
            "id": step.id,
            "dependencies": list(step.dependencies or []),
            "operation": step.operation,
        }
        for step in steps
    } | {
        "_diagnostics": {
            "parse_diagnostics": [diag.to_dict() for diag in diagnostics],
        }
    }


def _dependents(steps: Mapping[str, Mapping[str, Any]], step_id: str) -> list[str]:
    target = step_id.strip().upper()
    out: list[str] = []
    for key, step in steps.items():
        if key.startswith("_"):
            continue
        deps = [str(dep).strip().upper() for dep in step.get("dependencies") or []]
        if target in deps:
            out.append(str(step.get("id") or key))
    return sorted(set(out), key=str.upper)


def build_power_query_applied_step_edit_preview(
    *,
    before_raw_m: str,
    after_raw_m: str,
    operation: str,
    step_id: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    before_steps = _step_map(before_raw_m)
    after_steps = _step_map(after_raw_m)
    before_ids = [key for key in before_steps if not key.startswith("_")]
    after_ids = [key for key in after_steps if not key.startswith("_")]
    target = step_id or ""
    transform_plan = build_neutral_transform_plan(after_raw_m, project_root=project_root)
    parity_report = build_power_query_parity_gap_report(after_raw_m, project_root=project_root)
    dependency_impact = {
        "removed_step_ids": [step for step in before_ids if step not in after_ids],
        "added_step_ids": [step for step in after_ids if step not in before_ids],
        "reordered": before_ids != after_ids and sorted(before_ids) == sorted(after_ids),
        "direct_dependents_before": _dependents(before_steps, target) if target else [],
        "direct_dependents_after": _dependents(after_steps, target) if target else [],
    }
    return {
        "operation": operation,
        "step_id": step_id,
        "draft": True,
        "save_required": True,
        "dependency_impact": dependency_impact,
        "parse_diagnostics": after_steps.get("_diagnostics", {}).get("parse_diagnostics", []),
        "fold_frontier": transform_plan.get("fold_frontier"),
        "source_bindings": transform_plan.get("source_bindings") or [],
        "source_binding_count": len(transform_plan.get("source_bindings") or []),
        "parity_gap_summary": parity_report.get("summary") or {},
        "parity_gap_groups": parity_report.get("groups") or {},
    }
