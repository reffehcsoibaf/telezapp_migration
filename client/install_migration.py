"""Bring an already-installed copy in line with the TeleZapp name.

Why this exists: the installer is the only thing that ever creates the Desktop
and Start-menu shortcuts and the "Add or remove programs" entry, and it never
runs for a copy that updates itself in place. So a copy installed as WinZapp and
updated since keeps ``WinZapp.lnk`` and a "WinZapp" entry in the installed-apps
list forever. This module fixes both on the first run of a build that carries
the new name.

Everything here is best-effort and conservative: it only touches items that
provably belong to THIS installation (a shortcut whose target is this exe, an
uninstall entry whose InstallLocation is this folder), because a machine can
also have the original WinZapp installed next to this one, and its shortcuts
must not be renamed. Any failure is logged and ignored — the app must start
whether or not a shortcut could be renamed.

The executable, ZIP and registry-key names stay ``WinZapp`` on purpose; see
branding.py for the list and the reasons.
"""

import logging
import ntpath
import os
import struct
import sys

from branding import APP_NAME, LEGACY_SHORTCUT_FILENAME, SHORTCUT_FILENAME

# Windows shell folder ids (CSIDL) that can hold the installer's shortcuts.
_CSIDL_PROGRAMS = 0x0002
_CSIDL_DESKTOPDIRECTORY = 0x0010
_CSIDL_COMMON_PROGRAMS = 0x0017
_CSIDL_COMMON_DESKTOPDIRECTORY = 0x0019

_UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinZapp"


# ── .lnk parsing (MS-SHLLINK), no COM needed ─────────────────────────────────

_HAS_LINK_TARGET_ID_LIST = 0x01
_HAS_LINK_INFO = 0x02
_HAS_NAME = 0x04
_HAS_RELATIVE_PATH = 0x08
_HAS_WORKING_DIR = 0x10
_HAS_ARGUMENTS = 0x20
_HAS_ICON_LOCATION = 0x40
_IS_UNICODE = 0x80


def _cstring(buf: bytes, offset: int, wide: bool) -> str:
    """Read a NUL-terminated string at *offset* (UTF-16LE when *wide*)."""
    if offset <= 0 or offset >= len(buf):
        return ""
    if wide:
        end = offset
        while end + 1 < len(buf) and buf[end:end + 2] != b"\x00\x00":
            end += 2
        return buf[offset:end].decode("utf-16-le", errors="replace")
    end = buf.find(b"\x00", offset)
    if end < 0:
        end = len(buf)
    raw = buf[offset:end]
    for enc in ("mbcs", "cp1252", "utf-8"):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("latin-1")


def read_shortcut(path: str):
    """Return ``(target_path, working_dir)`` of a .lnk file, ``""`` when absent.

    Raises ``ValueError`` when the file is not a readable Shell Link.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 76 or struct.unpack_from("<I", data, 0)[0] != 0x4C:
        raise ValueError("not a shell link")
    flags = struct.unpack_from("<I", data, 20)[0]
    pos = 76

    if flags & _HAS_LINK_TARGET_ID_LIST:
        (id_size,) = struct.unpack_from("<H", data, pos)
        pos += 2 + id_size

    target = ""
    if flags & _HAS_LINK_INFO:
        base = pos
        info_size, header_size, info_flags = struct.unpack_from("<III", data, base)
        local_base_off = struct.unpack_from("<I", data, base + 16)[0]
        suffix_off = struct.unpack_from("<I", data, base + 24)[0]
        info = data[base:base + info_size]
        if info_flags & 0x1:  # VolumeIDAndLocalBasePath
            uni_base = uni_suffix = 0
            if header_size >= 0x24:
                uni_base, uni_suffix = struct.unpack_from("<II", data, base + 28)
            if uni_base:
                target = _cstring(info, uni_base, True)
                suffix = _cstring(info, uni_suffix, True) if uni_suffix else ""
            else:
                target = _cstring(info, local_base_off, False)
                suffix = _cstring(info, suffix_off, False) if suffix_off else ""
            target += suffix
        pos += info_size

    unicode_strings = bool(flags & _IS_UNICODE)

    def _string_data() -> str:
        nonlocal pos
        (count,) = struct.unpack_from("<H", data, pos)
        pos += 2
        size = count * (2 if unicode_strings else 1)
        raw = data[pos:pos + size]
        pos += size
        if unicode_strings:
            return raw.decode("utf-16-le", errors="replace")
        return raw.decode("mbcs" if sys.platform == "win32" else "cp1252",
                          errors="replace")

    working_dir = ""
    try:
        if flags & _HAS_NAME:
            _string_data()
        if flags & _HAS_RELATIVE_PATH:
            _string_data()
        if flags & _HAS_WORKING_DIR:
            working_dir = _string_data()
    except struct.error:
        pass
    return target, working_dir


def _norm(path: str) -> str:
    """Comparable form of a Windows path (case-insensitive, one separator)."""
    return ntpath.normpath(path.replace("/", "\\")).lower() if path else ""


def shortcut_belongs_to(path: str, exe_path: str) -> bool:
    """True when the .lnk at *path* launches *exe_path* (this installation).

    The target is compared first. When a link carries no readable target (only
    a shell ID list), the working directory plus the exe file name decide: the
    installer always sets the working directory to the install folder.
    """
    try:
        target, working_dir = read_shortcut(path)
    except (OSError, ValueError, struct.error):
        return False
    exe_norm = _norm(exe_path)
    if target:
        return _norm(target) == exe_norm
    return bool(working_dir) and _norm(working_dir) == ntpath.dirname(exe_norm)


# ── Shortcuts ────────────────────────────────────────────────────────────────

def _shell_folders():
    """Desktop and Start-menu folders, per-user and all-users (may be empty)."""
    import ctypes
    folders = []
    for csidl in (_CSIDL_DESKTOPDIRECTORY, _CSIDL_COMMON_DESKTOPDIRECTORY,
                  _CSIDL_PROGRAMS, _CSIDL_COMMON_PROGRAMS):
        buf = ctypes.create_unicode_buffer(1024)
        try:
            if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
                folders.append(buf.value)
        except Exception:
            continue
    return [f for f in folders if f]


def register_for_uninstall(install_dir: str, path: str) -> bool:
    """Add *path* to ``installed_files.dat`` so an OLD uninstall.exe removes it.

    uninstall.exe is laid down by the installer only; an in-place update never
    refreshes it, so an install that began as WinZapp keeps an uninstaller that
    deletes ``WinZapp.lnk`` by name and would leave the renamed shortcut behind.
    That uninstaller does delete every absolute path listed in
    ``installed_files.dat`` (UTF-16LE with BOM, one path per line), so the new
    shortcut is listed there. Returns True when the file was changed.
    """
    list_path = os.path.join(install_dir, "installed_files.dat")
    if not os.path.isfile(list_path):
        return False
    try:
        with open(list_path, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-16-le", errors="replace")
        if text.startswith("\ufeff"):
            text = text[1:]
        listed = {_norm(line) for line in text.splitlines() if line}
        if _norm(path) in listed:
            return False
        tail = b"" if raw.endswith("\r\n".encode("utf-16-le")) or not raw else "\r\n".encode("utf-16-le")
        with open(list_path, "ab") as fh:
            fh.write(tail + (path + "\r\n").encode("utf-16-le"))
        return True
    except OSError as exc:
        logging.info("install_migration: could not list %s for uninstall (%s)", path, exc)
        return False


def migrate_shortcuts(exe_path: str, folders=None) -> list:
    """Rename ``WinZapp.lnk`` to ``TeleZapp.lnk`` where it is this installation's.

    Returns a list of human-readable actions taken (for logging and tests).
    """
    install_dir = os.path.dirname(exe_path)
    actions = []
    for folder in (folders if folders is not None else _shell_folders()):
        legacy = os.path.join(folder, LEGACY_SHORTCUT_FILENAME)
        new = os.path.join(folder, SHORTCUT_FILENAME)
        try:
            if not os.path.isfile(legacy) or not shortcut_belongs_to(legacy, exe_path):
                continue
            if os.path.isfile(new):
                # Already has the new one: drop the old only if the new one is ours.
                if shortcut_belongs_to(new, exe_path):
                    os.remove(legacy)
                    actions.append(f"removed duplicate {legacy}")
                continue
            os.rename(legacy, new)
            actions.append(f"renamed {legacy} -> {new}")
            register_for_uninstall(install_dir, new)
        except OSError as exc:
            # All-users folders need admin: not being able to touch them is normal.
            logging.info("install_migration: left %s as is (%s)", legacy, exc)
    return actions


# ── "Add or remove programs" entry ───────────────────────────────────────────

def migrate_uninstall_entry(install_dir: str, version: str, winreg_module=None) -> bool:
    """Show the new name (and the real version) in the installed-apps list.

    The key itself stays ``...\\Uninstall\\WinZapp`` (uninstall.exe looks it up
    by that name); only the displayed values change, and only when the entry's
    InstallLocation is this folder.
    """
    winreg = winreg_module
    if winreg is None:
        import winreg  # noqa: F811 - Windows only
    changed = False
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            key = winreg.OpenKey(hive, _UNINSTALL_KEY, 0,
                                 winreg.KEY_READ | winreg.KEY_SET_VALUE)
        except OSError:
            continue
        try:
            try:
                location = winreg.QueryValueEx(key, "InstallLocation")[0]
            except OSError:
                continue
            if _norm(location) != _norm(install_dir):
                continue
            for name, value in (("DisplayName", APP_NAME),
                                ("Publisher", APP_NAME),
                                ("DisplayVersion", version)):
                try:
                    current = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    current = None
                if current != value:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                    changed = True
        except OSError as exc:
            logging.info("install_migration: uninstall entry not updated (%s)", exc)
        finally:
            winreg.CloseKey(key)
    return changed


# ── Entry point ──────────────────────────────────────────────────────────────

def run(exe_path: str, version: str) -> None:
    """Do every migration; never raises."""
    if sys.platform != "win32":
        return
    try:
        for action in migrate_shortcuts(exe_path):
            logging.info("install_migration: %s", action)
    except Exception:
        logging.exception("install_migration: shortcut migration failed")
    try:
        if migrate_uninstall_entry(os.path.dirname(exe_path), version):
            logging.info("install_migration: installed-apps entry updated")
    except Exception:
        logging.exception("install_migration: uninstall entry migration failed")
