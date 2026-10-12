"""
Windows autostart-registry helpers and single-instance management for WinZapp.

Registry key used for autostart:
    HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run  →  "TeleZapp"
    (copies installed before the rename used the value name "WinZapp"; it is
    still recognised and is replaced by the new name the next time autostart
    is written — see ``_legacy_value_is_ours``)

Single-instance mutex:
    Named mutex "Global\\WinZappSingleInstance" is acquired in the first
    instance and checked in subsequent launches.
"""

import os
import sys
import hashlib
from app_paths import data_path
from branding import APP_NAME, LEGACY_APP_NAME, is_app_window_title

_AUTORUN_KEY  = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_AUTORUN_NAME = APP_NAME
_LEGACY_AUTORUN_NAME = LEGACY_APP_NAME

def _get_dynamic_mutex_name() -> str:
    try:
        path_hash = hashlib.md5(data_path().encode("utf-8")).hexdigest()
        return f"Global\\WinZappSingleInstance_{path_hash}"
    except Exception:
        return "Global\\WinZappSingleInstance"

# The module-level handle must stay alive for the lifetime of the process;
# Windows releases the mutex when the process exits or the handle is closed.
_mutex_handle = None


# ── Command-line string ───────────────────────────────────────────────────────

def get_autostart_command() -> str:
    """
    Return the command that should be stored in the Run registry value.

    * Compiled (Nuitka/PyInstaller): ``"<install dir>\\WinZapp.exe" --background``
    * Development:                   ``"python.exe" "main.py" --background``
    """
    argv0 = os.path.abspath(sys.argv[0])
    # Detect compiled binary: sys.frozen is set by PyInstaller/cx_Freeze,
    # or argv[0] itself is an .exe (Nuitka standalone).
    if getattr(sys, "frozen", False) or argv0.lower().endswith(".exe"):
        return f'"{argv0}" --background'
    else:
        # Source-code run — interpreter + script
        return f'"{sys.executable}" "{argv0}" --background'


# ── Registry helpers ──────────────────────────────────────────────────────────

def _legacy_value_is_ours(command: str) -> bool:
    """Whether a legacy "WinZapp" Run value launches THIS installation.

    A machine can also run the original WinZapp, which owns a value with the
    same name; that one must be left alone.
    """
    try:
        ours = os.path.normcase(os.path.abspath(sys.argv[0]))
        return ours != "" and ours in os.path.normcase(command or "")
    except Exception:
        return False


def _query(winreg, name):
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0, winreg.KEY_READ
        )
    except OSError:
        return None
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)


def is_autostart_enabled() -> bool:
    """Return True if this app has an entry in the current-user Run key.

    The new value name counts, and so does the legacy "WinZapp" one when it
    launches this installation (an update in place never rewrote it).
    """
    import winreg
    if _query(winreg, _AUTORUN_NAME) is not None:
        return True
    legacy = _query(winreg, _LEGACY_AUTORUN_NAME)
    return legacy is not None and _legacy_value_is_ours(legacy)


def enable_autostart() -> None:
    """
    Write the TeleZapp Run registry value (and retire this install's legacy one).

    Raises ``OSError`` (or a subclass) if the key cannot be written — the
    caller is responsible for showing a user-facing error message.
    """
    import winreg
    cmd = get_autostart_command()
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0, winreg.KEY_SET_VALUE
    )
    try:
        winreg.SetValueEx(key, _AUTORUN_NAME, 0, winreg.REG_SZ, cmd)
        # Only after the new value is in place, and only if the old one is ours.
        legacy = _query(winreg, _LEGACY_AUTORUN_NAME)
        if legacy is not None and _legacy_value_is_ours(legacy):
            try:
                winreg.DeleteValue(key, _LEGACY_AUTORUN_NAME)
            except OSError:
                pass
    finally:
        winreg.CloseKey(key)


def migrate_autostart() -> bool:
    """Switch an existing legacy entry to the new name, keeping autostart on.

    Returns True when something was rewritten. Safe to call on every start.
    """
    import winreg
    legacy = _query(winreg, _LEGACY_AUTORUN_NAME)
    if legacy is None or not _legacy_value_is_ours(legacy):
        return False
    enable_autostart()
    return True


def disable_autostart() -> None:
    """Remove this app's Run registry value (silently ignores missing entries)."""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0, winreg.KEY_SET_VALUE
        )
    except OSError:
        return
    try:
        try:
            winreg.DeleteValue(key, _AUTORUN_NAME)
        except OSError:
            pass
        legacy = _query(winreg, _LEGACY_AUTORUN_NAME)
        if legacy is not None and _legacy_value_is_ours(legacy):
            try:
                winreg.DeleteValue(key, _LEGACY_AUTORUN_NAME)
            except OSError:
                pass
    finally:
        winreg.CloseKey(key)


# ── Single-instance helpers ───────────────────────────────────────────────────

def acquire_single_instance_mutex() -> bool:
    """
    Attempt to create and own the named mutex.

    Returns ``True``  — this is the first (and only) running instance.
    Returns ``False`` — another instance already holds the mutex.
    """
    import ctypes
    global _mutex_handle
    mutex_name = _get_dynamic_mutex_name()
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
    # ERROR_ALREADY_EXISTS (183) means a second instance tried to create the mutex
    return ctypes.windll.kernel32.GetLastError() != 183


def activate_existing_window() -> None:
    """
    Enumerate top-level windows, find one whose title starts with the app name (TeleZapp, or WinZapp for
    a copy that has not updated yet),
    restore it (in case it is hidden or minimised), and bring it to the
    foreground.  Safe to call even if no matching window is found.
    """
    import ctypes
    from ctypes import wintypes

    found = [0]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd, lparam):
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        if is_app_window_title(buf.value):
            found[0] = hwnd
            return False   # stop enumeration
        return True        # keep going

    ctypes.windll.user32.EnumWindows(_enum_proc, 0)

    if found[0]:
        SW_SHOW = 5
        ctypes.windll.user32.ShowWindow(found[0], SW_SHOW)
        ctypes.windll.user32.SetForegroundWindow(found[0])
