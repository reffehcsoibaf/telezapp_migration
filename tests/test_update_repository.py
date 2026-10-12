"""The updater's repository: the project's own, with the old env var still read."""

import importlib

import pytest

import branding
import config


@pytest.fixture
def reload_config(monkeypatch):
    def _reload(**env):
        monkeypatch.delenv("TELEZAPP_GITHUB_REPO", raising=False)
        monkeypatch.delenv("WINZAPP_GITHUB_REPO", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _reload
    monkeypatch.delenv("TELEZAPP_GITHUB_REPO", raising=False)
    monkeypatch.delenv("WINZAPP_GITHUB_REPO", raising=False)
    importlib.reload(config)


def test_default_is_the_projects_own_repository(reload_config):
    cfg = reload_config()
    assert cfg.GITHUB_REPO == branding.GITHUB_REPO_DEFAULT == "reffehcsoibaf/telezapp"
    assert cfg.GITHUB_REPO != branding.LEGACY_GITHUB_REPO


def test_old_env_var_still_overrides(reload_config):
    assert reload_config(WINZAPP_GITHUB_REPO="me/fork").GITHUB_REPO == "me/fork"


def test_new_env_var_wins_over_the_old_one(reload_config):
    cfg = reload_config(TELEZAPP_GITHUB_REPO="me/new", WINZAPP_GITHUB_REPO="me/old")
    assert cfg.GITHUB_REPO == "me/new"


def test_release_urls_follow_the_repository(reload_config):
    cfg = reload_config()
    assert cfg.GITHUB_API_LATEST_RELEASE == (
        "https://api.github.com/repos/reffehcsoibaf/telezapp/releases")
    assert cfg.GITHUB_API_LATEST_STABLE_RELEASE.startswith(cfg.GITHUB_API_LATEST_RELEASE)
