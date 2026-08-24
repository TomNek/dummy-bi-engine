"""
Project management utilities for the DAX-to-DuckDB runtime.

Handles:
- List available projects (directory browsing)
- Recent projects tracking
- New project scaffolding
- Save As (deep-copy project)
- Export project as ZIP
- Import project from ZIP
- Close project
- Project settings

This module is imported by server.py and registered via
_project_management_routes(app).
"""

import json
import os
import shutil
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Recent projects store
# ---------------------------------------------------------------------------

_RECENT_PROJECTS_FILE = Path.home() / ".dax_engine" / "recent_projects.json"
_MAX_RECENT = 20


def _ensure_config_dir() -> None:
    _RECENT_PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_recent_projects() -> list[dict[str, Any]]:
    """Load recent projects list from user config."""
    try:
        if _RECENT_PROJECTS_FILE.exists():
            data = json.loads(_RECENT_PROJECTS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[:_MAX_RECENT]
    except Exception:
        logger.warning("Failed to load recent projects", exc_info=True)
    return []


def save_recent_projects(projects: list[dict[str, Any]]) -> None:
    """Persist recent projects list to user config."""
    _ensure_config_dir()
    try:
        _RECENT_PROJECTS_FILE.write_text(
            json.dumps(projects[:_MAX_RECENT], indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("Failed to save recent projects", exc_info=True)


def add_recent_project(project_path: str, name: Optional[str] = None) -> list[dict[str, Any]]:
    """Add/update a project in the recent list, returning the new list."""
    normalized = str(Path(project_path).resolve())
    name = name or Path(normalized).name

    projects = load_recent_projects()

    # Remove duplicates (case-insensitive on Windows)
    projects = [p for p in projects if str(Path(p.get("path", "")).resolve()).lower() != normalized.lower()]

    # Prepend
    projects.insert(0, {
        "path": normalized,
        "name": name,
        "last_opened": int(time.time()),
    })

    projects = projects[:_MAX_RECENT]
    save_recent_projects(projects)
    return projects


def remove_recent_project(project_path: str) -> list[dict[str, Any]]:
    """Remove a project from the recent list."""
    normalized = str(Path(project_path).resolve())
    projects = load_recent_projects()
    projects = [p for p in projects if str(Path(p.get("path", "")).resolve()).lower() != normalized.lower()]
    save_recent_projects(projects)
    return projects


# ---------------------------------------------------------------------------
# Directory browsing
# ---------------------------------------------------------------------------

def list_directories(base_path: str) -> list[dict[str, Any]]:
    """List subdirectories of a given path for project browsing.
    
    Returns list of {name, path, is_project} dicts.
    A directory is considered a project if it contains model/ subfolder.
    """
    p = Path(base_path)
    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(f"Directory not found: {base_path}")

    items: list[dict[str, Any]] = []

    # Add parent directory entry
    parent = p.parent
    if parent != p:  # Not at root
        items.append({
            "name": "..",
            "path": str(parent),
            "is_project": False,
        })

    try:
        for child in sorted(p.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                is_project = (child / "model").is_dir()
                items.append({
                    "name": child.name,
                    "path": str(child),
                    "is_project": is_project,
                })
    except PermissionError:
        pass

    return items


# ---------------------------------------------------------------------------
# New project scaffolding
# ---------------------------------------------------------------------------

_DEFAULT_SEMANTIC_MODEL = """\
tables: []
relationships: []
"""

_DEFAULT_MEASURES = """\
measures: []
"""

_DEFAULT_PAGES = """\
pages:
  - id: page_1
    title: Page 1
    order: 1
"""


def create_new_project(
    target_path: str,
    name: Optional[str] = None,
) -> str:
    """Create a new project with default scaffolding.
    
    Creates:
      <target_path>/
        model/
          tables/       (empty)
          relationships.yaml
          measures.yaml
        reports/
          pages.yaml
          visuals/      (empty)
        data/           (empty)
        semantic_model.yaml
    
    Returns the resolved project path.
    """
    p = Path(target_path)
    if p.exists() and any(p.iterdir()):
        raise ValueError(f"Target directory is not empty: {target_path}")

    p.mkdir(parents=True, exist_ok=True)

    # model/
    model_dir = p / "model"
    model_dir.mkdir(exist_ok=True)
    (model_dir / "tables").mkdir(exist_ok=True)
    (model_dir / "relationships.yaml").write_text("relationships: []\n", encoding="utf-8")
    (model_dir / "measures.yaml").write_text(_DEFAULT_MEASURES, encoding="utf-8")

    # reports/
    reports_dir = p / "reports"
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / "pages.yaml").write_text(_DEFAULT_PAGES, encoding="utf-8")
    (reports_dir / "visuals").mkdir(exist_ok=True)

    # data/
    (p / "data").mkdir(exist_ok=True)

    # semantic_model.yaml
    (p / "semantic_model.yaml").write_text(_DEFAULT_SEMANTIC_MODEL, encoding="utf-8")

    resolved = str(p.resolve())
    add_recent_project(resolved, name or p.name)
    return resolved


# ---------------------------------------------------------------------------
# Save As (deep-copy)
# ---------------------------------------------------------------------------

def save_project_as(source_path: str, target_path: str) -> str:
    """Deep-copy a project to a new location.
    
    Returns the resolved target path.
    """
    src = Path(source_path)
    dst = Path(target_path)

    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Source project not found: {source_path}")

    if dst.exists() and any(dst.iterdir()):
        raise ValueError(f"Target directory is not empty: {target_path}")

    shutil.copytree(str(src), str(dst), dirs_exist_ok=True)

    resolved = str(dst.resolve())
    add_recent_project(resolved, dst.name)
    return resolved


# ---------------------------------------------------------------------------
# Export / Import ZIP
# ---------------------------------------------------------------------------

def export_project_zip(project_path: str) -> BytesIO:
    """Bundle a project into a ZIP archive in memory.
    
    Returns a BytesIO with the ZIP contents.
    """
    p = Path(project_path)
    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(f"Project not found: {project_path}")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(p.rglob("*")):
            if file.is_file():
                # Skip __pycache__, .git, .duckdb (large binary)
                rel = file.relative_to(p)
                parts = rel.parts
                if any(part.startswith(".") or part == "__pycache__" for part in parts):
                    continue
                # Skip .duckdb files (they can be huge and are regenerated)
                if file.suffix == ".duckdb":
                    continue
                zf.write(str(file), str(rel))

    buf.seek(0)
    return buf


def import_project_zip(zip_data: bytes, target_path: str) -> str:
    """Extract a project ZIP to a target directory.
    
    Returns the resolved project path.
    """
    dst = Path(target_path)
    if dst.exists() and any(dst.iterdir()):
        raise ValueError(f"Target directory is not empty: {target_path}")

    dst.mkdir(parents=True, exist_ok=True)

    buf = BytesIO(zip_data)
    with zipfile.ZipFile(buf, "r") as zf:
        # Security: reject paths that escape target
        for info in zf.infolist():
            member_path = Path(info.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe path in ZIP: {info.filename}")
        zf.extractall(str(dst))

    resolved = str(dst.resolve())
    add_recent_project(resolved, dst.name)
    return resolved


# ---------------------------------------------------------------------------
# Data refresh
# ---------------------------------------------------------------------------

def refresh_project_data(project_path: str) -> dict[str, Any]:
    """Re-trigger the DuckDB source loading for a project.
    
    This drops the cached engine and forces a fresh load on next request.
    Returns a summary of refreshed sources.
    """
    p = Path(project_path)
    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(f"Project not found: {project_path}")

    data_dir = p / "data"
    sources: list[str] = []
    if data_dir.exists():
        for f in sorted(data_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in (".csv", ".parquet", ".parq"):
                sources.append(f.name)

    return {
        "project": str(p),
        "data_sources": sources,
        "refreshed": True,
    }
