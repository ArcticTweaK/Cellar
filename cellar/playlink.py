"""The website's "Play" button: Cellar as the handler of roblox-player: / roblox: links.

When it is turned on (Settings), the browser hands Cellar the link instead of Sober. Cellar works out which game
and server it points at and asks which accounts should join - or hands the link to your normal Sober unchanged,
which then plays as the account you are logged in with on the website (the link carries a one-time login ticket
for that account). Turning it off gives the links back to Sober.
"""

import os
import subprocess
from typing import Dict, Optional
from urllib.parse import parse_qsl, unquote, urlsplit

from . import APP_ID, sober, util
from .models import LaunchSpec

SCHEMES = ("roblox-player", "roblox")
SOBER_DESKTOP = f"{sober.SOBER_ID}.desktop"
CELLAR_DESKTOP = f"{APP_ID}.desktop"


def is_link(s: str) -> bool:
    return any(s.lower().startswith(sc + ":") for sc in SCHEMES)


def _player_fields(uri: str) -> Dict[str, str]:
    """roblox-player:1+launchmode:play+gameinfo:...+placelauncherurl:https%3A...  -> {key: value}"""
    out = {}
    for part in uri.split(":", 1)[1].split("+"):
        k, sep, v = part.partition(":")
        if sep:
            out[k.lower()] = v
    return out


def parse(uri: str) -> Optional[LaunchSpec]:
    """Which game / server the link points at, or None (e.g. it only opens Roblox's home screen).
    LaunchSpec.kind 'Reserved' = a server only the website's own account can enter (forward it to Sober)."""
    q: Dict[str, str] = {}
    if uri.lower().startswith("roblox-player:"):
        f = _player_fields(uri)
        pl = unquote(f.get("placelauncherurl", ""))
        if pl:
            q = {k.lower(): v for k, v in parse_qsl(urlsplit(pl).query)}
    else:
        rest = uri.split(":", 1)[1].lstrip("/")
        query = rest.split("?", 1)[1] if "?" in rest else rest
        q = {k.lower(): v for k, v in parse_qsl(query.replace("&amp;", "&"))}
    place = q.get("placeid", "")
    place_id = int(place) if place.isdigit() else 0
    job = q.get("gameid") or q.get("gameinstanceid") or ""
    if q.get("userid", "").isdigit() and (q.get("request", "").lower() == "requestfollowuser" or not place_id):
        return LaunchSpec(kind="Follow", follow_user_id=int(q["userid"]))
    if place_id <= 0:
        return None
    if q.get("linkcode"):
        return LaunchSpec(kind="Private", place_id=place_id, link_code=q["linkcode"])
    if q.get("accesscode"):
        return LaunchSpec(kind="Reserved", place_id=place_id)
    if util.looks_like_guid(job):
        return LaunchSpec(kind="Job", place_id=place_id, job_id=job)
    return LaunchSpec(kind="Game", place_id=place_id)


def forward_to_sober(uri: str) -> None:
    """Plays the link in your normal Sober, exactly as if Cellar were not in between."""
    fp = sober.which("flatpak") or "flatpak"
    subprocess.Popen([fp, "run", "--command=sober", sober.SOBER_ID, "--", uri], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# ---------------------------------------------------------------- registering as the handler
def _xdg_mime(*args: str) -> str:
    exe = sober.which("xdg-mime")
    if not exe:
        raise OSError("xdg-mime is missing (package xdg-utils)")
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=10).stdout.strip()


def handler_is_cellar() -> bool:
    try:
        return _xdg_mime("query", "default", "x-scheme-handler/roblox-player") == CELLAR_DESKTOP
    except (OSError, subprocess.SubprocessError):
        return False


def set_handler(cellar: bool) -> None:
    """Makes Cellar (or Sober again) open Roblox links. Needs Cellar's desktop file to list the schemes,
    which the Nix package and install.sh do; running from source writes a user desktop file for it."""
    if cellar:
        _ensure_desktop_file()
    for sc in SCHEMES:
        _xdg_mime("default", CELLAR_DESKTOP if cellar else SOBER_DESKTOP, f"x-scheme-handler/{sc}")


def _ensure_desktop_file() -> None:
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs = [data] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    for d in dirs:
        f = os.path.join(d, "applications", CELLAR_DESKTOP)
        try:
            with open(f, encoding="utf-8") as fh:
                if "x-scheme-handler/roblox-player" in fh.read():
                    return
        except OSError:
            continue
    # no installed desktop file knows the schemes (running from source): write a user one
    import shutil
    import sys
    exe = shutil.which(APP_ID)
    cmd = f'"{exe}"' if exe else f'"{sys.executable}" -m cellar'
    path = os.path.join(data, "applications", CELLAR_DESKTOP)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[Desktop Entry]\nType=Application\nName=Cellar\nComment=Roblox account launcher\n"
                 f"Exec={cmd} %u\nIcon={APP_ID}\nTerminal=false\nCategories=Game;\n"
                 "MimeType=x-scheme-handler/roblox-player;x-scheme-handler/roblox;\n")
    upd = sober.which("update-desktop-database")
    if upd:
        subprocess.run([upd, "-q", os.path.dirname(path)], capture_output=True, timeout=20)


def play_in_main_sober(spec: LaunchSpec) -> str:
    """Plays a game in your normal Sober, as the account it is logged in with - like pressing Play on the website.
    Blocking (asks Roblox for a login ticket). Returns '' or what went wrong."""
    from . import api, store
    import random
    if sober.main_sober_running():
        return "Your normal Sober is already open - close it first (Sober runs one game at a time)."
    cookie = sober.main_cookie()
    if not cookie:
        return "Your normal Sober is not logged in (or keeps its login in the keyring)."
    t = api.get_ticket(cookie)
    if not t.ticket:
        return "Roblox did not give a login ticket: " + (t.error or "unknown error")
    tracker = random.randint(10**11, 10**12 - 1)
    url = sober.place_launcher_url(store.settings, spec, tracker)
    forward_to_sober(sober.build_uri(t.ticket, util.now_ms(), url, tracker))
    return ""
