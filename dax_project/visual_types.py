from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from dax_project.open_core_profile import OPEN_CORE_VISUAL_TYPES, is_open_core_mvp


@dataclass(frozen=True)
class SlotSpec:
    kind: str  # 'dimension' | 'measure' | 'any'
    required: bool = False
    multi: bool = False


@dataclass(frozen=True)
class VisualTypeSpec:
    key: str
    label: str
    renderer: str
    px_func: Optional[str]
    slots: Dict[str, SlotSpec]
    static: bool = False
    go_type: Optional[str] = None


def _load_yaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to load visual types. Please install 'pyyaml'.") from exc

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _as_bool(v: Any, *, default: bool = False) -> bool:
    if v is None:
        return default
    return bool(v)


def load_visual_type_registry(project_path: str, *, profile: str | None = None) -> Dict[str, VisualTypeSpec]:
    """Load visual type registry metadata.

    Resolution order:
    1) packaged defaults filtered to Plotly renderers when
       ``profile``/``DAX_PRODUCT_PROFILE`` is ``open-core-mvp`` (project
       overrides cannot re-enable excluded visuals)
    2) <project>/reports/visual_types.yaml
    3) packaged defaults at dax_project/visual_types.yaml

    This module is metadata-only and must not import Plotly.
    """

    root = Path(project_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    open_core = is_open_core_mvp(profile)
    if open_core:
        path = Path(__file__).with_name("visual_types.yaml")
    else:
        candidate = root / "reports" / "visual_types.yaml"
        if candidate.exists():
            path = candidate
        else:
            path = Path(__file__).with_name("visual_types.yaml")

    raw = _load_yaml(path)
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"visual_types.yaml must be a mapping: {path}")

    vt_raw = raw.get("visual_types")
    if not isinstance(vt_raw, Mapping):
        raise ValueError(f"visual_types.yaml must contain 'visual_types' mapping: {path}")

    out: Dict[str, VisualTypeSpec] = {}
    for k, spec in vt_raw.items():
        if not isinstance(k, str) or not k.strip():
            raise ValueError("visual_types keys must be non-empty strings")
        if not isinstance(spec, Mapping):
            raise ValueError(f"visual_types[{k!r}] must be a mapping")

        label = spec.get("label")
        renderer = spec.get("renderer")
        px_func = spec.get("px_func")
        go_type = spec.get("go_type")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"visual_types[{k!r}].label must be a non-empty string")
        if not isinstance(renderer, str) or not renderer.strip():
            raise ValueError(f"visual_types[{k!r}].renderer must be a non-empty string")
        if px_func is not None and (not isinstance(px_func, str) or not px_func.strip()):
            raise ValueError(f"visual_types[{k!r}].px_func must be a non-empty string if provided")

        is_static = _as_bool(spec.get("static"), default=False)

        slots_raw = spec.get("slots")
        if slots_raw is None:
            slots_raw = {}
        if not isinstance(slots_raw, Mapping):
            raise ValueError(f"visual_types[{k!r}].slots must be a mapping")
        if not slots_raw and not is_static:
            raise ValueError(f"visual_types[{k!r}].slots must be a non-empty mapping (unless static=true)")

        slots: Dict[str, SlotSpec] = {}
        for slot_name, slot_spec in slots_raw.items():
            if not isinstance(slot_name, str) or not slot_name.strip():
                raise ValueError(f"visual_types[{k!r}].slots keys must be non-empty strings")
            if not isinstance(slot_spec, Mapping):
                raise ValueError(f"visual_types[{k!r}].slots[{slot_name!r}] must be a mapping")

            kind = slot_spec.get("kind")
            if not isinstance(kind, str) or not kind.strip():
                raise ValueError(f"visual_types[{k!r}].slots[{slot_name!r}].kind must be a non-empty string")

            slots[slot_name] = SlotSpec(
                kind=kind.strip(),
                required=_as_bool(slot_spec.get("required"), default=False),
                multi=_as_bool(slot_spec.get("multi"), default=False),
            )

        key = k.strip()
        if open_core and key not in OPEN_CORE_VISUAL_TYPES:
            continue

        out[key] = VisualTypeSpec(
            key=key,
            label=label.strip(),
            renderer=renderer.strip(),
            px_func=px_func.strip() if isinstance(px_func, str) else None,
            slots=slots,
            static=is_static,
            go_type=go_type.strip() if isinstance(go_type, str) else None,
        )

    # Deterministic: sort by key case-insensitive.
    return dict(sorted(out.items(), key=lambda kv: kv[0].upper()))
