from __future__ import annotations

from typing import Any, Mapping

from .parser import parse_m_query
from .graph import build_power_query_graph
from .source_map import map_source_bindings_from_m
from .transpiler import build_neutral_transform_plan

_REPORT_GROUPS = (
    "exact_local_pending",
    "folding_pending",
    "binding_pending",
    "live_certification_pending",
    "ui_authoring_pending",
)


def _append(groups: dict[str, list[dict[str, Any]]], group: str, item: Mapping[str, Any]) -> None:
    if group not in groups:
        groups[group] = []
    normalized = dict(item)
    key = tuple(sorted((str(k), str(v)) for k, v in normalized.items()))
    existing = {
        tuple(sorted((str(k), str(v)) for k, v in old.items()))
        for old in groups[group]
    }
    if key not in existing:
        groups[group].append(normalized)


def build_power_query_parity_gap_report(
    raw_m: str,
    *,
    project_root: str | None = None,
    schema_probe_mode: str = "plan",
    credential_profile_id: str | None = None,
    fixture_mode: bool = True,
    execution_target: str = "duckdb",
    query_id: str | None = None,
    query_entries: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Group remaining parity work for a query into actionable buckets.

    The report intentionally separates exact-execution parity from SQL folding:
    local exact execution can be acceptable parity while still producing a
    folding-pending item when pushdown equivalence is not proven.
    """

    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in _REPORT_GROUPS}
    bindings = [binding.to_dict() for binding in map_source_bindings_from_m(raw_m)]
    steps, _result_expression, functions, _diagnostics = parse_m_query(raw_m)
    plan = build_neutral_transform_plan(
        raw_m,
        project_root=project_root,
        schema_probe_mode=schema_probe_mode,
        credential_profile_id=credential_profile_id,
        fixture_mode=fixture_mode,
        execution_target=execution_target,
    )

    graph_node: Mapping[str, Any] = {}
    resolved_source_bindings: list[Mapping[str, Any]] = []
    if query_id and query_entries:
        graph = build_power_query_graph(list(query_entries))
        graph_node = next(
            (
                item for item in graph.get("nodes", [])
                if isinstance(item, Mapping) and str(item.get("id") or "").strip().upper() == query_id.strip().upper()
            ),
            {},
        )
        resolved_source_bindings = [
            item for item in graph_node.get("resolved_source_bindings") or []
            if isinstance(item, Mapping)
        ]

    if raw_m.strip() and not bindings and not resolved_source_bindings:
        _append(
            groups,
            "binding_pending",
            {
                "status": "pending",
                "reason": "No normalized source binding could be inferred from this M query.",
                "next_action": "Add parser-backed binding for the source/navigation shape.",
            },
        )

    for binding in bindings:
        source_step_id = binding.get("source_step_id")
        binding_resolved_via_graph = (
            str(binding.get("source_type") or "") == "query_reference"
            and any(item.get("resolved") for item in resolved_source_bindings)
        )
        if not binding.get("schema_probe_candidate") and not binding_resolved_via_graph:
            _append(
                groups,
                "binding_pending",
                {
                    "status": "pending",
                    "source_type": binding.get("source_type"),
                    "source_step_id": source_step_id,
                    "reason": "Binding has no schema-probe candidate yet.",
                    "next_action": "Teach the adapter registry how to probe this source shape.",
                },
            )
        if binding.get("confidence") not in {"high", "medium"}:
            _append(
                groups,
                "binding_pending",
                {
                    "status": "pending",
                    "source_type": binding.get("source_type"),
                    "source_step_id": source_step_id,
                    "reason": f"Binding confidence is {binding.get('confidence') or 'unknown'}.",
                    "next_action": "Normalize this source/navigation form through the parser-backed binder.",
                },
            )
        source_block = binding.get("source_block") if isinstance(binding.get("source_block"), Mapping) else {}
        requires_credentials = bool((binding.get("schema_probe_candidate") or {}).get("requires_credentials"))
        if requires_credentials and not credential_profile_id and not source_block.get("credential_profile_id"):
            _append(
                groups,
                "live_certification_pending",
                {
                    "status": "pending",
                    "source_type": binding.get("source_type"),
                    "connector_id": binding.get("connector_id"),
                    "source_step_id": source_step_id,
                    "reason": "Live source requires a credential profile before production certification.",
                    "next_action": "Run Connector Setup Wizard or provide a certified credential profile.",
                },
            )

    if query_id and query_entries:
        unresolved_query_references = [
            {
                "source_step_id": item.get("source_step_id"),
                "query_id": item.get("target_query_id"),
                "status": "unresolved_target_query",
                "via_query_references": item.get("via_query_references") or [],
            }
            for item in resolved_source_bindings
            if not item.get("resolved")
        ]
    else:
        unresolved_query_references = [
            {
                "binding_id": binding.get("binding_id"),
                "source_step_id": binding.get("source_step_id"),
                "query_id": ref.get("query_id"),
                "status": "unresolved_without_query_graph_context",
            }
            for binding in bindings
            for ref in (binding.get("query_references") or [])
            if isinstance(ref, Mapping) and ref.get("query_id")
        ]
    schema_probe_results_by_binding = [
        {
            "binding_id": binding.get("binding_id"),
            "source_type": binding.get("source_type"),
            "source_step_id": binding.get("source_step_id"),
            "schema_probe_candidate": binding.get("schema_probe_candidate"),
            "status": "candidate" if binding.get("schema_probe_candidate") else "not_available",
        }
        for binding in bindings
    ]
    if resolved_source_bindings:
        schema_probe_results_by_binding.extend(
            {
                "binding_id": f"resolved:{idx}",
                "source_type": binding.get("source_type"),
                "source_step_id": binding.get("source_step_id"),
                "schema_probe_candidate": binding.get("schema_probe_candidate"),
                "status": "resolved_inherited" if binding.get("resolved") else "unresolved",
                "via_query_references": binding.get("via_query_references") or [],
            }
            for idx, binding in enumerate(resolved_source_bindings, start=1)
        )
    folder_steps = [
        step.id
        for step in steps
        if str(step.operation or "").upper() in {"FOLDER.FILES", "FOLDER.CONTENTS"}
        or "Folder.Files" in step.expression
        or "Folder.Contents" in step.expression
    ]
    helper_steps = [
        step.id
        for step in steps
        if "Transform File" in step.id or "Sample File" in step.id or "Parameter" in step.id
    ]
    error_functions = [
        fn for fn in functions if fn in {"Table.RemoveRowsWithErrors", "Table.ReplaceErrorValues", "Table.SelectRowsWithErrors"}
    ]
    culture_markers = sorted({marker for marker in ("en-US", "de-DE", "fr-FR", "ja-JP") if marker in raw_m})
    timezone_functions = [fn for fn in functions if fn.startswith("DateTimeZone.") or fn == "#datetimezone"]

    blockers: list[Mapping[str, Any]] = []
    for key in ("blockers",):
        blockers.extend(item for item in plan.get(key) or [] if isinstance(item, Mapping))
    for section_key in ("relational_ast", "duckdb_sql", "connector_native_plan"):
        section = plan.get(section_key)
        if isinstance(section, Mapping):
            blockers.extend(item for item in section.get("blockers") or [] if isinstance(item, Mapping))
    for blocker in blockers:
        _append(
            groups,
            "folding_pending",
            {
                "status": "pending",
                "step_id": blocker.get("step_id"),
                "reason": blocker.get("reason") or "Step cannot be folded with proven equivalence yet.",
                "next_action": "Keep local exact execution or add a golden local-vs-folded equivalence test before promotion.",
            },
        )

    for item in plan.get("local_exact_reasons") or []:
        if not isinstance(item, Mapping):
            continue
        _append(
            groups,
            "exact_local_pending",
            {
                "status": "tracked",
                "step_id": item.get("step_id"),
                "reason": item.get("reason") or "Step executes through the local exact evaluator.",
                "next_action": "Add exact local golden tests, then consider folding only if equivalent.",
            },
        )

    _append(
        groups,
        "ui_authoring_pending",
        {
            "status": "pending",
            "capability": "query_level_authoring",
            "reason": "Applied-step add/delete/rename/reorder/settings draft edits are available; query duplicate/reference, load toggle, and source settings still need first-class UI/API parity.",
            "next_action": "Finish draft-only query-level authoring operations with dependency, source-binding, and fold-frontier previews.",
        },
    )

    return {
        "version": "pq-parity-gap-report.v1",
        "definition": "100% parity means exact Power Query behavior is executable or visibly local/blocked with truthful foldability.",
        "summary": {group: len(items) for group, items in groups.items()},
        "groups": groups,
        "source_bindings": bindings,
        "resolved_source_bindings": resolved_source_bindings,
        "unresolved_query_references": unresolved_query_references,
        "schema_probe_results_by_binding": schema_probe_results_by_binding,
        "folder_combine_bundle": {
            "status": "detected" if folder_steps or helper_steps else "not_detected",
            "folder_step_ids": folder_steps,
            "helper_step_ids": helper_steps,
            "pushdown_policy": "local_exact_unless_homogeneous_schema_union_is_proven",
        },
        "m_error_provenance": {
            "status": "tracked" if error_functions else "not_detected",
            "functions": error_functions,
            "folding_policy": "fold_only_when_proven_equivalent_error_flags_exist",
        },
        "culture_timezone_profile": {
            "cultures": culture_markers,
            "timezone_functions": timezone_functions,
            "folding_policy": "explicit_template_and_golden_equivalence_required",
        },
        "applied_step_edit_preview": None,
        "fold_frontier": plan.get("fold_frontier"),
        "execution_strategy": plan.get("execution_strategy"),
        "parity_status": plan.get("parity_status"),
    }
