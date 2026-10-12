"""The name the user sees, in one place.

The project is now TeleZapp (a fork of WinZapp). Only what a person reads or
hears changes; identifiers that other code, the OS or an already-installed copy
depend on keep their old WinZapp spelling for now:

* the executable and ZIP file names (an installed copy's updater relaunches
  ``WinZapp.exe`` and looks for ``WinZapp.zip``),
* the Windows AppUserModelID / registry keys / autostart value / mutex and IPC
  names (renaming them would orphan settings and allow two instances),
* the release manifest header (``# winzapp-version:``), which older installs
  verify.

``LEGACY_APP_NAME`` is still recognised wherever the app name is compared, so a
saved account that was named "WinZapp", or a window opened by a copy that has
not updated yet, keeps behaving as the default account / the app's own window.
"""

APP_NAME = "TeleZapp"
LEGACY_APP_NAME = "WinZapp"
APP_NAMES = (APP_NAME, LEGACY_APP_NAME)

# Names of the shortcuts the installer drops on the Desktop / Start menu. A copy
# that was installed (or updated in place) before the rename still carries the
# legacy name; install_migration.py renames it on the first run of a new build.
SHORTCUT_FILENAME = f"{APP_NAME}.lnk"
LEGACY_SHORTCUT_FILENAME = f"{LEGACY_APP_NAME}.lnk"

# Update source. The repository is the project's own, no longer the WinZapp
# fork. Installed copies that predate this still ask the old repository, which
# is why the build that first carries this value is published THERE; every
# copy that installs it then asks the new one.
GITHUB_REPO_DEFAULT = "reffehcsoibaf/telezapp"
LEGACY_GITHUB_REPO = "reffehcsoibaf/winzapp"


def is_default_account_name(name) -> bool:
    """True for "no custom account name": unset, or either spelling of the app."""
    return not name or name in APP_NAMES


def is_app_window_title(title) -> bool:
    """Whether a top-level window title belongs to this app (either spelling)."""
    return isinstance(title, str) and title.startswith(APP_NAMES)
