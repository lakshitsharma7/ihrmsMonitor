# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collect full package for shiboken6 (critical binding layer for PySide6)
shiboken_datas, shiboken_binaries, shiboken_hiddenimports = collect_all('shiboken6')

# Explicitly ensure all files from shiboken6 are placed in 'shiboken6' subfolder
shiboken_explicit_binaries = []
try:
    import shiboken6
    shiboken_pkg_dir = Path(shiboken6.__file__).parent
    for f in shiboken_pkg_dir.iterdir():
        if f.is_file():
            shiboken_explicit_binaries.append((str(f), 'shiboken6'))
except Exception:
    pass

# Collect VC runtime and helper binaries from PySide6 if available
extra_binaries = []
try:
    import PySide6
    pyside6_dir = Path(PySide6.__file__).parent
    for dll_name in [
        'msvcp140.dll',
        'msvcp140_1.dll',
        'msvcp140_2.dll',
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'concrt140.dll',
        'vcomp140.dll',
    ]:
        dll_file = pyside6_dir / dll_name
        if dll_file.is_file():
            extra_binaries.append((str(dll_file), '.'))
except Exception:
    pass

all_binaries = extra_binaries + shiboken_binaries + shiboken_explicit_binaries
all_datas = [
    ('assets', 'assets'),
    ('VERSION', '.'),
] + shiboken_datas

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=[
        'config',
        'config.settings',
        'config.api_config',
        'database',
        'database.database',
        'database.models',
        'database.repository',
        'platform_support',
        'platform_support.windows',
        'platform_support.windows.active_window',
        'platform_support.windows.idle_detector',
        'platform_support.windows.provider',
        'platform_support.macos',
        'services',
        'services.activity_service',
        'services.device_registry_service',
        'services.error_report_service',
        'services.screenshot',
        'services.secure_session',
        'services.session_service',
        'services.settings_service',
        'services.sync_service',
        'services.update_service',
        'services.update_state',
        'system',
        'system.startup',
        'system.tray',
        'tracker',
        'tracker.activity_tracker',
        'tracker.tracker_worker',
        'ui',
        'ui.activity_table',
        'ui.dashboard',
        'ui.login_window',
        'ui.main_window',
        'ui.settings',
        'ui.styles',
        'ui.update_dialog',
        'ui.weekly_timeline',
        'utils',
        'utils.device',
        'utils.logger',
        'utils.paths',
        'utils.security',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'sqlalchemy',
        'sqlalchemy.sql.default_comparator',
        'sqlalchemy.dialects.sqlite',
        'win32gui',
        'win32process',
        'win32api',
        'win32con',
        'win32event',
        'pywintypes',
        'winreg',
        'psutil',
        'PIL',
        'PIL.Image',
        'PIL.ImageGrab',
        'PIL.BmpImagePlugin',
        'PIL.PngImagePlugin',
        'PIL.JpegImagePlugin',
        'mss',
        'mss.windows',
        'requests',
        'urllib3',
        'certifi',
        'idna',
        'charset_normalizer',
        'ctypes',
        'ctypes.wintypes',
        'multiprocessing',
    ] + shiboken_hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['hooks/rthook-pyside6-fix.py'],

    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'torch',
        'transformers',
        'onnxruntime',
        'playwright',
        'sentence_transformers',
        'IPython',
        'notebook',
        'jupyter',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='iHRMS Monitor',
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
    version='file_version_info.txt',
    icon=['assets/ihrms-logo-icon.ico'],
)

from PyInstaller.building.datastruct import Tree

shiboken_tree = Tree(str(Path(shiboken6.__file__).parent), prefix='shiboken6')

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    shiboken_tree,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='iHRMS Monitor',
)


