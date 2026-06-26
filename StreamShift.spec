# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(SPECPATH)

block_cipher = None

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'stream_controller' / 'resources'), 'stream_controller/resources'),
        (str(ROOT / 'stream_controller' / 'plugins'), 'stream_controller/plugins'),
    ],
    hiddenimports=[
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
    icon=str(ROOT / 'stream_controller' / 'resources' / 'icon.icns') if sys.platform == 'darwin' else None,
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
            'CFBundleShortVersionString': '1.0.3',
            'CFBundleVersion': '1.0.3',
            'NSMicrophoneUsageDescription': 'StreamShift uses the microphone for PNGtuber avatar animation.',
            'NSHighResolutionCapable': True,
        },
    )
