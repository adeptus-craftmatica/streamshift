# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH)

block_cipher = None

# Walk the source tree to build hidden imports for every stream_controller
# module. This is more reliable than collect_submodules() which requires the
# package to be importable on the build machine.
def _find_modules(root: Path, pkg: str) -> list[str]:
    modules = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__' and not d.startswith('.')]
        for fname in filenames:
            if fname.endswith('.py'):
                rel = Path(dirpath).relative_to(root.parent)
                mod = str(rel / fname[:-3]).replace(os.sep, '.').replace('/', '.')
                modules.append(mod)
    return modules

_sc_modules = _find_modules(ROOT / 'stream_controller', 'stream_controller')

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Resources (styles, icons) — physically present on disk in the bundle
        (str(ROOT / 'stream_controller' / 'resources'), 'stream_controller/resources'),
        # Plugins directory — physically present so the plugin loader can scan
        # manifest.json files and discover plugins at runtime
        (str(ROOT / 'stream_controller' / 'plugins'), 'stream_controller/plugins'),
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
        'cryptography',
        'cryptography.hazmat.primitives.ciphers.aead',
        'cryptography.exceptions',
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
            'CFBundleShortVersionString': '1.0.8',
            'CFBundleVersion': '1.0.8',
            'NSMicrophoneUsageDescription': 'StreamShift uses the microphone for PNGtuber avatar animation.',
            'NSHighResolutionCapable': True,
        },
    )
