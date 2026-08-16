# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('Singularity-Engine.ico', '.'), ('Singularity-Engine2.png', '.')]
hiddenimports = ['psutil', 'pystray', 'PIL', 'pywinstyles', 'ui.mixins.system_mixin', 'ui.mixins.installer_mixin', 'ui.mixins.build_mixin', 'ui.mixins.game_mixin']
datas += collect_data_files('pywinstyles')
hiddenimports += collect_submodules('psutil')
hiddenimports += collect_submodules('pystray')
hiddenimports += collect_submodules('PIL')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='SingularityEngine',
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
    icon=['Singularity-Engine.ico'],
)
