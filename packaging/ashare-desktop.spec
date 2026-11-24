# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ashare-mcp desktop app (onedir, windowed).

Run via scripts/build_desktop.py, which builds the web frontend and stages
src/ashare_mcp/web/static first so collect_all("ashare_mcp") picks it up.
"""
from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
)

block_cipher = None

# spec-relative paths resolve against packaging/ regardless of cwd
_ICO = "ashare.ico"
datas = [(_ICO, ".")]  # tray NotifyIcon reads it from _internal
binaries = []
hiddenimports = []

# Packages with data files / dynamic imports that need full collection.
for pkg in (
    "ashare_mcp",      # web/static + bundled csv data files
    "akshare",         # data files
    "py_mini_racer",   # mini_racer.dll + icudtl.dat
    "tushare",
    "webview",         # pywebview js/lib assets
    "clr_loader",      # .NET runtime loader
    "pythonnet",
    "mcp",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # noqa: BLE001
        print(f"collect_all({pkg}) skipped: {e}")

hiddenimports += collect_submodules("ashare_mcp")
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]

a = Analysis(
    ["../src/ashare_mcp/desktop.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["streamlit", "plotly", "matplotlib", "pytest",
              "tkinter", "notebook", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ashare-desktop",
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
    icon=_ICO,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ashare-desktop",
)
