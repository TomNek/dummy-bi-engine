"""Pytest configuration for the test suite.

This module provides fixtures that ensure test isolation by resetting
global engine state before each test.

NOTE: We intentionally do NOT auto-reset engine state globally because
many tests rely on the server's engine cache being populated by prior
setup (within the same test worker process). Tests that specifically need
a fresh state (like iterator tests that bypass the server) should call
dax_compiler.reset_engine_state() explicitly.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark test modules excluded by the edition manifest as enterprise.

    Keeping this classification in the publishing manifest gives local and CI
    test gates the same product boundary as the generated community artifact.
    """
    root = Path(str(config.rootpath))
    manifest_path = root / "open_core_boundary.yml"
    if not manifest_path.exists():
        return

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    excluded = {
        str(pattern).replace("\\", "/")
        for pattern in (
            manifest.get("edition_rules", {})
            .get("community", {})
            .get("excluded_patterns", [])
        )
        if str(pattern).startswith("tests/") and "*" not in str(pattern)
    }
    for item in items:
        rel_path = Path(str(item.path)).resolve().relative_to(root.resolve()).as_posix()
        if rel_path in excluded:
            item.add_marker(pytest.mark.enterprise)
        if Path(rel_path).name.startswith("test_ui_playwright"):
            item.add_marker(pytest.mark.playwright)

# No autouse fixture - tests that need isolation should reset state explicitly.
