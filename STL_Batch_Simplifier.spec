# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('pymeshlab')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


source = Path(SPECPATH) / 'src'
a = Analysis(
    [str(source / 'stl_batch_simplifier_qt.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Do not bundle Poppler's ICU 78 DLLs found on the build PATH. Their exported
# function names are versioned, while Qt 6 expects Windows' unversioned system ICU.
a.binaries = [
    entry for entry in a.binaries
    if entry[0].lower().replace('\\', '/').split('/')[-1] not in {'icuuc.dll', 'icudt78.dll', 'icudt.dll'}
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='STL_Batch_Simplifier_v1.7',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
