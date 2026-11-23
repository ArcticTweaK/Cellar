"""Roblox web API (port of Api.cs). Every call is blocking - run them off the UI thread."""

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from . import log
from .models import Account, LaunchSpec

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TIMEOUT = 25
_tls = threading.local()


def _session() -> requests.Session:
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _tls.s = s
    return s


@dataclass
class UserInfo:
    id: int = 0
    name: str = ""
    display: str = ""
    error: str = ""
    valid: bool = False
    locked: bool = False


@dataclass
class TicketResult:
    ticket: Optional[str] = None
    error: str = ""
    unauthorized: bool = False
    locked: bool = False


@dataclass
class PresenceInfo:
    type: int = 0
    location: str = ""
    place_id: int = 0
    game_id: str = ""


@dataclass
class ServerInfo:
    id: str = ""
    playing: int = 0
    max: int = 0
    ping: int = 0
    fps: float = 0.0


@dataclass
class ServerPage:
    servers: List[ServerInfo] = field(default_factory=list)
    next: str = ""
    error: str = ""


@dataclass
class GameInfo:
    name: str = ""
    place_id: int = 0
    players: int = 0


def _req(method: str, url: str, cookie: str = None, json_body=None, csrf: str = None,
         extra: Dict[str, str] = None, origin: bool = True) -> requests.Response:
    h = {"Referer": "https://www.roblox.com/"}
    if origin:
        h["Origin"] = "https://www.roblox.com"
    if cookie:
        h["Cookie"] = ".ROBLOSECURITY=" + cookie
    if csrf:
        h["X-CSRF-TOKEN"] = csrf
    if extra:
        h.update({k: v for k, v in extra.items() if v})
    kw = {"headers": h, "timeout": TIMEOUT, "allow_redirects": True}
    if json_body is not None:
        kw["json"] = json_body
    elif method == "POST":
        # Empty body, but still labelled JSON like the Windows app: without a Content-Type Roblox answers 415.
        kw["data"] = b""
        h.setdefault("Content-Type", "application/json")
    return _session().request(method, url, **kw)


def _post_csrf(url: str, cookie: str = None, body=None, extra=None, origin=True) -> requests.Response:
    """POST that handles Roblox's CSRF handshake (403 + token, then retry)."""
    r = _req("POST", url, cookie, body, None, extra, origin)
    if r.status_code == 403:
        token = r.headers.get("x-csrf-token")
        if token:
            r = _req("POST", url, cookie, body, token, extra, origin)
    return r


def internet_ok() -> bool:
    try:
        return _req("GET", "https://users.roblox.com/v1/users/1").status_code > 0
    except Exception:
        return False


def authenticated(cookie: str) -> UserInfo:
    u = UserInfo()
    try:
        r = _req("GET", "https://users.roblox.com/v1/users/authenticated", cookie)
        if r.status_code == 401:
            u.error = "Cookie expired or invalid"
        elif r.status_code == 403:
            u.locked, u.error = True, "Account locked or blocked by Roblox (HTTP 403)"
        elif r.status_code == 429:
            u.error = "Rate limited (HTTP 429) - try again in a minute"
        elif not r.ok:
            u.error = f"HTTP {r.status_code}"
        else:
            j = r.json()
            u.id, u.name, u.display = int(j.get("id") or 0), j.get("name", ""), j.get("displayName", "")
            u.valid = u.id > 0
            if not u.valid:
                u.error = "Unexpected response"
    except Exception as ex:
        u.error = str(ex)
    return u


def get_ticket(cookie: str) -> TicketResult:
    t = TicketResult()
    try:
        r = _post_csrf("https://auth.roblox.com/v1/authentication-ticket/", cookie, None,
                       {"Referer": "https://www.roblox.com/games/4924922222/Brookhaven-RP"}, origin=False)
        if r.status_code == 401:
            t.unauthorized, t.error = True, "cookie expired or invalid (HTTP 401)"
        elif r.status_code == 403:
            t.locked, t.error = True, "account locked or blocked by Roblox (HTTP 403)"
        elif r.status_code == 429:
            t.error = "rate limited by Roblox (HTTP 429) - wait a bit and retry"
        else:
            ticket = r.headers.get("rbx-authentication-ticket", "")
            if not r.ok or not ticket:
                t.error = f"no authentication ticket received (HTTP {r.status_code})"
            else:
                t.ticket = ticket
    except Exception as ex:
        t.error = str(ex)
    return t


def rotate_cookie(cookie: str, logf) -> Optional[str]:
    """Exchanges the cookie for a brand-new one (signs the account out of its other sessions)."""
    try:
        t = get_ticket(cookie)
        if not t.ticket:
            logf("cookie refresh failed: " + t.error)
            return None
        r = _post_csrf("https://auth.roblox.com/v1/authentication-ticket/redeem", None,
                       {"authenticationTicket": t.ticket}, {"RBXAuthenticationNegotiation": "1"})
        nc = r.cookies.get(".ROBLOSECURITY")
        if not nc:
            m = re.search(r"\.ROBLOSECURITY=([^;\s]+)", r.headers.get("Set-Cookie", ""))
            nc = m.group(1) if m else None
        if not nc:
            logf(f"cookie refresh failed: Roblox did not return a new cookie (HTTP {r.status_code})")
            return None
        u = authenticated(nc)
        if not u.valid:
            logf(f"cookie refresh failed: the new cookie did not validate ({u.error})")
            return None
        return nc
    except Exception as ex:
        logf(f"cookie refresh error: {ex}")
        return None


def presence(cookie: str, ids: List[int]) -> Dict[int, PresenceInfo]:
    res: Dict[int, PresenceInfo] = {}
    try:
        for i in range(0, len(ids), 100):
            r = _post_csrf("https://presence.roblox.com/v1/presence/users", cookie, {"userIds": ids[i:i + 100]})
            if not r.ok:
                continue
            for p in r.json().get("userPresences", []):
                res[int(p.get("userId") or 0)] = PresenceInfo(
                    int(p.get("userPresenceType") or 0), p.get("lastLocation") or "",
                    int(p.get("placeId") or 0), p.get("gameId") or "")
    except Exception as ex:
        log.write(f"Presence lookup failed: {ex}")
    return res


@dataclass
class Friend:
    user_id: int
    name: str = ""
    display_name: str = ""
    presence: Optional[PresenceInfo] = None


def friends(cookie: str, user_id: int) -> Tuple[List[Friend], str]:
    """An account's friends with names and presence. Returns (friends, error)."""
    try:
        r = _req("GET", f"https://friends.roblox.com/v1/users/{user_id}/friends", cookie)
        if not r.ok:
            return [], f"HTTP {r.status_code}"
        out = [Friend(int(d.get("id") or 0), d.get("name") or "", d.get("displayName") or "")
               for d in r.json().get("data", []) if d.get("id")]
        missing = [f.user_id for f in out if not f.name]        # newer API versions only send ids
        names: Dict[int, Tuple[str, str]] = {}
        for i in range(0, len(missing), 100):
            u = _post_csrf("https://users.roblox.com/v1/users", None,
                           {"userIds": missing[i:i + 100], "excludeBannedUsers": False})
            if u.ok:
                for d in u.json().get("data", []):
                    names[int(d["id"])] = (d.get("name") or "", d.get("displayName") or "")
        for f in out:
            if not f.name and f.user_id in names:
                f.name, f.display_name = names[f.user_id]
        pres = presence(cookie, [f.user_id for f in out])
        for f in out:
            f.presence = pres.get(f.user_id)
        return out, ""
    except Exception as ex:
        return [], str(ex)


def user_by_name(name: str) -> UserInfo:
    u = UserInfo()
    try:
        r = _post_csrf("https://users.roblox.com/v1/usernames/users", None,
                       {"usernames": [name], "excludeBannedUsers": False})
        if not r.ok:
            u.error = f"HTTP {r.status_code}"
            return u
        for d in r.json().get("data", []):
            u.id, u.name = int(d.get("id") or 0), d.get("name", "")
            u.valid = u.id > 0
            return u
        u.error = "User not found"
    except Exception as ex:
        u.error = str(ex)
    return u


def servers(place_id: int, ascending: bool, cursor: str, cookie: str) -> ServerPage:
    sp = ServerPage()
    try:
        url = (f"https://games.roblox.com/v1/games/{place_id}/servers/Public?sortOrder="
               f"{'Asc' if ascending else 'Desc'}&excludeFullGames=false&limit=100")
        if cursor:
            url += "&cursor=" + quote(cursor, safe="")
        r = _req("GET", url, cookie)
        if r.status_code == 429:
            sp.error = "Rate limited by Roblox (HTTP 429). Wait a minute and try again."
            return sp
        if not r.ok:
            sp.error = f"HTTP {r.status_code} {r.text[:100]}"
            return sp
        j = r.json()
        sp.next = j.get("nextPageCursor") or ""
        for s in j.get("data", []):
            si = ServerInfo(s.get("id", ""), int(s.get("playing") or 0), int(s.get("maxPlayers") or 0),
                            int(s.get("ping") or 0), float(s.get("fps") or 0))
            if si.id:
                sp.servers.append(si)
    except Exception as ex:
        sp.error = str(ex)
    return sp


def avatar_urls(ids: List[int]) -> Dict[int, str]:
    res: Dict[int, str] = {}
    try:
        for i in range(0, len(ids), 100):
            chunk = ",".join(str(x) for x in ids[i:i + 100])
            r = _req("GET", "https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds=" + chunk
                     + "&size=150x150&format=Png&isCircular=false")
            if not r.ok:
                continue
            for d in r.json().get("data", []):
                if d.get("state") == "Completed" and d.get("imageUrl"):
                    res[int(d.get("targetId") or 0)] = d["imageUrl"]
    except Exception as ex:
        log.write(f"Avatar lookup failed: {ex}")
    return res


def download(url: str) -> Optional[bytes]:
    try:
        r = _session().get(url, timeout=TIMEOUT)
        return r.content if r.ok else None
    except Exception:
        return None


def place_name(place_id: int) -> str:
    try:
        r = _req("GET", f"https://apis.roblox.com/universes/v1/places/{place_id}/universe")
        if not r.ok:
            return ""
        uni = int(r.json().get("universeId") or 0)
        if not uni:
            return ""
        g = _req("GET", f"https://games.roblox.com/v1/games?universeIds={uni}")
        for d in g.json().get("data", []) if g.ok else []:
            return d.get("name", "")
    except Exception:
        pass
    return ""


def search_games(query: str, cookie: str) -> List[GameInfo]:
    out: List[GameInfo] = []
    try:
        url = ("https://apis.roblox.com/search-api/omni-search?searchQuery=" + quote(query, safe="")
               + "&sessionId=" + str(uuid.uuid4()) + "&pageType=all")
        r = _req("GET", url, cookie)
        if r.ok:
            _collect_games(r.json(), out, 0)
        else:
            log.write(f"Game search returned HTTP {r.status_code}")
    except Exception as ex:
        log.write(f"Game search failed: {ex}")
    return out


def _collect_games(node, acc: List[GameInfo], depth: int) -> None:
    if node is None or depth > 8:
        return
    if isinstance(node, dict):
        if "rootPlaceId" in node and "name" in node:
            pid = int(node.get("rootPlaceId") or 0)
            if pid > 0 and not any(g.place_id == pid for g in acc):
                acc.append(GameInfo(node.get("name", ""), pid, int(node.get("playerCount") or 0)))
            return
        for v in node.values():
            _collect_games(v, acc, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _collect_games(v, acc, depth + 1)


def resolve_share(code: str, cookie: str) -> Optional[LaunchSpec]:
    """New style private-server links: https://www.roblox.com/share?code=XXXX&type=Server"""
    try:
        clean = re.sub(r"[^A-Za-z0-9]", "", code)
        r = _post_csrf("https://apis.roblox.com/sharelinks/v1/resolve-link", cookie,
                       {"linkId": clean, "linkType": "Server"})
        if not r.ok:
            return None
        d = r.json().get("privateServerInviteData") or {}
        s = LaunchSpec(kind="Private", place_id=int(d.get("placeId") or 0), link_code=d.get("linkCode") or "")
        if s.place_id > 0 and s.link_code:
            return s
    except Exception as ex:
        log.write(f"Share link resolve failed: {ex}")
    return None


def details(a: Account) -> str:
    lines = [f"Username:      {a.username}", f"Display name:  {a.display_name}", f"User ID:       {a.user_id}"]
    try:
        u = _req("GET", f"https://users.roblox.com/v1/users/{a.user_id}")
        if u.ok:
            j = u.json()
            try:
                created = datetime.fromisoformat(j.get("created", "").replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - created).days
                lines.append(f"Account age:   {days} days (created {created:%Y-%m-%d})")
            except ValueError:
                pass
            lines.append("Banned:        " + ("yes" if j.get("isBanned") else "no"))
        e = _req("GET", f"https://economy.roblox.com/v1/users/{a.user_id}/currency", a.cookie)
        lines.append(f"Robux:         {e.json().get('robux')}" if e.ok else f"Robux:         (could not load, HTTP {e.status_code})")
        p = _req("GET", f"https://premiumfeatures.roblox.com/v1/users/{a.user_id}/validate-membership", a.cookie)
        if p.ok:
            lines.append("Premium:       " + ("yes" if p.text.strip().lower() == "true" else "no"))
    except Exception as ex:
        lines.append(f"(some details failed: {ex})")
    return "\n".join(lines)
