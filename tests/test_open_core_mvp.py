from __future__ import annotations

from pathlib import Path

import yaml

from dax_project.open_core_profile import (
    OPEN_CORE_DATA_CONNECTIONS,
    OPEN_CORE_PROFILE,
    OPEN_CORE_VISUAL_TYPES,
)
from dax_project.visual_types import load_visual_type_registry
from tools.publish_open_core_mvp import collect_open_core_files, publish
from tools.validate_open_core_mvp import validate


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_matches_full_connector_and_plotly_capabilities() -> None:
    manifest = yaml.safe_load((ROOT / "open_core_mvp.yml").read_text(encoding="utf-8"))
    assert set(manifest["data_connections"]["allowed"]) == OPEN_CORE_DATA_CONNECTIONS
    assert set(manifest["visuals"]["allowed"]) == OPEN_CORE_VISUAL_TYPES
    assert len(OPEN_CORE_DATA_CONNECTIONS) == 17
    assert len(OPEN_CORE_VISUAL_TYPES) == 31


def test_open_core_registry_keeps_every_plotly_visual_and_no_other_renderer() -> None:
    registry = load_visual_type_registry(str(ROOT / "sample_project"), profile=OPEN_CORE_PROFILE)
    assert set(registry) == OPEN_CORE_VISUAL_TYPES
    assert {spec.renderer for spec in registry.values()} == {"plotly_express", "graph_objects"}


def test_open_core_profile_ignores_project_visual_overrides(tmp_path: Path) -> None:
    project = tmp_path / "project"
    reports = project / "reports"
    reports.mkdir(parents=True)
    (reports / "visual_types.yaml").write_text(
        "visual_types:\n  private_svg:\n    label: Private\n    renderer: svg\n    slots:\n      x: {kind: any, required: true}\n",
        encoding="utf-8",
    )
    registry = load_visual_type_registry(str(project), profile=OPEN_CORE_PROFILE)
    assert "private_svg" not in registry
    assert set(registry) == OPEN_CORE_VISUAL_TYPES


def test_public_file_selection_uses_only_the_small_frontend() -> None:
    files = set(collect_open_core_files())
    assert "dax_ui/frontend/src/open-core/OpenCoreApp.tsx" in files
    assert "dax_ui/open_core_main.py" in files
    assert {
        "src-tauri/tauri.open-core.conf.json",
        "src-tauri/tauri.conf.json",
    } & files
    assert "dax_ui/frontend/src/App.tsx" not in files
    assert not any("components/visuals/ibcs" in rel for rel in files)
    assert "dax_ui/server/routes_enterprise.py" not in files


def test_published_artifact_passes_boundary_validator(tmp_path: Path) -> None:
    output = tmp_path / "open-core"
    assert publish(output)
    assert validate(output) == []
