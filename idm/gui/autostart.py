"""Best-effort "start on boot" toggle, implemented per-OS.

Windows: a value under HKCU\\...\\Run (no admin rights needed).
macOS/Linux: not implemented for v1 (would be a LaunchAgent plist / a
.desktop file under autostart respectively) -- is_supported() reports this
so the Settings dialog can disable the checkbox instead of silently no-op'ing.
"""

from __future__ import annotations

import sys

APP_REGISTRY_NAME = "LavatiDownloader"


def is_supported() -> bool:
    return sys.platform == "win32"


def is_enabled() -> bool:
    if not is_supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, APP_REGISTRY_NAME)
            return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool) -> None:
    if not is_supported():
        return
    import winreg
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            command = _launch_command()
            winreg.SetValueEx(key, APP_REGISTRY_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_REGISTRY_NAME)
            except FileNotFoundError:
                pass


def _launch_command() -> str:
    """Command to relaunch the app. Works both from a PyInstaller-frozen
    executable (sys.executable IS the app) and from a plain `python -m idm`
    dev run (sys.executable is the interpreter, so pass the module)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m idm.main'
