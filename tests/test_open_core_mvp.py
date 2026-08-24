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
from tools.create_tauri_updater_manifest import create_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_matches_full_connector_and_plotly_capabilities() -> None:
    manifest = yaml.safe_load((ROOT / "open_core_mvp.yml").read_text(encoding="utf-8"))
    assert set(manifest["data_connections"]["allowed"]) == OPEN_CORE_DATA_CONNECTIONS
    assert set(manifest["visuals"]["allowed"]) == OPEN_CORE_VISUAL_TYPES
    assert len(OPEN_CORE_DATA_CONNECTIONS) == 17
    assert len(OPEN_CORE_VISUAL_TYPES) == 32
    assert "table" in OPEN_CORE_VISUAL_TYPES
    assert "matrix" not in OPEN_CORE_VISUAL_TYPES


def test_open_core_registry_keeps_every_plotly_visual_and_no_other_renderer() -> None:
    registry = load_visual_type_registry(str(ROOT / "sample_project"), profile=OPEN_CORE_PROFILE)
    assert set(registry) == OPEN_CORE_VISUAL_TYPES
    assert {spec.renderer for spec in registry.values()} == {"plotly_express", "graph_objects", "table"}


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


def test_public_file_selection_uses_shared_shell_without_excluded_implementations() -> None:
    files = set(collect_open_core_files())
    assert "dax_ui/frontend/open-core/src/main.tsx" in files
    assert "dax_ui/frontend/src/App.tsx" in files
    assert "dax_ui/frontend/src/lib/edition.ts" in files
    assert "dax_ui/frontend/src/components/layout/VisualsPane.tsx" in files
    assert "dax_ui/open_core_main.py" in files
    assert {
        "src-tauri/tauri.open-core.conf.json",
        "src-tauri/tauri.conf.json",
    } & files
    assert "src-tauri/capabilities/default.json" in files
    assert not any("components/autogen/" in rel for rel in files)
    assert not any("components/stories/" in rel for rel in files)
    assert not any("components/power-query/" in rel for rel in files)
    assert "dax_project/tmdl_converter.py" not in files
    assert "dax_ui/server/routes_enterprise.py" not in files


def test_published_artifact_passes_boundary_validator(tmp_path: Path) -> None:
    output = tmp_path / "open-core"
    assert publish(output)
    assert validate(output) == []


def test_updater_manifest_targets_signed_public_release_asset(tmp_path: Path) -> None:
    installer = tmp_path / "Dummy BI Engine_0.2.0_x64-setup.exe"
    signature = installer.with_suffix(installer.suffix + ".sig")
    installer.write_bytes(b"installer")
    signature.write_text("signed-payload", encoding="utf-8")
    output = tmp_path / "latest.json"

    create_manifest(
        installer,
        signature,
        version="0.2.0",
        repository="TomNek/dummy-bi-engine",
        tag="v0.2.0",
        output=output,
    )

    payload = __import__("json").loads(output.read_text(encoding="utf-8"))
    platform = payload["platforms"]["windows-x86_64"]
    assert payload["version"] == "0.2.0"
    assert platform["signature"] == "signed-payload"
    assert platform["url"].endswith("Dummy.BI.Engine_0.2.0_x64-setup.exe")
