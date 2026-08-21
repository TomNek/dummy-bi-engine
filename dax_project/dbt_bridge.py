"""dbt import/export bridge for Dummy BI semantic models.

This module is intentionally conservative. It does not try to make dbt a
drop-in replacement for the native DAX compatibility compiler. Instead it
classifies what can be represented safely in dbt/MetricFlow, emits validation
artifacts for everything else, and imports the subset of dbt metadata that maps
cleanly back into the Dummy BI datamodel.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from dax_engine.ir import (
    CalcGroupItemRef,
    ColumnRef,
    DaxBinaryOp,
    DaxFunction,
    Expr,
    HierarchyRef,
    Literal,
    MeasureRef,
    ParamRef,
    ScalarExpr,
    SelectedMeasureRef,
    TableRef,
    WhatIfRef,
)

from .model import Column, MeasureDefinition, PageDefinition, Relationship, SemanticModel, Table, VisualDefinition


METRICFLOW_COMPATIBLE = "metricflow_compatible"
WAREHOUSE_SQL_COMPATIBLE = "warehouse_sql_compatible"
NATIVE_DAX_REQUIRED = "native_dax_required"
INVALID = "invalid"


_AGGREGATE_FUNCTIONS: dict[str, str] = {
    "SUM": "sum",
    "COUNT": "count",
    "COUNTROWS": "count",
    "DISTINCTCOUNT": "count_distinct",
    "AVERAGE": "average",
    "AVG": "average",
    "MIN": "min",
    "MAX": "max",
}

_NATIVE_DAX_REQUIRED_FUNCTIONS = {
    "ADDCOLUMNS",
    "ALL",
    "ALLEXCEPT",
    "ALLSELECTED",
    "CALCULATE",
    "CALCULATETABLE",
    "CROSSFILTER",
    "EARLIER",
    "CALCULATION_GROUP",
    "FIELD_PARAMETER",
    "FILTER",
    "GENERATE",
    "HIERARCHY_REF",
    "KEEPFILTERS",
    "REMOVEFILTERS",
    "RANKX",
    "SELECTEDMEASURE",
    "SUMMARIZE",
    "SUMMARIZECOLUMNS",
    "TREATAS",
    "USERELATIONSHIP",
    "VALUES",
    "WHATIFVALUE",
}

_ITERATOR_FUNCTION_SUFFIXES = ("X",)
_ITERATOR_EXCEPTIONS = {"MAX", "MIN"}


@dataclass(frozen=True)
class MeasureClassification:
    measure_name: str
    capability: str
    reason: str
    dax: str = ""
    metric_type: Optional[str] = None
    aggregate: Optional[str] = None
    source_table: Optional[str] = None
    source_column: Optional[str] = None
    measure_refs: list[str] = field(default_factory=list)
    column_refs: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DbtExportResult:
    artifacts: dict[str, str]
    validation_report: dict[str, Any]
    classifications: list[MeasureClassification]


@dataclass(frozen=True)
class DbtImportResult:
    model: SemanticModel
    validation_report: dict[str, Any]
    imported_files: list[str]


def classify_measures(model: SemanticModel) -> list[MeasureClassification]:
    """Classify every measure in *model* for dbt/MetricFlow compatibility."""

    by_name = {m.name.upper(): m for m in model.measures}
    cache: dict[str, MeasureClassification] = {}
    return [_classify_measure(m, by_name=by_name, cache=cache, stack=()) for m in model.measures]


def classify_measure(model: SemanticModel, measure: MeasureDefinition) -> MeasureClassification:
    """Classify one measure using the surrounding model for dependency lookup."""

    by_name = {m.name.upper(): m for m in model.measures}
    return _classify_measure(measure, by_name=by_name, cache={}, stack=())


def export_dbt_project(
    model: SemanticModel,
    *,
    pages: Sequence[PageDefinition] | None = None,
    visuals: Sequence[VisualDefinition] | None = None,
    project_name: str = "dummy_bi_export",
    profile_name: str = "dummy_bi",
    report_url_base: str | None = None,
) -> DbtExportResult:
    """Generate an in-memory dbt project from a Dummy BI semantic model.

    The returned ``artifacts`` mapping is keyed by relative POSIX paths and can
    be written with :func:`write_dbt_export`.
    """

    pages = list(pages or [])
    visuals = list(visuals or [])
    classifications = classify_measures(model)
    class_by_name = {c.measure_name.upper(): c for c in classifications}

    source_name = "dummy_bi"
    stage_name_by_table = {t.name: f"stg_{_dbt_name(t.name)}" for t in model.tables}
    artifacts: dict[str, str] = {}

    artifacts["dbt_project.yml"] = _dump_yaml(
        {
            "name": _dbt_name(project_name),
            "version": "1.0.0",
            "config-version": 2,
            "profile": profile_name,
            "model-paths": ["models"],
            "models": {_dbt_name(project_name): {"+materialized": "view"}},
        }
    )

    artifacts["models/sources.yml"] = _dump_yaml(
        {
            "version": 2,
            "sources": [
                {
                    "name": source_name,
                    "description": "Generated from Dummy BI semantic model.",
                    "tables": [_dbt_source_table(t) for t in model.tables if not t.is_calculated],
                }
            ],
        }
    )

    staging_schema: dict[str, Any] = {"version": 2, "models": []}
    for table in model.tables:
        stage_name = stage_name_by_table[table.name]
        if table.is_calculated and table.expression:
            sql = _calculated_table_sql_placeholder(table)
        else:
            select_cols = _select_columns_sql(table.columns)
            sql = f"select\n  {select_cols}\nfrom {{{{ source('{source_name}', '{_dbt_name(table.name)}') }}}}\n"
        artifacts[f"models/staging/{stage_name}.sql"] = sql
        staging_schema["models"].append(
            {
                "name": stage_name,
                "description": table.description or f"Staging model for Dummy BI table {table.name}.",
                "columns": [{"name": _dbt_name(c.name), "description": c.description or ""} for c in table.columns],
            }
        )
    artifacts["models/staging/schema.yml"] = _dump_yaml(staging_schema)

    semantic_models = []
    metrics: list[dict[str, Any]] = []
    measures_by_table: dict[str, list[dict[str, Any]]] = {}
    for classification in classifications:
        metric = _metric_from_classification(classification)
        if metric is not None:
            metrics.append(metric)
        measure_def = _semantic_measure_from_classification(classification)
        if measure_def is not None and classification.source_table:
            measures_by_table.setdefault(classification.source_table.upper(), []).append(measure_def)

    for table in model.tables:
        semantic_models.append(
            {
                "name": _dbt_name(table.name),
                "description": table.description or f"Semantic model for {table.name}.",
                "model": f"ref('{stage_name_by_table[table.name]}')",
                "entities": _semantic_entities_for_table(table, model.relationships),
                "dimensions": _semantic_dimensions_for_table(table),
                "measures": measures_by_table.get(table.name.upper(), []),
            }
        )

    artifacts["models/semantic/semantic_models.yml"] = _dump_yaml(
        {"semantic_models": semantic_models}
    )
    artifacts["models/semantic/metrics.yml"] = _dump_yaml({"metrics": metrics})
    artifacts["models/exposures.yml"] = _dump_yaml(
        {"version": 2, "exposures": _exposures_for_reports(pages, visuals, class_by_name, report_url_base)}
    )

    validation = _validation_report(model, classifications)
    artifacts["target/dummy_bi_dbt_validation_report.json"] = json.dumps(validation, indent=2, sort_keys=True) + "\n"
    return DbtExportResult(artifacts=artifacts, validation_report=validation, classifications=classifications)


def write_dbt_export(result: DbtExportResult, target_dir: str | Path) -> None:
    """Write an export result to *target_dir*."""

    root = Path(target_dir)
    root.mkdir(parents=True, exist_ok=True)
    for rel_path, content in result.artifacts.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def import_dbt_project(project_dir: str | Path) -> DbtImportResult:
    """Read dbt YAML metadata and return a Dummy BI ``SemanticModel`` shape."""

    root = Path(project_dir)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    yaml_files = sorted([p for p in root.rglob("*.yml")] + [p for p in root.rglob("*.yaml")])
    imported_files: list[str] = []
    table_map: dict[str, Table] = {}
    measure_map: dict[str, MeasureDefinition] = {}
    warnings: list[dict[str, Any]] = []
    semantic_measure_lookup: dict[str, tuple[str, str, str]] = {}

    for path in yaml_files:
        data = _load_yaml_file(path)
        if not isinstance(data, Mapping):
            continue
        imported_files.append(str(path.relative_to(root)).replace("\\", "/"))

        for source in _as_list(data.get("sources")):
            if not isinstance(source, Mapping):
                continue
            source_name = str(source.get("name") or "source").strip()
            for table_raw in _as_list(source.get("tables")):
                if not isinstance(table_raw, Mapping):
                    continue
                table = _table_from_dbt_source(source_name, table_raw)
                table_map[_key(table.name)] = table

        for model_raw in _as_list(data.get("models")):
            if not isinstance(model_raw, Mapping):
                continue
            table = _table_from_dbt_model(model_raw)
            if table is not None:
                table_map.setdefault(_key(table.name), table)

        for sem_raw in _as_list(data.get("semantic_models")):
            if not isinstance(sem_raw, Mapping):
                continue
            table, semantic_measures = _table_from_semantic_model(sem_raw)
            if table is not None:
                table_map.setdefault(_key(table.name), table)
            for metric_name, payload in semantic_measures.items():
                semantic_measure_lookup[_key(metric_name)] = payload

        for metric_raw in _as_list(data.get("metrics")):
            if not isinstance(metric_raw, Mapping):
                continue
            measure, warning = _measure_from_dbt_metric(metric_raw, semantic_measure_lookup)
            if measure is not None:
                measure_map[_key(measure.name)] = measure
            if warning is not None:
                warnings.append(warning)

    model = SemanticModel(
        tables=sorted(table_map.values(), key=lambda t: t.name.upper()),
        relationships=[],
        measures=sorted(measure_map.values(), key=lambda m: m.name.upper()),
    )
    validation = {
        "status": "ok" if not warnings else "partial",
        "imported_files": imported_files,
        "tables": len(model.tables),
        "measures": len(model.measures),
        "warnings": warnings,
    }
    return DbtImportResult(model=model, validation_report=validation, imported_files=imported_files)


def _classify_measure(
    measure: MeasureDefinition,
    *,
    by_name: Mapping[str, MeasureDefinition],
    cache: dict[str, MeasureClassification],
    stack: tuple[str, ...],
) -> MeasureClassification:
    key = measure.name.upper()
    if key in cache:
        return cache[key]
    if key in stack:
        return MeasureClassification(
            measure_name=measure.name,
            capability=NATIVE_DAX_REQUIRED,
            reason="Recursive measure dependency cannot be exported to MetricFlow.",
            dax=measure.dax,
        )

    try:
        from dax_parser.ir_mapper import ast_to_ir
        from dax_parser.parser import parse_expression

        ir = ast_to_ir(parse_expression(measure.dax))
    except Exception as exc:
        result = MeasureClassification(
            measure_name=measure.name,
            capability=INVALID,
            reason=f"DAX parse failed: {exc}",
            dax=measure.dax,
        )
        cache[key] = result
        return result

    analysis = _analyze_expr(ir)
    blocked = _blocked_functions(analysis["functions"])
    if blocked:
        result = MeasureClassification(
            measure_name=measure.name,
            capability=NATIVE_DAX_REQUIRED,
            reason=f"Requires native DAX compiler because it uses {', '.join(blocked)}.",
            dax=measure.dax,
            measure_refs=analysis["measure_refs"],
            column_refs=analysis["column_refs"],
            functions=analysis["functions"],
        )
        cache[key] = result
        return result

    direct = _direct_aggregate_classification(measure, ir, analysis)
    if direct is not None:
        cache[key] = direct
        return direct

    derived = _derived_metric_classification(measure, ir, analysis, by_name=by_name, cache=cache, stack=stack)
    if derived is not None:
        cache[key] = derived
        return derived

    result = MeasureClassification(
        measure_name=measure.name,
        capability=WAREHOUSE_SQL_COMPATIBLE,
        reason="Expression is deterministic but does not map to the conservative MetricFlow subset.",
        dax=measure.dax,
        metric_type="expression",
        measure_refs=analysis["measure_refs"],
        column_refs=analysis["column_refs"],
        functions=analysis["functions"],
    )
    cache[key] = result
    return result


def _direct_aggregate_classification(
    measure: MeasureDefinition,
    ir: Expr,
    analysis: Mapping[str, list[str]],
) -> Optional[MeasureClassification]:
    if not isinstance(ir, DaxFunction):
        return None
    fn = ir.fn.upper()
    if fn not in _AGGREGATE_FUNCTIONS:
        return None
    if fn == "COUNTROWS":
        if len(ir.args) == 1 and isinstance(ir.args[0], TableRef):
            return MeasureClassification(
                measure_name=measure.name,
                capability=METRICFLOW_COMPATIBLE,
                reason="Simple COUNTROWS table aggregate maps to a MetricFlow simple metric.",
                dax=measure.dax,
                metric_type="simple",
                aggregate=_AGGREGATE_FUNCTIONS[fn],
                source_table=ir.args[0].name,
                source_column=None,
                measure_refs=analysis["measure_refs"],
                column_refs=analysis["column_refs"],
                functions=analysis["functions"],
            )
        return None
    if len(ir.args) != 1 or not isinstance(ir.args[0], ColumnRef):
        return None
    col = ir.args[0]
    return MeasureClassification(
        measure_name=measure.name,
        capability=METRICFLOW_COMPATIBLE,
        reason=f"Simple {fn} column aggregate maps to a MetricFlow simple metric.",
        dax=measure.dax,
        metric_type="simple",
        aggregate=_AGGREGATE_FUNCTIONS[fn],
        source_table=col.table,
        source_column=col.column,
        measure_refs=analysis["measure_refs"],
        column_refs=analysis["column_refs"],
        functions=analysis["functions"],
    )


def _derived_metric_classification(
    measure: MeasureDefinition,
    ir: Expr,
    analysis: Mapping[str, list[str]],
    *,
    by_name: Mapping[str, MeasureDefinition],
    cache: dict[str, MeasureClassification],
    stack: tuple[str, ...],
) -> Optional[MeasureClassification]:
    refs = _ordered_measure_refs(ir)
    if len(refs) < 2:
        return None
    if not _is_simple_ratio_expr(ir):
        return None

    deps: list[MeasureClassification] = []
    for ref in refs:
        dep = by_name.get(ref.upper())
        if dep is None:
            return None
        dep_class = _classify_measure(dep, by_name=by_name, cache=cache, stack=stack + (measure.name.upper(),))
        if dep_class.capability != METRICFLOW_COMPATIBLE:
            return None
        deps.append(dep_class)

    return MeasureClassification(
        measure_name=measure.name,
        capability=METRICFLOW_COMPATIBLE,
        reason="Simple ratio over MetricFlow-compatible measures maps to a derived metric.",
        dax=measure.dax,
        metric_type="derived",
        measure_refs=refs,
        column_refs=analysis["column_refs"],
        functions=analysis["functions"],
    )


def _ordered_measure_refs(expr: Expr) -> list[str]:
    out: list[str] = []

    def visit(e: Any) -> None:
        if isinstance(e, MeasureRef):
            out.append(e.name)
            return
        if isinstance(e, DaxFunction):
            for arg in e.args:
                visit(arg)
            return
        if isinstance(e, DaxBinaryOp):
            visit(e.left)
            visit(e.right)

    visit(expr)
    deduped: list[str] = []
    seen: set[str] = set()
    for ref in out:
        key = ref.upper()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _is_simple_ratio_expr(expr: Expr) -> bool:
    if isinstance(expr, DaxFunction) and expr.fn.upper() == "DIVIDE":
        return len(expr.args) >= 2 and isinstance(expr.args[0], MeasureRef) and isinstance(expr.args[1], MeasureRef)
    if isinstance(expr, DaxBinaryOp) and expr.operator == "/":
        return isinstance(expr.left, MeasureRef) and isinstance(expr.right, MeasureRef)
    return False


def _analyze_expr(expr: Expr) -> dict[str, list[str]]:
    measure_refs: set[str] = set()
    column_refs: set[str] = set()
    functions: set[str] = set()

    def visit(e: Any) -> None:
        if isinstance(e, MeasureRef):
            measure_refs.add(e.name)
            return
        if isinstance(e, ColumnRef):
            column_refs.add(f"{e.table}.{e.column}" if e.table else e.column)
            return
        if isinstance(e, DaxFunction):
            functions.add(e.fn.upper())
            for arg in e.args:
                visit(arg)
            return
        if isinstance(e, DaxBinaryOp):
            visit(e.left)
            visit(e.right)
            return
        if isinstance(e, WhatIfRef):
            functions.add("WHATIFVALUE")
            return
        if isinstance(e, SelectedMeasureRef):
            functions.add("SELECTEDMEASURE")
            return
        if isinstance(e, ParamRef):
            functions.add("FIELD_PARAMETER")
            return
        if isinstance(e, CalcGroupItemRef):
            functions.add("CALCULATION_GROUP")
            return
        if isinstance(e, HierarchyRef):
            functions.add("HIERARCHY_REF")
            return
        if isinstance(e, (Literal, TableRef)):
            return
        if hasattr(e, "__dict__"):
            for value in vars(e).values():
                if isinstance(value, list):
                    for item in value:
                        visit(item)
                else:
                    visit(value)

    visit(expr)
    return {
        "measure_refs": sorted(measure_refs, key=str.upper),
        "column_refs": sorted(column_refs, key=str.upper),
        "functions": sorted(functions),
    }


def _blocked_functions(functions: Iterable[str]) -> list[str]:
    blocked: set[str] = set()
    for fn in functions:
        f = fn.upper()
        if f in _NATIVE_DAX_REQUIRED_FUNCTIONS:
            blocked.add(f)
        if f.endswith(_ITERATOR_FUNCTION_SUFFIXES) and f not in _ITERATOR_EXCEPTIONS and f not in {"DIVIDE"}:
            blocked.add(f)
    return sorted(blocked)


def _dbt_source_table(table: Table) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": _dbt_name(table.name),
        "identifier": table.name,
        "description": table.description or "",
        "columns": [
            {
                "name": _dbt_name(c.name),
                "description": c.description or "",
                "data_type": _dbt_type(c.type),
            }
            for c in table.columns
            if not c.is_calculated
        ],
    }
    if table.source:
        source_type = str(table.source.get("type") or "").strip()
        if source_type:
            out["meta"] = {"dummy_bi_source_type": source_type, "dummy_bi_source": dict(table.source)}
    return out


def _select_columns_sql(columns: Sequence[Column]) -> str:
    if not columns:
        return "*"
    parts = []
    for col in columns:
        if col.is_calculated:
            continue
        source_name = str((col.source or {}).get("name") or col.name)
        parts.append(f"{_quote_identifier(source_name)} as {_quote_identifier(_dbt_name(col.name))}")
    return ",\n  ".join(parts) if parts else "*"


def _calculated_table_sql_placeholder(table: Table) -> str:
    return (
        "-- Dummy BI calculated table expression cannot be losslessly converted to dbt SQL yet.\n"
        f"-- Original DAX expression for {table.name}:\n"
        f"-- {table.expression}\n"
        "select null as unsupported_calculated_table where false\n"
    )


def _semantic_measure_from_classification(classification: MeasureClassification) -> Optional[dict[str, Any]]:
    if classification.capability != METRICFLOW_COMPATIBLE or classification.metric_type != "simple":
        return None
    return {
        "name": _dbt_name(classification.measure_name),
        "description": classification.reason,
        "agg": classification.aggregate,
        "expr": _dbt_name(classification.source_column) if classification.source_column else "1",
    }


def _metric_from_classification(classification: MeasureClassification) -> Optional[dict[str, Any]]:
    if classification.capability != METRICFLOW_COMPATIBLE:
        return None
    metric_name = _dbt_name(classification.measure_name)
    if classification.metric_type == "simple":
        return {
            "name": metric_name,
            "label": classification.measure_name,
            "type": "simple",
            "type_params": {"measure": metric_name},
        }
    if classification.metric_type == "derived":
        expr = _metric_expr_from_dax_ratio(classification)
        return {
            "name": metric_name,
            "label": classification.measure_name,
            "type": "derived",
            "type_params": {
                "expr": expr,
                "metrics": [{"name": _dbt_name(ref)} for ref in classification.measure_refs],
            },
        }
    return None


def _metric_expr_from_dax_ratio(classification: MeasureClassification) -> str:
    if len(classification.measure_refs) >= 2:
        left = _dbt_name(classification.measure_refs[0])
        right = _dbt_name(classification.measure_refs[1])
        return f"{left} / nullif({right}, 0)"
    return _dbt_name(classification.measure_name)


def _semantic_entities_for_table(table: Table, relationships: Sequence[Relationship]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    primary = _guess_primary_key(table)
    if primary:
        entities.append({"name": _dbt_name(table.name), "type": "primary", "expr": _dbt_name(primary)})
    for rel in relationships:
        if rel.from_table.upper() == table.name.upper():
            entities.append({"name": _dbt_name(rel.to_table), "type": "foreign", "expr": _dbt_name(rel.from_column)})
        elif rel.to_table.upper() == table.name.upper():
            entities.append({"name": _dbt_name(rel.from_table), "type": "foreign", "expr": _dbt_name(rel.to_column)})
    return _dedupe_dicts(entities, key="name")


def _semantic_dimensions_for_table(table: Table) -> list[dict[str, Any]]:
    out = []
    for col in table.columns:
        if col.is_calculated:
            continue
        dtype = _semantic_dimension_type(col.type)
        out.append({"name": _dbt_name(col.name), "type": dtype, "expr": _dbt_name(col.name)})
    return out


def _exposures_for_reports(
    pages: Sequence[PageDefinition],
    visuals: Sequence[VisualDefinition],
    class_by_name: Mapping[str, MeasureClassification],
    report_url_base: str | None,
) -> list[dict[str, Any]]:
    visuals_by_page: dict[str, list[VisualDefinition]] = {}
    for visual in visuals:
        visuals_by_page.setdefault(visual.page_id, []).append(visual)

    exposures = []
    for page in pages:
        depends_on = set()
        for visual in visuals_by_page.get(page.id, []):
            for measure in getattr(visual.spec, "measures", []) or []:
                if isinstance(measure, MeasureRef):
                    classification = class_by_name.get(measure.name.upper())
                    if classification and classification.capability == METRICFLOW_COMPATIBLE:
                        depends_on.add(f"metric('{_dbt_name(measure.name)}')")
            for dim in getattr(visual.spec, "dimensions", []) or []:
                if isinstance(dim, ColumnRef):
                    depends_on.add(f"ref('stg_{_dbt_name(dim.table)}')")
        if not depends_on:
            continue
        exposure: dict[str, Any] = {
            "name": _dbt_name(page.title or page.id),
            "label": page.title or page.id,
            "type": "dashboard",
            "maturity": "medium",
            "depends_on": sorted(depends_on),
            "owner": {"name": "Dummy BI"},
        }
        if report_url_base:
            exposure["url"] = report_url_base.rstrip("/") + "/" + page.id
        exposures.append(exposure)
    return exposures


def _validation_report(model: SemanticModel, classifications: Sequence[MeasureClassification]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for c in classifications:
        counts[c.capability] = counts.get(c.capability, 0) + 1
    return {
        "status": "ok" if counts.get(NATIVE_DAX_REQUIRED, 0) == 0 and counts.get(INVALID, 0) == 0 else "partial",
        "tables": len(model.tables),
        "measures": len(model.measures),
        "capability_counts": counts,
        "measures": [asdict(c) for c in classifications],
        "unsupported_model_features": _unsupported_model_features(model),
    }


def _unsupported_model_features(model: SemanticModel) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if model.calculation_groups:
        out.append({"feature": "calculation_groups", "reason": "Calculation groups require native DAX compatibility execution."})
    if model.field_parameters:
        out.append({"feature": "field_parameters", "reason": "Field parameters are visual/planner-time semantics, not dbt semantic metrics."})
    if model.what_if_parameters:
        out.append({"feature": "what_if_parameters", "reason": "What-if values require runtime parameter binding."})
    if model.security_roles:
        out.append({"feature": "security_roles", "reason": "Security roles need warehouse-specific policy mapping."})
    return out


def _table_from_dbt_source(source_name: str, raw: Mapping[str, Any]) -> Table:
    name = str(raw.get("identifier") or raw.get("name") or "").strip()
    if not name:
        name = "dbt_source"
    columns = [_column_from_dbt(c) for c in _as_list(raw.get("columns")) if isinstance(c, Mapping)]
    return Table(
        name=name,
        columns=columns,
        source={"type": "dbt_source", "source": source_name, "table": str(raw.get("name") or name)},
        description=_opt_str(raw.get("description")),
    )


def _table_from_dbt_model(raw: Mapping[str, Any]) -> Optional[Table]:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    columns = [_column_from_dbt(c) for c in _as_list(raw.get("columns")) if isinstance(c, Mapping)]
    return Table(
        name=name,
        columns=columns,
        source={"type": "dbt_model", "model": name},
        description=_opt_str(raw.get("description")),
    )


def _table_from_semantic_model(raw: Mapping[str, Any]) -> tuple[Optional[Table], dict[str, tuple[str, str, str]]]:
    name = str(raw.get("name") or "").strip()
    model_ref = str(raw.get("model") or "").strip()
    table_name = _relation_name_from_ref(model_ref) or name
    if not table_name:
        return None, {}

    columns: dict[str, Column] = {}
    for dim in _as_list(raw.get("dimensions")):
        if not isinstance(dim, Mapping):
            continue
        col_name = str(dim.get("expr") or dim.get("name") or "").strip()
        if col_name:
            columns[_key(col_name)] = Column(name=col_name, type=_dummy_type_from_semantic_dim(dim.get("type")))

    semantic_measures: dict[str, tuple[str, str, str]] = {}
    for measure in _as_list(raw.get("measures")):
        if not isinstance(measure, Mapping):
            continue
        mname = str(measure.get("name") or "").strip()
        agg = str(measure.get("agg") or "").strip().lower()
        expr = str(measure.get("expr") or "").strip()
        if mname and agg:
            semantic_measures[_dbt_name(mname)] = (table_name, agg, expr)
            if expr and expr != "1":
                columns.setdefault(_key(expr), Column(name=expr, type="DOUBLE"))

    table = Table(
        name=table_name,
        columns=sorted(columns.values(), key=lambda c: c.name.upper()),
        source={"type": "dbt_semantic_model", "model": name},
        description=_opt_str(raw.get("description")),
    )
    return table, semantic_measures


def _measure_from_dbt_metric(
    raw: Mapping[str, Any],
    semantic_measure_lookup: Mapping[str, tuple[str, str, str]],
) -> tuple[Optional[MeasureDefinition], Optional[dict[str, Any]]]:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None, {"feature": "metric", "reason": "Metric without name skipped."}

    metric_type = str(raw.get("type") or "").strip().lower()
    type_params = raw.get("type_params") if isinstance(raw.get("type_params"), Mapping) else {}
    if metric_type == "simple":
        measure_name = str(type_params.get("measure") or "").strip()
        source = semantic_measure_lookup.get(_key(measure_name)) or semantic_measure_lookup.get(_dbt_name(measure_name).upper())
        if not source:
            return None, {"feature": "metric", "name": name, "reason": f"Referenced semantic measure {measure_name!r} was not found."}
        table, agg, expr = source
        dax = _dax_from_agg(table, agg, expr)
        if dax is None:
            return None, {"feature": "metric", "name": name, "reason": f"Aggregate {agg!r} cannot be represented as DAX v1 import."}
        return MeasureDefinition(name=_title_from_dbt_name(name), dax=dax, description=_opt_str(raw.get("description"))), None

    if metric_type == "derived":
        metrics = [str(m.get("name") or "").strip() for m in _as_list(type_params.get("metrics")) if isinstance(m, Mapping)]
        if len(metrics) == 2:
            dax = f"DIVIDE([{_title_from_dbt_name(metrics[0])}], [{_title_from_dbt_name(metrics[1])}])"
            return MeasureDefinition(name=_title_from_dbt_name(name), dax=dax, description=_opt_str(raw.get("description"))), None
        return None, {"feature": "metric", "name": name, "reason": "Only two-metric derived ratios are imported in v1."}

    return None, {"feature": "metric", "name": name, "reason": f"Metric type {metric_type!r} is not supported in v1 import."}


def _dax_from_agg(table: str, agg: str, expr: str) -> Optional[str]:
    agg_upper = {
        "sum": "SUM",
        "count": "COUNT",
        "count_distinct": "DISTINCTCOUNT",
        "average": "AVERAGE",
        "avg": "AVERAGE",
        "min": "MIN",
        "max": "MAX",
    }.get(agg.lower())
    if not agg_upper:
        return None
    if not expr or expr == "1":
        if agg.lower() == "count":
            return f"COUNTROWS({table})"
        return None
    return f"{agg_upper}({table}[{expr}])"


def _column_from_dbt(raw: Mapping[str, Any]) -> Column:
    name = str(raw.get("name") or "").strip() or "column"
    dtype = str(raw.get("data_type") or raw.get("type") or "UNKNOWN").strip() or "UNKNOWN"
    return Column(name=name, type=_dummy_type(dtype), description=_opt_str(raw.get("description")))


def _relation_name_from_ref(value: str) -> Optional[str]:
    match = re.search(r"ref\(['\"]([^'\"]+)['\"]\)", value)
    if match:
        return match.group(1)
    match = re.search(r"source\(['\"][^'\"]+['\"],\s*['\"]([^'\"]+)['\"]\)", value)
    if match:
        return match.group(1)
    return value.strip() or None


def _guess_primary_key(table: Table) -> Optional[str]:
    candidates = [c.name for c in table.columns]
    table_key = _key(table.name)
    for col in candidates:
        ckey = _key(col)
        if ckey == "ID" or ckey == f"{table_key}ID" or ckey == f"{table_key}KEY":
            return col
    for col in candidates:
        if _key(col).endswith("KEY") or _key(col).endswith("ID"):
            return col
    return None


def _semantic_dimension_type(dtype: str) -> str:
    t = dtype.upper()
    if "DATE" in t or "TIME" in t:
        return "time"
    return "categorical"


def _dummy_type_from_semantic_dim(dtype: Any) -> str:
    t = str(dtype or "").strip().lower()
    if t == "time":
        return "DATE"
    return "VARCHAR"


def _dummy_type(dtype: str) -> str:
    t = dtype.upper()
    if any(x in t for x in ("INT", "NUMBER", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")):
        return "DOUBLE" if any(x in t for x in ("DECIMAL", "FLOAT", "DOUBLE", "REAL", "NUMERIC", "NUMBER")) else "BIGINT"
    if "BOOL" in t:
        return "BOOLEAN"
    if "DATE" in t and "TIME" not in t:
        return "DATE"
    if "TIME" in t or "TIMESTAMP" in t:
        return "TIMESTAMP"
    return "VARCHAR"


def _dbt_type(dtype: str) -> str:
    t = dtype.upper()
    if t in {"BIGINT", "INTEGER", "INT", "SMALLINT"}:
        return "integer"
    if t in {"DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC"}:
        return "numeric"
    if t == "BOOLEAN":
        return "boolean"
    if t == "DATE":
        return "date"
    if "TIME" in t:
        return "timestamp"
    return "string"


def _dbt_name(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        return "unnamed"
    if raw[0].isdigit():
        raw = f"n_{raw}"
    return raw


def _title_from_dbt_name(value: str) -> str:
    text = str(value or "").replace("_", " ").strip()
    return " ".join(part.capitalize() for part in text.split()) or "Metric"


def _quote_identifier(value: str) -> str:
    escaped = str(value).replace('"', '""')
    return f'"{escaped}"'


def _key(value: str) -> str:
    return str(value or "").strip().upper()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _opt_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.strip() else None


def _dedupe_dicts(items: Sequence[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        marker = str(item.get(key) or "").upper()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def _dump_yaml(data: Any) -> str:
    try:
        import yaml
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required for dbt bridge YAML generation.") from exc
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def _load_yaml_file(path: Path) -> Any:
    try:
        import yaml
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required for dbt bridge YAML loading.") from exc
    return yaml.safe_load(path.read_text(encoding="utf-8"))


__all__ = [
    "DbtExportResult",
    "DbtImportResult",
    "INVALID",
    "METRICFLOW_COMPATIBLE",
    "NATIVE_DAX_REQUIRED",
    "WAREHOUSE_SQL_COMPATIBLE",
    "MeasureClassification",
    "classify_measure",
    "classify_measures",
    "export_dbt_project",
    "import_dbt_project",
    "write_dbt_export",
]
