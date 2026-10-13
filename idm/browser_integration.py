"""Registers the native-messaging host so Chrome and Edge can start it for the Lavati Downloader extension.

Done by the app itself at startup (idempotent, per-user, no admin rights): a manifest file in the user data folder
plus the registry keys that point the browsers at it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOST_NAME = "com.lavati.idm_downloader"
# derived from the "key" in browser_extension/manifest.json, so it is the same on every machine
EXTENSION_ID = "bnpkghimiajapbmgmbalfaecmacecpfa"
_REGISTRY_PATHS = (
    rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}",
    rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}",
)


def app_dir() -> Path:
    """Folder holding the executable (installed) or the repository root (source checkout)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def extension_dir() -> Path | None:
    """The unpacked extension to load in the browser, if it ships with this install."""
    for candidate in (app_dir() / "browser_extension", app_dir() / "_internal" / "browser_extension"):
        if (candidate / "manifest.json").exists():
            return candidate
    return None


def host_command_path(data_dir: Path) -> Path:
    """What the browser launches. A real exe when installed; a tiny .bat that runs the module from source."""
    exe = app_dir() / "idm-native-host.exe"
    if exe.exists():
        return exe
    bat = data_dir / "idm-native-host.bat"
    bat.write_text(f'@echo off\r\n"{sys.executable}" -m idm.native_host\r\n', encoding="ascii")
    return bat


def build_manifest(host_path: Path) -> dict:
    return {
        "name": HOST_NAME,
        "description": "Lavati Downloader browser integration",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }


def register(data_dir: str | os.PathLike) -> Path | None:
    """Write the manifest and point Chrome and Edge at it. Returns the manifest path, or None off Windows."""
    if sys.platform != "win32":
        return None
    import winreg

    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    manifest_path = data / f"{HOST_NAME}.json"
    manifest_path.write_text(json.dumps(build_manifest(host_command_path(data)), indent=2), encoding="utf-8")
    for subkey in _REGISTRY_PATHS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
    return manifest_path


def unregister() -> None:
    if sys.platform != "win32":
        return
    import winreg

    for subkey in _REGISTRY_PATHS:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except OSError:
            pass
