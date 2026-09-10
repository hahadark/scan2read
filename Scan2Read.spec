# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

# sv_ttk's theme is loaded at runtime via Tcl `source` on its .tcl file and
# PNG sprite sheets (see sv_ttk/__init__.py's `Path(__file__).with_name(...)`)
# -- pure-Python analysis alone won't pick up these non-.py assets, so they
# need to be collected explicitly or the frozen app raises a missing-file
# error the first time it tries to apply the theme.
datas = collect_data_files('sv_ttk')

a = Analysis(
    ['scripts/gui_launcher.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Scan2Read',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Scan2Read',
)
