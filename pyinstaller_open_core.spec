# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller sidecar for the public open-core desktop application."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


HERE = Path(SPECPATH)
FRONTEND_DIST = HERE / "dax_ui" / "frontend" / "dist"
SAMPLE_PROJECT = HERE / "sample_project"

if not (FRONTEND_DIST / "index.html").is_file():
    raise SystemExit("Open-core frontend is missing; run npm run build first")

datas = [
    (str(FRONTEND_DIST), os.path.join("dax_ui", "frontend", "dist")),
    (str(HERE / "dax_project" / "visual_types.yaml"), "dax_project"),
    (str(HERE / "dax_sql_mapping.json"), "."),
]
if SAMPLE_PROJECT.is_dir():
    datas.append((str(SAMPLE_PROJECT), "sample_project"))

hiddenimports = [
    "dax_ui",
    "dax_ui.server",
    "dax_ui.version",
    "dax_ui.open_core_app",
    "dax_ui.open_core_main",
    "dax_project",
    "dax_project.loader",
    "dax_project.model",
    "dax_project.save",
    "dax_project.security",
    "dax_project.open_core_profile",
    "dax_engine",
    "dax_engine.compiler",
    "dax_engine.context",
    "dax_engine.filters_ir",
    "dax_engine.ir",
    "dax_engine.planner",
    "dax_engine.relationships",
    "dax_engine.storage_modes",
    "dax_engine.table_sources",
    "dax_parser",
    "dax_parser.ast",
    "dax_parser.ir_mapper",
    "dax_parser.parser",
    "dax_parser.tokenizer",
    "duckdb",
    "fastapi",
    "pydantic",
    "starlette",
    "uvicorn",
    "yaml",
]
for package in ["uvicorn", "fastapi", "starlette", "pydantic", "yaml"]:
    hiddenimports += collect_submodules(package)

a = Analysis(
    [str(HERE / "dax_ui" / "open_core_main.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "jupyter",
        "matplotlib",
        "notebook",
        "playwright",
        "pytest",
        "scipy",
        "tkinter",
        "dax_engine.autogen",
        "dax_engine.decision",
        "dax_engine.explanations",
        "dax_ui.server.routes_enterprise",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="dax_backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
