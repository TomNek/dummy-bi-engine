from __future__ import annotations

from pathlib import Path

import pytest

from dax_project.power_query.credentials import (
    get_credential_secrets,
    upsert_credential_profile,
)
from dax_ui.server._runtime_helpers import _resolve_project_path_runtime
from dax_ui.server._visual_calcs import _parse_one_calc


def test_server_mode_rejects_project_outside_configured_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    inside = allowed / "project"
    outside = tmp_path / "outside"
    inside.mkdir(parents=True)
    outside.mkdir()
    monkeypatch.setenv("DAX_SERVER_MODE", "server")
    monkeypatch.setenv("DAX_PROJECT_PATH", str(allowed))

    assert Path(_resolve_project_path_runtime(str(inside))) == inside.resolve()
    with pytest.raises(ValueError, match="within the configured DAX_PROJECT_PATH"):
        _resolve_project_path_runtime(str(outside))


def test_author_mode_accepts_an_explicit_local_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "chosen-project"
    project.mkdir()
    monkeypatch.setenv("DAX_SERVER_MODE", "author")

    assert Path(_resolve_project_path_runtime(str(project))) == project.resolve()


def test_power_query_secret_store_never_contains_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault.json"
    monkeypatch.setenv("DUMMY_BI_PQ_SECRET_STORE", str(vault))
    monkeypatch.setenv("DUMMY_BI_PQ_SECRET_KEY", str(tmp_path / "vault.key"))

    upsert_credential_profile(
        tmp_path,
        {
            "profile_id": "security-contract",
            "connector_id": "sql",
            "properties": {"connection_string": "Password=not-in-plaintext"},
            "secrets": {"password": "not-in-plaintext"},
        },
    )

    assert get_credential_secrets("security-contract") == {"password": "not-in-plaintext"}
    assert "not-in-plaintext" not in vault.read_text(encoding="utf-8")
    metadata = tmp_path / ".dummy_bi" / "power_query_credential_profiles.json"
    assert "not-in-plaintext" not in metadata.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("expression", "calc_type"),
    [
        ("RANK(DENSE, ROWS, ORDERBY([Sales], DESC))", "rank"),
        (
            'FORMAT(DIVIDE([Sales], COLLAPSEALL([Sales], ROWS)), "percent")',
            "grand_total_pct",
        ),
    ],
)
def test_visual_calculation_parser_uses_linear_patterns(
    expression: str, calc_type: str
) -> None:
    assert _parse_one_calc("test", expression).calc_type == calc_type
