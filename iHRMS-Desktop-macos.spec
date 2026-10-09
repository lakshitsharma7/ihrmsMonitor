# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collect full package for shiboken6 (critical binding layer for PySide6)
shiboken_datas, shiboken_binaries, shiboken_hiddenimports = collect_all('shiboken6')

# Collect full package and CA bundle for certifi
certifi_datas, certifi_binaries, certifi_hiddenimports = collect_all('certifi')
import certifi
cacert_path = certifi.where()

all_binaries = shiboken_binaries + certifi_binaries
all_datas = [
    ('assets', 'assets'),
    ('VERSION', '.'),
    ('version.log', '.'),
    (cacert_path, 'certifi'),
    (cacert_path, '.'),
] + shiboken_datas + certifi_datas

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
        'platform_support.macos',
        'platform_support.macos.active_window',
        'platform_support.macos.idle_detector',
        'platform_support.macos.provider',
        'services',
        'services.activity_service',
        'services.attendance_service',
        'services.device_registry_service',
        'services.error_report_service',
        'services.hrms_portal_service',
        'services.mac_permission_service',
        'services.network_monitor',
        'services.screenshot',
        'services.secure_session',
        'services.session_service',
        'services.settings_service',
        'services.sync_service',
        'services.task_service',
        'services.uninstall_reporter',
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
        'ui.task_table',
        'ui.update_dialog',
        'ui.attendance_page',
        'ui.leave_balance_dialog',
        'ui.weekly_timeline',
        'utils',
        'utils.device',
        'utils.logger',
        'utils.paths',
        'utils.security',
        'utils.system_health',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
        'sqlalchemy',
        'sqlalchemy.sql.default_comparator',
        'sqlalchemy.dialects.sqlite',
        'psutil',
        'PIL',
        'PIL.Image',
        'PIL.ImageGrab',
        'PIL.PngImagePlugin',
        'PIL.JpegImagePlugin',
        'mss',
        'mss.darwin',
        'requests',
        'urllib3',
        'certifi',
        'idna',
        'charset_normalizer',
        'ctypes',
        'multiprocessing',
        'AppKit',
        'Quartz',
        'Cocoa',
        'Foundation',
        'objc',
    ] + shiboken_hiddenimports + certifi_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'win32gui',
        'win32process',
        'win32api',
        'win32con',
        'win32event',
        'win32ui',
        'pywintypes',
        'winreg',
        'ctypes.wintypes',
        'mss.windows',
        'tkinter',
        'tcl',
        'tk',
        'wx',
        'matplotlib',
        'scipy',
        'numpy',
        'pandas',
        'torch',
        'transformers',
        'onnxruntime',
        'playwright',
        'sentence_transformers',
        'sklearn',
        'IPython',
        'notebook',
        'jupyter',
        'ipykernel',
        'ipywidgets',
        'PIL._avif',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQuick3D',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DExtras',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtDesigner',
        'PySide6.QtUiTools',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtPositioning',
        'PySide6.QtLocation',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtSpatialAudio',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtVirtualKeyboard',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtStateMachine',
        'unittest',
        'doctest',
        'pdb',
        'test',
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

# Filter out genuinely unused Qt6 dynamic libraries and plugins
excluded_bin_patterns = (
    'Qt6Quick', 'Qt6Qml', 'Qt6Pdf', 'Qt6Sensors',
    'Qt6SerialPort', 'Qt6Positioning', 'Qt6Location', 'Qt6Bluetooth',
    'Qt6Nfc', 'Qt6SpatialAudio', 'Qt6Charts', 'Qt6DataVisualization',
    'Qt6VirtualKeyboard', 'Qt6RemoteObjects', 'Qt6Scxml', 'Qt6Multimedia',
    'Qt63D', 'QtQuick', 'QtQml', 'QtPdf'
)

filtered_binaries = [
    b for b in a.binaries
    if not any(pat.lower() in b[0].lower() for pat in excluded_bin_patterns)
]

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='iHRMS-Desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='entitlements.mac.plist' if os.path.exists('entitlements.mac.plist') else None,
    icon='assets/ihrms-logo-icon.icns',
)

coll = COLLECT(
    exe,
    filtered_binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='iHRMS-Desktop',
)

app_version = '1.0'
if os.path.exists('VERSION'):
    try:
        with open('VERSION', 'r', encoding='utf-8') as vf:
            v = vf.read().strip()
            if v:
                app_version = v
    except Exception:
        pass

app = BUNDLE(
    coll,
    name='iHRMS-Desktop.app',
    icon='assets/ihrms-logo-icon.icns',
    bundle_identifier='com.indovision.ihrms-desktop',
    info_plist={
        'CFBundleName': 'iHRMS Desktop',
        'CFBundleDisplayName': 'iHRMS Desktop',
        'CFBundleIdentifier': 'com.indovision.ihrms-desktop',
        'CFBundleVersion': app_version,
        'CFBundleShortVersionString': app_version,
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': '????',
        'CFBundleExecutable': 'iHRMS-Desktop',
        'CFBundleIconFile': 'ihrms-logo-icon.icns',
        'NSHighResolutionCapable': 'True',
        'NSRequiresAquaSystemAppearance': 'False',
        'LSMinimumSystemVersion': '11.0',
        'NSAppleEventsUsageDescription': 'iHRMS Desktop monitors active applications and window titles to track employee work activity.',
        'NSScreenCaptureUsageDescription': 'iHRMS Desktop takes periodic desktop screenshots for work activity verification.',
    },
)
