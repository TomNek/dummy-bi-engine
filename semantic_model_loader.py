from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

import dax_compiler
from dax_compiler import Relationship, define_measure
from dax_parser.parser import parse_expression
from dax_parser.ir_mapper import ast_to_ir


@dataclass(frozen=True)
class MeasureMeta:
    name: str
    description: Optional[str] = None
    folder: Optional[str] = None
    format: Optional[str] = None


# In-memory metadata registry (stored even if unused by compiler)
MEASURE_METADATA: Dict[str, MeasureMeta] = {}


def validate_semantic_model(model: dict) -> None:
    """Validate semantic model structure: required fields and uniqueness.

    Raises ValueError with aggregated error messages if validation fails.
    """
    errors: List[str] = []

    # Validate relationships
    rels = model.get("relationships") or []
    seen_pair: set[str] = set()
    seen_rel_id: set[str] = set()
    for i, r in enumerate(rels):
        if not isinstance(r, dict):
            errors.append(f"relationships[{i}] must be an object")
            continue
        frm = r.get("from") or {}
        to = r.get("to") or {}
        ft = str(frm.get("table", "")).strip()
        fc = str(frm.get("column", "")).strip()
        tt = str(to.get("table", "")).strip()
        tc = str(to.get("column", "")).strip()
        if not ft:
            errors.append(f"relationships[{i}].from.table is required")
        if not fc:
            errors.append(f"relationships[{i}].from.column is required")
        if not tt:
            errors.append(f"relationships[{i}].to.table is required")
        if not tc:
            errors.append(f"relationships[{i}].to.column is required")
        pair = f"{ft}.{fc}->{tt}.{tc}"
        if pair in seen_pair:
            errors.append(f"Duplicate relationship pair: {pair}")
        else:
            seen_pair.add(pair)
        rel_id = str(r.get("rel_id", "")).strip()
        if rel_id:
            if rel_id in seen_rel_id:
                errors.append(f"Duplicate relationship rel_id: {rel_id}")
            else:
                seen_rel_id.add(rel_id)

    # Validate measures
    measures = model.get("measures") or []
    seen_names: set[str] = set()
    for i, m in enumerate(measures):
        if not isinstance(m, dict):
            errors.append(f"measures[{i}] must be an object")
            continue
        name = str(m.get("name", "")).strip()
        dax_text = str(m.get("dax", "")).strip()
        if not name:
            errors.append(f"measures[{i}].name is required")
        if not dax_text:
            errors.append(f"measures[{i}].dax is required")
        key = name.upper()
        if key in seen_names:
            errors.append(f"Duplicate measure name: {name}")
        else:
            seen_names.add(key)
        # Optional metadata type checks
        for field in ("description", "folder", "format"):
            v = m.get(field)
            if v is not None and not isinstance(v, str):
                errors.append(f"measures[{i}].{field} must be a string if provided")

    if errors:
        raise ValueError("Semantic model validation errors:\n" + "\n".join(f"- {e}" for e in errors))


def _load_yaml(path: Union[str, Path]) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Semantic model file not found: {p}")

    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "PyYAML is required to load semantic_model.yaml. Please install 'pyyaml'."
        ) from exc

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("semantic_model.yaml must map to an object at the root")
    return data


def load_semantic_model(model_path: Union[str, Path] = "semantic_model.yaml") -> None:
    """Load relationships and measures from a semantic model YAML.

    - Registers relationships via `dax_compiler.set_relationships`
    - Parses measure DAX text → AST → IR and registers via `define_measure`
    - Stores description/folder/format metadata in `MEASURE_METADATA`
    """

    data = _load_yaml(model_path)
    validate_semantic_model(data)

    # Relationships
    rels_raw = data.get("relationships") or []
    relationships: List[Relationship] = []
    for r in rels_raw:
        if not isinstance(r, dict):
            continue
        frm = r.get("from") or {}
        to = r.get("to") or {}
        relationships.append(
            Relationship(
                from_table=str(frm.get("table", "")).strip(),
                from_column=str(frm.get("column", "")).strip(),
                to_table=str(to.get("table", "")).strip(),
                to_column=str(to.get("column", "")).strip(),
                active=bool(r.get("active", True)),
                rel_id=str(r.get("rel_id", "")),
            )
        )

    if relationships:
        dax_compiler.set_relationships(relationships)

    # Measures
    measures_raw = data.get("measures") or []
    for m in measures_raw:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name", "")).strip()
        dax_text = str(m.get("dax", "")).strip()
        if not name or not dax_text:
            continue

        # Parse DAX → AST → IR and register
        ast = parse_expression(dax_text)
        ir = ast_to_ir(ast)
        # Measures must be scalar expressions
        if not isinstance(ir, dax_compiler.ScalarExpr):
            # Best-effort: wrap non-scalar IR into a scalar-safe form when possible
            # For v1 we reject invalid shapes to keep deterministic behavior
            raise TypeError(f"Measure '{name}' must compile to a scalar expression")
        define_measure(name, ir)

        # Store metadata
        meta = MeasureMeta(
            name=name,
            description=(m.get("description") or None),
            folder=(m.get("folder") or None),
            format=(m.get("format") or None),
        )
        MEASURE_METADATA[name.upper()] = meta


def get_measure_metadata(name: str) -> Optional[MeasureMeta]:
    return MEASURE_METADATA.get(name.upper().strip())


def get_all_measure_metadata() -> List[MeasureMeta]:
    return list(MEASURE_METADATA.values())
