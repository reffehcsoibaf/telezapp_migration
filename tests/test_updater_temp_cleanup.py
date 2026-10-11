"""The auto-updater must not leave winzapp_* files and folders in %TEMP%.

Every update used to leave its extraction folder (winzapp_ext_*) behind: the
batch installer never removed it and the worker had no cleanup path at all.
"""

import os
import tempfile

import updater


def test_removes_only_updater_leftovers_inside_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    ext = tmp_path / "winzapp_ext_abc"
    (ext / "WinZapp").mkdir(parents=True)
    (ext / "WinZapp" / "a.txt").write_text("x")
    zip_file = tmp_path / "winzapp_upd_xyz.zip"
    zip_file.write_text("x")
    other = tmp_path / "other_program"
    other.mkdir()

    for leftover in (ext, zip_file, other):
        updater._remove_update_temp(str(leftover))

    assert not ext.exists()
    assert not zip_file.exists()
    assert other.exists()


def test_refuses_paths_outside_temp(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    temp = tmp_path / "temp"
    elsewhere.mkdir()
    temp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp))
    target = elsewhere / "winzapp_ext_abc"
    target.mkdir()

    updater._remove_update_temp(str(target))
    updater._remove_update_temp(None)

    assert target.exists()


def test_script_removes_extraction_only_on_success_path():
    args = ("C:\\src", "C:\\app", "C:\\app\\WinZapp.exe", "C:\\log.txt",
            "C:\\app\\update_failed.marker", 123, 6300)
    with_cleanup = updater._build_installer_script(*args, cleanup_dir="C:\\Temp\\winzapp_ext_1")
    without = updater._build_installer_script(*args)

    assert 'rmdir /s /q "C:\\Temp\\winzapp_ext_1"' in with_cleanup
    assert "rmdir" not in without
    success = with_cleanup.split("xcopy OK", 1)[1]
    failure = with_cleanup.split("xcopy FAILED", 1)[1].split("xcopy OK", 1)[0]
    assert "rmdir" in success
    assert "rmdir" not in failure
