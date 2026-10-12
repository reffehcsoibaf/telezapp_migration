"""autostart: the Run value moves from "WinZapp" to "TeleZapp" without losing it.

winreg exists only on Windows, so a small in-memory fake stands in for it.
"""

import os
import sys
import types

import pytest

import autostart

OTHER_COMMAND = r'"D:\Original\WinZapp\WinZapp.exe" --background'


class FakeKey:
    def __init__(self, values):
        self.values = values


def make_winreg(values):
    mod = types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU", KEY_READ=1, KEY_SET_VALUE=2, REG_SZ=1)

    def open_key(hive, path, reserved=0, access=0):
        return FakeKey(values)

    def query(key, name):
        if name not in key.values:
            raise OSError("no value")
        return key.values[name], 1

    def set_value(key, name, reserved, typ, value):
        key.values[name] = value

    def delete(key, name):
        if name not in key.values:
            raise OSError("no value")
        del key.values[name]

    mod.OpenKey = open_key
    mod.QueryValueEx = query
    mod.SetValueEx = set_value
    mod.DeleteValue = delete
    mod.CloseKey = lambda key: None
    return mod


@pytest.fixture
def run_key(monkeypatch):
    values = {}
    monkeypatch.setitem(sys.modules, "winreg", make_winreg(values))
    monkeypatch.setattr(sys, "argv", [os.path.join("C:\\", "Apps", "WinZapp.exe")])
    return values


def ours():
    return autostart.get_autostart_command()


def test_value_names():
    assert autostart._AUTORUN_NAME == "TeleZapp"
    assert autostart._LEGACY_AUTORUN_NAME == "WinZapp"


def test_legacy_value_of_this_install_counts_as_enabled(run_key):
    run_key["WinZapp"] = ours()
    assert autostart.is_autostart_enabled() is True


def test_legacy_value_of_another_install_does_not_count(run_key):
    run_key["WinZapp"] = OTHER_COMMAND
    assert autostart.is_autostart_enabled() is False


def test_new_value_counts_as_enabled(run_key):
    run_key["TeleZapp"] = ours()
    assert autostart.is_autostart_enabled() is True


def test_nothing_set_is_disabled(run_key):
    assert autostart.is_autostart_enabled() is False


def test_migrate_moves_legacy_to_new_name_and_keeps_it_enabled(run_key):
    run_key["WinZapp"] = ours()
    assert autostart.migrate_autostart() is True
    assert run_key == {"TeleZapp": ours()}
    assert autostart.is_autostart_enabled() is True


def test_migrate_leaves_the_original_apps_value_alone(run_key):
    run_key["WinZapp"] = OTHER_COMMAND
    assert autostart.migrate_autostart() is False
    assert run_key == {"WinZapp": OTHER_COMMAND}


def test_migrate_without_a_legacy_value_does_nothing(run_key):
    assert autostart.migrate_autostart() is False
    assert run_key == {}


def test_enable_writes_new_name_and_retires_own_legacy(run_key):
    run_key["WinZapp"] = ours()
    autostart.enable_autostart()
    assert run_key == {"TeleZapp": ours()}


def test_enable_keeps_another_installs_legacy_value(run_key):
    run_key["WinZapp"] = OTHER_COMMAND
    autostart.enable_autostart()
    assert run_key == {"WinZapp": OTHER_COMMAND, "TeleZapp": ours()}


def test_disable_removes_both_names_of_this_install(run_key):
    run_key["WinZapp"] = ours()
    run_key["TeleZapp"] = ours()
    autostart.disable_autostart()
    assert run_key == {}
    assert autostart.is_autostart_enabled() is False


def test_disable_keeps_another_installs_legacy_value(run_key):
    run_key["WinZapp"] = OTHER_COMMAND
    autostart.disable_autostart()
    assert run_key == {"WinZapp": OTHER_COMMAND}


def test_disable_with_nothing_set_is_silent(run_key):
    autostart.disable_autostart()
    assert run_key == {}
