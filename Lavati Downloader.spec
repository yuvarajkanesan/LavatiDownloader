# -*- mode: python ; coding: utf-8 -*-
# One-folder build (the installer compresses it) with two executables sharing one runtime:
#   Lavati Downloader.exe     the app
#   idm-native-host.exe    the Chrome/Edge native-messaging helper (no Qt)
# build.bat then trims unused Qt files.

# the app only uses QtCore / QtGui / QtWidgets / QtNetwork (local socket)
QT_UNUSED = [
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtPdf', 'PySide6.QtSvg',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtMultimedia', 'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtPrintSupport',
]
COMMON_EXCLUDES = ['tkinter', 'unittest', 'pydoc', 'doctest', 'pytest', 'test']

app = Analysis(
    ['idm/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('LICENSE.txt', '.'),
        ('THIRD_PARTY_NOTICES.txt', '.'),
        ('browser_extension', 'browser_extension'),
        ('idm/gui/fonts', 'idm/gui/fonts'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=QT_UNUSED + COMMON_EXCLUDES,
    noarchive=False,
    optimize=2,
)
host = Analysis(
    ['idm/native_host.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'shiboken6', 'yt_dlp', 'requests', 'numpy', 'imageio_ffmpeg'] + COMMON_EXCLUDES,
    noarchive=False,
    optimize=2,
)

app_pyz = PYZ(app.pure)
host_pyz = PYZ(host.pure)

app_exe = EXE(
    app_pyz,
    app.scripts,
    [],
    exclude_binaries=True,
    name='Lavati Downloader',
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
    version='version_info.txt',
    icon=['build_scripts/app_icon.ico'],
)
host_exe = EXE(
    host_pyz,
    host.scripts,
    [],
    exclude_binaries=True,
    name='idm-native-host',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # talks to the browser over stdin/stdout
    version='version_info.txt',
    icon=['build_scripts/app_icon.ico'],
)
coll = COLLECT(
    app_exe, app.binaries, app.datas,
    host_exe, host.binaries, host.datas,
    strip=False,
    upx=False,
    name='Lavati Downloader',
)
