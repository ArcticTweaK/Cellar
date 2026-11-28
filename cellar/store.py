"""Settings + encrypted account storage (port of Store.cs)."""

import json
import os
import shutil
import threading
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import crypto, log, paths
from .models import Account, AppSettings, LiveInfo, from_dict, to_dict

settings = AppSettings()
accounts: List[Account] = []
password: Optional[str] = None        # None = keyring mode ('K')
loaded = False                        # never overwrite the file until it loaded successfully
_live = {}
_save_lock = threading.RLock()


def live(a: Account) -> LiveInfo:
    li = _live.get(a.id)
    if li is None:
        li = _live[a.id] = LiveInfo()
    return li


def atomic_write(path, data: bytes, mode: int = 0o600) -> None:
    path = Path(path)
    # Exports and background saves can overlap: never share a predictable .tmp file.
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- settings
def load_settings() -> None:
    global settings
    raw: dict = {}
    try:
        if paths.SETTINGS_FILE.exists():
            raw = json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8"))
            settings = from_dict(AppSettings, raw)
    except Exception as ex:
        log.error("load settings", ex)
    s = settings
    if raw and int(raw.get("settings_version", 1) or 1) < 2:
        _migrate_alt_defaults(s, raw)
    if raw and int(raw.get("settings_version", 1) or 1) < 3:
        s.accounts_view = "table"       # the MultiHub layout shows the list as a table (Cards still switches)
        s.settings_version = 3
        _save_settings()
    if raw and int(raw.get("settings_version", 1) or 1) < 4:
        for r in s.history:             # joins from before sessions had an end: their length is unknown
            r.end = -1.0
        s.settings_version = 4
        _save_settings()
    s.anti_afk_action = s.anti_afk_action if s.anti_afk_action in ("Zoom", "Space", "Nudge") else "Zoom"
    s.layout.min_w = max(100, s.layout.min_w)
    s.layout.min_h = max(80, s.layout.min_h)


# Messages for the app log about one-time changes made while loading (shown by the main window).
notices: List[str] = []
# Set by the settings migration: mark the account your normal Sober is logged in with as "Full quality".
mark_main_full_quality = False


def _migrate_alt_defaults(s: AppSettings, raw: dict) -> None:
    """Settings from before version 2 ran every account at 240 FPS with Roblox's default graphics.
    Give alts the measured alt defaults - unless the user had chosen a cap / real graphics settings."""
    global mark_main_full_quality
    from . import gfx
    changed = []
    if int(raw.get("fps_cap", 0) or 0) == 0:
        s.fps_cap = 30
        changed.append("30 FPS")
    g = raw.get("gfx") or {}
    untouched = (g.get("preset", "Default") in ("Default", "Custom") and int(g.get("quality", 0) or 0) == 0
                 and int(g.get("texture", -1)) == -1)
    if untouched:
        gfx.apply_preset(s.gfx, "Lowest")
        changed.append("the Lowest graphics preset")
    s.settings_version = max(s.settings_version, 2)
    mark_main_full_quality = True
    if changed:
        notices.append("Alts now run at " + " and ".join(changed) + " (measured: about 5x less CPU per alt; "
                       "change it in the Performance tab).")
    _save_settings()


def apply_main_full_quality() -> None:
    """After accounts are loaded: the account your normal Sober is logged in with is your main."""
    global mark_main_full_quality
    if not mark_main_full_quality:
        return
    mark_main_full_quality = False
    from . import sober
    c = sober.main_cookie()
    a = find_by_cookie(c) if c else None
    if a:
        if not a.full_quality:
            a.full_quality = True
            save_accounts()
        notices.append(f"{a.name} is your normal Sober's account, so it is marked 'Full quality - this is my main' "
                       "(Edit account): it keeps full graphics when you launch it here.")
    else:
        notices.append("Tick 'Full quality - this is my main' in Edit account for your main, so it keeps full graphics.")


def save_settings() -> None:
    with _save_lock:
        _save_settings()


def _save_settings() -> None:
    try:
        atomic_write(paths.SETTINGS_FILE, json.dumps(to_dict(settings), indent=1).encode("utf-8"), 0o600)
    except Exception as ex:
        log.error("save settings", ex)


# ---------------------------------------------------------------- accounts
def file_kind() -> str:
    """'' (no file), 'P', 'K', 'D' or '?'."""
    try:
        with open(paths.ACCOUNTS_FILE, "rb") as f:
            b = f.read(1)
        return b.decode("latin-1") if b in (b"P", b"K", b"D") else ("?" if b else "")
    except FileNotFoundError:
        return ""


def accounts_from_json(text: str) -> List[Account]:
    """Reads both this app's format and the Windows app's (PascalCase) JSON."""
    data = json.loads(text)
    raw = data.get("accounts") if "accounts" in data else data.get("Accounts", [])
    out = []
    for r in raw or []:
        if "Cookie" in r or "Username" in r:          # Windows format
            r = {
                "id": r.get("Id") or None, "username": r.get("Username", ""), "user_id": r.get("UserId", 0),
                "display_name": r.get("DisplayName", ""), "cookie": r.get("Cookie", ""),
                "password": r.get("Password", ""), "alias": r.get("Alias", ""),
                "description": r.get("Description", ""), "group": r.get("Group", ""),
                "saved_place_id": r.get("SavedPlaceId", ""), "saved_job_id": r.get("SavedJobId", ""),
                "fps_cap": r.get("FpsCap", 0), "game_link": r.get("GameLink", ""),
                "tracker_id": r.get("TrackerId", 0), "order": r.get("Order", 0),
                "last_used": max(0.0, (int(r.get("LastUsedTicks", 0) or 0) - 621355968000000000) / 1e7),
            }
            r = {k: v for k, v in r.items() if v is not None}
        out.append(from_dict(Account, r))
    return out


def decrypt_file(raw: bytes, pw: Optional[str]) -> str:
    kind = raw[:1]
    if kind == b"P":
        if pw is None:
            raise crypto.DecryptError("This accounts file is protected by a password.")
        return crypto.decrypt_password(raw, pw).decode("utf-8")
    if kind == b"K":
        return crypto.decrypt_keyring(raw).decode("utf-8")
    if kind == b"D":
        raise crypto.DecryptError(
            "This accounts file was encrypted with Windows DPAPI and can only be opened on that Windows PC. "
            "In the Windows app set a password (Settings > Encryption) and copy the file again, "
            "or export your cookies from there.")
    raise crypto.DecryptError("Unknown accounts file format.")


def load_accounts(pw: Optional[str]) -> Optional[str]:
    """Returns None on success, otherwise a human readable error."""
    global accounts, password, loaded
    try:
        if not paths.ACCOUNTS_FILE.exists():
            accounts, password, loaded = [], pw, True
            return None
        raw = paths.ACCOUNTS_FILE.read_bytes()
        accounts = accounts_from_json(decrypt_file(raw, pw))
        accounts.sort(key=lambda a: a.order)
        password, loaded = pw, True
        backup()
        return None
    except crypto.DecryptError as ex:
        return str(ex)
    except Exception as ex:
        log.error("load accounts", ex)
        return f"Could not read the accounts file: {ex}"


def start_fresh() -> None:
    global accounts, password, loaded
    try:
        if paths.ACCOUNTS_FILE.exists():
            shutil.copy2(paths.ACCOUNTS_FILE, str(paths.ACCOUNTS_FILE) + ".old")
    except OSError:
        pass
    accounts, password, loaded = [], None, True
    save_accounts()


def save_accounts(fresh_provider: bool = False) -> bool:
    with _save_lock:
        return _save_accounts(fresh_provider)


def _save_accounts(fresh_provider: bool) -> bool:
    if not loaded:
        return False
    try:
        renumber()
        data = json.dumps({"accounts": [to_dict(a) for a in accounts]}).encode("utf-8")
        if password is not None:
            enc = crypto.encrypt_password(data, password)
        else:
            raw = paths.ACCOUNTS_FILE.read_bytes() if paths.ACCOUNTS_FILE.exists() and not fresh_provider else b""
            provider = crypto.provider_of(raw) or crypto.pick_provider()
            enc = crypto.encrypt_keyring(data, provider)
        atomic_write(paths.ACCOUNTS_FILE, enc, 0o600)
        return True
    except Exception as ex:
        log.error("save accounts", ex)
        return False


def set_password(new_pw: Optional[str]) -> bool:
    """None = switch to the keyring. Keep the old password if encryption / writing fails."""
    global password
    with _save_lock:
        previous = password
        backup()
        password = new_pw
        if _save_accounts(fresh_provider=new_pw is None):
            return True
        password = previous
        return False


def key_location() -> str:
    if password is not None:
        return "your password"
    try:
        p = crypto.provider_of(paths.ACCOUNTS_FILE.read_bytes())
        if p:
            return p.label
    except OSError:
        pass
    return crypto.pick_provider().label


def backup() -> None:
    try:
        if not paths.ACCOUNTS_FILE.exists():
            return
        paths.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dst = paths.BACKUP_DIR / (time.strftime("accounts_%Y%m%d_%H%M%S_") + f"{time.time_ns() % 10**9:09d}.dat")
        shutil.copy2(paths.ACCOUNTS_FILE, dst)
        os.chmod(dst, 0o600)
        old = sorted(paths.BACKUP_DIR.glob("accounts_*.dat"))
        for f in old[:-10]:
            f.unlink()
    except OSError:
        pass


def export_accounts(f: Path, accs: List[Account], pw: str) -> None:
    """A password-protected copy of these accounts for another PC: the same 'P' format as accounts.dat (also
    readable by the Windows app). Import it with Add account > Import accounts file."""
    data = json.dumps({"accounts": [to_dict(a) for a in accs]}).encode("utf-8")
    atomic_write(f, crypto.encrypt_password(data, pw), 0o600)


def backups() -> List[Path]:
    """Newest first."""
    try:
        return sorted(paths.BACKUP_DIR.glob("accounts_*.dat"), reverse=True)
    except OSError:
        return []


def read_backup(f: Path) -> Tuple[Optional[List[Account]], str]:
    """(accounts, '') or (None, why). Uses the current password / keyring, like the file it came from."""
    try:
        return accounts_from_json(decrypt_file(f.read_bytes(), password)), ""
    except crypto.DecryptError as ex:
        return None, str(ex)
    except Exception as ex:
        return None, f"Could not read it: {ex}"


def restore(accs: List[Account]) -> None:
    """Replaces the account list with a backup's (the current file is backed up first)."""
    global accounts
    backup()
    accounts = sorted(accs, key=lambda a: a.order)
    save_accounts()


def renumber() -> None:
    for i, a in enumerate(accounts):
        a.order = i


def all_groups() -> List[str]:
    g = list(settings.groups)
    for a in accounts:
        if a.group and a.group not in g:
            g.append(a.group)
    return sorted(g, key=str.lower)


def find_by_cookie(cookie: str) -> Optional[Account]:
    return next((a for a in accounts if a.cookie == cookie), None)


def find_by_user_id(uid: int) -> Optional[Account]:
    return next((a for a in accounts if uid and a.user_id == uid), None)


def find_by_id(acc_id: str) -> Optional[Account]:
    return next((a for a in accounts if a.id == acc_id), None)


def find_by_tracker(tracker: int) -> Optional[Account]:
    return next((a for a in accounts if tracker and a.tracker_id == tracker), None)
