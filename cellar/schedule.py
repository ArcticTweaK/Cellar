"""Scheduled presets: which schedules are due right now (no Qt - the UI runs this every 30 s).

A start fires once per day when the clock is past its time (within 15 minutes, so a PC that wakes up a bit
late still runs it, but one that was off all evening does not start a farm at midnight). A stop works the same
way; a stop time earlier than the start time means the next morning (18:00 -> 02:00).
"""

import time
from typing import List, Tuple

from .models import Schedule

GRACE_MIN = 15


def _minutes(hhmm: str) -> int:
    h, _, m = (hhmm or "").partition(":")
    return int(h) * 60 + int(m)


def valid(hhmm: str) -> bool:
    try:
        v = _minutes(hhmm)
        return 0 <= v < 24 * 60 and len(hhmm.split(":")[1]) == 2
    except (ValueError, IndexError):
        return False


def due(schedules: List[Schedule], now: float = None) -> List[Tuple[Schedule, str]]:
    """-> [(schedule, "start" | "stop")] that should fire now. Marks them as fired for today."""
    t = time.localtime(now if now is not None else time.time())
    today = time.strftime("%Y-%m-%d", t)
    cur = t.tm_hour * 60 + t.tm_min
    out = []
    for s in schedules:
        if not s.enabled or not valid(s.start):
            continue
        st = _minutes(s.start)
        if t.tm_wday in s.days and s.last_start != today and 0 <= cur - st <= GRACE_MIN:
            s.last_start = today
            out.append((s, "start"))
        if s.stop and valid(s.stop):
            sp = _minutes(s.stop)
            overnight = sp <= st                       # 18:00 -> 02:00: the stop belongs to yesterday's start
            run_day = (t.tm_wday - 1) % 7 if overnight else t.tm_wday
            # (also when the accounts were started by hand: "stop at 02:00" means stop at 02:00)
            if run_day in s.days and s.last_stop != today and 0 <= cur - sp <= GRACE_MIN:
                s.last_stop = today
                out.append((s, "stop"))
    return out
