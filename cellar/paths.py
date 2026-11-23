"""Where everything lives on disk (XDG base directories)."""

import os
from pathlib import Path
from typing import List

from . import APP_ID

HOME = Path.home()


def _xdg(var: str, default: Path) -> Path:
    v = os.environ.get(var, "").strip()
    return Path(v) if v and os.path.isabs(v) else default


CONFIG_HOME = _xdg("XDG_CONFIG_HOME", HOME / ".config")
DATA_HOME = _xdg("XDG_DATA_HOME", HOME / ".local" / "share")
CACHE_HOME = _xdg("XDG_CACHE_HOME", HOME / ".cache")

CONFIG_DIR = CONFIG_HOME / APP_ID
DATA_DIR = DATA_HOME / APP_ID
CACHE_DIR = CACHE_HOME / APP_ID

SETTINGS_FILE = CONFIG_DIR / "settings.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.dat"
KEY_FILE = DATA_DIR / ".accounts.key"          # only used when no keyring is available
BACKUP_DIR = DATA_DIR / "backups"
PROFILES_DIR = DATA_DIR / "profiles"           # one Sober HOME per account (multi-instance)
LOG_FILE = DATA_DIR / "log.txt"
AVATAR_DIR = CACHE_DIR / "avatars"

SOBER_ID = "org.vinegarhq.Sober"
# The Sober profile the user plays with normally (seed for the per-account profiles).
MAIN_SOBER_DIR = HOME / ".var" / "app" / SOBER_ID

AUTOSTART_FILE = CONFIG_HOME / "autostart" / f"{APP_ID}.desktop"

# Cellar was called "Roblox MultiHub for Linux" before; its folders had this name.
OLD_ID = "roblox-multihub"
OLD_DATA_DIR = DATA_HOME / OLD_ID


def runtime_dir() -> Path:
    v = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    return Path(v) if v else Path("/run/user") / str(os.getuid())


def migrate_old_name() -> List[str]:
    """Moves the folders of Roblox MultiHub for Linux to Cellar's names, once (a rename on the
    same disk: instant, nothing copied). Returns what was done, for the log."""
    done = []
    for new in (CONFIG_DIR, DATA_DIR, CACHE_DIR):
        old = new.parent / OLD_ID
        if os.path.lexists(new) or old.is_symlink() or not old.is_dir():
            continue
        os.rename(old, new)
        done.append(f"moved {old} to {new}")
        if new == DATA_DIR:
            # Sober clients started before the move still have their HOME under the old path.
            os.symlink(APP_ID, old)
    old_auto = CONFIG_HOME / "autostart" / f"{OLD_ID}.desktop"
    if old_auto.is_file():
        try:
            old_auto.unlink()
            done.append("removed the old autostart entry (turn 'Start Cellar when I log in' on again in Settings)")
        except OSError:
            pass
    return done


def drop_old_link() -> bool:
    """Removes the compatibility link at the old data folder once nothing needs it any more."""
    if OLD_DATA_DIR.is_symlink() and os.readlink(OLD_DATA_DIR) == APP_ID:
        OLD_DATA_DIR.unlink()
        return True
    return False


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, CACHE_DIR, BACKUP_DIR, PROFILES_DIR, AVATAR_DIR):
        d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)       # accounts + per-account Sober logins live here
    except OSError:
        pass
