# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file build for the Windows desktop release.

Purpose: Package the KoshFlow desktop application and brand assets into KoshFlow.exe.
Project: KoshFlow | Source version: 0.6.3
Maintainer: Mayank Chawdhari (BOSS294)
"""

from pathlib import Path

project_root = Path(SPECPATH).resolve()
asset_dir = project_root / "assets"

analysis = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(asset_dir), "assets")],
    hiddenimports=[
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PIL.Image",
        "reportlab.pdfbase._fontdata",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="KoshFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(asset_dir / "koshflow.ico"),
)
