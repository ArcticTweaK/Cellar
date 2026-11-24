"""New-version check against GitHub releases (at most once a day, can be turned off in Settings).

Only asks GitHub's public API for the latest release of ArcticTweaK/Cellar - nothing about you or your accounts
is sent. Blocking: call it from a worker thread.
"""

import os
import re
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import requests

from . import __version__

REPO = "ArcticTweaK/Cellar"
RELEASES_URL = f"https://github.com/{REPO}/releases"
_API = f"https://api.github.com/repos/{REPO}/releases"


@dataclass
class Release:
    version: str
    url: str
    notes: str


def vtuple(v: str) -> Tuple[int, ...]:
    """'v1.10.2' -> (1, 10, 2); anything that is not a number counts as 0."""
    return tuple(int(x) if x.isdigit() else 0 for x in re.findall(r"\d+|[A-Za-z]+", v.lstrip("vV"))[:4])


def _get(url: str) -> Optional[dict]:
    try:
        r = requests.get(url, timeout=10, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "Cellar-update-check"})
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def latest() -> Optional[Release]:
    j = _get(_API + "/latest")
    if not j or j.get("draft") or j.get("prerelease"):
        return None
    return Release(j.get("tag_name", "").lstrip("vV"), j.get("html_url") or RELEASES_URL, j.get("body") or "")


def notes_for(version: str) -> Optional[Release]:
    for tag in (f"v{version}", version):
        j = _get(f"{_API}/tags/{tag}")
        if j:
            return Release(version, j.get("html_url") or RELEASES_URL, j.get("body") or "")
    return None


def newer(than: str = __version__) -> Optional[Release]:
    r = latest()
    return r if r and vtuple(r.version) > vtuple(than) else None


def due(last_check: float) -> bool:
    return time.time() - last_check > 20 * 3600


def how_to_update() -> str:
    """How this copy was installed decides how to update it."""
    here = os.path.abspath(__file__)
    if here.startswith("/nix/store/"):
        return ("Installed with Nix: <tt>nix profile upgrade Cellar</tt> (or update the flake input in your NixOS / "
                "home-manager config and rebuild).")
    if "/cellar-app/" in here:
        return "Installed with install.sh: download the new version (or <tt>git pull</tt>) and run <tt>./install.sh</tt> again."
    if os.path.isdir(os.path.join(os.path.dirname(os.path.dirname(here)), ".git")):
        return "Running from a git checkout: <tt>git pull</tt>, then start it again."
    return f"Download it from <a href='{RELEASES_URL}'>{RELEASES_URL}</a>."

