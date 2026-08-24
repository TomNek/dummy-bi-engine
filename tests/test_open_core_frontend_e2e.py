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
    frontend = ROOT / "dax_ui" / "frontend" / "dist"
    assert (frontend / "index.html").is_file(), "Build the public frontend before this test"
    project = tmp_path / "sample_project"
    shutil.copytree(ROOT / "sample_project", project)
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
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


def test_open_core_shell_views_visuals_and_save(open_core_runtime: str, page: Page) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))

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
    assert console_errors == []
