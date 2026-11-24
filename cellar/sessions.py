"""Session history: which account played what, for how long (local only - settings.history).

A JoinRecord is one session: it starts when an account's Roblox log says it joined a server and ends when the
account joins another server (teleport / server change), leaves, is disconnected, or its window is gone.
end == 0 means it is still going, end < 0 unknown (sessions recorded before 1.1 only had their start). Times come
from the Roblox log lines, so when Cellar restarts and re-reads the log of a client that kept running, joins it
already has are recognised and skipped (same server within 5 s, or older than the open session).
"""

import time
from typing import Dict, Iterable, List, Optional, Tuple

from .models import JoinRecord

KEEP = 1000                     # sessions kept (newest first); ~150 bytes each in settings.json


def _latest(history: List[JoinRecord], account_id: str) -> Optional[JoinRecord]:
    return max((r for r in history if r.account_id == account_id), key=lambda r: r.ts, default=None)


def _open(history: List[JoinRecord], account_id: str) -> Optional[JoinRecord]:
    r = _latest(history, account_id)
    return r if r is not None and not r.end else None


def start(history: List[JoinRecord], account_id: str, account: str, place_id: int, job_id: str,
          now: Optional[float] = None) -> bool:
    """An account joined a server. Returns False when it only continued the open session (same server)."""
    now = time.time() if now is None else now
    if any(r.account_id == account_id and r.job_id == job_id and abs(r.ts - now) < 5 for r in history):
        return False                            # this join is on record already (the log was read again)
    cur = _open(history, account_id)
    if cur is not None:
        if (cur.job_id == job_id and cur.place_id == place_id) or now < cur.ts:
            return False                        # the same server still, or an older join replayed
        cur.end = now
    history.insert(0, JoinRecord(now, account_id, account, place_id, job_id))
    history.sort(key=lambda r: -r.ts)           # newest first, also when joins of two accounts arrive late
    del history[KEEP:]
    return True


def end(history: List[JoinRecord], account_id: str, now: Optional[float] = None) -> bool:
    """It left / was disconnected / its window closed. Returns True if a session was open."""
    cur = _open(history, account_id)
    now = time.time() if now is None else now
    if cur is None or now < cur.ts:             # nothing open, or an event from before this session (replay)
        return False
    cur.end = now
    return True


def close_missing(history: List[JoinRecord], running: Iterable[str], now: Optional[float] = None) -> int:
    """Open sessions of accounts that are not running any more end at `now` (or when Cellar last quit, for
    clients that closed while Cellar was not running). Returns how many were closed."""
    running = set(running)
    now = time.time() if now is None else now
    n = 0
    for aid in {r.account_id for r in history} - running:
        r = _latest(history, aid)
        if not r.end:
            r.end = max(r.ts, now)
            n += 1
    return n


def duration(r: JoinRecord, now: Optional[float] = None) -> float:
    """Seconds; -1 when unknown (recorded before sessions had an end)."""
    if r.end < 0:
        return -1.0
    return max(0.0, (r.end or (time.time() if now is None else now)) - r.ts)


def totals(history: List[JoinRecord], since: float, now: Optional[float] = None) -> List[Tuple[str, int, int, float]]:
    """(account, place id, sessions, seconds) for the time since `since`, most played first. A session that
    began before `since` counts only its part after it."""
    now = time.time() if now is None else now
    acc: Dict[Tuple[str, int], List[float]] = {}
    for r in history:
        if r.end < 0:
            continue
        stop = r.end or now
        if stop <= since:
            continue
        k = (r.account, r.place_id)
        e = acc.setdefault(k, [0, 0.0])
        e[0] += 1
        e[1] += stop - max(r.ts, since)
    return sorted(((a, p, int(n), s) for (a, p), (n, s) in acc.items()), key=lambda t: -t[3])


def human(seconds: float) -> str:
    """3725 -> '1 h 2 min', 50 -> '50 s'."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    h, m = divmod(seconds // 60, 60)
    return (f"{h} h {m} min" if m else f"{h} h") if h else f"{m} min"
