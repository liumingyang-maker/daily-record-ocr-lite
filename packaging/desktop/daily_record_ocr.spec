# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

root = Path(SPECPATH).parents[1]
datas = [
    (str(root / "config"), "config"),
    (str(root / "lite_app" / "templates"), "lite_app/templates"),
    (str(root / "lite_app" / "static"), "lite_app/static"),
]
hiddenimports = []
binaries = []
for package in ("paddle", "paddleocr", "paddlex", "cv2", "pystray"):
    hiddenimports += collect_submodules(package)
    binaries += collect_dynamic_libs(package)

a = Analysis(
    [str(root / "packaging" / "desktop" / "launcher_entry.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DailyRecordOCR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64" if sys.platform == "darwin" else None,
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DailyRecordOCR",
)
if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="DailyRecordOCR.app",
        icon=None,
        bundle_identifier="com.dailyrecordocr.lite",
        info_plist={
            "CFBundleDisplayName": "手写配方识别",
            "LSMinimumSystemVersion": "14.0",
            "NSHighResolutionCapable": True,
        },
    )
