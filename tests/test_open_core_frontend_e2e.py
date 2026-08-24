from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Iterator

import pytest
from playwright.sync_api import Page, expect


pytestmark = [pytest.mark.ui, pytest.mark.playwright, pytest.mark.serial]
ROOT = Path(__file__).resolve().parents[1]
DESKTOP_TEST_TOKEN = "open-core-e2e-desktop-token"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_ready(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as error:  # noqa: BLE001 - retain the final startup error
            last_error = error
        time.sleep(0.2)
    raise RuntimeError(f"Open-core runtime did not become ready: {last_error}")


@pytest.fixture()
def open_core_runtime(tmp_path: Path) -> Iterator[str]:
    open_core_frontend = ROOT / "dax_ui" / "frontend" / "dist-open-core"
    frontend = open_core_frontend if open_core_frontend.is_dir() else ROOT / "dax_ui" / "frontend" / "dist"
    assert (frontend / "index.html").is_file(), "Build the public frontend before this test"
    project = tmp_path / "sample_project"
    shutil.copytree(ROOT / "sample_project", project)
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["DAX_FRONTEND_DIST"] = str(frontend)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "dax_ui.open_core_main",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workspace",
            str(project),
            "--auth-token",
            DESKTOP_TEST_TOKEN,
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/runtime/ui-react"
    try:
        _wait_ready(url)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture()
def open_core_runtime_without_project(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    open_core_frontend = ROOT / "dax_ui" / "frontend" / "dist-open-core"
    frontend = open_core_frontend if open_core_frontend.is_dir() else ROOT / "dax_ui" / "frontend" / "dist"
    assert (frontend / "index.html").is_file(), "Build the public frontend before this test"
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["DAX_FRONTEND_DIST"] = str(frontend)
    env["DAX_PROJECT_PATH"] = r"%CD%\sample_project"
    env["HOME"] = str(tmp_path / "home")
    env["USERPROFILE"] = str(tmp_path / "home")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "dax_ui.open_core_main",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--auth-token",
            DESKTOP_TEST_TOKEN,
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/runtime/ui-react"
    try:
        _wait_ready(url)
        yield url, tmp_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_open_core_shell_views_visuals_and_save(open_core_runtime: str, page: Page) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("response", lambda response: failed_responses.append(f"{response.status} {response.url}") if response.status >= 400 else None)

    response = page.goto(open_core_runtime, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    expect(page.locator('[data-testid="app-root"]')).to_be_visible(timeout=30_000)
    expect(page.locator('[data-testid="loading-overlay"]')).to_have_count(0, timeout=30_000)
    expect(page).to_have_title("sample_project — Dummy BI Engine")
    screenshot = os.environ.get("OPEN_CORE_QA_SCREENSHOT", "").strip()
    if screenshot:
        page.screenshot(path=screenshot, full_page=True)
    topbar = page.locator('[data-testid="topbar"]')
    try:
        expect(topbar).to_be_visible(timeout=30_000)
    except AssertionError as error:
        details = page.get_by_text("Error details", exact=True)
        if details.count():
            details.click()
        raise AssertionError(
            f"Open-core shell failed to render. page_errors={page_errors}; "
            f"console_errors={console_errors}; body={page.locator('body').inner_text()}"
        ) from error
    expect(page.locator('[data-testid="project-label"]')).to_contain_text("sample_project", timeout=30_000)

    shell_layout = page.locator('[data-testid="app-root"]').evaluate(
        "el => ({display: getComputedStyle(el).display, height: el.getBoundingClientRect().height})"
    )
    assert shell_layout["display"] == "flex"
    assert shell_layout["height"] >= 600
    logo = page.locator('[data-testid="logo"] img')
    expect(logo).to_be_visible()
    assert logo.evaluate("img => img.naturalWidth") > 0

    for view in ("report", "data", "model"):
        expect(page.locator(f'[data-testid="view-switch-{view}"]')).to_be_visible()
    expect(page.locator('[data-testid="view-switch-transform"]')).to_have_count(0)
    expect(page.locator('[data-testid="vpane-matrix"]')).to_have_count(0)
    expect(page.locator('[data-testid="vpane-table"]')).to_be_visible()
    expect(page.locator('[data-testid="vpane-bar"]')).to_be_visible()

    page.locator('[data-testid="view-switch-data"]').click()
    expect(page.locator('[data-testid="data-view"]')).to_be_visible()
    page.locator('[data-testid="view-switch-model"]').click()
    expect(page.locator('[data-testid="relationship-graph"]')).to_be_visible()
    expect(page.locator('[data-testid="model-subview-edu"]')).to_have_count(0)
    expect(page.locator('[data-testid="model-subview-ml"]')).to_have_count(0)

    page.locator('[data-testid="view-switch-report"]').click()
    existing_visuals = page.locator('[data-testid^="visual-v_"]').count()
    page.locator('[data-testid="vpane-table"]').click()
    expect(page.locator('[data-testid^="visual-v_"]')).to_have_count(existing_visuals + 1)
    expect(page.locator('[data-testid="dirty-indicator"]')).to_be_visible()
    page.locator('[data-testid="save-all-btn"]').click()
    expect(page.locator('[data-testid="dirty-indicator"]')).to_have_count(0, timeout=20_000)

    if screenshot:
        page.screenshot(path=screenshot, full_page=True)
    assert page_errors == []
    assert console_errors == [], f"console_errors={console_errors}; failed_responses={failed_responses}"


def test_startup_project_picker_can_search_create_and_continue_empty(
    open_core_runtime_without_project: tuple[str, Path],
    page: Page,
) -> None:
    url, tmp_path = open_core_runtime_without_project
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("response", lambda response: failed_responses.append(f"{response.status} {response.url}") if response.status >= 400 else None)

    response = page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    picker = page.locator('[data-testid="project-picker"]')
    expect(picker).to_be_visible(timeout=30_000)
    expect(page.locator('[data-testid="project-picker-title"]')).to_have_text("Open or create a project")
    expect(page.locator('[data-testid="project-picker-search"]')).to_be_visible()
    expect(page.locator('[data-testid="project-picker-close"]')).to_be_visible()
    expect(page.locator('[data-testid="project-picker-continue"]')).to_be_visible()
    expect(page.locator('[data-testid="project-picker-error"]')).to_have_count(0)
    expect(page.locator('[data-testid="project-picker-input"]')).not_to_have_value(r"%CD%\sample_project")

    page.locator('[data-testid="project-picker-search"]').fill("no-project-matches-this")
    expect(page.get_by_text("No matching recent projects", exact=True)).to_be_visible()
    page.locator('[data-testid="project-picker-search"]').fill("")

    page.locator('[data-testid="project-picker-new-tab"]').click()
    new_project_parent = tmp_path / "projects"
    page.locator('[data-testid="project-picker-new-location"]').fill(str(new_project_parent))
    page.locator('[data-testid="project-picker-new-name"]').fill("Blank Project")
    expect(page.locator('[data-testid="project-picker-create-preview"]')).to_contain_text("Blank Project")
    page.locator('[data-testid="project-picker-create"]').click()

    try:
        expect(picker).to_have_count(0, timeout=30_000)
    except AssertionError as error:
        raise AssertionError(
            f"Project creation did not close the picker. body={page.locator('body').inner_text()}; "
            f"page_errors={page_errors}; console_errors={console_errors}"
        ) from error
    expect(page.locator('[data-testid="project-label"]')).to_contain_text("Blank Project", timeout=30_000)
    project_path = new_project_parent / "Blank Project"
    assert (project_path / "semantic_model.yaml").is_file()
    assert (project_path / "model" / "measures.yaml").is_file()
    assert (project_path / "reports" / "pages.yaml").is_file()

    page.goto(url, wait_until="domcontentloaded")
    expect(picker).to_be_visible(timeout=30_000)
    page.locator('[data-testid="project-picker-close"]').click()
    expect(picker).to_have_count(0)
    expect(page.locator('[data-testid="app-root"]')).to_be_visible()
    expect(page.locator('[data-testid="error-display"]')).to_have_count(0)
    expect(page.locator('[data-testid="project-label"]')).to_contain_text("No project loaded")

    screenshot = os.environ.get("OPEN_CORE_PICKER_QA_SCREENSHOT", "").strip()
    if screenshot:
        page.goto(url, wait_until="domcontentloaded")
        expect(picker).to_be_visible(timeout=30_000)
        page.screenshot(path=screenshot, full_page=True)

    assert page_errors == []
    assert console_errors == [], f"console_errors={console_errors}; failed_responses={failed_responses}"
