# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH)

block_cipher = None

# Collect every stream_controller submodule so plugin imports resolve correctly
# even though plugins are loaded dynamically at runtime.
_sc_modules = collect_submodules('stream_controller')

# Collect non-Python data files from the stream_controller package
# (HTML overlays, QSS stylesheets, JSON manifests, images, etc.)
_sc_datas = collect_data_files('stream_controller', excludes=['**/*.py', '**/*.pyc'])

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'stream_controller' / 'resources'), 'stream_controller/resources'),
        *_sc_datas,
    ],
    hiddenimports=[
        *_sc_modules,
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
        'obsws_python',
        'pygame',
        'mutagen',
        'flask',
        'werkzeug',
        'sounddevice',
        'numpy',
        'keyring',
        'keyring.backends',
        'keyring.backends.macOS',
        'keyring.backends.Windows',
        'keyring.backends.SecretService',
        'keyring.backends.fail',
        'certifi',
        'websocket',
        'sqlite3',
        '_sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='StreamShift',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'stream_controller' / 'resources' / 'icon.icns') if sys.platform == 'darwin'
        else str(ROOT / 'stream_controller' / 'resources' / 'icon.ico') if sys.platform == 'win32'
        else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StreamShift',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='StreamShift.app',
        icon=str(ROOT / 'stream_controller' / 'resources' / 'icon.icns'),
        bundle_identifier='com.streamshift.app',
        info_plist={
            'CFBundleName': 'StreamShift',
            'CFBundleDisplayName': 'StreamShift',
            'CFBundleShortVersionString': '1.0.4',
            'CFBundleVersion': '1.0.4',
            'NSMicrophoneUsageDescription': 'StreamShift uses the microphone for PNGtuber avatar animation.',
            'NSHighResolutionCapable': True,
        },
    )
