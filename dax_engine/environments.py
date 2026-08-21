"""Environments — isolated report catalogs for Phase 14."""

import datetime
import threading
import os
import re
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from dax_project.errors import NotFoundError

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")

_UPDATABLE_FIELDS = frozenset({"display_name", "color", "description"})


def _load_yaml(path: Path) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _save_yaml(path: Path, data: dict) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)


@dataclass
class Environment:
    """Represents an isolated report catalog environment."""
    name: str
    display_name: str
    color: str = "#3B82F6"
    description: str = ""
    catalog_dir: str = ""
    created_at: str = ""


class EnvironmentManager:
    """CRUD for environments. Thread-safe. Persisted in YAML.

    Constructor: EnvironmentManager(base_dir: str)
      - base_dir is the project root (or .report_server parent)
      - environments.yaml lives at <base_dir>/.report_server/environments.yaml
      - Each environment's catalog_dir defaults to .report_server/catalogs/<name>
    """

    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)
        self._yaml_path = self._base_dir / ".report_server" / "environments.yaml"
        self._lock = threading.Lock()
        self._environments: dict[str, Environment] = {}
        if self._yaml_path.exists():
            self._read_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_environments(self) -> list[Environment]:
        with self._lock:
            return list(self._environments.values())

    def get_environment(self, name: str) -> Environment:
        """Raises NotFoundError if not found."""
        with self._lock:
            env = self._environments.get(name)
            if env is None:
                raise NotFoundError(f"Environment not found: {name}")
            return env

    def create_environment(
        self,
        name: str,
        display_name: str,
        color: str = "#3B82F6",
        description: str = "",
    ) -> Environment:
        """Validates name, creates catalog_dir on disk, persists to YAML.

        Raises ValueError if name invalid or already exists.
        """
        self._validate_name(name)
        with self._lock:
            if name in self._environments:
                raise ValueError(f"Environment already exists: {name}")
            catalog_rel = os.path.join(".report_server", "catalogs", name)
            catalog_abs = self._base_dir / catalog_rel
            catalog_abs.mkdir(parents=True, exist_ok=True)
            env = Environment(
                name=name,
                display_name=display_name,
                color=color,
                description=description,
                catalog_dir=catalog_rel,
                created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            )
            self._environments[name] = env
            self._write_to_disk()
            return env

    def update_environment(self, name: str, updates: dict[str, Any]) -> Environment:
        """Update display_name, color, description. Cannot change name or catalog_dir.

        Raises NotFoundError if not found, ValueError if invalid field.
        """
        with self._lock:
            env = self._environments.get(name)
            if env is None:
                raise NotFoundError(f"Environment not found: {name}")
            for key in updates:
                if key not in _UPDATABLE_FIELDS:
                    raise ValueError(f"Cannot update field: {key}")
            for key, value in updates.items():
                setattr(env, key, value)
            self._write_to_disk()
            return env

    def delete_environment(self, name: str, force: bool = False) -> None:
        """Delete environment. If force=False, raises ValueError if catalog_dir is non-empty.

        At least one environment must remain.
        Raises NotFoundError if not found, ValueError if constraints violated.
        """
        with self._lock:
            env = self._environments.get(name)
            if env is None:
                raise NotFoundError(f"Environment not found: {name}")
            if len(self._environments) <= 1:
                raise ValueError("Cannot delete the last environment")
            catalog_abs = self._base_dir / env.catalog_dir
            if catalog_abs.exists() and any(catalog_abs.iterdir()):
                if not force:
                    raise ValueError(
                        f"Catalog directory is non-empty: {env.catalog_dir}. "
                        "Use force=True to delete anyway."
                    )
                shutil.rmtree(catalog_abs, ignore_errors=True)
            elif catalog_abs.exists():
                shutil.rmtree(catalog_abs, ignore_errors=True)
            del self._environments[name]
            self._write_to_disk()

    def ensure_defaults(self) -> None:
        """If no environments exist, create dev/test/prod defaults."""
        with self._lock:
            if self._environments:
                return
        # Release lock before calling create_environment (which acquires it)
        defaults = [
            ("dev", "Development", "#3B82F6", "Author and test new reports"),
            ("test", "Testing / UAT", "#F59E0B", "Review before production"),
            ("prod", "Production", "#10B981", "Live reports for viewers"),
        ]
        for name, display_name, color, description in defaults:
            self.create_environment(name, display_name, color=color, description=description)

    def get_catalog_path(self, env_name: str) -> Path:
        """Return the absolute Path to an environment's catalog directory."""
        env = self.get_environment(env_name)
        return (self._base_dir / env.catalog_dir).resolve()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_name(name: str) -> None:
        if not isinstance(name, str):
            raise ValueError(
                f"Invalid environment name: {name!r}. Name must be a string."
            )
        if not _NAME_RE.match(name):
            raise ValueError(
                f"Invalid environment name: {name!r}. "
                "Must be 2-32 chars, lowercase alphanumeric + hyphens, "
                "no leading/trailing hyphens."
            )

    def _read_from_disk(self) -> None:
        data = _load_yaml(self._yaml_path)
        envs_raw = data.get("environments", [])
        for item in envs_raw:
            env = Environment(
                name=item["name"],
                display_name=item.get("display_name", item["name"]),
                color=item.get("color", "#3B82F6"),
                description=item.get("description", ""),
                catalog_dir=item.get("catalog_dir", ""),
                created_at=item.get("created_at", ""),
            )
            self._environments[env.name] = env

    def _write_to_disk(self) -> None:
        data = {
            "environments": [asdict(env) for env in self._environments.values()]
        }
        _save_yaml(self._yaml_path, data)
