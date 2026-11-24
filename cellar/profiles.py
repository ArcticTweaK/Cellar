"""Everything an account's profile page shows (blocking - call from a worker thread).

Public Roblox endpoints for the profile itself; the account's own login only for what Roblox keeps private
(Robux, Premium, badges). Avatars and badge icons are cached in ~/.cache/cellar like the game icons.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from . import api, paths
from .games import _save
from .models import Account

BODY_DIR = paths.CACHE_DIR / "bodies"           # full-body avatar pictures (420 px)
BADGE_DIR = paths.CACHE_DIR / "badges"


@dataclass
class Profile:
    user_id: int = 0
    name: str = ""
    display: str = ""
    about: str = ""
    created: Optional[datetime] = None
    banned: bool = False
    friends: int = -1
    followers: int = -1
    following: int = -1
    robux: Optional[int] = None
    premium: Optional[bool] = None
    groups: List[Tuple[str, str]] = field(default_factory=list)        # (group, your role)
    badges: List[Tuple[int, str]] = field(default_factory=list)        # (badge id, name), newest first
    error: str = ""

    @property
    def age_days(self) -> Optional[int]:
        return (datetime.now(timezone.utc) - self.created).days if self.created else None


def _get(url: str, cookie: Optional[str] = None):
    try:
        r = api._req("GET", url, cookie)
        return r.json() if r.ok else None
    except Exception:
        return None


def _count(url: str) -> int:
    j = _get(url)
    return int(j.get("count", -1)) if isinstance(j, dict) else -1


def load(a: Account) -> Profile:
    p = Profile(user_id=a.user_id, name=a.username, display=a.display_name)
    if not a.user_id:
        p.error = "This account has no user id yet (check its login)."
        return p
    u = _get(f"https://users.roblox.com/v1/users/{a.user_id}")
    if isinstance(u, dict):
        p.name, p.display = u.get("name") or p.name, u.get("displayName") or p.display
        p.about = (u.get("description") or "").strip()
        p.banned = bool(u.get("isBanned"))
        try:
            p.created = datetime.fromisoformat((u.get("created") or "").replace("Z", "+00:00"))
        except ValueError:
            pass
    base = f"https://friends.roblox.com/v1/users/{a.user_id}"
    p.friends, p.followers, p.following = (_count(f"{base}/friends/count"), _count(f"{base}/followers/count"),
                                           _count(f"{base}/followings/count"))
    g = _get(f"https://groups.roblox.com/v2/users/{a.user_id}/groups/roles")
    if isinstance(g, dict):
        p.groups = [((d.get("group") or {}).get("name", ""), (d.get("role") or {}).get("name", ""))
                    for d in g.get("data", [])]
    if a.cookie:
        e = _get(f"https://economy.roblox.com/v1/users/{a.user_id}/currency", a.cookie)
        if isinstance(e, dict) and "robux" in e:
            p.robux = int(e["robux"])
        try:
            r = api._req("GET", f"https://premiumfeatures.roblox.com/v1/users/{a.user_id}/validate-membership",
                         a.cookie)
            if r.ok:
                p.premium = r.text.strip().lower() == "true"
        except Exception:
            pass
        b = _get(f"https://badges.roblox.com/v1/users/{a.user_id}/badges?limit=10&sortOrder=Desc", a.cookie)
        if isinstance(b, dict):
            p.badges = [(int(d["id"]), d.get("displayName") or d.get("name") or "") for d in b.get("data", [])]
    return p


def body_path(user_id: int):
    return BODY_DIR / f"{user_id}.png"


def badge_path(badge_id: int):
    return BADGE_DIR / f"{badge_id}.png"


def fetch_pictures(user_id: int, badge_ids: List[int]) -> None:
    """Full-body avatar (refreshed every start of a profile page: outfits change) and badge icons (kept)."""
    BODY_DIR.mkdir(parents=True, exist_ok=True)
    BADGE_DIR.mkdir(parents=True, exist_ok=True)
    j = _get(f"https://thumbnails.roblox.com/v1/users/avatar?userIds={user_id}&size=420x420&format=Png"
             "&isCircular=false")
    for d in (j or {}).get("data", []):
        if d.get("state") == "Completed" and d.get("imageUrl"):
            data = api.download(d["imageUrl"])
            if data:
                _save(body_path(user_id), data)
    need = [b for b in badge_ids if not badge_path(b).exists()]
    if need:
        j = _get("https://thumbnails.roblox.com/v1/badges/icons?badgeIds=" + ",".join(map(str, need))
                 + "&size=150x150&format=Png&isCircular=false")
        for d in (j or {}).get("data", []):
            if d.get("state") == "Completed" and d.get("imageUrl"):
                data = api.download(d["imageUrl"])
                if data:
                    _save(badge_path(int(d["targetId"])), data)
