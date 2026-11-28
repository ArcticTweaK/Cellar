"""Small helpers shared by everything."""

import re
import time
import uuid
from typing import List

_COOKIE_RE = re.compile(r"_\|WARNING:[^|\s\"]*\|_[A-Za-z0-9_\-\.%]+")


def now_ms() -> int:
    return int(time.time() * 1000)


def extract_cookies(text: str) -> List[str]:
    """Every .ROBLOSECURITY cookie inside any pasted text / file contents."""
    found: List[str] = []
    for m in _COOKIE_RE.finditer(text or ""):
        if m.group(0) not in found:
            found.append(m.group(0))
    return found


def parse_place_id(s: str) -> int:
    """Accepts "123456", "https://www.roblox.com/games/123456/Some-Game", "...placeId=123" ..."""
    if not s:
        return 0
    m = re.search(r"/games/(\d+)", s) or re.search(r"placeId=(\d+)", s, re.I) or re.match(r"^\s*(\d{3,})", s)
    return int(m.group(1)) if m else 0


def looks_like_guid(s: str) -> bool:
    try:
        uuid.UUID((s or "").strip())
        return True
    except ValueError:
        return False


def ago(ts: float) -> str:
    if not ts or ts <= 0:
        return "never"
    d = time.time() - ts
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 48 * 3600:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} days ago"


def trunc(s: str, n: int) -> str:
    s = (s or "").replace("\r", " ").replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


def natural_key(s: str):
    """"account3" sorts before "account10"."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s or "")]


def share_code_of(link: str) -> str:
    """The code of a new-style share link (roblox.com/share?code=...&type=Server), or ""."""
    if not link or "share" not in link.lower():
        return ""
    m = re.search(r"[?&]code=([A-Za-z0-9]+)", link)
    return m.group(1) if m else ""


def private_link_code(link: str) -> str:
    m = re.search(r"privateServerLinkCode=([^&#\s]+)", link or "")
    return m.group(1) if m else ""


def launch_action(account_ids, running_ids) -> str:
    """Name the effect for an offline, running, or mixed selection (no process scans on the UI thread)."""
    ids = set(account_ids)
    count = len(ids.intersection(running_ids))
    return "Relaunch" if ids and count == len(ids) else "Launch / relaunch" if count else "Launch"
