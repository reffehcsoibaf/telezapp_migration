"""install_migration: rename the old WinZapp shortcuts / installed-apps entry.

The .lnk files are built by hand from the MS-SHLLINK layout, so the parser is
exercised on the same structures Windows writes (an ID list, a LinkInfo block
carrying the local base path in ANSI and, since Vista, in UTF-16, and the
working directory as string data).
"""

import os
import struct

import pytest

import install_migration as im
from branding import LEGACY_SHORTCUT_FILENAME, SHORTCUT_FILENAME

EXE = r"C:\Users\fabio\AppData\Local\WinZapp\WinZapp.exe"
OTHER_EXE = r"D:\Original\WinZapp\WinZapp.exe"


def make_lnk(path, target, workdir="", *, id_list=True, link_info=True,
             unicode_info=True):
    flags = 0x80  # IsUnicode (string data)
    body = b""
    if id_list:
        flags |= 0x01
        body += struct.pack("<H", 2) + b"\x00\x00"
    if link_info and target:
        flags |= 0x02
        header_size = 0x24 if unicode_info else 0x1C
        volume_id = struct.pack("<IIII", 0x11, 3, 0, 0x10) + b"\x00"
        base_ansi = target.encode("cp1252", errors="replace") + b"\x00"
        suffix_ansi = b"\x00"
        base_uni = target.encode("utf-16-le") + b"\x00\x00"
        suffix_uni = b"\x00\x00"
        vol_off = header_size
        base_off = vol_off + len(volume_id)
        suffix_off = base_off + len(base_ansi)
        base_uni_off = suffix_off + len(suffix_ansi)
        suffix_uni_off = base_uni_off + len(base_uni)
        tail = volume_id + base_ansi + suffix_ansi
        if unicode_info:
            tail += base_uni + suffix_uni
        size = header_size + len(tail)
        info = struct.pack("<IIIIIII", size, header_size, 1, vol_off,
                           base_off, 0, suffix_off)
        if unicode_info:
            info += struct.pack("<II", base_uni_off, suffix_uni_off)
        body += info + tail
    if workdir:
        flags |= 0x10
        body += struct.pack("<H", len(workdir)) + workdir.encode("utf-16-le")
    header = struct.pack("<I", 0x4C)
    header += bytes.fromhex("0114020000000000c000000000000046")
    header += struct.pack("<I", flags) + b"\x00" * (76 - 24)
    with open(path, "wb") as fh:
        fh.write(header + body)


# ── parsing ──────────────────────────────────────────────────────────────────

def test_read_target_and_workdir(tmp_path):
    lnk = tmp_path / "a.lnk"
    make_lnk(lnk, EXE, os.path.dirname(EXE.replace("\\", "/")).replace("/", "\\"))
    target, workdir = im.read_shortcut(str(lnk))
    assert target == EXE
    assert workdir == r"C:\Users\fabio\AppData\Local\WinZapp"


def test_read_non_ascii_path_through_unicode_info(tmp_path):
    exe = "C:\\Users\\Paweł\\AppData\\Local\\WinZapp\\WinZapp.exe"
    lnk = tmp_path / "a.lnk"
    make_lnk(lnk, exe)
    assert im.read_shortcut(str(lnk))[0] == exe


def test_read_old_style_ansi_only_link_info(tmp_path):
    lnk = tmp_path / "a.lnk"
    make_lnk(lnk, EXE, unicode_info=False)
    assert im.read_shortcut(str(lnk))[0] == EXE


def test_garbage_is_not_a_shortcut(tmp_path):
    bad = tmp_path / "a.lnk"
    bad.write_bytes(b"not a shortcut at all" * 10)
    with pytest.raises(ValueError):
        im.read_shortcut(str(bad))
    assert im.shortcut_belongs_to(str(bad), EXE) is False


def test_belongs_by_target(tmp_path):
    lnk = tmp_path / "a.lnk"
    make_lnk(lnk, EXE)
    assert im.shortcut_belongs_to(str(lnk), EXE)
    assert im.shortcut_belongs_to(str(lnk), EXE.lower())  # Windows paths ignore case
    assert not im.shortcut_belongs_to(str(lnk), OTHER_EXE)


def test_belongs_by_workdir_when_link_has_no_readable_target(tmp_path):
    # Only a shell ID list: the shape some shortcuts have. The installer always
    # sets the working directory to the install folder.
    lnk = tmp_path / "a.lnk"
    make_lnk(lnk, "", r"C:\Users\fabio\AppData\Local\WinZapp", link_info=False)
    assert im.shortcut_belongs_to(str(lnk), EXE)
    assert not im.shortcut_belongs_to(str(lnk), OTHER_EXE)


def test_no_target_and_no_workdir_is_not_ours(tmp_path):
    lnk = tmp_path / "a.lnk"
    make_lnk(lnk, "", link_info=False)
    assert not im.shortcut_belongs_to(str(lnk), EXE)


# ── shortcut migration ───────────────────────────────────────────────────────

@pytest.fixture
def install(tmp_path):
    """An install folder with an installed_files.dat, plus a Desktop folder."""
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    exe = str(install_dir / "WinZapp.exe")
    return install_dir, desktop, exe


def write_list(install_dir, *paths):
    text = "\ufeff" + "".join(p + "\r\n" for p in paths)
    (install_dir / "installed_files.dat").write_bytes(text.encode("utf-16-le"))


def read_list(install_dir):
    raw = (install_dir / "installed_files.dat").read_bytes().decode("utf-16-le")
    return raw.lstrip("\ufeff").splitlines()


def test_legacy_shortcut_of_this_install_is_renamed(install):
    install_dir, desktop, exe = install
    make_lnk(desktop / LEGACY_SHORTCUT_FILENAME, exe)
    actions = im.migrate_shortcuts(exe, [str(desktop)])
    assert not (desktop / LEGACY_SHORTCUT_FILENAME).exists()
    assert (desktop / SHORTCUT_FILENAME).exists()
    assert len(actions) == 1 and "renamed" in actions[0]


def test_another_installs_shortcut_is_left_alone(install):
    # The original WinZapp can live next to TeleZapp; its shortcut stays.
    install_dir, desktop, exe = install
    make_lnk(desktop / LEGACY_SHORTCUT_FILENAME, OTHER_EXE)
    assert im.migrate_shortcuts(exe, [str(desktop)]) == []
    assert (desktop / LEGACY_SHORTCUT_FILENAME).exists()
    assert not (desktop / SHORTCUT_FILENAME).exists()


def test_nothing_to_do_without_a_legacy_shortcut(install):
    install_dir, desktop, exe = install
    make_lnk(desktop / SHORTCUT_FILENAME, exe)
    assert im.migrate_shortcuts(exe, [str(desktop)]) == []
    assert (desktop / SHORTCUT_FILENAME).exists()


def test_duplicate_legacy_is_dropped_when_new_one_is_ours(install):
    install_dir, desktop, exe = install
    make_lnk(desktop / LEGACY_SHORTCUT_FILENAME, exe)
    make_lnk(desktop / SHORTCUT_FILENAME, exe)
    im.migrate_shortcuts(exe, [str(desktop)])
    assert not (desktop / LEGACY_SHORTCUT_FILENAME).exists()
    assert (desktop / SHORTCUT_FILENAME).exists()


def test_legacy_kept_when_the_new_name_is_somebody_elses(install):
    install_dir, desktop, exe = install
    make_lnk(desktop / LEGACY_SHORTCUT_FILENAME, exe)
    make_lnk(desktop / SHORTCUT_FILENAME, OTHER_EXE)
    im.migrate_shortcuts(exe, [str(desktop)])
    assert (desktop / LEGACY_SHORTCUT_FILENAME).exists()
    assert im.read_shortcut(str(desktop / SHORTCUT_FILENAME))[0] == OTHER_EXE


def test_missing_folder_is_not_an_error(install):
    install_dir, desktop, exe = install
    assert im.migrate_shortcuts(exe, [str(desktop / "nope")]) == []


def test_every_folder_is_handled(install, tmp_path):
    install_dir, desktop, exe = install
    start = tmp_path / "Programs"
    start.mkdir()
    make_lnk(desktop / LEGACY_SHORTCUT_FILENAME, exe)
    make_lnk(start / LEGACY_SHORTCUT_FILENAME, exe)
    im.migrate_shortcuts(exe, [str(desktop), str(start)])
    assert (desktop / SHORTCUT_FILENAME).exists()
    assert (start / SHORTCUT_FILENAME).exists()


def test_rename_failure_is_swallowed(install, monkeypatch):
    install_dir, desktop, exe = install
    make_lnk(desktop / LEGACY_SHORTCUT_FILENAME, exe)

    def boom(*a, **k):
        raise PermissionError("all-users folder needs admin")

    monkeypatch.setattr(os, "rename", boom)
    assert im.migrate_shortcuts(exe, [str(desktop)]) == []
    assert (desktop / LEGACY_SHORTCUT_FILENAME).exists()


# ── old uninstall.exe must still clean the renamed shortcut ──────────────────

def test_renamed_shortcut_is_listed_for_the_old_uninstaller(install):
    install_dir, desktop, exe = install
    write_list(install_dir, str(install_dir / "WinZapp.exe"))
    make_lnk(desktop / LEGACY_SHORTCUT_FILENAME, exe)
    im.migrate_shortcuts(exe, [str(desktop)])
    assert str(desktop / SHORTCUT_FILENAME) in read_list(install_dir)
    # the original entry is intact and the file keeps its UTF-16LE BOM
    assert str(install_dir / "WinZapp.exe") in read_list(install_dir)
    assert (install_dir / "installed_files.dat").read_bytes()[:2] == b"\xff\xfe"


def test_listing_is_idempotent(install):
    install_dir, desktop, exe = install
    write_list(install_dir)
    target = str(desktop / SHORTCUT_FILENAME)
    assert im.register_for_uninstall(str(install_dir), target) is True
    assert im.register_for_uninstall(str(install_dir), target) is False
    assert read_list(install_dir).count(target) == 1


def test_listing_is_skipped_without_an_installed_files_list(install):
    install_dir, desktop, exe = install  # no installed_files.dat: a portable copy
    assert im.register_for_uninstall(str(install_dir), "x") is False
    assert not (install_dir / "installed_files.dat").exists()


def test_listing_handles_a_file_without_trailing_newline(install):
    install_dir, desktop, exe = install
    (install_dir / "installed_files.dat").write_bytes(
        ("\ufeff" + "C:\\a.txt").encode("utf-16-le"))
    im.register_for_uninstall(str(install_dir), "C:\\b.lnk")
    assert read_list(install_dir) == ["C:\\a.txt", "C:\\b.lnk"]


# ── installed-apps entry ─────────────────────────────────────────────────────

class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, hives):
        self.hives = hives  # {"HKCU": {name: value} | None}
        self.closed = 0

    def OpenKey(self, hive, path, reserved=0, access=0):
        assert path.endswith("\\Uninstall\\WinZapp")
        if self.hives.get(hive) is None:
            raise OSError("not found")
        return (hive, self.hives[hive])

    def QueryValueEx(self, key, name):
        values = key[1]
        if name not in values:
            raise OSError("no value")
        return values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, typ, value):
        key[1][name] = value

    def CloseKey(self, key):
        self.closed += 1


def test_uninstall_entry_shows_new_name_and_real_version():
    values = {"InstallLocation": r"C:\Users\fabio\AppData\Local\WinZapp",
              "DisplayName": "WinZapp", "Publisher": "WinZapp",
              "DisplayVersion": "1.1.5.2"}
    reg = FakeWinreg({"HKCU": values, "HKLM": None})
    changed = im.migrate_uninstall_entry(
        r"C:\Users\fabio\AppData\Local\WinZapp", "2026.10.12.0", reg)
    assert changed is True
    assert values["DisplayName"] == "TeleZapp"
    assert values["Publisher"] == "TeleZapp"
    assert values["DisplayVersion"] == "2026.10.12.0"
    assert reg.closed == 1


def test_uninstall_entry_of_another_folder_is_untouched():
    values = {"InstallLocation": r"D:\Original\WinZapp", "DisplayName": "WinZapp"}
    reg = FakeWinreg({"HKCU": values, "HKLM": None})
    assert im.migrate_uninstall_entry(
        r"C:\Users\fabio\AppData\Local\WinZapp", "2026.10.12.0", reg) is False
    assert values["DisplayName"] == "WinZapp"


def test_uninstall_entry_already_current_reports_no_change():
    values = {"InstallLocation": r"C:\App", "DisplayName": "TeleZapp",
              "Publisher": "TeleZapp", "DisplayVersion": "2026.10.12.0"}
    reg = FakeWinreg({"HKCU": values, "HKLM": None})
    assert im.migrate_uninstall_entry(r"C:\App", "2026.10.12.0", reg) is False


def test_uninstall_entry_without_install_location_is_ignored():
    values = {"DisplayName": "WinZapp"}
    reg = FakeWinreg({"HKCU": values, "HKLM": None})
    assert im.migrate_uninstall_entry(r"C:\App", "1", reg) is False
    assert values["DisplayName"] == "WinZapp"


def test_no_entry_at_all_is_fine():
    reg = FakeWinreg({"HKCU": None, "HKLM": None})
    assert im.migrate_uninstall_entry(r"C:\App", "1", reg) is False


def test_run_never_raises_off_windows(monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "linux")
    im.run("/x/WinZapp.exe", "1")  # returns quietly
