# region_mirror.spec
# PyInstaller-Spec für den Windows-Build (via GitHub Actions oder lokalem Windows)
# Aufruf: pyinstaller region_mirror.spec

import sys
from PyInstaller.building.build_main import Analysis, PYZ, EXE

a = Analysis(
    ['daoc_overlay.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'mss',
        'mss.windows',
        'numpy',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RegionMirror',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # kein CMD-Fenster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,          # optional: icon='icon.ico' eintragen
    uac_admin=False,
)
