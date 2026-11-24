"""Games for the Home tab: discover lists, search, favourites, details and icons (cached on disk).

Blocking network calls - run them on a worker thread (ui.common.bg). The public endpoints here need no login;
favourites and search use the account's cookie when one is given (private favourites, personalised search).
"""

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from . import api, log, paths

ICON_DIR = paths.CACHE_DIR / "games"
ICON_DAYS = 7                   # game icons change rarely; refresh weekly
_UNI_FILE = paths.CACHE_DIR / "place-universe.json"
_uni: Dict[int, int] = {}       # place id -> universe id (never changes, kept on disk)

# Roblox's own discover lists (explore-api sortId -> our title), in the order they are shown
DISCOVER = [("top-playing-now", "Popular right now"), ("top-trending", "Trending"),
            ("up-and-coming", "Up and coming"), ("fun-with-friends", "Fun with friends")]


@dataclass
class Game:
    universe_id: int = 0
    place_id: int = 0
    name: str = ""
    players: int = 0
    up: int = 0
    down: int = 0
    description: str = ""
    creator: str = ""
    visits: int = 0
    max_players: int = 0
    genre: str = ""
    updated: str = ""
    favourites: int = 0

    @property
    def rating(self) -> Optional[int]:
        """Like ratio in % (None when nobody voted)."""
        total = self.up + self.down
        return round(self.up * 100 / total) if total else None


def short(n: int) -> str:
    """242333 -> '242K', 45493296137 -> '45.5B'."""
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            v = n / div
            return (f"{v:.1f}".rstrip("0").rstrip(".") if v < 100 else f"{v:.0f}") + unit
    return str(n)


def _from_list_item(d: dict) -> Game:
    return Game(universe_id=int(d.get("universeId") or 0), place_id=int(d.get("rootPlaceId") or 0),
                name=d.get("name") or "", players=int(d.get("playerCount") or 0),
                up=int(d.get("totalUpVotes") or 0), down=int(d.get("totalDownVotes") or 0),
                description=d.get("description") or "", creator=d.get("creatorName") or "",
                genre=d.get("genreL1") or "")


# ---------------------------------------------------------------- lists
def discover() -> List[Tuple[str, List[Game]]]:
    """Roblox's public discover rows (no login needed)."""
    out: List[Tuple[str, List[Game]]] = []
    try:
        r = api._req("GET", "https://apis.roblox.com/explore-api/v1/get-sorts?sessionId="
                     f"{uuid.uuid4()}&device=computer&country=all")
        if not r.ok:
            log.write(f"Home: Roblox's game lists returned HTTP {r.status_code}.")
            return out
        sorts = {s.get("sortId"): s for s in r.json().get("sorts", [])}
        for sid, title in DISCOVER:
            games = [_from_list_item(g) for g in (sorts.get(sid) or {}).get("games") or []]
            games = [g for g in games if g.place_id and g.universe_id]
            if games:
                out.append((title, games[:40]))
    except Exception as ex:
        log.write(f"Home: could not load Roblox's game lists ({ex}).")
    return out


def search(query: str, cookie: Optional[str] = None) -> List[Game]:
    out: List[Game] = []
    try:
        r = api._req("GET", "https://apis.roblox.com/search-api/omni-search?searchQuery=" + quote(query, safe="")
                     + f"&sessionId={uuid.uuid4()}&pageType=all", cookie)
        if not r.ok:
            log.write(f"Game search returned HTTP {r.status_code}.")
            return out
        for grp in r.json().get("searchResults", []):
            if grp.get("contentGroupType") != "Game":
                continue
            for c in grp.get("contents") or []:
                g = _from_list_item(c)
                if g.place_id and not any(x.universe_id == g.universe_id for x in out):
                    out.append(g)
    except Exception as ex:
        log.write(f"Game search failed: {ex}")
    return out


def favourites(user_id: int, cookie: Optional[str] = None) -> List[Game]:
    """The account's favourite games on Roblox (newest first)."""
    try:
        r = api._req("GET", f"https://games.roblox.com/v2/users/{user_id}/favorite/games?limit=50&sortOrder=Desc",
                     cookie)
        if not r.ok:
            return []
        games = [Game(universe_id=int(d.get("id") or 0), place_id=int((d.get("rootPlace") or {}).get("id") or 0),
                      name=d.get("name") or "") for d in r.json().get("data", [])]
        games = [g for g in games if g.universe_id and g.place_id]
        fill(games)
        return games
    except Exception as ex:
        log.write(f"Home: could not load favourites ({ex}).")
        return []


# ---------------------------------------------------------------- details
def _load_uni() -> None:
    if not _uni and _UNI_FILE.exists():
        try:
            _uni.update({int(k): int(v) for k, v in json.loads(_UNI_FILE.read_text()).items()})
        except (OSError, ValueError):
            pass


def cached_universe(place_id: int) -> int:
    """The universe id if it is already known (no network) - 0 otherwise."""
    _load_uni()
    return _uni.get(place_id, 0)


def universes(place_ids: Iterable[int]) -> Dict[int, int]:
    """place id -> universe id (one request per place the first time, then from the disk cache)."""
    _load_uni()
    out, new = {}, False
    for pid in dict.fromkeys(p for p in place_ids if p > 0):
        if pid not in _uni:
            try:
                r = api._req("GET", f"https://apis.roblox.com/universes/v1/places/{pid}/universe")
                uni = int(r.json().get("universeId") or 0) if r.ok else 0
            except Exception:
                uni = 0
            if uni:
                _uni[pid], new = uni, True
        if pid in _uni:
            out[pid] = _uni[pid]
    if new:
        try:
            paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _UNI_FILE.write_text(json.dumps(_uni))
        except OSError:
            pass
    return out


def fill(games: List[Game]) -> None:
    """Fills in name, players, votes, description... for games that only have ids (50 per request)."""
    by_uni = {g.universe_id: g for g in games if g.universe_id}
    ids = list(by_uni)
    try:
        for i in range(0, len(ids), 50):
            chunk = ",".join(map(str, ids[i:i + 50]))
            r = api._req("GET", f"https://games.roblox.com/v1/games?universeIds={chunk}")
            for d in r.json().get("data", []) if r.ok else []:
                g = by_uni.get(int(d.get("id") or 0))
                if g:
                    g.name = d.get("name") or g.name
                    g.place_id = int(d.get("rootPlaceId") or g.place_id)
                    g.players = int(d.get("playing") or 0)
                    g.description = d.get("description") or ""
                    g.creator = (d.get("creator") or {}).get("name") or ""
                    g.visits = int(d.get("visits") or 0)
                    g.max_players = int(d.get("maxPlayers") or 0)
                    g.genre = d.get("genre_l1") or d.get("genre") or ""
                    g.updated = (d.get("updated") or "")[:10]
                    g.favourites = int(d.get("favoritedCount") or 0)
            v = api._req("GET", f"https://games.roblox.com/v1/games/votes?universeIds={chunk}")
            for d in v.json().get("data", []) if v.ok else []:
                g = by_uni.get(int(d.get("id") or 0))
                if g:
                    g.up, g.down = int(d.get("upVotes") or 0), int(d.get("downVotes") or 0)
    except Exception as ex:
        log.write(f"Home: could not load game details ({ex}).")


def from_places(place_ids: List[int]) -> List[Game]:
    """Games for a list of place ids (recently played), in the same order, with details."""
    unis = universes(place_ids)
    games = [Game(universe_id=unis[p], place_id=p) for p in place_ids if p in unis]
    fill(games)
    return games


# ---------------------------------------------------------------- icons
def _save(path: Path, data: bytes) -> bool:
    """Atomic write with a temp name of its own: Home, Library and profiles may fetch the same picture at once."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def icon_path(universe_id: int) -> Path:
    return ICON_DIR / f"{universe_id}.png"


def fetch_icons(universe_ids: Iterable[int]) -> int:
    """Downloads the icons not cached yet (or older than a week). Returns how many were saved."""
    now = time.time()
    need = [u for u in dict.fromkeys(universe_ids) if u > 0 and (
        not icon_path(u).exists() or now - icon_path(u).stat().st_mtime > ICON_DAYS * 86400)]
    saved = 0
    if not need:
        return 0
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for i in range(0, len(need), 100):
            chunk = ",".join(map(str, need[i:i + 100]))
            r = api._req("GET", "https://thumbnails.roblox.com/v1/games/icons?universeIds=" + chunk
                         + "&size=150x150&format=Png&isCircular=false")
            for d in r.json().get("data", []) if r.ok else []:
                url = d.get("imageUrl")
                if d.get("state") != "Completed" or not url:
                    continue
                data = api.download(url)
                if data and _save(icon_path(int(d["targetId"])), data):
                    saved += 1
    except Exception as ex:
        log.write(f"Home: could not load game icons ({ex}).")
    return saved


def fetch_avatars(user_ids: Iterable[int]) -> int:
    """Head shots for friends (same cache as the accounts' own: paths.AVATAR_DIR/<id>.png)."""
    need = [u for u in dict.fromkeys(user_ids) if u > 0 and not (paths.AVATAR_DIR / f"{u}.png").exists()]
    if not need:
        return 0
    paths.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for uid, url in api.avatar_urls(need).items():
        data = api.download(url)
        if data and _save(paths.AVATAR_DIR / f"{uid}.png", data):
            saved += 1
    return saved


def is_favourite(universe_id: int, cookie: str) -> Optional[bool]:
    try:
        r = api._req("GET", f"https://games.roblox.com/v1/games/{universe_id}/favorites", cookie)
        return bool(r.json().get("isFavorited")) if r.ok else None
    except Exception:
        return None


def set_favourite(universe_id: int, cookie: str, on: bool) -> str:
    """Favourites a game on the account (like the star on the website). Returns '' or the error."""
    try:
        r = api._post_csrf(f"https://games.roblox.com/v1/games/{universe_id}/favorites", cookie, {"isFavorited": on})
        return "" if r.ok else f"HTTP {r.status_code}"
    except Exception as ex:
        return str(ex)
