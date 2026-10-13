"""Tests for the sync/media/auto-offline announcements master mute.

Settings > Geral > "Anunciar sincronização, download de mídias e modo offline
automático" gates the spoken+sound warnings for sync progress/completion, media
downloads and the automatic offline transition. When unchecked, none of them may
fire; when missing, it must default to enabled so existing installs keep their
current behaviour.

MainWindow is a wx.Frame and cannot be instantiated without a running app, so the
method under test is exercised as a plain function against a small stub that
carries just the attribute it touches.
"""

import pytest

from main import MainWindow


class _Stub:
    """Minimal stand-in for MainWindow for the announce-sync-events method."""

    def __init__(self, settings=None):
        self.settings = settings or {}

    _announce_sync_events_enabled = MainWindow._announce_sync_events_enabled


def test_defaults_to_enabled_when_setting_missing():
    # A settings dict without the key at all (existing installs / partial
    # configs) must keep announcing — the master mute is opt-out.
    assert _Stub({})._announce_sync_events_enabled() is True


def test_defaults_to_enabled_when_general_missing():
    assert _Stub({"general": {}})._announce_sync_events_enabled() is True


def test_explicit_true_is_enabled():
    stub = _Stub({"general": {"announce_sync_events": True}})
    assert stub._announce_sync_events_enabled() is True


def test_explicit_false_is_disabled():
    stub = _Stub({"general": {"announce_sync_events": False}})
    assert stub._announce_sync_events_enabled() is False


# ── Periodic progress lines ("Sincronizando conversas: X de Y", "Baixando
# mídia: X de Y processadas") ─────────────────────────────────────────────────
#
# They used to be spoken unconditionally — the only sync announcements that
# ignored both the checkbox above and background mode. The status bar keeps
# getting the text either way; only speech is gated.


class _ProgressStub(_Stub):
    def __init__(self, settings=None, background_mode=False):
        super().__init__(settings)
        self.background_mode = background_mode
        self.status = []
        self.spoken = []

    def _set_status(self, text):
        self.status.append(text)

    def output(self, text, *args, **kwargs):
        self.spoken.append(text)

    _report_sync_progress = MainWindow._report_sync_progress


def test_progress_is_spoken_and_shown_by_default():
    stub = _ProgressStub({})
    stub._report_sync_progress("Sincronizando conversas: 3 de 10", "announce_sync_progress")
    assert stub.status == ["Sincronizando conversas: 3 de 10"]
    assert stub.spoken == ["Sincronizando conversas: 3 de 10"]


def test_progress_is_not_spoken_when_announcements_are_off():
    stub = _ProgressStub({"general": {"announce_sync_events": False}})
    stub._report_sync_progress("Baixando mídia: 5 de 40 processadas (2 baixadas)", "announce_media_progress")
    assert stub.status == ["Baixando mídia: 5 de 40 processadas (2 baixadas)"]
    assert stub.spoken == []


def test_progress_is_not_spoken_in_background_mode():
    stub = _ProgressStub({}, background_mode=True)
    stub._report_sync_progress("Sincronizando conversas: 1 de 2", "announce_sync_progress")
    assert stub.status == ["Sincronizando conversas: 1 de 2"]
    assert stub.spoken == []


def test_sync_sweeps_speak_progress_only_through_the_gated_helper():
    """Both sweeps must go through _report_sync_progress — a direct
    wx.CallAfter(self.output, progress_text) would bypass the mute again."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "client" / "main.py").read_text(encoding="utf-8")
    flat = "".join(source.split())
    assert "wx.CallAfter(self.output,progress_text)" not in flat
    assert flat.count('wx.CallAfter(self._report_sync_progress,progress_text,"announce_sync_progress")') == 1
    assert flat.count('wx.CallAfter(self._report_sync_progress,progress_text,"announce_media_progress")') == 1


# ── Configurações > Acessibilidade > Conteúdo falado: one box per sweep ───────


@pytest.mark.parametrize("key", ["announce_sync_progress", "announce_media_progress"])
def test_each_spoken_content_box_silences_only_its_own_progress(key):
    other = ({"announce_sync_progress", "announce_media_progress"} - {key}).pop()
    stub = _ProgressStub({"speech_content": {key: False}})
    stub._report_sync_progress("muted", key)
    stub._report_sync_progress("spoken", other)
    assert stub.status == ["muted", "spoken"]
    assert stub.spoken == ["spoken"]


def test_both_boxes_default_to_on():
    import json
    from pathlib import Path

    from core.utils import DEFAULT_SETTINGS

    defaults = json.loads((Path(__file__).resolve().parents[1] / "client" / "data"
                           / "settings_default.json").read_text(encoding="utf-8"))
    for key in ("announce_sync_progress", "announce_media_progress"):
        assert defaults["speech_content"][key] is True
        assert DEFAULT_SETTINGS["speech_content"][key] is True
